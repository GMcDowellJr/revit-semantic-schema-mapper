# Revit Semantic Schema Mapper

A docs-first crawler and parser for [RevitApiDocs](https://www.revitapidocs.com/) that
extracts the generic `Autodesk.Revit.DB` API surface (classes, inheritance, properties,
methods, enums, descriptions) and produces a **candidate** semantic schema graph — node and
edge candidates, each with an explicit confidence label and evidence trail.

This is **not** about extracting elements from a specific RVT model. The target is the
generic Revit DB object model itself, as documented, with an eye toward eventually building a
graph schema for it.

## Status: scaffold complete, live crawl pending

The crawler, parser, classifier, exporter, docs, and test suite are all implemented and
unit-tested against representative fixture HTML. **No page in `outputs/revit_2027/` has been
produced by an actual crawl of revitapidocs.com yet** — the session this was built in had its
outbound network access blocked entirely (confirmed independently via both `curl` and the
`WebFetch` tool; see `docs/crawl_notes.md` for the full account). Running the one command
below against a network-enabled environment is what's left to do.

```
python -m revit_schema_mapper --version 2027
```

See `docs/crawl_notes.md` → "What to check on the first real run" for how to sanity-check
that first live run before trusting its output.

## Quickstart

```bash
pip install -e ".[dev]"
python -m pytest tests/           # run the test suite against fixture HTML
python -m revit_schema_mapper --version 2027 --max-pages 25 --verbose   # small live smoke test
python -m revit_schema_mapper --version 2027                            # full run
```

Outputs land in `outputs/revit_<version>/`: `raw_index.json`, `api_pages.json`,
`node_type_candidates.json`, `property_relationship_candidates.json`,
`method_relationship_candidates.json`, `enum_catalogs.json`, `candidate_edges.json`, and a
human-readable `summary.md`. Fetched HTML is cached under `outputs/revit_<version>/cache/`
and is not re-fetched on subsequent runs unless `--force-refresh` is passed.

## How it works

```
crawl.py    -- polite, cached, resumable HTTP fetching + link discovery, scoped to
               www.revitapidocs.com
parse.py    -- turns one page's HTML into an ApiPage (class/struct/enum/property/method)
classify.py -- turns parsed members into NodeCandidate / EdgeCandidate objects, each with
               a candidate_edge_type (docs/edge_taxonomy_v0.md) and edge_confidence
               (docs/confidence_model_v0.md)
export.py   -- writes all outputs/revit_<version>/*.json + summary.md
pipeline.py -- wires the above into the single command in __main__.py
```

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
Number, and the relevant `BuiltInParameter` entries each run. See `summary.md` section 10 and
`docs/crawl_notes.md` for the caveat that this hasn't been checked against a live Room page
yet.

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
