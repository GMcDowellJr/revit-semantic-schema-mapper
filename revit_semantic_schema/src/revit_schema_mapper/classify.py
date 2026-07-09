"""Turn parsed ApiPage objects into node and edge candidates.

This is the "candidate schema" layer described in the project brief: it is
deliberately conservative. Every rule here is written to prefer an
``UNKNOWN_*`` edge type with honest evidence over a specific, wrong-looking
edge type. See docs/edge_taxonomy_v0.md and docs/confidence_model_v0.md for
the taxonomy and confidence labels this module assigns.
"""

from __future__ import annotations

import re
from dataclasses import replace

from .models import (
    ApiPage,
    ClassRole,
    ConfidenceLabel,
    EdgeCandidate,
    EdgeType,
    IsElementCandidate,
    Kind,
    MemberInfo,
    MemberKind,
    NodeCandidate,
)

# Types explicitly called out in the brief as "reference-bearing" even when
# we haven't crawled a page for them ourselves (e.g. because they live in a
# namespace we didn't crawl, or a page failed to parse).
KNOWN_REFERENCE_TYPES = {
    "Element",
    "ElementType",
    "Family",
    "FamilySymbol",
    "Material",
    "Category",
    "Parameter",
    "Definition",
    "View",
    "ViewSheet",
    "Level",
    "Phase",
    "Workset",
    "DesignOption",
    "FilterElement",
    "ParameterFilterElement",
    "FillPatternElement",
    "LinePatternElement",
    "Document",
}

PRIMITIVE_TYPES = {
    "void",
    "bool",
    "int",
    "long",
    "double",
    "float",
    "string",
    "String",
    "Boolean",
    "Int32",
    "Int64",
    "Double",
    "object",
    "Object",
    "byte",
    "short",
    "XYZ",  # a value type, not reference-bearing
    "UV",
    "Color",
    "Plane",
    "Transform",
    "BoundingBoxXYZ",
    "CurveLoop",
    "Outline",
    # Opaque API identifier/value-wrapper types -- confirmed against a real
    # 2024 crawl's unknown_pareto.py breakdown: ForgeTypeId (4031 edges, 26
    # distinct source types, e.g. BaseImportOptions.GetDefaultLengthUnit) and
    # FailureDefinitionId (2067 edges, 166 distinct source types, almost all
    # static fields on BuiltInFailures.* nested classes, e.g.
    # BuiltInFailures.AlignmentFailures.AlignmentCheckStationLabels) together
    # were 71% of every UNKNOWN_DB_OBJECT_REFERENCE/UNKNOWN_ELEMENTID_REFERENCE
    # edge in that crawl. Neither represents a relationship to another BIM
    # object -- a ForgeTypeId identifies a unit/spec/parameter type, a
    # FailureDefinitionId identifies a warning/failure code -- so they belong
    # in the same "value type, not reference-bearing" bucket as XYZ/Color
    # above, not the semantic relationship graph. The rest of this group are
    # smaller siblings of the same pattern (opaque identifier/descriptor
    # wrapper types, not persistent BIM elements), each confirmed present in
    # the same crawl at smaller counts.
    "ForgeTypeId",
    "FailureDefinitionId",
    "ExternalServiceId",
    "ExternalResourceType",
    "IFCAnyHandle",
    "IFCData",
    "ModelPath",
    "FormatOptions",
    "FailureMessage",
    "FailureResolutionType",
    # LinkLoadResult describes the outcome of a link load/reload operation
    # (success/failure/warnings) -- an operation-status object, not a BIM
    # relationship. Evidence, stable across a real 2024/2025/2026 crawl: 11
    # edges, 5 distinct source types, e.g. CADLinkType.LoadFrom/.Reload,
    # LinkLoadContent.GetLinkLoadResult.
    "LinkLoadResult",
    # Geometry/value types beyond the CurveLoop/BoundingBoxXYZ/etc. set
    # above -- same "value type, not reference-bearing" reasoning, also
    # confirmed present in the same crawl (smaller counts, e.g. Curve: 65
    # direct-return + 27 needs_runtime_validation edges across 45+ distinct
    # source types).
    "Curve",
    "Solid",
    "GeometryElement",
    "GeometryObject",
    "Face",
    "CurveArrArray",
    "CurveArray",  # legacy pre-CurveLoop geometry container, same category
    "Polyloop",
}

# The subset of PRIMITIVE_TYPES that are genuine C# scalar primitives, as
# opposed to concrete, already-known API value/identifier types (XYZ,
# ForgeTypeId, FailureDefinitionId, Curve, ...). This distinction matters
# for classify_member's name_match fallback: a bare bool/int/string is
# intentionally still eligible for a weak name_only_candidate guess (rule 5
# of docs/edge_taxonomy_v0.md's precedence list) because the member could
# plausibly be a flag/count that merely hints at a real relationship
# elsewhere. A member returning e.g. FailureDefinitionId cannot -- it's a
# real, different, already-known type, so a keyword collision in a long
# descriptive member name is always a false positive, never weak evidence.
_TRUE_SCALAR_PRIMITIVES = {
    "void", "bool", "int", "long", "double", "float", "string", "String",
    "Boolean", "Int32", "Int64", "Double", "object", "Object", "byte", "short",
}

# Regression case that motivated this split: BuiltInFailures.* fields like
# HighestAssociatedLevelBelowLowestAssociatedLevel return FailureDefinitionId
# (already excluded from the direct-return path above) but their name
# contains "Level" -- without this guard, classify_member fell through to
# name_match and emitted a false ASSIGNED_TO_LEVEL -> Level edge, exactly
# the kind of noise PRIMITIVE_TYPES was extended to remove in the first
# place, just relabeled as a specific-looking (and therefore more
# misleading) edge type instead of an honest UNKNOWN_*.
_STRUCTURALLY_INCOMPATIBLE_VALUE_TYPES = PRIMITIVE_TYPES - _TRUE_SCALAR_PRIMITIVES

# Typed identifier structs that, unlike bare ElementId, unambiguously name
# their own target through the type system alone -- no member-name
# disambiguation needed. Evidence from a real 2024 crawl's
# unknown_pareto.py breakdown: WorksetId, 11 edges, 10 distinct source
# types, all named exactly "WorksetId"/"GetWorksetId" (e.g. Element.WorksetId,
# Document.GetWorksetId), zero counterexamples. This is a deliberate,
# blessed exception to classify_member's direct-return conflict check right
# below: the return type (WorksetId) and the target (Workset) are
# intentionally different types by design, not a coincidental collision.
_TYPED_ID_TARGETS: dict[str, tuple[str, EdgeType]] = {
    "WorksetId": ("Workset", EdgeType.OWNED_BY_WORKSET),
}

# Most _NAME_KEYWORD_RULES target_hint values (Level, Phase, Workset,
# Material, ...) happen to live directly under Autodesk.Revit.DB, so the
# final "Autodesk.Revit.DB.{target}" prefixing below is correct for them by
# coincidence, not by design. Room and Schema don't: their real
# fully-qualified names are Autodesk.Revit.DB.Architecture.Room and
# Autodesk.Revit.DB.ExtensibleStorage.Schema (docs/edge_taxonomy_v0.md,
# pipeline.DEFAULT_TARGET_CLASSES) -- blindly prefixing produced a bogus
# "Autodesk.Revit.DB.Room"/"Autodesk.Revit.DB.Schema" node that doesn't
# correspond to any real crawled type, wrong in candidate_edges.json even
# before graph._Resolver gets a chance to (sometimes) paper over it via
# short-name fallback. Applied only at the final candidate_target_type
# normalization step, not to target_hint itself -- name_match_confirms_
# return_type/the conflict check above compare target_hint against
# bare_return, which is always a bare short name (Room/Schema), so target_hint
# must stay a bare short name too; only the exported full name needs fixing.
_NON_DB_NAMESPACE_TARGETS: dict[str, str] = {
    "Room": "Autodesk.Revit.DB.Architecture.Room",
    "Schema": "Autodesk.Revit.DB.ExtensibleStorage.Schema",
}

# A "Create*" method constructs and returns a brand-new object -- it says
# nothing about a relationship *of* source_type, even though it's declared
# on it (usually a factory/utility class). The negative lookahead excludes
# "Created*" (a real past-tense property naming convention, e.g.
# Element.CreatedPhaseId, which the ASSIGNED_TO_PHASE keyword rule already
# legitimately matches -- this must not suppress that). Evidence: real
# 2024 crawl examples include ParameterFilterRuleFactory.CreateBeginsWithRule
# -> FilterRule, ConnectorElement.CreateCableTrayConnector -> ConnectorElement,
# AssemblyViewUtils.CreatePartList -> ViewSchedule.
_FACTORY_METHOD_NAME_RE = re.compile(r"^Create(?!d)")

# A METHOD that returns its own declaring type is, in every real case found
# across a real 2024/2025/2026 crawl, a fluent/builder method returning
# `this` for chaining -- not a relationship to another object of the same
# type. Originally scoped to just a "Set*" name prefix (evidence:
# OverrideGraphicSettings.SetCutBackgroundPatternColor and four Set*
# siblings, all -> the same OverrideGraphicSettings type), but
# FilteredElementCollector's entire query-builder API turned out to use
# other verb prefixes for the exact same pattern -- ContainedInDesignOption/
# Excluding/IntersectWith/OfCategory/OfCategoryId, all -> the same
# FilteredElementCollector type, 12/12 edges in that cluster, zero
# counterexamples -- so the name-prefix requirement was dropped entirely.
# Still gated to MemberKind.METHOD (not PROPERTY), so a genuine
# self-referential property relationship (e.g. a parent-of-same-type
# reference) stays unaffected -- see
# test_self_referential_property_is_not_treated_as_a_fluent_setter.

# LinkElementId is a general-purpose ID wrapper, structurally the same role
# as bare ElementId -- Revit uses it wherever a reference might cross into a
# linked document -- not a fixed-target typed ID like WorksetId (its
# GetRodAttachedElementId/NumberedElementId/GetSourceElementIds siblings
# have different real targets, confirmed by reading their actual docs
# prose). Evidence: NumberSystem.PlacementLevelId returns LinkElementId and
# its docs literally say "The id of the base level of stairs..." -- a real
# ASSIGNED_TO_LEVEL relationship that the direct-return-object path's
# target_hint-vs-return-type conflict check was incorrectly rejecting,
# because that check assumes the return type itself should equal the
# target (right for a real DB object, wrong for an ID wrapper whose own
# type name is never going to equal any target name). Trusting the
# keyword-matched name here (elementid_with_strong_name), the same way
# bare ElementId already works, is the correct treatment.
_ELEMENTID_LIKE_TYPES = {"ElementId", "LinkElementId"}

_ELEMENTID_COLLECTION_RE = re.compile(
    r"^(?:ICollection|IList|ISet|IEnumerable|List|HashSet)\s*<\s*(?:ElementId|LinkElementId)\s*>$"
)
_GENERIC_ELEMENTID_COLLECTION_RE = re.compile(
    r"^(?:ICollection|IList|ISet|IEnumerable|List|HashSet)\s*<\s*([\w.]+)\s*>$"
)

# (name keyword regex, edge type, inferred target short type name or None)
# Order matters: first match wins. More specific keywords are listed before
# their more generic overlaps (e.g. "FillPattern" before the bare "Pattern").
_NAME_KEYWORD_RULES: list[tuple[re.Pattern[str], EdgeType, str | None]] = [
    (re.compile(r"Template", re.IGNORECASE), EdgeType.CONTROLLED_BY_TEMPLATE, "View"),
    (re.compile(r"FillPattern", re.IGNORECASE), EdgeType.USES_FILL_PATTERN, "FillPatternElement"),
    (re.compile(r"LinePattern", re.IGNORECASE), EdgeType.USES_LINE_PATTERN, "LinePatternElement"),
    (re.compile(r"Material", re.IGNORECASE), EdgeType.USES_MATERIAL, "Material"),
    (re.compile(r"Sheet", re.IGNORECASE), EdgeType.PLACED_ON_SHEET, "ViewSheet"),
    (re.compile(r"^GetTagged|Tag(ged)?", re.IGNORECASE), EdgeType.TAGS_ELEMENT, None),
    (re.compile(r"^GetHosted|Host", re.IGNORECASE), EdgeType.HOSTED_BY, None),
    (re.compile(r"Workset", re.IGNORECASE), EdgeType.OWNED_BY_WORKSET, "Workset"),
    (re.compile(r"Level", re.IGNORECASE), EdgeType.ASSIGNED_TO_LEVEL, "Level"),
    (re.compile(r"Phase", re.IGNORECASE), EdgeType.ASSIGNED_TO_PHASE, "Phase"),
    (re.compile(r"DesignOption", re.IGNORECASE), EdgeType.ASSIGNED_TO_DESIGN_OPTION, "DesignOption"),
    (re.compile(r"^GetMember|Group", re.IGNORECASE), EdgeType.MEMBER_OF_GROUP, None),
    (re.compile(r"Assembly", re.IGNORECASE), EdgeType.MEMBER_OF_ASSEMBLY, None),
    (re.compile(r"^GetDependent|Dependent", re.IGNORECASE), EdgeType.DEPENDS_ON, None),
    (re.compile(r"^Symbol$", re.IGNORECASE), EdgeType.INSTANCE_OF, "FamilySymbol"),
    (re.compile(r"^(Family)$", re.IGNORECASE), EdgeType.BELONGS_TO_FAMILY, "Family"),
    # Evidence from a live 2024 crawl: 19 edges, 19 distinct source types
    # (spanning DB, DB.Events, DB.IFC, DB.Structure), all named exactly
    # "Document"/"GetDocument", all returning Document with direct_return_type
    # confidence, zero counterexamples -- see docs/edge_taxonomy_v0.md's
    # REFERENCES entry.
    (re.compile(r"^(Get)?Document$", re.IGNORECASE), EdgeType.REFERENCES, "Document"),
    # Evidence from a real 2024 crawl's unknown_pareto.py breakdown: 12
    # UNKNOWN_ELEMENTID_REFERENCE edges across 12 distinct source types, all
    # named exactly "ViewId"/"GetViewId" (e.g. BIMExportOptions.ViewId,
    # ElevationMarker.GetViewId), zero counterexamples -- same evidence shape
    # as the Document/GetDocument rule above.
    (re.compile(r"^(Get)?ViewId$", re.IGNORECASE), EdgeType.REFERENCES, "View"),
    # Exact match. Evidence from a real crawl's candidate_edges.json: 6
    # UNKNOWN_DB_OBJECT_REFERENCE edges across 6 distinct source types, all
    # named exactly "View" (Control.View, Dimension.View, Options.View,
    # SpatialElementTag.View, Events.ViewPrintedEventArgs.View,
    # Events.ViewPrintingEventArgs.View), all already direct_return_type
    # confidence (View is always a crawled type), zero counterexamples --
    # this rule only upgrades the edge_type from the generic unknown bucket
    # to REFERENCES, same as the Document/ViewId rules above.
    (re.compile(r"^View$", re.IGNORECASE), EdgeType.REFERENCES, "View"),
    # Exact match. Evidence from a real crawl's candidate_edges.json: 7
    # UNKNOWN_DB_OBJECT_REFERENCE edges across 7 distinct source types, all
    # named exactly "Location" (AssemblyInstance/Element/FamilyInstance/
    # Group/ModelText/SpatialElement/SpatialElementTag.Location) -- Element
    # is the base declaring type, the others are all overrides of it, per
    # AssemblyInstance's docs ("used to find the physical location of the
    # assembly instance") -- zero counterexamples, same evidence shape as
    # the View rule above.
    (re.compile(r"^Location$", re.IGNORECASE), EdgeType.REFERENCES, "Location"),
    # Exact match. Evidence from a real crawl's candidate_edges.json: 3
    # UNKNOWN_DB_OBJECT_REFERENCE edges across 3 distinct source types, all
    # named exactly "GetExternalResourceReference" (Element/
    # ExternalResourceLoadData/LinkLoadResult), all returning
    # ExternalResourceReference, zero counterexamples -- the method name
    # already spells out its own return type, self-confirming the same way
    # GetDocument/SketchPlane do.
    (re.compile(r"^GetExternalResourceReference$", re.IGNORECASE), EdgeType.REFERENCES, "ExternalResourceReference"),
    # Evidence from a real 2024 crawl's unknown_pareto.py breakdown: 7 edges
    # across 4 distinct source types (FamilyInstance.Room/.FromRoom/.ToRoom,
    # Document.GetRoomAtPoint), 3 of 7 independently corroborated by
    # RevitLookup, zero apparent counterexamples -- same evidence shape as
    # the Document/ViewId rules above.
    (re.compile(r"Room", re.IGNORECASE), EdgeType.REFERENCES, "Room"),
    # Exact match (not a bare substring) deliberately, unlike most rules
    # above: the "Schema" cluster in a real 2024/2025/2026 crawl was mixed --
    # Entity.Schema/Field.Schema/Field.SubSchema are a genuine "this
    # object's structure is defined by this Schema" relationship, but
    # Schema.ListSchemas/Schema.Lookup are static registry/lookup utility
    # methods with different semantics that a bare "Schema" substring match
    # would have incorrectly swept up too (ListSchemas contains "Schema").
    (re.compile(r"^(Sub)?Schema$", re.IGNORECASE), EdgeType.REFERENCES, "Schema"),
    # Exact match, checked before the "Sketch$" rule below: SketchPlane is a
    # distinct real DB type (a work plane), not a kind of Sketch, even though
    # its name ends in "Sketch...". Evidence from a real 2024 crawl: 4 edges,
    # 4 distinct source types, all named exactly "SketchPlane"
    # (CurveByPoints.SketchPlane, CurveElement.SketchPlane, Sketch.SketchPlane,
    # View.SketchPlane), zero counterexamples.
    (re.compile(r"^SketchPlane$", re.IGNORECASE), EdgeType.REFERENCES, "SketchPlane"),
    # Ends-with, not a bare substring: catches BottomSketch/TopSketch/
    # PathSketch/ProfileSketch/bare Sketch (the profile/path that defines a
    # solid's shape) while naturally excluding SketchPlane (doesn't end in
    # "Sketch") and unrelated coincidences like View.GetSketchyLines (a
    # ViewDisplaySketchyLines graphics-style enum, nothing to do with
    # geometry sketches). Evidence from a real 2024 crawl: 10 edges, 5
    # distinct source types (Blend, Extrusion, Revolution, Sweep,
    # SweptBlend), zero counterexamples. The optional "Id" suffix covers the
    # ElementId-returning form of the same relationship (e.g.
    # Toposolid.SketchId/FabricSheet.SketchId) -- doesn't collide with the
    # SketchPlane rule above since "SketchPlaneId" ends in "PlaneId", not
    # "SketchId" ('SketchPlaneId'.endswith('SketchId') is False).
    (re.compile(r"Sketch(Id)?$", re.IGNORECASE), EdgeType.DEPENDS_ON, "Sketch"),
    # "TypeId" added after the original "Type"/"GetTypeId" pair turned out to
    # miss the dominant real naming convention entirely: the same crawl's
    # UNKNOWN_ELEMENTID_REFERENCE "Type" cluster (9 edges, 9 distinct source
    # types) was 100% literally named "TypeId" (e.g. DirectShape.TypeId,
    # Subelement.TypeId) -- none matched the pre-existing pattern at all.
    (re.compile(r"^(Type|TypeId|GetTypeId)$", re.IGNORECASE), EdgeType.TYPE_OF, None),
    # Ends-with, not a bare exact match: a follow-up pareto re-run (same
    # three crawled years) confirmed the exact-match version above left
    # exactly one edge behind every year -- Structure.Hub
    # .GetHubConnectorManager, the same real member all three times, also
    # returning ConnectorManager but not named exactly "ConnectorManager".
    # Safe to broaden since the direct-return-object path's target-vs-
    # return-type conflict check still gates this on the return type
    # actually being ConnectorManager -- a member named e.g. "FooManager"
    # can't accidentally match ("ConnectorManager" is checked as a suffix,
    # not a substring, so it also can't fire on an unrelated "...Connector
    # ManagerThing"-shaped name). Original evidence: a stable 6-edge/
    # 6-distinct-source-type cluster every year (Connector/FabricationPart/
    # MEPCurve/MEPModel/MEPSystem.ConnectorManager + Hub.GetHubConnectorManager),
    # zero counterexamples now that all 6 are accounted for.
    (re.compile(r"ConnectorManager$", re.IGNORECASE), EdgeType.REFERENCES, "ConnectorManager"),
    # Exact match. Evidence from the same three-year pareto breakdown: a
    # complete (all examples captured, cluster count == 5 == examples shown)
    # 5-edge/5-distinct-source-type cluster every year
    # (BuildingPadType/CeilingType/FloorType/RoofType/WallType), all named
    # exactly "ThermalProperties", zero counterexamples.
    (re.compile(r"^ThermalProperties$", re.IGNORECASE), EdgeType.REFERENCES, "ThermalProperties"),
    # Ends-with, no target hint: this single naming pattern covers two
    # distinct real target types (RebarRoundingManager, FabricRoundingManager)
    # that differ only in which structural concept they round for, so the
    # target must come from the (type-system-verified) return type itself,
    # same as the direct-return-object path already does for every other
    # rule with target_hint=None. Evidence from the same three-year pareto
    # breakdown: two complete clusters, stable every year --
    # Rebar/RebarBarType/RebarContainer/RebarInSystem.GetReinforcementRoundingManager
    # + ReinforcementSettings.GetRebarRoundingManager (5 edges) and
    # FabricArea/FabricSheet/FabricSheetType.GetReinforcementRoundingManager +
    # ReinforcementSettings.GetFabricRoundingManager (4 edges), zero
    # counterexamples.
    (re.compile(r"RoundingManager$", re.IGNORECASE), EdgeType.REFERENCES, None),
    # Exact match, checked ahead of the generic "Category" rule below on
    # purpose: "Subcategory" contains "Category" as a substring, so without
    # this more specific rule first, CurveByPoints/ModelCurve/SymbolicCurve
    # .Subcategory (all really return GraphicsStyle, not Category -- Revit
    # represents a subcategory as a GraphicsStyle object) hit the
    # target_hint-vs-return-type conflict check and fall back to
    # UNKNOWN_DB_OBJECT_REFERENCE instead of asserting the wrong target.
    # Evidence from the three-year pareto breakdown: a complete 3-edge/
    # 3-distinct-source-type cluster every year, zero counterexamples.
    (re.compile(r"^Subcategory$", re.IGNORECASE), EdgeType.REFERENCES, "GraphicsStyle"),
    # Evidence from the same breakdown: a complete 4-edge/4-distinct-source
    # ("GetGraphicsStyle" self-confirming direct-return, same shape as
    # GetDocument/SketchPlane) plus a complete 3-edge/3-distinct-source
    # "GraphicsStyleId" ElementId cluster, both stable every year, zero
    # counterexamples.
    (re.compile(r"GraphicsStyle", re.IGNORECASE), EdgeType.REFERENCES, "GraphicsStyle"),
    (re.compile(r"Category", re.IGNORECASE), EdgeType.HAS_CATEGORY, "Category"),
    (re.compile(r"Parameter", re.IGNORECASE), EdgeType.HAS_PARAMETER, None),
    (re.compile(r"^GetAll", re.IGNORECASE), EdgeType.RETURNS_ELEMENT_IDS, None),
    (re.compile(r"^GetMaterial", re.IGNORECASE), EdgeType.USES_MATERIAL, "Material"),
    (re.compile(r"^GetGenerating", re.IGNORECASE), EdgeType.DEPENDS_ON, None),
]

_DOCS_HINT_PHRASES = [
    "is controlled by",
    "is hosted by",
    "hosted by",
    "template for",
    "belongs to the family",
    "assigned to the level",
    "assigned to the phase",
    "owned by the workset",
    "member of the group",
    "member of the assembly",
    "depends on",
    "references the",
]


def _resolve_base_type_map(pages: list[ApiPage]) -> dict[str, str]:
    return {page.full_type_name: page.base_type for page in pages if page.kind in (Kind.CLASS, Kind.STRUCT) and page.base_type}


def _resolve_inheritance_chain(full_type_name: str, base_map: dict[str, str], short_to_full: dict[str, str]) -> tuple[list[str], IsElementCandidate]:
    chain: list[str] = []
    current = full_type_name
    seen = {current}
    resolved_fully = True
    while True:
        base = base_map.get(current)
        if base is None:
            # try resolving a short base-class name (e.g. "Element") to a full name we know about
            base_full = short_to_full.get(current.rsplit(".", 1)[-1]) if current in seen else None
            base = base_map.get(base_full) if base_full else None
        if base is None:
            break
        if base in seen:
            break
        chain.append(base)
        seen.add(base)
        current = base
    last = chain[-1] if chain else full_type_name
    if any(node.rsplit(".", 1)[-1] == "Element" for node in chain) or full_type_name.rsplit(".", 1)[-1] == "Element":
        return chain, IsElementCandidate.TRUE
    if not chain:
        return chain, IsElementCandidate.UNKNOWN
    if last.rsplit(".", 1)[-1] in {"Object", "ValueType"}:
        return chain, IsElementCandidate.FALSE
    resolved_fully = last in base_map
    return chain, (IsElementCandidate.UNKNOWN if not resolved_fully else IsElementCandidate.FALSE)


_UTILITY_NAME_SUFFIXES = ("Utils", "Utility", "Utilities")
_ELEMENT_TYPE_SHORT_NAMES = {"Element", "ElementType"}


def classify_class_role(page: ApiPage, is_element: IsElementCandidate) -> ClassRole:
    """Coarse structural classification, orthogonal to ``is_element_candidate``.

    Deliberately name/kind-based (not runtime-verified) -- treat as a
    starting hypothesis for grouping candidates, same spirit as the rest of
    this module's confidence labels. Precedence (first match wins):

    1. ``enum`` -- an enum page can't be anything else.
    2. ``value_object`` -- a struct (.NET value type; a data holder, not an
       Element).
    3. ``options_class`` -- name ends in "Options" (e.g. ACADExportOptions).
    4. ``element_type`` -- literally ``Element``/``ElementType`` themselves.
    5. ``element_subtype`` -- anything else the inheritance chain resolves
       as deriving from Element/ElementType.
    6. ``utility_class`` -- name ends in Utils/Utility/Utilities, or every
       member is a method with no properties at all (a static helper bag).
       Interfaces are excluded from this check: an interface with only
       method members (the normal shape for an interface) is a contract,
       not a static helper class, and ``build_node_candidates`` includes
       ``Kind.INTERFACE`` pages here.
    7. ``unknown`` -- none of the above matched (including any interface
       that didn't match an earlier, kind-agnostic rule).
    """
    if page.kind is Kind.ENUM:
        return ClassRole.ENUM
    if page.kind is Kind.STRUCT:
        return ClassRole.VALUE_OBJECT

    short_name = page.type_name
    if short_name.endswith("Options"):
        return ClassRole.OPTIONS_CLASS

    if short_name in _ELEMENT_TYPE_SHORT_NAMES:
        return ClassRole.ELEMENT_TYPE
    if is_element is IsElementCandidate.TRUE:
        return ClassRole.ELEMENT_SUBTYPE

    if page.kind is not Kind.INTERFACE:
        if short_name.endswith(_UTILITY_NAME_SUFFIXES):
            return ClassRole.UTILITY_CLASS
        if page.members and all(m.kind is MemberKind.METHOD for m in page.members):
            return ClassRole.UTILITY_CLASS

    return ClassRole.UNKNOWN


def build_node_candidates(pages: list[ApiPage]) -> list[NodeCandidate]:
    type_pages = [p for p in pages if p.kind in (Kind.CLASS, Kind.STRUCT, Kind.ENUM, Kind.INTERFACE)]
    base_map = _resolve_base_type_map(type_pages)
    short_to_full = {p.full_type_name.rsplit(".", 1)[-1]: p.full_type_name for p in type_pages}

    candidates: list[NodeCandidate] = []
    for page in type_pages:
        chain, is_element = _resolve_inheritance_chain(page.full_type_name, base_map, short_to_full)
        evidence = [f"declared kind: {page.kind.value}"]
        if page.base_type:
            evidence.append(f"syntax block base list: {page.base_type}")
        if chain:
            evidence.append(f"resolved inheritance chain: {' -> '.join(chain)}")
        if page.kind is Kind.ENUM:
            is_element = IsElementCandidate.FALSE
            evidence.append("enums are never element candidates")

        candidates.append(
            NodeCandidate(
                full_type_name=page.full_type_name,
                short_name=page.type_name,
                kind=page.kind,
                namespace=page.namespace,
                base_type=page.base_type,
                inheritance_chain=chain,
                is_element_candidate=is_element,
                class_role=classify_class_role(page, is_element),
                evidence=evidence,
                source_url=page.source_url,
            )
        )
    return candidates


def _match_name_keyword(member_name: str) -> tuple[EdgeType, str | None, str] | None:
    for pattern, edge_type, target_hint in _NAME_KEYWORD_RULES:
        if pattern.search(member_name):
            return edge_type, target_hint, pattern.pattern
    return None


def _find_docs_hint(text: str) -> str | None:
    lowered = text.lower()
    for phrase in _DOCS_HINT_PHRASES:
        if phrase in lowered:
            return phrase
    return None


def classify_member(member: MemberInfo, source_type: str, known_type_short_names: set[str]) -> EdgeCandidate | None:
    if not member.return_type:
        return None
    return_type = member.return_type.strip()

    is_elementid = return_type in _ELEMENTID_LIKE_TYPES
    collection_match = _ELEMENTID_COLLECTION_RE.match(return_type)
    is_elementid_collection = bool(collection_match)
    generic_match = _GENERIC_ELEMENTID_COLLECTION_RE.match(return_type)
    generic_inner_bare = generic_match.group(1).rsplit(".", 1)[-1] if generic_match else None
    is_unresolved_generic_collection = (
        bool(generic_match)
        and not is_elementid_collection
        and generic_inner_bare not in PRIMITIVE_TYPES
    )

    bare_return = return_type.rsplit(".", 1)[-1]

    # Hard stop before name_match is even consulted: a member whose return
    # type (bare or the element type of an unresolved generic collection)
    # is a concrete, already-known value/identifier type can never
    # structurally be the target of a name-matched relationship guess --
    # see _STRUCTURALLY_INCOMPATIBLE_VALUE_TYPES's docstring.
    if bare_return in _STRUCTURALLY_INCOMPATIBLE_VALUE_TYPES or generic_inner_bare in _STRUCTURALLY_INCOMPATIBLE_VALUE_TYPES:
        return None

    if member.kind is MemberKind.METHOD:
        # A factory method constructs a brand-new object; it isn't a
        # relationship of source_type regardless of what it returns -- see
        # _FACTORY_METHOD_NAME_RE's docstring.
        if _FACTORY_METHOD_NAME_RE.match(member.name):
            return None
        # A method that returns its own declaring type is a fluent/builder
        # method returning `this` for chaining, not referencing another
        # object of the same type -- see the comment above this block. Also
        # covers a static registry/lookup utility that returns a collection
        # of its own declaring type (e.g. Schema.ListSchemas() -> IList
        # <Schema>) -- same "not a relationship of source_type" reasoning,
        # just wrapped in a collection instead of returned bare. Confirmed
        # against real docs: Schema.ListSchemas is exactly the case the
        # Schema keyword rule's own comment already calls out as a
        # different, static-utility pattern to exclude, but the generic-
        # collection form slipped through this check because bare_return
        # for "IList<Schema>" is the whole collection type string, not
        # "Schema" -- generic_inner_bare (computed above, before this
        # block) is what actually holds "Schema" here.
        if bare_return == source_type.rsplit(".", 1)[-1] or generic_inner_bare == source_type.rsplit(".", 1)[-1]:
            return None

    # Checked ahead of is_direct_db_object, not nested under it: a typed ID
    # struct's own type is the evidence (see _TYPED_ID_TARGETS's docstring),
    # so this must not depend on known_type_short_names/KNOWN_REFERENCE_TYPES
    # -- a scoped/targeted crawl (docs/edge_taxonomy_v0.md's
    # DEFAULT_TARGET_CLASSES) can easily parse a member returning WorksetId
    # (e.g. Element.WorksetId) without also crawling WorksetId's own type
    # page, in which case is_direct_db_object would be False and this rule
    # would silently never fire, falling back to a much weaker
    # name_only_candidate guess (kept out of graph_core.json's CORE tier)
    # instead of the type-system-backed evidence this rule exists to use.
    is_typed_id = bare_return in _TYPED_ID_TARGETS
    name_match = _match_name_keyword(member.name)

    # A name-keyword match whose own hardcoded target_hint agrees *exactly*
    # with the actual (compiler-verified) return type is self-confirming
    # evidence, independent of whether the crawl happened to also discover
    # that target's own type page -- the same principle as _TYPED_ID_TARGETS
    # above, generalized to every keyword rule instead of a fixed whitelist.
    # Regression case: a scoped/targeted crawl that parses FamilyInstance/
    # ExtensibleStorage.Entity but never crawls Room's/Schema's own type
    # page left known_type_short_names without "Room"/"Schema", so
    # FamilyInstance.Room and Entity.Schema (both real, confirmed
    # direct-return relationships -- the keyword rule wouldn't exist
    # without that evidence) fell back to a weak name_only_candidate guess,
    # kept out of graph_core.json's CORE tier for no good reason.
    name_match_confirms_return_type = bool(name_match and name_match[1] is not None and name_match[1] == bare_return)

    is_direct_db_object = (
        not is_elementid
        and not is_elementid_collection
        and not is_typed_id
        and bare_return not in PRIMITIVE_TYPES
        and (
            bare_return in KNOWN_REFERENCE_TYPES
            or bare_return in known_type_short_names
            or name_match_confirms_return_type
        )
    )

    docs_hint = _find_docs_hint(member.summary) or _find_docs_hint(member.remarks)

    if not (is_typed_id or is_elementid or is_elementid_collection or is_direct_db_object or is_unresolved_generic_collection or name_match):
        return None

    evidence: list[str] = []
    parser_notes: list[str] = []

    if is_typed_id:
        target_short_name, edge_type = _TYPED_ID_TARGETS[bare_return]
        candidate_target_type = target_short_name
        confidence = ConfidenceLabel.DIRECT_RETURN_TYPE
        evidence.append(
            f"return type '{return_type}' is a typed identifier that unambiguously names its own "
            f"target ('{target_short_name}') through the type system alone"
        )
    elif is_direct_db_object:
        confidence = ConfidenceLabel.DIRECT_RETURN_TYPE
        # A name-keyword match whose own target_hint names a *different*
        # concrete type than what this member actually, verifiably returns
        # is a coincidental name collision, not real relationship evidence
        # -- e.g. a BuiltInFailures.* field matching the "Level" keyword
        # while actually returning FailureDefinitionId. direct_return_type
        # is documented (docs/confidence_model_v0.md) as "the strongest
        # static signal available from docs alone: the compiler itself
        # guarantees the relationship's target type" -- that guarantee is
        # exactly what a conflicting target_hint contradicts, so the
        # (weaker, heuristic) name match loses and this falls back to the
        # honest unknown bucket instead of asserting a type-incoherent
        # edge_type/target_type pair. No conflict (target_hint is None, or
        # equals bare_return, or there's no name_match at all) keeps the
        # existing behavior unchanged.
        if name_match and name_match[1] is not None and name_match[1] != bare_return:
            edge_type = EdgeType.UNKNOWN_DB_OBJECT_REFERENCE
            candidate_target_type = bare_return
            evidence.append(
                f"member name '{member.name}' matches keyword pattern /{name_match[2]}/ implying target "
                f"'{name_match[1]}', but the actual return type '{bare_return}' conflicts -- treating the "
                "name match as a coincidental collision rather than relationship evidence"
            )
        else:
            edge_type = name_match[0] if name_match else EdgeType.UNKNOWN_DB_OBJECT_REFERENCE
            candidate_target_type = bare_return
        evidence.append(f"return type '{return_type}' directly names a Revit DB object type")
    elif is_elementid:
        if name_match:
            edge_type, target_hint, pattern = name_match
            confidence = ConfidenceLabel.ELEMENTID_WITH_STRONG_NAME
            evidence.append(f"member name '{member.name}' matches keyword pattern /{pattern}/")
            candidate_target_type = target_hint
            if target_hint is None:
                parser_notes.append("name keyword matched but no reliable target type mapping exists for it yet")
        else:
            edge_type = EdgeType.UNKNOWN_ELEMENTID_REFERENCE
            confidence = ConfidenceLabel.UNKNOWN_REFERENCE
            candidate_target_type = None
            evidence.append(f"return type is {return_type!r}, an ID wrapper, but member name gives no strong hint of the target type")
    elif is_elementid_collection:
        if name_match:
            edge_type, target_hint, pattern = name_match
            confidence = ConfidenceLabel.ELEMENTID_COLLECTION_WITH_STRONG_NAME
            evidence.append(f"member name '{member.name}' matches keyword pattern /{pattern}/")
            candidate_target_type = target_hint
        else:
            edge_type = EdgeType.RETURNS_ELEMENT_IDS
            confidence = ConfidenceLabel.UNKNOWN_REFERENCE
            candidate_target_type = None
            evidence.append(f"return type '{return_type}' is a collection of ID wrappers with no strong name hint")
    elif is_unresolved_generic_collection:
        edge_type = name_match[0] if name_match else EdgeType.UNKNOWN_DB_OBJECT_REFERENCE
        confidence = ConfidenceLabel.NEEDS_RUNTIME_VALIDATION
        candidate_target_type = generic_match.group(1) if generic_match else None
        evidence.append(f"return type '{return_type}' is a generic collection whose element type cannot be statically confirmed as reference-bearing")
        parser_notes.append("needs_runtime_validation: element type of the generic collection should be confirmed against a live model or the .NET metadata")
    else:
        edge_type, target_hint, pattern = name_match  # type: ignore[misc]
        confidence = ConfidenceLabel.NAME_ONLY_CANDIDATE
        candidate_target_type = target_hint
        evidence.append(f"member name '{member.name}' matches keyword pattern /{pattern}/ but return type '{return_type}' gives no type-level confirmation")

    if docs_hint:
        evidence.append(f"docs text contains relationship phrase: {docs_hint!r}")
        if confidence in (ConfidenceLabel.NAME_ONLY_CANDIDATE, ConfidenceLabel.UNKNOWN_REFERENCE):
            confidence = ConfidenceLabel.DOCS_SEMANTIC_HINT

    if candidate_target_type and not candidate_target_type.startswith("Autodesk.Revit"):
        candidate_target_type = _NON_DB_NAMESPACE_TARGETS.get(
            candidate_target_type, f"Autodesk.Revit.DB.{candidate_target_type}"
        )

    return EdgeCandidate(
        source_type=source_type,
        member_name=member.name,
        member_kind=member.kind,
        raw_signature=member.raw_signature,
        return_type=return_type,
        parameter_types=[p.type for p in member.parameters],
        candidate_target_type=candidate_target_type,
        candidate_edge_type=edge_type,
        edge_confidence=confidence,
        evidence=evidence,
        source_url=member.source_url,
        parser_notes=parser_notes,
    )


def build_edge_candidates(pages: list[ApiPage]) -> list[EdgeCandidate]:
    known_type_short_names = {
        p.type_name for p in pages if p.kind in (Kind.CLASS, Kind.STRUCT, Kind.INTERFACE)
    } | KNOWN_REFERENCE_TYPES

    candidates: list[EdgeCandidate] = []
    for page in pages:
        for member in page.members:
            source_type = member.declaring_type or page.full_type_name
            candidate = classify_member(member, source_type, known_type_short_names)
            if candidate is not None:
                candidates.append(candidate)
    return candidates
