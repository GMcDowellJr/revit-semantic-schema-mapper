# Revit Semantic Schema Mapper - Run Summary

## 1. Crawl scope
- Revit version: 2027
- Namespace: Autodesk.Revit.DB

## 2. Pages discovered
- 0

## 3. Pages parsed
- 0

## 4. Node candidates
- 0

## 5. Property relationship candidates
- 0

## 6. Method relationship candidates
- 0

## 7. Enum members extracted
- 0

## 8. Top 25 highest-confidence candidate edges
- (none)

## 9. Top 25 uncertain candidates needing review
- (none)

## 10. Room / Room Number / Room Name findings
## Room / Room Number / Room Name investigation

No `Room` type page was present in this run's input set, so this section reports prior/general knowledge of the Revit API rather than a finding pulled from a crawled page. **This has not been verified against a live revitapidocs.com page in this session** (see docs/crawl_notes.md, "Network access limitation"). Treat the following as a hypothesis to confirm on the first real crawl, not a fact:

- `Autodesk.Revit.DB.Architecture.Room` does not appear to declare its own `Name` CLR property; room name is expected to be exposed via the inherited `Element.Name` property, which is backed by the `BuiltInParameter.ROOM_NAME` parameter under the hood.
- `Room.Number` is expected to be a dedicated CLR property (not merely a `get_Parameter(BuiltInParameter.ROOM_NUMBER)` lookup), directly backed by `BuiltInParameter.ROOM_NUMBER`.
- If confirmed, this means Name and Number reach the object model through two different mechanisms (inherited base property vs. a type-specific property), even though both ultimately resolve to BuiltInParameter-backed values. The schema should keep `Room.Name`/`ROOM_NAME` and `Room.Number`/`ROOM_NUMBER` as **two distinct concepts**, not collapsed into one 'room identity' node.
- Action item for the first live crawl: fetch the `Room` class page and its `Number` property page, and check the `BuiltInParameter` enum catalog for `ROOM_NAME` and `ROOM_NUMBER` entries, to confirm or correct the above.

## 11. Limitations
- Edge classification is a static, docs-only heuristic; no candidate edge has been validated against a live Revit document (see confidence label needs_runtime_validation).
- Member pages reachable only via a type's members table are discovered incrementally during parsing; a partial/interrupted crawl can under-count members for the last few types processed.
- Name-keyword-to-edge-type mapping (classify.py) is heuristic and English-name-based; it will misclassify or under-classify members whose names don't match the documented keyword list.
- discover_index encountered 1 error(s) while finding pages to crawl (see logs for full detail): ["root_page fetch/parse failed: HttpError('Failed to reach https://www.revitapidocs.com/2027/: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Missing Authority Key Identifier (_ssl.c:1081)')"]
- 0 pages were discovered this run. This is not 'the site has nothing under this namespace' -- discover_index's fetch attempts all failed (see the error(s) above), which most commonly means a network/proxy/TLS/reachability problem, not a parser bug.

## 12. Recommended next steps
- Run against a live revitapidocs.com session and diff parser_notes across all pages to find and fix selector assumptions that didn't hold (see docs/crawl_notes.md).
- Expand the name-keyword edge taxonomy with additional evidence gathered from real docs text (docs_semantic_hint) rather than name matching alone.
- Cross-check high-confidence candidate edges (direct_return_type, elementid_with_strong_name) against a small number of real Revit documents to promote them out of 'candidate' status.
- Extend to Autodesk.Revit.DB.Architecture and Autodesk.Revit.DB.Structure for Room/Space and structural element coverage once the core DB namespace is validated.
