# Revit Semantic Schema Mapper - Targeted Validation Crawl

## 1. Scope
- Revit version: 2024
- Target classes: 13
- Known-edge checks: 9

## 2. Crawler coverage (were pages found and fetched?)
- 13/13 target classes found in the namespace_json tree
- 508 total page URLs discovered (class + Members + Methods/Properties + individual member pages)
- 0 page(s) failed to fetch or parse

## 3. Parser success (did we extract structured data?)
- 13/13 target classes successfully parsed into a node candidate
- 469 total pages parsed
- 6/9 known-edge members found on a parsed page
- 51/469 parsed pages have at least one parser_note (a selector assumption that didn't fully hold)

## 4. Classifier confidence (what did classify.py conclude, and how sure is it?)
- 13 node candidates ({'element_subtype': 7, 'element_type': 2, 'unknown': 4})
- 48 property-based edge candidates, 117 method-based edge candidates
- 6/9 known-edge checks produced a relationship edge
- Edge confidence breakdown:
  - direct_return_type: 27
  - elementid_with_strong_name: 11
  - elementid_collection_with_strong_name: 14
  - docs_semantic_hint: 2
  - name_only_candidate: 62
  - unknown_reference: 37
  - needs_runtime_validation: 12

## 5. Target class report

| Target | Found in index | Class page parsed | Member pages parsed | Reason (if incomplete) |
|---|---|---|---|---|
| `Autodesk.Revit.DB.Element` | yes | yes | 92 | - |
| `Autodesk.Revit.DB.ElementType` | yes | yes | 11 | - |
| `Autodesk.Revit.DB.View` | yes | yes | 142 | - |
| `Autodesk.Revit.DB.ViewSheet` | yes | yes | 20 | - |
| `Autodesk.Revit.DB.Viewport` | yes | yes | 16 | - |
| `Autodesk.Revit.DB.Family` | yes | yes | 26 | - |
| `Autodesk.Revit.DB.FamilySymbol` | yes | yes | 12 | - |
| `Autodesk.Revit.DB.FamilyInstance` | yes | yes | 61 | - |
| `Autodesk.Revit.DB.Material` | yes | yes | 25 | - |
| `Autodesk.Revit.DB.FillPatternElement` | yes | yes | 5 | - |
| `Autodesk.Revit.DB.LinePatternElement` | yes | yes | 8 | - |
| `Autodesk.Revit.DB.ParameterFilterElement` | yes | yes | 17 | - |
| `Autodesk.Revit.DB.Architecture.Room` | yes | yes | 9 | - |

## 6. Known-edge test report

| Type.Member | Member found | Edge produced | Edge type (confidence) | Note |
|---|---|---|---|---|
| `Autodesk.Revit.DB.View.ViewTemplateId` | yes | yes | CONTROLLED_BY_TEMPLATE (`elementid_with_strong_name`) | edge produced: CONTROLLED_BY_TEMPLATE (elementid_with_strong_name) |
| `Autodesk.Revit.DB.FamilyInstance.Symbol` | yes | yes | INSTANCE_OF (`direct_return_type`) | edge produced: INSTANCE_OF (direct_return_type) |
| `Autodesk.Revit.DB.FamilySymbol.Family` | yes | yes | BELONGS_TO_FAMILY (`direct_return_type`) | edge produced: BELONGS_TO_FAMILY (direct_return_type) |
| `Autodesk.Revit.DB.ViewSheet.GetAllPlacedViews` | yes | yes | RETURNS_ELEMENT_IDS (`elementid_collection_with_strong_name`) | edge produced: RETURNS_ELEMENT_IDS (elementid_collection_with_strong_name) |
| `Autodesk.Revit.DB.Viewport.ViewId` | yes | yes | UNKNOWN_ELEMENTID_REFERENCE (`unknown_reference`) | edge produced: UNKNOWN_ELEMENTID_REFERENCE (unknown_reference) |
| `Autodesk.Revit.DB.Element.WorksetId` | yes | yes | OWNED_BY_WORKSET (`name_only_candidate`) | edge produced: OWNED_BY_WORKSET (name_only_candidate) |
| `Autodesk.Revit.DB.Material.SurfacePatternId` | **NOT CRAWLED** | no | - | member page was not crawled/parsed in this run -- not a classifier problem, a coverage gap |
| `Autodesk.Revit.DB.Material.CutPatternId` | **NOT CRAWLED** | no | - | member page was not crawled/parsed in this run -- not a classifier problem, a coverage gap |
| `Autodesk.Revit.DB.Architecture.Room.Number` | **NOT CRAWLED** | no | - | member page was not crawled/parsed in this run -- not a classifier problem, a coverage gap |

## 7. Definition-of-done checklist
- [x] At least 10/13 target classes found (13 found in index, 13 actually parsed)
- [x] At least 5 known-edge checks reported (9 evaluated)
- [x] candidate_edges includes both property-based (48) and method-based (117) relationships
- [x] This summary distinguishes crawler coverage (section 2), parser success (section 3), and classifier confidence (section 4)

## 8. Limitations
- This report only reflects general Revit API knowledge where it is directly backed by a crawled/parsed page in this run; any target marked 'NOT CRAWLED' above has no verified data in this run, and nothing about it should be treated as fact.
- Edge classification is a static, docs-only heuristic (see classify.py); no candidate edge has been validated against a live Revit document.
