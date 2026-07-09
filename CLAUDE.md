# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A docs-first crawler/parser/classifier that mines `www.revitapidocs.com` and produces a
**candidate** semantic schema graph (nodes + edges, each with a confidence label and evidence
trail) for the generic `Autodesk.Revit.DB` API surface. It does **not** extract data from a
specific RVT model, does not build a graph database, and does not treat any inferred edge as
verified fact — everything is explicitly a candidate. See
`revit_semantic_schema/README.md`'s "Non-goals" section before adding anything that would
change that posture (e.g. making live Revit/DLL access required rather than optional
secondary evidence).

The actual package lives one directory down: **`revit_semantic_schema/`** is the project root
for all commands below, not the repo root.

## Commands

Run everything from `revit_semantic_schema/`:

```bash
pip install -e ".[dev]"                 # pytest only; enough to run the whole pipeline
pip install -e ".[fast]"                # adds requests + beautifulsoup4 (optional speedup)

python -m pytest tests/                 # full test suite (204 tests, fixture HTML only, no network)
python -m pytest tests/test_classify.py -q                       # one file
python -m pytest tests/test_classify.py::test_room_number_is_not_classified_as_a_relationship  # one test
python -m pytest tests/ -k "inherited"  # by name substring

python -m revit_schema_mapper --version 2024 --max-pages 25 --verbose   # small live smoke test
python -m revit_schema_mapper --version 2024                            # full crawl
python -m revit_schema_mapper --targeted-validation                     # scoped crawl, see below
python -m revit_schema_mapper --version 2024 --graph-only               # recompute graph.json only, no crawl
```

There is no configured lint/format/typecheck command in this repo — don't invent one; match
existing style (plain dataclasses, `from __future__ import annotations`, type hints).

`requests`/`beautifulsoup4` are optional: `crawl.py`/`parse.py` fall back to stdlib-only
equivalents (`http_compat.py`/`html_compat.py`) when they're missing, and the full test suite
must pass identically either way. If you touch either compat module, run the suite with the
`fast` extra both installed and uninstalled before considering the change done.

`OPENROUTER_API_KEY` (read from the environment only, no CLI flag) enables
`--label-communities-llm`; everything else runs with zero external services and zero network
access required for tests.

## Architecture

Pipeline stages, in order, each its own module under `src/revit_schema_mapper/`:

```
crawl.py     -> parse.py -> classify.py -> graph.py -> community.py -> semantic_roles.py -> export.py
                                                                                                ^
                                                                                          pipeline.py wires
                                                                                          all of the above;
                                                                                          __main__.py is the CLI
```

- **`crawl.py`** — polite, cached, resumable HTTP fetching scoped to `www.revitapidocs.com`
  only (`OutOfScopeURLError` on any other host). Discovery is primarily via
  `Crawler.discover_via_namespace_json` (a client-side JSON tree the site's TOC is actually
  built from — HTML-anchor scraping is a fallback only, kept for defensiveness). Every fetch is
  cached to `outputs/revit_<version>/cache/<sha256(url)>.htm` + a `.meta.json` sidecar; re-runs
  skip cached URLs unless `--force-refresh`.
- **`parse.py`** — turns one page's HTML into an `ApiPage` (models.py). Selectors here are
  fragile by nature (Sandcastle-generated docs, and the markup shape has changed across Revit
  doc years — see `docs/crawl_notes.md`); any parse failure is recorded as a `parser_notes`
  string on the page rather than raising, so one bad page doesn't kill a 20k-page crawl.
- **`classify.py`** — turns `MemberInfo`s into `NodeCandidate`/`EdgeCandidate` objects
  (models.py), each with a `candidate_edge_type` (`docs/edge_taxonomy_v0.md`), an
  `edge_confidence` label (`docs/confidence_model_v0.md`), and (for nodes) a `class_role`. The
  classification precedence is a strict waterfall — most specific applicable signal wins; see
  the taxonomy doc before adding a new edge type. Conservative by design: prefer an `UNKNOWN_*`
  edge type with honest evidence over guessing a specific one.
- **`graph.py`** — materializes candidates into `graph.json` (full) and `graph_core.json`
  (filtered to `confidence_tier: core` only). Resolves each edge's loose
  `candidate_target_type` string against crawled nodes (exact match, then unambiguous
  short-name fallback; unresolved becomes an `external` stub node, never a dropped edge) and
  collapses the seven-label `ConfidenceLabel` into a four-bucket `ConfidenceTier`. Note:
  `UNKNOWN_DB_OBJECT_REFERENCE`/`UNKNOWN_ELEMENTID_REFERENCE` edges are pinned to
  `unverified_reference` regardless of their underlying confidence label — these two types
  alone are ~77% of edges in a real full crawl, so without the override "core" would be mostly
  noise.
- **`community.py`** — dependency-free, deterministic single-level greedy modularity detection
  (Louvain's local-move phase only) over the core-tier subgraph, plus a free heuristic labeler
  (most-connected member names) or an opt-in LLM labeler via OpenRouter.
- **`semantic_roles.py`** — a coarser, independent classification (`classify_api_role`, ~21
  domain roles like `View`/`Family`/`Room / Space`) used only for the Sankey+heatmap
  `semantic_relationship_map.html` view — deliberately lossy in places for readability (see
  `test_classify_api_role_family_ambiguity_is_a_known_tradeoff`), not a replacement for
  `class_role`.
- **`ground_truth.py`** — Stages B and C of DLL reflection cross-validation
  (`docs/dll_reflection_v0.md`): Stage B loads a manifest produced by `reflect_revit_api.ps1`
  (Stage A, runs separately on a Windows+Revit machine) and cross-checks it against candidates,
  in place, via `--cross-validate-dll`. Stage C loads a `revitlookup_reference_<version>.json`
  (produced separately by `revitlookup.py`'s own mining) and cross-checks each edge candidate's
  `revitlookup_referenced`/`revitlookup_requires_document_context` fields, in place, via
  `--cross-validate-revitlookup`. Both are purely optional secondary evidence, independent of
  each other — the docs-crawl pipeline must always work standalone with no Revit install/DLL/
  RevitLookup access.
- **`export.py`** — writes every `outputs/revit_<version>/*.json` file, `summary.md` (or
  `validation_summary.md` for a targeted run), `graph.html`, and
  `semantic_relationship_map.html`.
- **`pipeline.py`** — wires the whole thing into one `run_pipeline`/`run_targeted_pipeline`
  call; also owns `DEFAULT_TARGET_CLASSES` and `DEFAULT_KNOWN_EDGE_CHECKS` for
  `--targeted-validation`.
- **`http_compat.py` / `html_compat.py`** — stdlib-only fallbacks (`urllib.request`,
  `html.parser`) used automatically when `requests`/`beautifulsoup4` aren't installed.
  `html_compat.MiniSoup` implements a CSS selector engine scoped to exactly the shapes this
  codebase uses (tag/`#id`/`.class`/`:first-of-type`, descendant/child combinators) — not a
  general CSS implementation; read its module docstring before adding a new selector shape.
- **`revitlookup.py`** — parses RevitLookup C# descriptor source (fixtures under
  `tests/fixtures/revitlookup/`) into `revitlookup_reference_<version>.json`, mined separately
  via `python -m revit_schema_mapper.revitlookup`; `ground_truth.cross_validate_revitlookup`
  (Stage C) consumes that file.

Every dataclass lives in **`models.py`** and is JSON-round-trippable via `dataclasses.asdict`
with no dependency on crawl/parse internals — that's what every `outputs/*.json` file actually
is on disk.

### Key invariants worth knowing before changing pipeline code

- **`GraphNode.id` / `GraphEdge.source`/`target` are always fully-qualified type names** — the
  join key for any downstream consumer (Neo4j, RDF, `networkx`, etc.).
- **Inherited members must be attributed to their real declaring type**, not the subclass page
  that happens to link to them — a members-index row's `data="...;inherited;..."` attribute and
  "(Inherited from X.)" text are the source of truth (`declaring_type_hint`), not the crawling
  type. This has been the source of multiple real bugs (see `docs/crawl_notes.md`); don't
  reintroduce a "assume the current type declared it" shortcut.
- **Room.Name / Room.Number must never collapse into one concept** — a specific regression
  target called out in the README and covered by
  `tests/test_classify.py::test_room_number_is_not_classified_as_a_relationship`. If you touch
  `classify_member`'s keyword matching, re-check this case.
- **Large per-run outputs are gitignored on purpose** (`outputs/<version>/*.json`,
  `graph.json`, `candidate_edges.json`, etc. — tens of MB per crawl); only `summary.md` /
  `validation_summary.md` and the small `_fixture_smoke_test`/`revit_2024_targeted` examples
  are committed. Don't add full crawl output to a commit — bulk data is meant to be published
  separately (e.g. a GitHub Release asset) per Revit version.
- **The RevitApiDocs markup has changed across doc years** (2024 vs. 2025 moved the syntax
  block into a per-language code-snippet widget, moved section headings to a collapsible-region
  span, etc. — see `docs/crawl_notes.md` for the full, chronological list of confirmed
  real-markup findings). When a selector stops matching, add the new selector *ahead of* the
  old one in the relevant `_SELECTORS` list rather than replacing it, so older cached years
  keep working.

## Testing conventions

- Tests run entirely against fixture HTML under `tests/fixtures/` — no network access, ever.
  `tests/conftest.py`'s `load_fixture` fixture reads a fixture file by name.
- When fixing a real bug found against a live run (see `docs/crawl_notes.md` for the running
  log of these), add a fixture modeled on the *actual* markup that broke, and a regression test
  that's verified to fail before the fix and pass after — that pattern is the norm throughout
  this codebase's history, not just a suggestion.
- `docs/crawl_notes.md` is the project's running log of what's been confirmed against real
  crawls/reflection runs vs. what's still reasoned-but-unverified. Check it before assuming a
  parser/classifier assumption is solid, and append to it (don't rewrite history) when you
  confirm or fix something against a real run.

## Docs to read before non-trivial changes

- `revit_semantic_schema/README.md` — full CLI flag reference, output file list, knowledge
  graph / communities / semantic-role-map design rationale.
- `revit_semantic_schema/docs/edge_taxonomy_v0.md` — full edge type list + classification
  precedence.
- `revit_semantic_schema/docs/confidence_model_v0.md` — definition of each confidence label.
- `revit_semantic_schema/docs/dll_reflection_v0.md` — design for the optional Stage
  A (`reflect_revit_api.ps1`, PowerShell, runs on Windows+Revit) / Stage B (`ground_truth.py`)
  cross-validation pass.
- `revit_semantic_schema/docs/multi_source_corroboration_v0.md` — design-only record of open
  questions for combining Stage B (DLL) and Stage C (RevitLookup) evidence with the base
  docs-derived confidence, plus downstream-consumer (RDF/Neo4j) and possible-future-ontology
  considerations. Nothing in it is implemented yet.
- `revit_semantic_schema/docs/crawl_notes.md` — chronological log of every real-run finding,
  bug, and markup change confirmed so far; long, but the authoritative source for "has this
  actually been verified against the live site or a real Revit install."
