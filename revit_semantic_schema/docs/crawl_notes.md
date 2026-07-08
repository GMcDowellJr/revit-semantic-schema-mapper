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

   **A second review pass found the "already known" guard in `enqueue_member_links` still let
   this leak through.** The namespace JSON's flatten (`Crawler._flatten_namespace_node`)
   structurally nests every page it finds under whichever type node contains it, without any
   notion of inheritance -- if it lists an inherited member (e.g. `ArePhasesModifiable`) directly
   under the *derived* type's own subtree (plausible/likely, mirroring what the Members page
   itself displays), that URL lands in `by_url` with `declaring_type_hint="...Wall"` *before* the
   real Members page is ever fetched. The original fix only set `declaring_type_hint` when
   creating a *new* `by_url` entry (`if url not in by_url`); when the real Members-page row parse
   later resolved the true owner (`Element`), the `elif`-less guard silently discarded that
   correction because the URL was already known, leaving the stale `Wall` hint in place. Fixed:
   `enqueue_member_links` now updates an existing `by_url` entry's `declaring_type_hint` in place
   when a row supplies its own explicit, resolved hint that differs from what's stored (only for
   a URL not yet fetched); the per-iteration lookup in the crawl loop also now checks `by_url`
   before the `member_queue` list, so a correction always wins over whatever was recorded at
   enqueue time. Covered by
   `test_preseeded_inherited_member_url_gets_corrected_by_members_page_parse` (verified to fail
   with the exact false attribution before this second fix, pass after).

### First live confirmation: a real run (Raspberry Pi, 2026-07) found a real parser gap

Namespace-JSON discovery reached real GUID-style pages (confirmed reachable from that
network), but many logged `unrecognized page kind for <url>; skipping`. Inspecting a cached
page (`Element.ChangeTypeId`'s overload pages) showed the actual title:
`ChangeTypeId Method (ElementId)` and `ChangeTypeId Method (Document, ICollection(ElementId),
ElementId)`. Sandcastle gives each overload of an overloaded method its own page, with the
parameter-type list appended *after* the kind suffix -- so `_parse_title`'s
`raw_title.strip().endswith("Method")` check never matched (the title actually ends in `)`),
and both kind detection and `_strip_kind_suffix`'s name extraction failed for every overloaded
method's own page. Fixed: `_strip_trailing_overload_signature` walks back from the end of the
title tracking paren depth (a regex can't do this correctly, since the parameter list itself
can contain parens, e.g. `ICollection(ElementId)`) and strips a trailing, possibly-nested
`(...)` group before kind-suffix matching in both `_parse_title` and `_strip_kind_suffix`; the
returned `raw_title` itself is unchanged. Covered by
`test_strip_trailing_overload_signature_single_param`,
`test_strip_trailing_overload_signature_nested_parens`,
`test_sniff_kind_recognizes_overloaded_method_page`, and
`test_parse_member_page_overloaded_method_title`, using the exact real titles found on the Pi.

### First full targeted-validation-crawl run (Raspberry Pi, 2024): clean, plus two real findings

After the two fixes above, a full `--targeted-validation` run against Revit 2024 came back
clean: **13/13 target classes found and parsed, 508 pages discovered, 469 parsed, 0 failed
pages, 165 edge candidates** (48 property-based, 117 method-based). All definition-of-done
checklist items passed. Two of the nine known-edge checks initially looked like coverage gaps
but turned out to be real, useful findings rather than bugs:

1. **`Material.SurfacePatternId`/`CutPatternId` don't exist in the real Revit 2024 API.**
   Confirmed by listing every member actually found under `Material` in that run: the real
   properties are `CutBackgroundPatternId`, `CutForegroundPatternId`,
   `SurfaceBackgroundPatternId`, and `SurfaceForegroundPatternId` -- Revit apparently split
   each pattern into separate background/foreground layers at some point, deprecating the
   singular names. `DEFAULT_KNOWN_EDGE_CHECKS` deliberately keeps checking the original
   (brief-specified, "if present") names rather than the confirmed real ones, since the
   check's job is to honestly report whether that exact hypothesis holds, not to quietly
   correct itself -- and it now correctly reports "member page was not crawled/parsed" for
   both, which is the accurate answer.
2. **`Room.Number` is inherited from an intermediate base class between `Room` and `Element`,
   not declared on `Room` itself** (`Room : SpatialElement : Element`) -- confirmed by finding
   the parsed `Number` property page's `declaring_type` directly. This refines the "Room / Room
   Number / Room Name" hypothesis in the README: `Name` (from `Element`) and `Number` (from
   `SpatialElement`) reach the object model through the *same* mechanism (an inherited base
   property), just at different levels of the inheritance chain, not two different mechanisms
   as originally guessed. This exposed a real reporting bug: `_build_known_edge_report` was
   reporting this as "**NOT CRAWLED**" (implying a coverage gap) when the member had, in fact,
   been crawled and correctly attributed -- just not to the type the check happened to name.
   Fixed: when the exact (declaring_type, member_name) pair isn't found, the report now also
   checks whether that member name was found under a *different* declaring type before
   concluding it's genuinely missing, and reports `actual_declaring_type` plus an explanatory
   note when so. Covered by
   `test_known_edge_report_resolves_member_found_under_different_declaring_type` and
   `test_known_edge_report_genuinely_missing_member_is_not_confused_with_cross_type_match`.

   **Correction**: that live run's exact fully-qualified name for the resolved owner --
   `Autodesk.Revit.DB.Architecture.SpatialElement` -- was itself wrong, produced by the
   namespace-mis-qualification bug described just below. A re-run with that fix should report
   the corrected fully-qualified name instead (most likely `Autodesk.Revit.DB.SpatialElement`,
   given that's where fundamental base types like `Element` live, but that's still an
   unconfirmed guess until an actual re-run says so).

### Three more bugs found by code review after the first live run

1. **Inherited owners were mis-qualified with the current page's own (sub-)namespace.**
   `Autodesk.Revit.DB.Architecture.Room`'s real base types (`Element`, `SpatialElement`) live in
   the top-level `Autodesk.Revit.DB` namespace, not in `.Architecture` -- but both
   `extract_member_links` and `parse_members_index_page` blindly prefixed an inherited row's
   owner with the *current page's* namespace, fabricating a nonexistent
   `Autodesk.Revit.DB.Architecture.Element`/`...SpatialElement` instead of the real
   `Autodesk.Revit.DB.Element`/`Autodesk.Revit.DB.SpatialElement`. This is exactly what produced
   the wrong fully-qualified name in finding 2 above. Fixed: `_resolve_inherited_owner_namespace`
   is a heuristic (documented as such) that falls back to the top-level `Autodesk.Revit.DB`
   namespace whenever the current page's own namespace is a sub-namespace of it -- the common
   real-world pattern (fundamental base types live at the top level) -- and only reuses the
   current namespace unchanged otherwise. Covered by
   `test_parse_members_index_page_does_not_qualify_inherited_owner_with_sub_namespace`
   (verified to fail with the exact fabricated sub-namespace owner before the fix, pass after).
2. **`known_edge_checks=[]` (an explicit "run no known-edge checks") was silently replaced with
   `DEFAULT_KNOWN_EDGE_CHECKS`.** `run_targeted_pipeline` used `known_edge_checks or
   DEFAULT_KNOWN_EDGE_CHECKS`, and `or` treats an empty list the same as `None` -- a caller
   deliberately passing `known_edge_checks=[]` (as the existing Wall-only tests already did) got
   9 unrelated default checks reported as "not crawled" in `known_edge_report.json`/
   `validation_summary.md` instead of an empty report. Fixed: explicit `is None` checks for both
   `known_edge_checks` and `target_full_type_names` (the same bug pattern applied to both
   parameters). Both existing Wall-only tests now assert `result.known_edge_report == []`
   (verified to fail with the leaked defaults before the fix, pass after).
3. **The known-edge cross-declaring-type fallback (finding 2's fix, above) matched *any*
   same-named member anywhere in the crawl, not just a confirmed base type of the expected
   type.** A common member name like `Name` or `Number` appears on many unrelated types; the
   fallback would have reported a genuinely missing check as "found" on whatever unrelated type
   happened to share the name, hiding the real coverage gap instead of reporting it honestly.
   Fixed: `_build_known_edge_report` now takes `node_candidates` too and restricts the fallback
   to declaring types in the expected type's own `NodeCandidate.inheritance_chain` (comparing by
   short name, since chain entries are sometimes short and sometimes fully-qualified depending
   on how much of the chain `classify.py` could resolve). Covered by
   `test_known_edge_report_rejects_same_named_member_on_unrelated_type` (verified to fail with
   an unrelated `Wall.Number` incorrectly matching a `Room.Number` check before the fix, pass
   after).

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

## Confirmed findings from a real 2025 run (2026-07, user-provided page source)

A real `--version 2025 --verbose` run (Raspberry Pi) logged `members table found under
unrecognized section heading None` on every "<Type> Members"/"<Type> Properties" page it
parsed. Not crawl-breaking (`0 failed`, since `parse_member_page` independently re-derives each
member's own `MemberKind` from its own page later), but a real 2025 markup change nonetheless:
the user pasted a real cached page (`ACADExportOptions Properties`, from the run's own
`outputs/revit_2025/cache/` -- every fetched page is cached locally keyed by
`sha256(url)`, so pulling the exact page a log line complained about needs no re-fetch).

**2025 dropped the 2024 `h1.heading` section marker.** Each Methods/Properties section is now a
collapsible region instead: `<div class=collapsibleAreaRegion><span
class=collapsibleRegionTitle tabindex=0><img class=collapseToggle
src='.../sectionexpanded.png'> Properties</span></div><div class=collapsibleSection
id=IDADASection><table class=members>...</table></div>` (attribute values unquoted, consistent
with the unquoted-attribute finding from the 2024 run above). The section name is the `<span
class=collapsibleRegionTitle>`'s trailing text after its icon `<img>` (which has no text of its
own). Fixed: `parse_members_index_page` now also recognizes
`<span class=collapsibleRegionTitle>` as a section-heading marker, in addition to (not instead
of) `h1.heading` -- 2025's markup change doesn't necessarily mean every still-cached older year
uses the new form. Covered by
`test_parse_members_index_page_recognizes_2025_collapsible_region_headings`, modeled on the
real pasted snippet (methods + properties collapsible regions in one page).

Everything else confirmed on this page matched the 2024 findings unchanged: `h4#api-title` for
the title, unquoted attributes, `[icon, name, description]` row shape via `_member_name_cell`,
and the "Top"/"See Also" nav following the last table.

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

## Stage A (`reflect_revit_api.ps1`): first real run, no Windows/Revit access (2026-07-08)

Building `docs/dll_reflection_v0.md`'s Stage A tool in a sandbox with **no Windows machine and
no Revit installation reachable at all** -- the same kind of hard constraint as the "Network
access limitation" section above, just for a different resource. Rather than write the whole
script against the design doc alone and call it done, the same write-run-look-fix loop was
applied against the closest real substitute available: this sandbox's own PowerShell host and
its own real, compiled .NET assemblies (not Revit's, but genuinely real, genuinely reflected
over, not fixture data).

### Step 1: which PowerShell host is this machine, actually?

Checked directly rather than assumed, per the design doc's own instruction: `uname -a` /
`/etc/os-release` show Ubuntu 24.04, no `powershell.exe` anywhere, no Windows. **Neither of the
design doc's two assumed hosts was already present.** PowerShell 7.6.3 ("pwsh", "Core" edition)
was installable via Microsoft's own apt repo (`packages.microsoft.com/config/ubuntu/24.04/...`),
reachable through this sandbox's proxy even though several unrelated third-party PPAs
(`ppa.launchpadcontent.net`) were blocked -- confirmed via `$PSVersionTable.PSVersion` (`7.6.3`)
and `.PSEdition` (`Core`). Windows PowerShell 5.1 ("Desktop" edition) is **not obtainable here at
all** -- it's a Windows-only, .NET-Framework-hosted binary. Confirmed directly:
`[System.Reflection.Assembly]::ReflectionOnlyLoadFrom(...)` exists as a method on pwsh7 but
throws `"ReflectionOnly loading is not supported on this platform"` when called -- exactly the
design doc's assumption that this API is .NET-Framework-only, now confirmed empirically from the
other side rather than just inferred. This means **the PS 5.1 / `ReflectionOnlyLoadFrom` code
path in `reflect_revit_api.ps1` has never been executed, at all, in this project** -- it's
written to match the design doc and mirrors patterns confirmed to work on the PS7 side, but
remains genuinely unverified until it runs on a real Windows+Revit machine. Treat that as this
stage's equivalent of the docs-crawler's "Network access limitation" section: an honest gap, not
a silent assumption.

`System.Reflection.MetadataLoadContext` (the PS7 fallback the design doc names) is indeed not
built in -- confirmed by `[System.Reflection.MetadataLoadContext]` failing to resolve until its
NuGet package's DLL is loaded explicitly. Fetched directly from
`api.nuget.org/v3-flatcontainer/system.reflection.metadataloadcontext/8.0.0/...nupkg` (also
reachable through the proxy) and `Add-Type -Path`-loaded its `lib/net8.0/` DLL successfully.

### Step 2: cheapest real test -- a generic BCL property, both `.ToString()` and `.FullName`

Before touching any install-dir scan, reflected `Dictionary<string,int>.Keys`
(`ICollection<TKey>`-shaped) and a few adjacent BCL shapes (a plain class, an array, `Nullable<T>`,
a `void` return, a `ref`/`out` parameter) directly in pwsh7. Confirmed both forms
`ground_truth.normalize_type_name`'s docstring already claims to handle:

- `Type.ToString()`: `System.Collections.Generic.ICollection\`1[System.String]`
- `Type.FullName`: `System.Collections.Generic.ICollection\`1[[System.String, System.Private.CoreLib, Version=10.0.0.0, Culture=neutral, PublicKeyToken=...]]`

Both normalize to `ICollection<String>` via the existing `normalize_type_name`, matching the
docs-side `ICollection(ElementId)`-shaped form's own normalized output pattern -- confirmed
directly against real reflection strings, not just the hand-written fixture. Also confirmed,
deliberately, that a genuine **multi**-type-argument generic (`Dictionary\`2[[...],[...]]`, from
`Dictionary<string,int>` itself) does **not** normalize correctly -- it leaks commas and assembly
metadata into the result instead of collapsing to a clean `Dictionary<String,Int32>`. This isn't
a new problem: `normalize_type_name`'s own docstring already discloses this exact limitation
("a deeply nested multi-type-arg generic is not specifically handled and would need this
function extended and re-tested, not silently trusted"). No fix applied -- no real Revit
signature has ever been found that needs one, and guessing at a fix without that evidence is
exactly the failure mode this whole project exists to avoid. `void` methods were also checked:
reflection reports `ReturnType.FullName == "System.Void"` for them, which `reflect_revit_api.ps1`
now maps to a manifest `return_type: null` (matching how a void method carries no return type on
the docs side either) rather than leaking the literal string `"System.Void"` into the manifest.

### Step 3: a real, at-scale scan -- not Revit, but real, and it found two real bugs

With no Revit install dir available, the closest honest substitute was this sandbox's own
PowerShell installation directory (`/opt/microsoft/powershell/7`, 536 real `*.dll` files,
`System.Management.Automation` as the stand-in namespace prefix) -- a genuinely real "a handful
of relevant assemblies buried among many irrelevant ones" scan, just not Revit's own. Running
`reflect_revit_api.ps1` against it end-to-end surfaced:

1. **`MetadataLoadContext` needs the host runtime's own core assembly resolvable too, not just
   the target install dir's DLLs.** `New-Object System.Reflection.MetadataLoadContext($resolver,
   "System.Private.CoreLib")` threw until the resolver's path list also included every DLL under
   `[System.Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()` -- confirmed by
   trial and error, now baked into `Invoke-CoreReflection`'s resolver setup.
2. **A real, separate cross-framework caveat for the PS7 path, confirmed by reasoning through
   what the working scan above actually resolved against, not yet by a live cross-framework
   run**: the host-runtime DLLs added in (1) are `.NET`/`.NET Core` assemblies. Revit's own
   `RevitAPI.dll` targets **.NET Framework**, whose core assembly is `mscorlib`, not
   `System.Private.CoreLib` -- a same-host-runtime resolver seed won't satisfy that resolution.
   `reflect_revit_api.ps1` now accepts a `-NetFrameworkReferenceAssembliesDir` parameter (e.g. a
   `Microsoft.NETFramework.ReferenceAssemblies` NuGet package's contents) for exactly this case,
   switches the core-assembly name to `mscorlib` when it's supplied, and prints an explicit
   `Write-Warning` when it's *not* supplied and the host is Core edition, rather than silently
   scanning and producing a manifest quietly missing every cross-assembly-referenced type. This
   combination (PS7 + MetadataLoadContext + real net48 RevitAPI.dll + reference assemblies) is
   still **unverified** -- flagging it precisely, the same way `crawl_notes.md` already
   distinguishes "confirmed" from "reasoned but not yet run" elsewhere in this file.
3. `Enum.GetNames($enumType)` actually **succeeds** even on a `MetadataLoadContext`-loaded
   (reflection-only) enum type -- it only reads field metadata, no value construction needed.
   `Enum.GetValues` and `Activator.CreateInstance` both **fail**, with an explicit
   `"The requested operation cannot be used on objects loaded by a MetadataLoadContext"` /
   `"Type must be a type provided by the runtime"` error -- confirming reflection-only loading
   really is metadata-only on this host, not silently falling back to a real load. Rather than
   depend on `Enum.GetNames`'s specific (and seemingly accidental) tolerance, `enum_members` is
   read via `GetFields(Public, Static)` instead -- confirmed to return the exact same names, and
   documented as metadata-only by design rather than by this one host's apparent leniency.
4. Timing: enumerating 536 `*.dll` recursively took ~0.03s; metadata-loading and filtering all of
   them (367 succeeded, 169 failed to load -- expected, not surfaced loudly, matching the design
   doc's own expectation) took well under a second total, with 3 assemblies matching the
   namespace filter and 722 types collected. Not Revit's ~3151-DLL scale, but the same order of
   magnitude within a 6x factor, and nothing here suggested the full Revit scan would be
   meaningfully slower per-DLL -- worth reconfirming on the real thing regardless, not assumed.
5. A real syntax bug, unrelated to reflection: `Write-Warning "..." + "..." + "..."` (string
   concatenation split across a cmdlet call's bare arguments) failed with `"A positional
   parameter cannot be found that accepts argument '+'."` -- PowerShell's command-mode argument
   parsing doesn't extend `+`-concatenation across a cmdlet's argument list the way expression
   mode does. Fixed by building the message into a variable first, then passing the variable.
6. **The important one: PowerShell's array-to-scalar/`$null` collapse silently corrupted the
   manifest's array-shaped fields.** The very first real run serialized
   `"inheritance_chain": "System.Object"` (a bare string, not a 1-element array),
   `"members": {...}` (a bare object, not a 1-element array), and `"enum_members": null` /
   `"parameters": null` (instead of `[]`) for every type/member that happened to have exactly one
   ancestor/member/parameter, or exactly zero interfaces/enum-values/parameters. Root cause,
   confirmed directly: capturing a PowerShell function's return value across the call boundary
   collapses a 0-item collection to `$null` and a 1-item collection to its bare scalar element
   (`function f { return @() }; $x = f` gives `$x -eq $null`; `function g { return @("only") };
   $y = g` gives `$y -is [array]` = `False`) -- a well-known PowerShell pipeline behavior that
   would have silently broken `ground_truth.load_manifest()` for exactly the common cases (a
   leaf type with one property, a parameterless method, a type with no implemented interfaces),
   not just rare edge cases. Fixed by wrapping every collection-returning helper's result with
   `@(...)` again at its call site in `Convert-TypeToManifest`/`Convert-MembersToManifest` --
   confirmed the general fix (not a special-cased one) by checking `@($null_var)` degrades to
   `[]` while `@($scalar_var)`/`@($real_array_var)` both still produce the correctly-shaped array.
   Re-ran the same scan afterward: `PowerShellAssemblyLoadContextInitializer` (exactly a
   1-ancestor, 1-member, 1-parameter, 0-interface, 0-enum-value type) now serializes correctly as
   real JSON arrays throughout.

A **fourth** manifestation of the same root cause turned up while checking a tiny (1-DLL)
install dir as a boundary-condition test: the script's own summary line
(`Write-Verbose "$matchedCount / ... scanned assemblies matched..."`) printed `"3 / 1 scanned
assemblies matched"` for a scan where exactly one assembly matched -- a smaller, sneakier variant
of the same array-collapse: `($AssembliesScanned | Where-Object { $_.matched }).Count` on a
one-match result collapses to that single `[ordered]@{...}` hashtable *itself* (not a 1-element
array), and `.Count` on that hashtable silently returns its own key count (3: `path`/`name`/
`matched`) instead of erroring -- a very easy wrong-but-plausible number to miss without an
independent count to compare against (the JSON on disk was correct throughout; only the
console summary text was wrong). Fixed the same way, wrapping with `@(...)` before `.Count`.
This is the same lesson repeated a fourth way: **any PowerShell pipeline/array expression whose
result feeds a JSON field or a `.Count` needs to be checked against 0- and 1-item inputs
specifically**, not just the many-item case that happens to look right by construction.

### Step 4: validated against `ground_truth.load_manifest()`/`cross_validate_dll()` directly, not just eyeballed

The fixed manifest (722 types: 106 enums, 30 interfaces, 7 structs, the rest classes; methods
with real multi-parameter signatures and non-void return types; one 6-level-deep inheritance
chain) round-trips cleanly through `ground_truth.load_manifest()`. Beyond just parsing, a
hand-built `NodeCandidate`/`EdgeCandidate` pair against a real matched type/method
(`PowerShellAssemblyLoadContextInitializer.SetPowerShellAssemblyLoadContext`) run through
`cross_validate_dll` correctly produced `dll_type_verified=True`,
`dll_signature_verified=True`, `dll_verified_status="signature_verified_declared"` -- Stage B's
actual diffing logic exercised against Stage A's actual real output, not a schema-shape-only
check.

### What's still genuinely unverified

Everything that requires an actual Windows machine with actual Revit installed:

- The PS 5.1 / `ReflectionOnlyLoadFrom` / `ReflectionOnlyAssemblyResolve` code path has never
  been executed (this sandbox only has pwsh/Core; `ReflectionOnlyLoadFrom` throws
  `PlatformNotSupportedException`-shaped errors there, confirmed above).
- No real `RevitAPI.dll`/`RevitAPIUI.dll` has ever been scanned; the full ~3151-DLL, mostly-
  irrelevant-assemblies scenario the design doc describes has only been approximated (536 DLLs,
  a different namespace prefix).
- The PS7 + `MetadataLoadContext` + cross-framework (`-NetFrameworkReferenceAssembliesDir`) path
  is implemented and reasoned through but not yet run against anything net48-targeted.
- Possible duplicate-simple-name collisions among Revit's own DLLs (e.g. localized resource
  assemblies) aren't exercised by this sandbox's DLL set at all.

The next real validation step is exactly the pattern the rest of this file already follows: run
`reflect_revit_api.ps1 -InstallDir "C:\Program Files\Autodesk\Revit 2024" -Out
ground_truth_manifest_2024.json -Verbose` on an actual Windows+Revit box, and record whatever it
finds here -- confirmed facts, not assumptions, the same as every other stage.

## Why member pages are discovered from class pages, not just the index/TOC

Sandcastle-style sites list a type's members with links to their own property/method pages
directly on the type's page. The pipeline (`pipeline.run_pipeline`) treats those links as a
second, generally more reliable discovery source and queues them alongside whatever
`discover_index()` found from the root page / TOC / sitemap, tagging them
`members_table_of:<FullTypeName>` in `raw_index.json` so it's traceable which page a given
member URL came from.
