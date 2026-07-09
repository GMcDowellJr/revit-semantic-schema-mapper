# Candidate edge taxonomy v0

Conservative by design: prefer an `UNKNOWN_*` type with honest evidence over a specific but
unverified edge type. Do not add new specific types to this list without real evidence from a
crawled page (return type + name + docs text); if you're tempted to invent a more specific
type for something that currently falls into an `UNKNOWN_*` bucket, that's a signal to look
at the evidence more closely first, not to guess.

| Edge type | Meaning | Example |
|---|---|---|
| `HAS_PARAMETER` | Source exposes a `Parameter`/`Definition` | `Element.get_Parameter(...)` |
| `HAS_CATEGORY` | Source is classified under a `Category` | `Element.Category` |
| `INSTANCE_OF` | Source is one concrete instance of a type-object | `FamilyInstance.Symbol -> FamilySymbol` |
| `TYPE_OF` | Source's `ElementType`/type-defining member | `Element.GetTypeId()` |
| `BELONGS_TO_FAMILY` | Source belongs to a `Family` | `FamilySymbol.Family -> Family` |
| `CONTROLLED_BY_TEMPLATE` | Source's settings are governed by a `View` acting as a template | `View.ViewTemplateId -> View` |
| `USES_MATERIAL` | Source references a `Material` | `Element.GetMaterialIds()` |
| `USES_FILL_PATTERN` | Source references a `FillPatternElement` | `FillPatternElement`-typed property |
| `USES_LINE_PATTERN` | Source references a `LinePatternElement` | `LinePatternElement`-typed property |
| `PLACED_ON_SHEET` | Source is placed on a `ViewSheet` | `Viewport.SheetId -> ViewSheet` |
| `TAGS_ELEMENT` | Source is a tag referencing a tagged element | `IndependentTag.GetTaggedElementIds()` |
| `HOSTED_BY` | Source is hosted by another element | `FamilyInstance.Host -> Element` |
| `OWNED_BY_WORKSET` | Source belongs to a `Workset` | `Element.WorksetId -> Workset` |
| `ASSIGNED_TO_LEVEL` | Source is associated with a `Level` | `Element.LevelId -> Level` |
| `ASSIGNED_TO_PHASE` | Source is associated with a `Phase` | `Element.CreatedPhaseId -> Phase` |
| `ASSIGNED_TO_DESIGN_OPTION` | Source is associated with a `DesignOption` | `Element.DesignOption -> DesignOption` |
| `MEMBER_OF_GROUP` | Source belongs to a `Group` | `Element.GroupId -> Group` |
| `MEMBER_OF_ASSEMBLY` | Source belongs to an `AssemblyInstance` | `Element.AssemblyInstanceId` |
| `DEPENDS_ON` | Source structurally depends on another element | `Element.GetDependentElements(...)` |
| `REFERENCES` | Generic reference that doesn't fit a more specific type but has a resolvable target concept not yet worth its own edge type | `Element.Document`/`FailuresAccessor.GetDocument() -> Document` (confirmed against a live 2024 crawl: 19 edges, 19 distinct source types, zero counterexamples); `BIMExportOptions.ViewId`/`ElevationMarker.GetViewId() -> View` (same crawl: 12 edges, 12 distinct source types, zero counterexamples) |
| `RETURNS_ELEMENT_IDS` | Bulk/collection accessor of `ElementId`s with no specific relationship semantics identified | `FilteredElementCollector`-style `GetAll...()` |
| `UNKNOWN_ELEMENTID_REFERENCE` | Returns `ElementId`, but the member name gives no reliable hint of the target type or relationship | `Element.Id` |
| `UNKNOWN_DB_OBJECT_REFERENCE` | Returns a concrete Revit DB object type, but no keyword/docs evidence identifies a specific relationship semantics for it | a property returning a DB type not covered by a more specific rule |

## Classification precedence

For a given property/method, `classify.classify_member` picks the most specific applicable
signal in this order:

1. **Return type is itself a Revit DB object type** (not `ElementId`, not a primitive) →
   `direct_return_type` confidence; edge type comes from a name-keyword match if any, else
   `UNKNOWN_DB_OBJECT_REFERENCE`.
2. **Return type is `ElementId`** → edge type from name-keyword match (confidence
   `elementid_with_strong_name`) or `UNKNOWN_ELEMENTID_REFERENCE` (confidence
   `unknown_reference`) if no keyword matches.
3. **Return type is a collection of `ElementId`** → analogous to (2), with
   `elementid_collection_with_strong_name` / `RETURNS_ELEMENT_IDS`.
4. **Return type is a generic collection whose element type isn't statically confirmed**
   (e.g. an `ICollection<T>` where `T` isn't independently known to be reference-bearing) →
   `needs_runtime_validation`.
5. **Name matches a relationship keyword but type evidence is weak** (e.g. returns `bool`,
   `int`, `string`) → `name_only_candidate`.
6. If the docs summary/remarks contain an explicit relationship phrase (e.g. "is hosted by",
   "template for"), that upgrades a `name_only_candidate` or `unknown_reference` result to
   `docs_semantic_hint` and is always recorded as an extra `evidence` entry regardless.

See `docs/confidence_model_v0.md` for the full definition of each confidence label.
