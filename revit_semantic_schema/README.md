# Revit Semantic Schema Mapper

A docs-first crawler and parser for [RevitApiDocs](https://www.revitapidocs.com/) that
extracts the generic `Autodesk.Revit.DB` API surface (classes, inheritance, properties,
methods, enums, descriptions) and produces a **candidate** semantic schema graph — node and
edge candidates, each with an explicit confidence label and evidence trail.

This is **not** about extracting elements from a specific RVT model. The target is the
generic Revit DB object model itself, as documented, with an eye toward eventually building a
graph schema for it.

## Status: full live crawl completed for Revit 2024; 2027 still pending

A full (non-targeted) live crawl of `Autodesk.Revit.DB` against Revit 2024 has now been run
successfully: 28,459 pages discovered, 23,241 parsed, 2,421 node candidates, and 10,697 edge
candidates. Its bulk output isn't committed to this repo (see "Where the crawl output lives"
below) but `outputs/revit_2024/summary.md` is. `outputs/revit_2027/` is still pending — run

```
python -m revit_schema_mapper --version 2027
```

against a network-enabled environment (falling back to `--version 2026
--fallback-reason "..."` if 2027 turns out to be unavailable or structurally inconsistent, per
the documented policy in `docs/crawl_notes.md`). See `docs/crawl_notes.md` → "What to check on
the first real run" for how to sanity-check a new live run before trusting its output.

### Where the crawl output lives

`outputs/revit_<version>/*.json` (everything except the markdown summaries and the small
targeted-crawl reports) is gitignored — a full crawl's `api_pages.json`/`candidate_edges.json`/
`graph.json` etc. run into the tens of megabytes and would otherwise bloat every commit that
touches this repo, even though the content mostly just churns from one crawl to the next. The
convention is: **small, durable summaries live in git; bulk per-run data gets published
separately** (e.g. as a GitHub Release asset for that Revit version) so it stays available
without living in git history. If you're looking for a specific version's full output and it
isn't attached to a Release yet, check with whoever ran that crawl.

## Quickstart

```bash
pip install -e ".[dev]"
python -m pytest tests/           # run the test suite against fixture HTML
python -m revit_schema_mapper --version 2027 --max-pages 25 --verbose   # small live smoke test
python -m revit_schema_mapper --version 2027                            # full run
```

`requests` and `beautifulsoup4` are optional (`pip install -e ".[fast]"` to add them) — if
they're not installed, the crawler/parser automatically fall back to stdlib-only
equivalents (`urllib.request`, `html.parser`), so the whole pipeline runs on a bare Python
install. Useful if your environment restricts installing packages from PyPI. Run with
`--verbose` to see which backend (fast or fallback) is active.

On a corporate network with an SSL-inspecting proxy, you may see
`CERTIFICATE_VERIFY_FAILED: ... Missing Authority Key Identifier` — that's the proxy's root
CA failing a stricter OpenSSL 3.2+ compliance check that browsers don't enforce; ask your
IT/security team to fix the CA or exempt the target domain. As a stopgap, set
`REVIT_SCHEMA_MAPPER_RELAX_TLS_STRICT=1` to disable only that newer check (chain-of-trust and
hostname verification stay on) — see `http_compat.py`'s module docstring for detail. See
`docs/crawl_notes.md` → "No-install-required fallback" for how this is implemented.

Outputs land in `outputs/revit_<version>/`: `raw_index.json`, `api_pages.json`,
`node_type_candidates.json`, `property_relationship_candidates.json`,
`method_relationship_candidates.json`, `enum_catalogs.json`, `candidate_edges.json`,
`graph.json`, `graph_core.json`, and a human-readable `summary.md`. Fetched HTML is cached
under `outputs/revit_<version>/cache/` and is not re-fetched on subsequent runs unless
`--force-refresh` is passed.

### CLI flags

`python -m revit_schema_mapper [flags]` -- every flag `argparse` knows about (see
`__main__.py`):

| Flag | Default | Meaning |
|---|---|---|
| `--version VERSION` | `2027` | Revit version path segment on revitapidocs.com |
| `--output-dir DIR` | `outputs/revit_<version>[_targeted]/` | Where all output files are written |
| `--cache-dir DIR` | `<output-dir>/cache` | Where fetched HTML is cached |
| `--namespace-prefix PREFIX` | `Autodesk.Revit.DB` | Only keep pages whose namespace starts with this |
| `--throttle-seconds N` | `1.5` | Minimum delay between HTTP requests (politeness) |
| `--max-pages N` | unlimited | Cap on total pages fetched -- for smoke tests |
| `--force-refresh` | off | Re-fetch pages even if already cached |
| `--fallback-reason TEXT` | none | Records why this run is a documented version fallback (e.g. 2027 -> 2026); shown in `summary.md` |
| `--targeted-validation` | off | Scoped crawl against `pipeline.DEFAULT_TARGET_CLASSES` + a known-edge report, instead of a full namespace crawl -- see "Targeted validation crawl" below |
| `--target-classes "A,B,C"` | `DEFAULT_TARGET_CLASSES` | Comma-separated fully-qualified class names, overriding the default target list (implies `--targeted-validation`) |
| `--discover-only` | off | Only run page discovery and report how many pages a full run would fetch; writes just `raw_index.json`, no fetching/parsing of individual pages |
| `--graph-only` | off | Recompute `graph.json`/`graph_core.json` (and refresh the summary's graph section) from an existing `--output-dir`'s already-written `node_type_candidates.json`/`candidate_edges.json`, without crawling or re-parsing anything -- see "Recomputing just the graph" below |
| `--include-doc-text` | off | Include full summary/remarks/code-example text (copied from the docs site) in `api_pages.json`; omitted by default since it's prose/code, not derived facts -- for local debugging only, don't republish the result |
| `-v`, `--verbose` | off | INFO-level logging (HTTP/HTML backend in use, crawl progress heartbeat, robots.txt rules, etc.) |

### Recomputing just the graph

`graph.json`/`graph_core.json` are cheap to recompute from a previous run's
`node_type_candidates.json`/`candidate_edges.json` -- no network access, no re-parsing HTML.
This matters because a full re-run reuses cached HTML (skips re-*fetching*) but still
re-parses and re-classifies every page from scratch, which is itself the slow part on
constrained hardware (e.g. tens of thousands of cached pages on a Raspberry Pi). If you've
only changed `graph.py` (or just want to regenerate `graph.json` after editing
`node_type_candidates.json`/`candidate_edges.json` by hand), skip straight to:

```bash
python -m revit_schema_mapper --version 2024 --graph-only
```

This requires `node_type_candidates.json` and `candidate_edges.json` to already exist in
`--output-dir` (from a previous full or `--targeted-validation` run) -- it errors out if
they're missing rather than silently doing nothing. It also refreshes the "Knowledge graph
materialization" section of whichever summary file exists (`summary.md` or
`validation_summary.md`) in place, without touching the rest of that file.

## How it works

```
crawl.py    -- polite, cached, resumable HTTP fetching + link discovery, scoped to
               www.revitapidocs.com
parse.py    -- turns one page's HTML into an ApiPage (class/struct/enum/property/method)
classify.py -- turns parsed members into NodeCandidate / EdgeCandidate objects, each with
               a candidate_edge_type (docs/edge_taxonomy_v0.md), edge_confidence
               (docs/confidence_model_v0.md), and (for node candidates) a class_role
graph.py    -- materializes node/edge candidates into an actual graph.json/graph_core.json
               (see "Knowledge graph output" below)
export.py   -- writes all outputs/revit_<version>/*.json + summary.md
pipeline.py -- wires the above into the single command in __main__.py
```

## Knowledge graph output

`node_type_candidates.json` + `candidate_edges.json` are already almost a graph -- `graph.py`
closes the two remaining gaps so downstream tools can consume it directly instead of
re-deriving this themselves:

1. **Resolved node ids.** An `EdgeCandidate.candidate_target_type` is a loose type-name string,
   not a guaranteed match against a crawled node. `graph.build_graph` resolves it in two passes:
   an exact match against `NodeCandidate.full_type_name`, then (only if unambiguous) a
   short-name fallback -- needed because edge classification and node classification are
   separate code paths that can disagree on namespace qualification for the same real type
   (confirmed on a live crawl: edges pointed at `Autodesk.Revit.DB.Room` while the actual
   crawled node was `Autodesk.Revit.DB.Architecture.Room`). Anything still unresolved becomes an
   `external` stub node (deduplicated by id) rather than a dropped edge, so nothing disappears
   silently -- it's just marked as pointing outside the crawled node set.
2. **A four-bucket `confidence_tier`**, collapsing the seven-label `ConfidenceLabel` model into
   `core` / `likely` / `needs_validation` / `unverified_reference`. `UNKNOWN_DB_OBJECT_REFERENCE`
   and `UNKNOWN_ELEMENTID_REFERENCE` edges are pinned to `unverified_reference` regardless of
   their `edge_confidence` label, even `direct_return_type` -- that label only reflects
   confidence in the *return type*, not in any specific relationship, and in the real Revit 2024
   crawl those two edge types alone are ~77% of all edges. Without that override, "core" would
   be mostly noise instead of a genuinely trustworthy subgraph.

`graph.json` is the full materialized graph plus a `metadata` block (node/edge counts, target
resolution counts, confidence tier counts). `graph_core.json` is the same graph filtered to
`confidence_tier: core` edges only, plus just the nodes those edges reference -- a small,
high-trust subgraph a downstream tool can load without re-implementing any of the above
filtering itself. Both are gitignored for the same bulk-output reason as `candidate_edges.json`
etc. (see "Where the crawl output lives" above); consume them from wherever that run's output
was published.

`GraphNode.id` and `GraphEdge.source`/`target` are always a type's fully-qualified name --
that's the join key for anything downstream (a Neo4j import, an RDF conversion, an in-memory
`networkx` graph, etc.).

## Targeted validation crawl

`python -m revit_schema_mapper --targeted-validation` runs a small, scoped crawl against a
fixed list of well-understood classes (`Element`, `View`, `FamilyInstance`, `Room`, etc. --
see `pipeline.DEFAULT_TARGET_CLASSES`) instead of the full `Autodesk.Revit.DB` namespace.
Use this to validate the crawler/parser/classifier quickly against real pages before trusting
a full run, or after changing a selector/heuristic. It writes everything a full run does, plus:

- `target_report.json` / section 5 of `validation_summary.md` -- for each target class,
  whether it was found in the site's namespace index, whether its class page actually parsed,
  and how many of its member pages parsed; missing/incomplete targets carry an explicit reason.
- `known_edge_report.json` / section 6 of `validation_summary.md` -- a fixed list of specific
  expected relationships (`View.ViewTemplateId`, `FamilyInstance.Symbol`,
  `Room.Number` -- see `pipeline.DEFAULT_KNOWN_EDGE_CHECKS`), each reported as found/missing,
  and (if found) exactly what `candidate_edge_type`/confidence `classify.py` assigned. Not
  every check is expected to produce an edge -- `Room.Number` is a plain value property by
  design (see "Room / Room Number / Room Name" below) and is reported as such rather than as a
  failure.
- `validation_summary.md` explicitly separates **crawler coverage** (were pages found/fetched),
  **parser success** (did `parse.py` extract structured data), and **classifier confidence**
  (what `classify.py` concluded and how confident it is) into distinct sections, since a low
  number in one doesn't imply a problem in the others.

Override the target list with `--target-classes "Autodesk.Revit.DB.View,Autodesk.Revit.DB.Wall"`.
Output defaults to `outputs/revit_<version>_targeted/` (separate from a full run's
`outputs/revit_<version>/`, so the two don't overwrite each other).

### class_role

Every `NodeCandidate` now also carries a `class_role` (`element_type`, `element_subtype`,
`utility_class`, `options_class`, `enum`, `value_object`, or `unknown`) -- a coarse structural
classification, orthogonal to `is_element_candidate`, based on kind/name/member-shape
heuristics. See `classify.classify_class_role`'s docstring for the precedence rules.

### Example candidate edges this is designed to surface

```
Autodesk.Revit.DB.View.ViewTemplateId
  returns: ElementId
  candidate edge: CONTROLLED_BY_TEMPLATE -> Autodesk.Revit.DB.View
  confidence: elementid_with_strong_name

Autodesk.Revit.DB.FamilyInstance.Symbol
  returns: FamilySymbol
  candidate edge: INSTANCE_OF -> Autodesk.Revit.DB.FamilySymbol
  confidence: direct_return_type
```

## Room / Room Number / Room Name

A specific test case the brief calls out: `Room.Name` and `Room.Number` (and the
`BuiltInParameter.ROOM_NAME` / `ROOM_NUMBER` entries behind them) must not collapse into one
concept. `classify.classify_member` never emits an edge candidate for `Room.Number` (it's a
plain `string` property matching no relationship keyword — see
`tests/test_classify.py::test_room_number_is_not_classified_as_a_relationship`), and
`export.write_summary` has a dedicated section reporting what's known/found about Room, Name,
Number, and the relevant `BuiltInParameter` entries each run. See `summary.md` section 10.

**Confirmed against a live targeted crawl (Revit 2024)**: the original hypothesis above was
half right. `Room.Name` is inherited from `Element.Name`, as expected -- but `Room.Number` is
*not* a Room-specific property either; it's inherited from an intermediate base class between
`Room` and `Element` (`Room : SpatialElement : Element`), not declared directly on `Room`. So
`Name` and `Number` reach the object model through the *same* mechanism (an inherited base
property), just at different levels of the inheritance chain, not two different mechanisms as
originally guessed. They're still correctly kept as two distinct concepts. (That live run's
fully-qualified owner name for `SpatialElement` was itself wrong at the time, due to a bug --
see `docs/crawl_notes.md` for the fix and how the known-edge report resolves this.)

## Non-goals (this pass)

Do not: open Revit; require `RevitAPI.dll`; build a graph database; mutate a model; generate
Revit commands; claim the produced graph is complete; treat any inferred edge as fact; crawl
namespaces outside `Autodesk.Revit.DB` (UI is touched only if needed to resolve a link).

## Docs

- `docs/crawl_notes.md` — crawl scope decisions, the network limitation this was built under,
  and what to validate on the first real run.
- `docs/edge_taxonomy_v0.md` — the full candidate edge type list and classification
  precedence.
- `docs/confidence_model_v0.md` — definition of each confidence label.
