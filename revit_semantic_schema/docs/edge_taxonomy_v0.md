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
| `REFERENCES` | Generic reference that doesn't fit a more specific type but has a resolvable target concept not yet worth its own edge type | `Element.Document`/`FailuresAccessor.GetDocument() -> Document` (confirmed against a live 2024 crawl: 19 edges, 19 distinct source types, zero counterexamples); `BIMExportOptions.ViewId`/`ElevationMarker.GetViewId() -> View` (same crawl: 12 edges, 12 distinct source types, zero counterexamples); `FamilyInstance.Room`/`.FromRoom`/`.ToRoom`/`Document.GetRoomAtPoint() -> Room` (same crawl: 7 edges, 4 distinct source types, 3 of 7 independently corroborated by RevitLookup); `Entity.Schema`/`Field.Schema`/`Field.SubSchema -> Schema` (exact-match keyword, not a bare substring -- `Schema.ListSchemas`/`.Lookup` are a different, static-utility pattern that a substring match would have incorrectly swept up too) |
| `RETURNS_ELEMENT_IDS` | Bulk/collection accessor of `ElementId`s with no specific relationship semantics identified | `FilteredElementCollector`-style `GetAll...()` |
| `UNKNOWN_ELEMENTID_REFERENCE` | Returns `ElementId`, but the member name gives no reliable hint of the target type or relationship | `Element.Id` |
| `UNKNOWN_DB_OBJECT_REFERENCE` | Returns a concrete Revit DB object type, but no keyword/docs evidence identifies a specific relationship semantics for it | a property returning a DB type not covered by a more specific rule |

## Classification precedence

For a given property/method, `classify.classify_member` picks the most specific applicable
signal in this order:

0. **Two "not a relationship at all" shapes are suppressed before anything else runs**, both
   `MemberKind.METHOD`-only: a **factory method** (name matches `^Create(?!d)` -- the negative
   lookahead excludes `Created*`, a real past-tense property convention like
   `Element.CreatedPhaseId` that the `Phase` keyword rule legitimately matches) constructs a
   brand-new object and says nothing about a relationship *of* `source_type`; a **self-returning
   method** (return type equals `source_type` itself, any name) returns `this` for chaining, not
   a reference to another object of the same type. Both produce no candidate at all. Evidence
   from a real 2024/2025/2026 crawl:
   `ParameterFilterRuleFactory.CreateBeginsWithRule -> FilterRule`,
   `ConnectorElement.CreateCableTrayConnector -> ConnectorElement`,
   `OverrideGraphicSettings.SetCutBackgroundPatternColor -> OverrideGraphicSettings` (and four
   `Set*` siblings on the same type); `FilteredElementCollector.OfCategory`/`.Excluding`/
   `.IntersectWith`/`.ContainedInDesignOption`/`.OfCategoryId -> FilteredElementCollector` (the
   self-return check originally required a `Set*` name prefix, but this cluster's entire
   query-builder API uses other verb prefixes for the identical pattern -- 12/12 edges, zero
   counterexamples -- so the name-prefix requirement was dropped entirely, gated only on
   `MemberKind.METHOD`).
1. **Return type is itself a Revit DB object type** (not `ElementId`, not a primitive) →
   `direct_return_type` confidence; edge type comes from a name-keyword match if any, else
   `UNKNOWN_DB_OBJECT_REFERENCE`. If a name-keyword match's own target type disagrees with the
   actual (compiler-verified) return type -- a coincidental name collision, e.g. a
   `BuiltInFailures.*` field matching the `Level` keyword while actually returning
   `FailureDefinitionId` -- the match is discarded and this falls back to
   `UNKNOWN_DB_OBJECT_REFERENCE` rather than asserting a type-incoherent edge. Confirmed against
   a real 2024 crawl: several previously-populous relationship buckets (`ASSIGNED_TO_LEVEL`,
   `HOSTED_BY`, `USES_MATERIAL`, ...) each dropped 20-70% once this fallback was added.
   `_TYPED_ID_TARGETS` (currently just `WorksetId -> Workset`/`OWNED_BY_WORKSET`) is the deliberate
   opposite exception: a handful of typed identifier structs (unlike bare `ElementId`) name their
   own target through the type system alone, no member name needed, so they bypass the conflict
   check above entirely. This check runs *ahead of* `is_direct_db_object`, not nested under it --
   it must not depend on `known_type_short_names`/`KNOWN_REFERENCE_TYPES`, since a scoped/targeted
   crawl (`DEFAULT_TARGET_CLASSES`) can parse a member returning `WorksetId` (e.g.
   `Element.WorksetId`) without also crawling `WorksetId`'s own type page. The same
   crawl-dependency gap affects *any* keyword rule whose `target_hint` happens to equal the
   actual return type (e.g. the `Room`/`Schema` rules firing on `FamilyInstance.Room`/
   `Entity.Schema` when a scoped crawl parsed `FamilyInstance`/`Entity` but not `Room`/`Schema`
   themselves) -- `is_direct_db_object`'s gate also accepts `name_match`'s own `target_hint`
   agreeing exactly with `bare_return` as sufficient evidence on its own, independent of
   `known_type_short_names`/`KNOWN_REFERENCE_TYPES`, generalizing the same principle to every
   keyword rule instead of a fixed whitelist.
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
