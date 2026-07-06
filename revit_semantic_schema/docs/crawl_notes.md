# Crawl notes

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
