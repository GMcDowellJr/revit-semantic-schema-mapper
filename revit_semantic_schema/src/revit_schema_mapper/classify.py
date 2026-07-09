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
    "Polyloop",
}

_ELEMENTID_COLLECTION_RE = re.compile(
    r"^(?:ICollection|IList|ISet|IEnumerable|List|HashSet)\s*<\s*ElementId\s*>$"
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
    # "TypeId" added after the original "Type"/"GetTypeId" pair turned out to
    # miss the dominant real naming convention entirely: the same crawl's
    # UNKNOWN_ELEMENTID_REFERENCE "Type" cluster (9 edges, 9 distinct source
    # types) was 100% literally named "TypeId" (e.g. DirectShape.TypeId,
    # Subelement.TypeId) -- none matched the pre-existing pattern at all.
    (re.compile(r"^(Type|TypeId|GetTypeId)$", re.IGNORECASE), EdgeType.TYPE_OF, None),
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

    is_elementid = return_type == "ElementId"
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
    is_direct_db_object = (
        not is_elementid
        and not is_elementid_collection
        and bare_return not in PRIMITIVE_TYPES
        and (bare_return in KNOWN_REFERENCE_TYPES or bare_return in known_type_short_names)
    )

    name_match = _match_name_keyword(member.name)
    docs_hint = _find_docs_hint(member.summary) or _find_docs_hint(member.remarks)

    if not (is_elementid or is_elementid_collection or is_direct_db_object or is_unresolved_generic_collection or name_match):
        return None

    evidence: list[str] = []
    parser_notes: list[str] = []

    if is_direct_db_object:
        edge_type = name_match[0] if name_match else EdgeType.UNKNOWN_DB_OBJECT_REFERENCE
        candidate_target_type = bare_return
        confidence = ConfidenceLabel.DIRECT_RETURN_TYPE
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
            evidence.append("return type is ElementId but member name gives no strong hint of the target type")
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
            evidence.append(f"return type '{return_type}' is a collection of ElementId with no strong name hint")
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
        candidate_target_type = f"Autodesk.Revit.DB.{candidate_target_type}"

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
