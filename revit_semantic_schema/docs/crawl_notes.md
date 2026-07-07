# Crawl notes

## Targeted validation crawl (`--targeted-validation`)

Built on `claude/targeted-validation-crawl` (branched off the crawler/parser fix work in PR #1)
in a session that again had no live network access to revitapidocs.com or its CDN (confirmed
blocked, same as the "Network access limitation" section below). Everything --
`Crawler.discover_targeted`, the `TargetReportEntry`/`KnownEdgeCheckResult` reporting,
`classify.classify_class_role`, `run_targeted_pipeline`, and `validation_summary.md` -- is
unit-tested against synthetic namespace-JSON trees and HTML fixtures modeled on the real
markup confirmed earlier in this file, but **has not yet been run against the live site**. The
target list (`pipeline.DEFAULT_TARGET_CLASSES`) and known-edge checks
(`pipeline.DEFAULT_KNOWN_EDGE_CHECKS`) are exactly what the brief specified; running
`python -m revit_schema_mapper --version 2024 --targeted-validation --verbose` (with
`REVIT_SCHEMA_MAPPER_RELAX_TLS_STRICT=1` if needed) against a network-enabled environment and
reading `validation_summary.md` is the next real validation step -- treat its
definition-of-done checklist (section 7) as the thing to check first.

### Two bugs found and fixed by code review before any live run

1. **Interfaces mis-tagged `utility_class`.** `build_node_candidates` includes `Kind.INTERFACE`
   pages, and `classify_class_role`'s "every member is a method, no properties" heuristic is
   exactly the normal shape of an interface (a contract), not a static helper bag. Any
   method-only interface (there are many in `Autodesk.Revit.DB`) would have been mis-tagged.
   Fixed: the utility-class checks (both the name-suffix and all-methods-no-properties ones)
   are now skipped entirely for `Kind.INTERFACE`, which falls through to `unknown` instead.
   Covered by `test_class_role_interface_with_only_methods_is_not_utility_class` and
   `test_class_role_interface_with_utils_like_name_is_not_utility_class`.
2. **Inherited members were mis-attributed to the wrong declaring type.** A real Members page
   lists both members declared on the type itself and members inherited from a base type (e.g.
   the real `Wall Members` page fixture lists `ArePhasesModifiable`, inherited from `Element`,
   with `data="public;inherited;notNetfw;"` and "(Inherited from Element.)" in its description
   cell). `parse_members_index_page`/`extract_member_links` previously ignored this and always
   returned the *current* type as the link's declaring type, which `pipeline.py` used verbatim
   whenever the inherited member's URL wasn't already known (e.g. a `--max-pages`-truncated
   smoke crawl, or a targeted crawl of `Wall` alone that never reaches `Element`) --
   fabricating false pages/edges like `Autodesk.Revit.DB.Wall.ArePhasesModifiable`. In a full
   crawl covering both types this was usually masked (whichever type's Members page was
   processed *first* won the URL in `by_url`), which is why it wasn't caught earlier. Fixed:
   both functions now check each row's `data` attribute for `inherited` and, when set, resolve
   the real owner from the row's own "(Inherited from X.)" text (regex `_row_inherited_from`),
   emitting a `declaring_type_hint` that `pipeline.py`'s `enqueue_member_links` now prefers over
   the caller-supplied type name. A row that's inherited but has no parseable owner text is
   skipped entirely rather than guessed. Covered by
   `test_parse_members_index_page_resolves_full_namespace_for_inherited_row`,
   `test_extract_member_links_preserves_inherited_ownership`, and an end-to-end regression test,
   `test_targeted_crawl_of_wall_alone_attributes_inherited_member_to_element` (verified to fail
   with the exact false attribution before the fix, pass after).

## Target version: 2027, with a documented fallback

The brief asks to start with Revit 2027 docs on revitapidocs.com and fall back to 2026
only if 2027 is unavailable or structurally inconsistent, with the reason documented.

**This has not yet been decided empirically**, because of the network limitation below.
`python -m revit_schema_mapper --version 2027` is the default; if a real run finds that
`https://www.revitapidocs.com/2027/` 404s, redirects, or has a members-table/syntax-block
structure the parser can't extract from at all (i.e. `parser_notes` on nearly every page),
re-run with `--version 2026 --fallback-reason "<what broke on 2027>"` and that reason will be
recorded in `summary.md` section 1 automatically.

## Network access limitation encountered while building this (2026-07-06)

This project's crawler, parser, classifier, and test suite were built and unit-tested in a
sandboxed session whose network egress policy blocked **all** outbound HTTP(S) traffic,
including to revitapidocs.com. This was confirmed two independent ways:

- Direct `curl` to `https://www.revitapidocs.com/` failed at the TLS-tunnel stage; the
  session's egress proxy status endpoint logged `connect_rejected ... policy denial` for
  `www.revitapidocs.com:443`.
- The environment's `WebFetch` tool returned HTTP 403 for `https://www.revitapidocs.com/`
  *and* for `https://example.com/`, indicating a blanket network policy for that session
  rather than anything specific to revitapidocs.com (e.g. bot-blocking).

Consequence: **no page in this repository's `outputs/revit_2027/` was produced by crawling
the live site.** Everything in `crawl.py` / `parse.py` was written from general knowledge of
how Sandcastle-generated API doc sites (which is what revitapidocs.com is) are typically
structured, and validated only against hand-written fixture HTML under `tests/fixtures/`
that approximates that structure. This is explicitly called out so nobody mistakes the
current `tests/fixtures/*.htm` for real scraped pages, and so the first real run is treated
as a validation pass rather than assumed correct.

### What to check on the first real run

Run with a small page cap first so a structural mismatch is cheap to notice:

```
python -m revit_schema_mapper --version 2027 --max-pages 25 --verbose
```

Then:

1. Open `outputs/revit_2027/api_pages.json` and grep for `"parser_notes"` — any non-empty
   list means a selector assumption in `parse.py` didn't hold for that page. The most likely
   candidates to need adjustment, in order of how much they'd affect the rest of the
   pipeline: `_SYNTAX_SELECTORS` (base type / return type extraction depends entirely on
   finding the syntax block), `_MEMBERS_TABLE_SELECTORS`, `_NAMESPACE_SELECTORS`.
2. Check `discover_index()`'s `discovery_errors` field on `raw_index.json` entries — if the
   root-page-anchor strategy failed, the crawl may be relying entirely on the regex-GUID
   fallback, which will under-count pages that don't follow the assumed
   `{version}/{guid}.htm` URL pattern.
3. Compare `len(raw_index.json)` to a rough expectation: Autodesk.Revit.DB has on the order
   of a few thousand types plus tens of thousands of members. A count in the low hundreds or
   fewer is a strong signal that discovery stopped early.

## Confirmed findings from a real run (2026-07, user-provided page source)

The network limitation above was resolved in a follow-up session with a real Windows/corporate
machine that could reach the live site (after working around a TLS-inspection-proxy
compatibility issue -- see `REVIT_SCHEMA_MAPPER_RELAX_TLS_STRICT` in `http_compat.py`). The
user pasted real page source (Revit 2024, `Wall` class) and screenshots, which corrected
several of the original guesses in `parse.py`:

1. **The version root page's `<a href>` anchors are not the type index; a client-side JSON
   file is.** The left-hand TOC/search is populated from a static JSON file
   (`https://d24b2zsrnzhmgb.cloudfront.net/static/json/namespace_<version>_min.json`,
   referenced via `var namespaceJson = ...` in every page's script block) via AJAX, not
   server-rendered links. `discover_index()`'s original `root_page_anchor` strategy was
   structurally incapable of finding more than a handful of junk links (confirmed: it found
   only `/2024/`, `/2024/#`, `/2024/news` on a real run, with `Pages parsed: 0` as a
   consequence -- not a parser bug, a discovery bug). **Confirmed and fixed**: the user shared
   a real excerpt of this JSON. Shape: a single root node `{"title": "Namespaces", "children":
   [...]}` whose children are namespace nodes (`"tag": "Namespace"`), each holding a tree of
   Class/Struct/Enum/Interface nodes, each holding Members/Methods/Properties nodes, down to
   individual Method/Property/Constructor pages (an overloaded method is its own node with
   both an `href` -- an overview page -- and `children` for each overload). `crawl.py` now
   fetches and flattens this via `Crawler.discover_via_namespace_json`, filtering to namespace
   nodes whose name equals or dot-extends `config.namespace_prefix` (so `Autodesk.Revit.DB`
   and `Autodesk.Revit.DB.Architecture` both qualify), and this runs as the *first* (most
   authoritative) strategy in `discover_index()`, with the old HTML-scraping strategies kept
   as a defensive fallback. `tests/test_crawl.py` covers this against a synthetic tree modeled
   on the real excerpt (namespace filtering, sub-namespace inclusion, overloaded-method
   flattening).

   **First real run of this hit a second bug**: `namespace_json parse failed:
   JSONDecodeError('Expecting value: line 1 column 1 (char 0)')`. That specific message is the
   signature of decoding *raw gzip bytes* as UTF-8 (the gzip magic byte isn't valid UTF-8, so it
   becomes a replacement character at position 0) -- not an empty response. This CDN-hosted
   `*_min.json` asset is served with `Content-Encoding: gzip`; `requests`/browsers decompress
   that transparently, but the plain-`urllib.request` fallback path did not. Fixed in
   `http_compat.py`: the urllib path now checks `Content-Encoding` and decompresses
   gzip/deflate (including raw/headerless deflate) before decoding as text.
   `tests/test_http_compat.py` reproduces this against a real local HTTP server serving
   gzip/deflate-encoded responses (not just a unit-level assumption).

   **After that fix, a real run reached 72 discovered / 6 parsed pages** (real class/enum data
   extracted correctly -- `ACADVersion`, `ACAObjectPreference`), but 41 pages still failed. Two
   more real bugs, both a direct consequence of the namespace JSON finding pages a lot more
   directly than the old "follow links from a class page" model assumed:
   - **Standalone "`<Type>` Methods"/"`<Type>` Properties" pages** (tags `"Methods"`/
     `"Properties"`, distinct from the combined `"Members"` page -- the real site has both) were
     not recognized by `sniff_kind()` at all (`_TITLE_KIND_SUFFIXES` only had singular
     `"Method"`/`"Property"` and `"Members"`). Fixed: added plural `"Methods"`/`"Properties"` ->
     `Kind.MEMBERS_INDEX` too; `parse_members_index_page`'s section-heading tracking degrades
     gracefully (member_kind stays `None`) if such a page has no heading of its own.
   - **Individual Property/Method pages discovered directly via the namespace JSON never got a
     `declaring_type`.** The only mechanism that threaded a declaring type through was "reached
     by following a class's Members-page link" (`member_queue` in `pipeline.py`); pages found
     directly by JSON flattening bypass that path entirely and were being skipped with "no known
     declaring type" -- silently inflating the failed-page count, not a parser problem on those
     specific pages. Fixed: `Crawler._flatten_namespace_node` now threads the enclosing type's
     fully-qualified name through as `declaring_type_hint` on every leaf entry (computed once,
     at the type-level node, from its own title + the enclosing namespace); `pipeline.py` falls
     back to `by_url[url]["declaring_type_hint"]` when `member_queue` doesn't have an entry.
     `tests/test_pipeline.py` has an end-to-end regression test for exactly this scenario
     (verified it fails with the old "has no known declaring type; skipping" warning before the
     fix, passes after).
   - Also noticed: some inherited `Object` members (`Equals`, `GetHashCode`, `ToString`) link out
     to `msdn2.microsoft.com` on some real pages (rather than rendering as an unlinked
     `<span class=nolink>` like the `Wall` fixture) -- correctly out-of-scope per
     `ALLOWED_HOST`, but were inflating the failed-page count for what's actually correct
     behavior. `enqueue_member_links` in `pipeline.py` now filters these out before enqueueing
     rather than letting them fail downstream.
2. **A class/struct/interface page does not embed its members table inline.** It links out to
   a separate "`<Type> Members`" page via a shared sub-nav (`table#bottomTable`, e.g. "Members
   | Example | See Also" on a class page, "`<Type>` Class | Methods | Properties | See Also" on
   its Members page). The Members page holds two `table.members`/`table#memberList` tables
   (Methods, then Properties, in that order) under `h1.heading` section headers, each row
   `[icon `<td>`, name+link `<td>`, description `<td>`]`. Fixed in `parse.py`:
   `find_members_page_link` finds the class page's "Members" link; `parse_members_index_page`
   parses the Members page into typed (Methods/Properties) member links; both are wired into
   `pipeline.py` right after a class/struct/interface page is parsed. `tests/fixtures/real_wall_members.htm`
   is the actual fetched HTML (trimmed), used to lock this in with real assertions rather than
   guesses.
3. **The page title lives in `<h4 id="api-title">`, not `<h1>` or `#PageHeader`.** Those two
   never appear in real markup; `_parse_title` now checks `#api-title` first and keeps the old
   selectors as fallbacks in case older cached years render differently.
4. **The namespace breadcrumb is also client-side-rendered** (`<ul class="breadcrumb">` is an
   empty placeholder filled by JS), so the original `_NAMESPACE_SELECTORS` never matched
   real pages. The same embedded `templateData` JS object has a reliable
   `"namespace": "Autodesk.Revit.DB"` field; `_parse_namespace` now regex-extracts it first and
   falls back to the breadcrumb/text scan for older cached years.
5. **A member row's name/link is in the *second* `<td>` (`[icon, name, description]`), not the
   first** -- the first cell is an icon `<img>` with no text. This silently broke
   `extract_member_links` (always returned `[]`) and `parse_type_page`'s inline-table branch
   (every row skipped, no name found). Fixed via a shared `_member_name_cell` helper.
6. **Real markup is not well-formed**: attribute values are frequently unquoted
   (`<a href=foo.htm>`), and at least one `<div>` (`div.saveHistory`) is never explicitly
   closed, so everything downstream nests inside it rather than being a sibling. Confirmed the
   stdlib-`html.parser`-based fallback (`html_compat.py`) handles unquoted attributes
   correctly; the unclosed-div case is why `parse_members_index_page` walks `.descendants`
   (full document-order traversal) rather than direct children only.
7. Some inherited members (e.g. `Object.Equals`, `GetHashCode`, `GetType`, `ToString`) render
   as `<span class=nolink>Name</span>` with no link -- they have no page of their own.
   `parse_members_index_page` correctly omits these rather than trying to crawl a URL that
   doesn't exist.

None of this has been re-validated against a full real crawl yet (only against pasted single-page
source) -- treat the next full `--version 2024`/`2027` run as the next validation checkpoint,
per "What to check on the first real run" above.

## Politeness / resumability design

- Custom `User-Agent` (see `crawl.USER_AGENT`) identifies the bot and its purpose.
- `CrawlConfig.throttle_seconds` (default 1.5s) enforces a minimum gap between requests.
- Every fetched page is cached to `outputs/revit_<version>/cache/<sha256(url)>.htm` plus a
  `.meta.json` sidecar recording status code and fetch time. A re-run of the same command
  reuses the cache and does not re-fetch unless `--force-refresh` is passed.
- `Crawler.fetch` refuses (raises `OutOfScopeURLError`) any URL whose host isn't
  `www.revitapidocs.com`, so a link-discovery bug cannot wander off-site.
- The crawl is resumable in the sense that re-running the same command against a partially
  filled cache directory will skip every already-cached URL and only fetch what's missing;
  it is not currently checkpointed mid-page-list, so an interrupted run should simply be
  re-run rather than resumed from a saved cursor.

## No-install-required fallback (`http_compat.py` / `html_compat.py`)

`requests` and `beautifulsoup4` are optional (`pip install -e ".[fast]"`), not required. When
either is missing, `crawl.py`/`parse.py` transparently fall back to stdlib-only equivalents:

- `http_compat.HttpClient` uses `requests.Session` when installed, otherwise
  `urllib.request` with the same headers/timeout/error semantics.
- `html_compat.MiniSoup`/`MiniTag` is a small dependency-free HTML tree built on
  `html.parser.HTMLParser`, with a CSS-selector engine scoped to exactly the selector shapes
  used elsewhere in this codebase (tag/`#id`/`.class`/`:first-of-type`, descendant and child
  combinators) — not a general CSS implementation. See that module's docstring before adding
  a selector shape it doesn't already support.

`python -m revit_schema_mapper ... --verbose` logs which backend (requests vs. urllib,
beautifulsoup4 vs. html_compat) is active for a given run. The full test suite passes
identically under both configurations — verified by running `pytest` with neither package
installed, then again with both installed via `pip install -e ".[fast]"`.

This matters for restricted corporate environments where installing packages from PyPI needs
IT approval: a bare `pip install -e ".[dev]"` (pytest only) is enough to run the whole
pipeline against the live site, no approval needed for `requests`/`beautifulsoup4`.

## Why member pages are discovered from class pages, not just the index/TOC

Sandcastle-style sites list a type's members with links to their own property/method pages
directly on the type's page. The pipeline (`pipeline.run_pipeline`) treats those links as a
second, generally more reliable discovery source and queues them alongside whatever
`discover_index()` found from the root page / TOC / sitemap, tagging them
`members_table_of:<FullTypeName>` in `raw_index.json` so it's traceable which page a given
member URL came from.
