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

DEPENDENCY FALLBACK: ``requests`` and ``beautifulsoup4`` are used when
installed (they're faster and more robust), but neither is required --
``http_compat``/``html_compat`` provide equivalent behavior on top of
``urllib.request``/``html.parser`` alone, so this runs on a bare Python
install with no third-party packages. See those modules for scope/limits.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    from bs4 import BeautifulSoup
except ImportError:
    from .html_compat import MiniSoup as BeautifulSoup

from .http_compat import HttpClient

USER_AGENT = (
    "RevitSemanticSchemaMapper/0.1 "
    "(+https://github.com/gmcdowelljr/revit-semantic-schema-mapper; "
    "docs-crawler for a candidate Revit DB semantic schema; "
    "polite, throttled, caches locally)"
)

DEFAULT_THROTTLE_SECONDS = 1.5
ALLOWED_HOST = "www.revitapidocs.com"


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
        if host != ALLOWED_HOST:
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

    def discover_index(self) -> list[dict]:
        """Discover candidate page URLs for the configured namespace.

        Returns a list of dicts with at least ``url``, ``link_text``, and
        ``discovered_via`` (which strategy produced the link), suitable for
        writing straight to ``raw_index.json``. Entries are de-duplicated by
        URL.

        Strategy (tried in order, all results merged):
        1. Parse every ``<a href>`` on the version root page.
        2. Look for a Sandcastle-style TOC data file (``toc.js``,
           ``webtoc.xml``, ``toc.json`` — the exact name varies by
           Sandcastle presentation theme) linked from the root page, fetch
           it, and pull hrefs/ids out of it if it looks like HTML/XML/JSON.
        3. If a same-host sitemap.xml exists, pull any URLs under the
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

        try:
            html = self.fetch(root_url)
            found.update(self._links_from_html(html, root_url, "root_page_anchor"))
        except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
            errors.append(f"root_page fetch/parse failed: {exc!r}")

        for toc_name in ("toc.js", "webtoc.xml", "toc.json", "toc.html"):
            toc_url = urljoin(root_url, toc_name)
            try:
                toc_text = self.fetch(toc_url)
            except Exception:  # noqa: BLE001 - most of these won't exist, that's fine
                continue
            try:
                found.update(self._links_from_html(toc_text, toc_url, f"toc_file:{toc_name}"))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{toc_name} parse failed: {exc!r}")

        sitemap_url = urljoin(self.config.base_url, "/sitemap.xml")
        try:
            sitemap_text = self.fetch(sitemap_url)
            found.update(self._links_from_html(sitemap_text, sitemap_url, "sitemap_xml"))
        except Exception:  # noqa: BLE001 - optional source
            pass

        entries = list(found.values())
        for entry in entries:
            entry["discovery_errors"] = errors
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
