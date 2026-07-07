"""Polite, resumable crawler for RevitApiDocs (https://www.revitapidocs.com/).

Design constraints (see docs/crawl_notes.md for the full rationale):

- Custom User-Agent identifying the bot and a contact-free purpose string.
- Throttled: a minimum delay between requests to the same host.
- Cached: every fetched page is written to disk under ``cache_dir`` keyed by
  URL, and is never re-fetched on a later run unless ``force_refresh=True``.
- Resumable: ``raw_index.json`` is written incrementally so a crawl that is
  interrupted partway through can be restarted and will pick up where it
  left off.
- Scoped: only URLs under the configured RevitApiDocs version path are
  followed; nothing outside revitapidocs.com is ever requested.

NOTE ON HTML STRUCTURE: the selectors used to discover TOC/index links in
``discover_index`` are written defensively (multiple fallback strategies)
because this module was built without live access to revitapidocs.com in
the environment it was authored in (see docs/crawl_notes.md, "Network
access limitation"). The first real run against the live site should be
treated as a validation pass: if ``discover_index`` finds zero or
suspiciously few links, that is a signal the selectors need adjusting, not
that Revit.DB has few types.

CONFIRMED AGAINST LIVE DATA (see docs/crawl_notes.md): the version root
page's ``<a href>`` anchors are *not* the page index -- the real site loads
its type tree client-side from a JSON file on a CDN
(``NAMESPACE_JSON_HOST``), which ``discover_via_namespace_json`` fetches and
flattens directly. This is the primary/authoritative discovery strategy;
the HTML-scraping strategies below (root page anchors, TOC files, sitemap)
are kept as a defensive fallback in case that JSON is ever unavailable, but
were confirmed to find almost nothing useful on their own.

DEPENDENCY FALLBACK: ``requests`` and ``beautifulsoup4`` are used when
installed (they're faster and more robust), but neither is required --
``http_compat``/``html_compat`` provide equivalent behavior on top of
``urllib.request``/``html.parser`` alone, so this runs on a bare Python
install with no third-party packages. See those modules for scope/limits.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from xml.etree import ElementTree
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    from bs4 import BeautifulSoup
except ImportError:
    from .html_compat import MiniSoup as BeautifulSoup

from .http_compat import HttpClient
from .parse import _strip_kind_suffix

logger = logging.getLogger(__name__)

USER_AGENT = (
    "RevitSemanticSchemaMapper/0.1 "
    "(+https://github.com/gmcdowelljr/revit-semantic-schema-mapper; "
    "docs-crawler for a candidate Revit DB semantic schema; "
    "polite, throttled, caches locally)"
)

DEFAULT_THROTTLE_SECONDS = 1.5
ALLOWED_HOST = "www.revitapidocs.com"
# CDN host serving the client-side namespace/TOC JSON (see discover_via_namespace_json).
NAMESPACE_JSON_HOST = "d24b2zsrnzhmgb.cloudfront.net"
ALLOWED_HOSTS = {ALLOWED_HOST, NAMESPACE_JSON_HOST}


@dataclass
class CrawlConfig:
    version: str = "2027"
    base_url: str = "https://www.revitapidocs.com"
    namespace_prefix: str = "Autodesk.Revit.DB"
    cache_dir: Path = field(default_factory=lambda: Path("outputs/revit_2027/cache"))
    throttle_seconds: float = DEFAULT_THROTTLE_SECONDS
    max_pages: int | None = None
    force_refresh: bool = False


class OutOfScopeURLError(ValueError):
    """Raised when the crawler is asked to fetch a URL outside revitapidocs.com."""


class Crawler:
    def __init__(self, config: CrawlConfig):
        self.config = config
        self.config.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = HttpClient({"User-Agent": USER_AGENT})
        self._last_request_time: float = 0.0
        self.last_discovery_errors: list[str] = []

    # -- low-level fetch -------------------------------------------------

    def _cache_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.config.cache_dir / f"{digest}.htm"

    def _cache_meta_path(self, url: str) -> Path:
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
        return self.config.cache_dir / f"{digest}.meta.json"

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        wait = self.config.throttle_seconds - elapsed
        if wait > 0:
            time.sleep(wait)

    def fetch(self, url: str) -> str:
        """Fetch a URL, using the on-disk cache when available.

        Raises OutOfScopeURLError if the URL is not on revitapidocs.com, so a
        bug in link discovery cannot accidentally crawl the wider internet.
        """
        host = urlparse(url).netloc
        if host not in ALLOWED_HOSTS:
            raise OutOfScopeURLError(f"Refusing to fetch out-of-scope host: {host!r} ({url})")

        cache_path = self._cache_path(url)
        if cache_path.exists() and not self.config.force_refresh:
            return cache_path.read_text(encoding="utf-8", errors="replace")

        self._throttle()
        result = self.client.get(url, timeout=30)
        self._last_request_time = time.monotonic()

        cache_path.write_text(result.text, encoding="utf-8")
        self._cache_meta_path(url).write_text(
            json.dumps(
                {
                    "url": url,
                    "status_code": result.status_code,
                    "fetched_at": time.time(),
                    "content_length": len(result.text),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return result.text

    def is_cached(self, url: str) -> bool:
        return self._cache_path(url).exists()

    # -- discovery ---------------------------------------------------------

    def version_root_url(self) -> str:
        return f"{self.config.base_url}/{self.config.version}/"

    def namespace_json_url(self) -> str:
        return f"https://{NAMESPACE_JSON_HOST}/static/json/namespace_{self.config.version}_min.json"

    def discover_via_namespace_json(self) -> tuple[list[dict], list[str]]:
        """Fetch and flatten the site's client-side namespace/TOC JSON.

        Confirmed shape: a single root node ``{"title": "Namespaces", ...,
        "children": [...]}`` whose children are namespace nodes (``tag":
        "Namespace"``), each containing a tree of Class/Struct/Enum/
        Interface nodes, each of those containing Members/Methods/
        Properties nodes, down to individual Method/Property/Constructor
        pages (an overloaded method is its own node with both an ``href``
        -- an overview page -- and ``children`` for each overload).

        Returns (entries, parser_notes). Every node with an ``href`` is
        included (tagged via ``discovered_via``) except the top-level
        Namespace nodes themselves, which are just overview pages, not
        something ``parse.py`` extracts anything from. Only the namespace
        subtree(s) whose name matches ``config.namespace_prefix`` (exactly,
        or as a dotted sub-namespace, e.g. ``Autodesk.Revit.DB.Architecture``
        under prefix ``Autodesk.Revit.DB``) are walked.
        """
        notes: list[str] = []
        url = self.namespace_json_url()
        try:
            text = self.fetch(url)
        except Exception as exc:  # noqa: BLE001 - see discover_index's philosophy
            msg = f"namespace_json fetch failed: {exc!r} (url={url})"
            notes.append(msg)
            logger.warning("discover_via_namespace_json: %s", msg)
            return [], notes

        try:
            tree = json.loads(text)
        except Exception as exc:  # noqa: BLE001
            msg = f"namespace_json parse failed: {exc!r}"
            notes.append(msg)
            logger.warning("discover_via_namespace_json: %s", msg)
            return [], notes

        roots = tree if isinstance(tree, list) else [tree]
        namespace_nodes = []
        for root in roots:
            for child in root.get("children", []) or []:
                title = child.get("title", "")
                ns_name = title[: -len(" Namespace")] if title.endswith(" Namespace") else title
                if ns_name == self.config.namespace_prefix or ns_name.startswith(f"{self.config.namespace_prefix}."):
                    namespace_nodes.append(child)

        if not namespace_nodes:
            notes.append(
                f"no namespace node in {url!r} matched prefix {self.config.namespace_prefix!r} "
                "(site's namespace naming may have changed, or the JSON's shape did)"
            )
            return [], notes

        version_root = self.version_root_url()
        entries: dict[str, dict] = {}
        for ns_node in namespace_nodes:
            ns_title = ns_node.get("title", "")
            ns_name = ns_title[: -len(" Namespace")] if ns_title.endswith(" Namespace") else ns_title
            for child in ns_node.get("children", []) or []:
                self._flatten_namespace_node(child, version_root, entries, ns_name, None)
        if not entries:
            notes.append(f"matched namespace node(s) but found no page hrefs under them: {[n.get('title') for n in namespace_nodes]}")
        return list(entries.values()), notes

    # Tags whose own node represents a type (as opposed to a Members/Methods/
    # Properties grouping node or an individual Method/Property/Constructor
    # page) -- these establish a new declaring_type_hint for their descendants.
    _TYPE_LEVEL_TAGS = {"Class", "Struct", "Structure", "Interface", "Enumeration", "Enum"}

    def _flatten_namespace_node(
        self,
        node: dict,
        version_root: str,
        out: dict[str, dict],
        namespace: str,
        declaring_type_hint: str | None,
    ) -> None:
        href = node.get("href")
        tag = node.get("tag", "")
        title = node.get("title", "")

        # A type-level node's own children (Members/Methods/Properties/Method/
        # Property groups) belong to *this* type -- not whatever type_hint was
        # passed in from further up (relevant for nested namespaces/types).
        if tag in self._TYPE_LEVEL_TAGS:
            short_name = _strip_kind_suffix(title)
            declaring_type_hint = f"{namespace}.{short_name}" if namespace else short_name

        if href:
            absolute = urljoin(version_root, href)
            entry = {"url": absolute, "link_text": title, "discovered_via": f"namespace_json:{tag}"}
            if declaring_type_hint is not None:
                entry["declaring_type_hint"] = declaring_type_hint
            out.setdefault(absolute, entry)

        for child in node.get("children", []) or []:
            self._flatten_namespace_node(child, version_root, out, namespace, declaring_type_hint)

    def discover_targeted(self, target_full_type_names: list[str]) -> tuple[list[dict], dict[str, bool], list[str]]:
        """Fetch the namespace JSON and flatten only the subtree(s) for
        specific fully-qualified type names -- for a scoped validation crawl
        against a short target list instead of a full-namespace crawl.

        Unlike ``discover_via_namespace_json`` (which walks every type under
        a namespace-prefix match), this walks the *entire* tree looking for
        an exact fully-qualified-name match, so targets don't need to share
        a namespace. Returns (entries, found_by_target, notes):
        ``found_by_target`` maps each requested name to whether a matching
        Class/Struct/Enum/Interface node was located anywhere in the tree.
        """
        notes: list[str] = []
        target_set = set(target_full_type_names)
        found: dict[str, bool] = {t: False for t in target_full_type_names}

        url = self.namespace_json_url()
        try:
            text = self.fetch(url)
        except Exception as exc:  # noqa: BLE001 - see discover_index's philosophy
            msg = f"namespace_json fetch failed: {exc!r} (url={url})"
            notes.append(msg)
            logger.warning("discover_targeted: %s", msg)
            return [], found, notes

        try:
            tree = json.loads(text)
        except Exception as exc:  # noqa: BLE001
            msg = f"namespace_json parse failed: {exc!r}"
            notes.append(msg)
            logger.warning("discover_targeted: %s", msg)
            return [], found, notes

        version_root = self.version_root_url()
        entries: dict[str, dict] = {}

        def walk(node: dict, namespace: str) -> None:
            tag = node.get("tag", "")
            title = node.get("title", "")

            if tag == "Namespace" and title.endswith(" Namespace"):
                namespace = title[: -len(" Namespace")]

            if tag in self._TYPE_LEVEL_TAGS:
                short_name = _strip_kind_suffix(title)
                full_name = f"{namespace}.{short_name}" if namespace else short_name
                if full_name in target_set:
                    found[full_name] = True
                    self._flatten_namespace_node(node, version_root, entries, namespace, None)
                    return  # already fully flattened (including all descendants) above

            for child in node.get("children", []) or []:
                walk(child, namespace)

        roots = tree if isinstance(tree, list) else [tree]
        for root in roots:
            walk(root, "")

        missing = [t for t, was_found in found.items() if not was_found]
        if missing:
            notes.append(f"target class(es) not found in namespace_json tree: {missing}")
        if not entries:
            notes.append("no target class pages found -- see 'target class(es) not found' note above, if any")

        return list(entries.values()), found, notes

    def discover_index(self) -> list[dict]:
        """Discover candidate page URLs for the configured namespace.

        Returns a list of dicts with at least ``url``, ``link_text``, and
        ``discovered_via`` (which strategy produced the link), suitable for
        writing straight to ``raw_index.json``. Entries are de-duplicated by
        URL.

        Strategy (tried in order, all results merged):
        1. Fetch and flatten the client-side namespace/TOC JSON
           (``discover_via_namespace_json``) -- the authoritative page index
           on the live site; see that method's docstring.
        2. Parse every ``<a href>`` on the version root page.
        3. Look for a Sandcastle-style TOC data file (``toc.js``,
           ``webtoc.xml``, ``toc.json`` — the exact name varies by
           Sandcastle presentation theme) linked from the root page, fetch
           it, and pull hrefs/ids out of it if it looks like HTML/XML/JSON.
        4. If a same-host sitemap.xml exists, pull any URLs under the
           version path.

        Every strategy is defensive: a failure in one does not abort the
        others, and is recorded in the returned entries'
        ``discovery_errors`` rather than raised, since the whole point of
        this function is "find what you can, and be honest about what you
        couldn't."
        """
        root_url = self.version_root_url()
        found: dict[str, dict] = {}
        errors: list[str] = []

        json_entries, json_errors = self.discover_via_namespace_json()
        found.update({e["url"]: e for e in json_entries})
        errors.extend(json_errors)

        try:
            html = self.fetch(root_url)
            found.update(self._links_from_html(html, root_url, "root_page_anchor"))
        except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
            msg = f"root_page fetch/parse failed: {exc!r}"
            errors.append(msg)
            logger.warning("discover_index: %s (root_url=%s)", msg, root_url)

        for toc_name in ("toc.js", "webtoc.xml", "toc.json", "toc.html"):
            toc_url = urljoin(root_url, toc_name)
            try:
                toc_text = self.fetch(toc_url)
            except Exception:  # noqa: BLE001 - most of these won't exist, that's fine
                continue
            try:
                found.update(self._links_from_html(toc_text, toc_url, f"toc_file:{toc_name}"))
            except Exception as exc:  # noqa: BLE001
                msg = f"{toc_name} parse failed: {exc!r}"
                errors.append(msg)
                logger.warning("discover_index: %s", msg)

        sitemap_url = urljoin(self.config.base_url, "/sitemap.xml")
        try:
            sitemap_text = self.fetch(sitemap_url)
            found.update(self._links_from_sitemap_xml(sitemap_text, sitemap_url))
        except Exception:  # noqa: BLE001 - optional source
            pass

        self.last_discovery_errors = errors
        entries = list(found.values())
        for entry in entries:
            entry["discovery_errors"] = errors
        if not entries and errors:
            logger.warning(
                "discover_index found 0 pages and encountered %d error(s) above -- "
                "this almost always means fetching failed (network/proxy/TLS/site "
                "reachability), not that the site has no content.",
                len(errors),
            )
        if self.config.max_pages is not None:
            entries = entries[: self.config.max_pages]
        return entries

    def _links_from_html(self, text: str, source_url: str, discovered_via: str) -> dict[str, dict]:
        found: dict[str, dict] = {}
        soup = BeautifulSoup(text, "html.parser")
        for anchor in soup.find_all("a", href=True):
            href = anchor["href"]
            absolute = urljoin(source_url, href)
            if urlparse(absolute).netloc != ALLOWED_HOST:
                continue
            if f"/{self.config.version}/" not in absolute:
                continue
            found[absolute] = {
                "url": absolute,
                "link_text": anchor.get_text(strip=True),
                "discovered_via": discovered_via,
            }

        # Sandcastle TOC data files are sometimes JS/JSON rather than HTML;
        # BeautifulSoup won't find <a> tags in those, so also regex out any
        # revitapidocs.com URLs or bare GUID-style page ids embedded as
        # string literals (e.g. `"id":"69712dc1-..."` in a toc.json).
        for match in re.finditer(r'["\'](/?' + re.escape(self.config.version) + r'/[0-9a-fA-F-]{8,}\.htm)["\']', text):
            absolute = urljoin(self.config.base_url, match.group(1))
            found.setdefault(
                absolute,
                {"url": absolute, "link_text": "", "discovered_via": f"{discovered_via}:regex_guid"},
            )
        return found

    def _links_from_sitemap_xml(self, text: str, source_url: str) -> dict[str, dict]:
        """A sitemap.xml lists pages as ``<url><loc>...</loc></url>``, not
        ``<a href>`` -- ``_links_from_html``'s BeautifulSoup/regex approach
        never matches that shape (and, parsing genuine XML with an HTML
        parser, only earns a noisy ``XMLParsedAsHTMLWarning``). Extract
        ``<loc>`` text directly via the stdlib XML parser instead.
        """
        found: dict[str, dict] = {}
        try:
            root = ElementTree.fromstring(text)
        except ElementTree.ParseError:
            return found
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] != "loc" or not element.text:
                continue
            absolute = urljoin(source_url, element.text.strip())
            if urlparse(absolute).netloc != ALLOWED_HOST:
                continue
            if f"/{self.config.version}/" not in absolute:
                continue
            found[absolute] = {"url": absolute, "link_text": "", "discovered_via": "sitemap_xml"}
        return found
