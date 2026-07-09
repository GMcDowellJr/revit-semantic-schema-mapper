from revit_schema_mapper.classify import classify_class_role, classify_member
from revit_schema_mapper.models import ApiPage, ClassRole, ConfidenceLabel, EdgeType, IsElementCandidate, Kind, MemberInfo, MemberKind


def _page(type_name, kind=Kind.CLASS, members=None, namespace="Autodesk.Revit.DB"):
    return ApiPage(
        revit_version="2024",
        namespace=namespace,
        type_name=type_name,
        full_type_name=f"{namespace}.{type_name}",
        kind=kind,
        members=members or [],
        source_url=f"https://www.revitapidocs.com/2024/{type_name.lower()}.htm",
    )


def _method(name):
    return MemberInfo(
        name=name,
        kind=MemberKind.METHOD,
        declaring_type="Autodesk.Revit.DB.Whatever",
        raw_signature=f"public void {name}()",
        source_url="https://www.revitapidocs.com/2024/fake.htm",
    )


def _property(name, return_type="string"):
    return MemberInfo(
        name=name,
        kind=MemberKind.PROPERTY,
        declaring_type="Autodesk.Revit.DB.Whatever",
        raw_signature=f"public {return_type} {name} {{ get; }}",
        return_type=return_type,
        source_url="https://www.revitapidocs.com/2024/fake.htm",
    )


def test_class_role_enum():
    page = _page("ACADVersion", kind=Kind.ENUM)
    assert classify_class_role(page, IsElementCandidate.FALSE) is ClassRole.ENUM


def test_class_role_value_object_for_struct():
    page = _page("XYZ", kind=Kind.STRUCT)
    assert classify_class_role(page, IsElementCandidate.UNKNOWN) is ClassRole.VALUE_OBJECT


def test_class_role_options_class():
    page = _page("ACADExportOptions")
    assert classify_class_role(page, IsElementCandidate.FALSE) is ClassRole.OPTIONS_CLASS


def test_class_role_element_type_for_element_itself():
    page = _page("Element")
    assert classify_class_role(page, IsElementCandidate.TRUE) is ClassRole.ELEMENT_TYPE


def test_class_role_element_subtype_when_inheritance_resolves_true():
    page = _page("FamilyInstance")
    assert classify_class_role(page, IsElementCandidate.TRUE) is ClassRole.ELEMENT_SUBTYPE


def test_class_role_utility_class_by_name_suffix():
    page = _page("AdaptiveComponentFamilyUtils", members=[_method("GetNumberOfAdaptivePoints")])
    assert classify_class_role(page, IsElementCandidate.FALSE) is ClassRole.UTILITY_CLASS


def test_class_role_utility_class_by_all_static_methods_no_properties():
    page = _page("SomeHelperBag", members=[_method("DoThing"), _method("DoOtherThing")])
    assert classify_class_role(page, IsElementCandidate.FALSE) is ClassRole.UTILITY_CLASS


def test_class_role_interface_with_only_methods_is_not_utility_class():
    # A method-only interface is the normal shape for an interface (a
    # contract), not a static helper bag -- must not be mis-tagged
    # utility_class just because build_node_candidates includes interfaces.
    page = _page("IFailuresPreprocessor", kind=Kind.INTERFACE, members=[_method("PreprocessFailures")])
    assert classify_class_role(page, IsElementCandidate.FALSE) is ClassRole.UNKNOWN


def test_class_role_interface_with_utils_like_name_is_not_utility_class():
    page = _page("IWallUtils", kind=Kind.INTERFACE, members=[_method("DoThing")])
    assert classify_class_role(page, IsElementCandidate.FALSE) is ClassRole.UNKNOWN


def test_class_role_unknown_when_nothing_matches():
    page = _page("SomeDataHolder", members=[_property("Foo"), _method("DoThing")])
    assert classify_class_role(page, IsElementCandidate.FALSE) is ClassRole.UNKNOWN


def _member(name, return_type, summary="", declaring_type="Autodesk.Revit.DB.View"):
    return MemberInfo(
        name=name,
        kind=MemberKind.PROPERTY,
        declaring_type=declaring_type,
        raw_signature=f"public {return_type} {name} {{ get; }}",
        return_type=return_type,
        summary=summary,
        source_url="https://www.revitapidocs.com/2027/fake.htm",
    )


def test_view_template_id_classified_as_controlled_by_template():
    member = _member("ViewTemplateId", "ElementId", summary="Gets or sets the id of the view template applied to this view.")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.View", known_type_short_names=set())

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.CONTROLLED_BY_TEMPLATE
    assert candidate.edge_confidence is ConfidenceLabel.ELEMENTID_WITH_STRONG_NAME
    assert candidate.candidate_target_type == "Autodesk.Revit.DB.View"


def test_family_instance_symbol_classified_as_instance_of():
    member = _member("Symbol", "FamilySymbol", declaring_type="Autodesk.Revit.DB.FamilyInstance")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.FamilyInstance", known_type_short_names={"FamilySymbol"})

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.INSTANCE_OF
    assert candidate.edge_confidence is ConfidenceLabel.DIRECT_RETURN_TYPE
    assert candidate.candidate_target_type == "Autodesk.Revit.DB.FamilySymbol"


def test_document_property_classified_as_references():
    """known_type_short_names is deliberately empty here -- Document must get
    direct_return_type confidence via KNOWN_REFERENCE_TYPES regardless of
    whether the current crawl happened to independently crawl Document's own
    type page. A scoped/targeted crawl using DEFAULT_TARGET_CLASSES never
    includes Document itself, so relying on known_type_short_names alone
    would silently degrade this to name_only_candidate for exactly that case
    -- see the regression test below.
    """
    member = _member("Document", "Document", declaring_type="Autodesk.Revit.DB.Element")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.Element", known_type_short_names=set())

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.REFERENCES
    assert candidate.edge_confidence is ConfidenceLabel.DIRECT_RETURN_TYPE
    assert candidate.candidate_target_type == "Autodesk.Revit.DB.Document"


def test_get_document_method_classified_as_references():
    member = _member("GetDocument", "Document", declaring_type="Autodesk.Revit.DB.FailuresAccessor")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.FailuresAccessor", known_type_short_names=set())

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.REFERENCES
    assert candidate.edge_confidence is ConfidenceLabel.DIRECT_RETURN_TYPE
    assert candidate.candidate_target_type == "Autodesk.Revit.DB.Document"


def test_document_reference_keeps_direct_return_type_confidence_in_scoped_crawl():
    """Regression test: a targeted/scoped crawl (e.g. DEFAULT_TARGET_CLASSES,
    none of which is Document itself) never adds 'Document' to
    known_type_short_names. Before Document was added to
    KNOWN_REFERENCE_TYPES, classify_member's direct-return branch required
    the bare return type to be in known_type_short_names OR
    KNOWN_REFERENCE_TYPES; with neither true, is_direct_db_object was False,
    so the member fell through to the name-only branch and got
    name_only_candidate confidence instead of direct_return_type -- silently
    under-reporting confidence for exactly the live-crawl findings this rule
    was added for.
    """
    member = _member("Document", "Document", declaring_type="Autodesk.Revit.DB.View")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.View", known_type_short_names=set())

    assert candidate is not None
    assert candidate.edge_confidence is ConfidenceLabel.DIRECT_RETURN_TYPE
    assert candidate.edge_confidence is not ConfidenceLabel.NAME_ONLY_CANDIDATE


def test_documented_but_unrelated_member_name_is_not_matched_by_document_rule():
    """The Document/GetDocument rule is an exact match, not a substring
    search -- a member merely containing 'Document' (e.g. a hypothetical
    DocumentVersion-style name) must not be swept up by it."""
    member = _member("DocumentVersion", "int", declaring_type="Autodesk.Revit.DB.Element")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.Element", known_type_short_names=set())

    assert candidate is None


def test_unknown_elementid_reference_preserved_when_name_gives_no_hint():
    member = _member("Id", "ElementId", declaring_type="Autodesk.Revit.DB.Element")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.Element", known_type_short_names=set())

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.UNKNOWN_ELEMENTID_REFERENCE
    assert candidate.edge_confidence is ConfidenceLabel.UNKNOWN_REFERENCE
    assert candidate.candidate_target_type is None


def test_room_number_is_not_classified_as_a_relationship():
    """Room.Number is a plain string property; it must not be conflated with an
    ElementId-style relationship, and must not collapse with Room.Name semantics."""
    member = _member("Number", "string", declaring_type="Autodesk.Revit.DB.Architecture.Room")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.Architecture.Room", known_type_short_names=set())

    assert candidate is None


def test_docs_semantic_hint_upgrades_name_only_candidate():
    member = _member(
        "PrimaryDesignOption",
        "bool",
        summary="Indicates whether this design option is hosted by the primary model.",
        declaring_type="Autodesk.Revit.DB.DesignOption",
    )
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.DesignOption", known_type_short_names=set())

    assert candidate is not None
    assert candidate.edge_confidence is ConfidenceLabel.DOCS_SEMANTIC_HINT


def test_generic_collection_of_strings_is_not_classified_as_a_db_reference():
    """Regression test: a collection of a primitive type (IList<string>) was
    previously falling into the unresolved-generic-collection branch, which
    doesn't check its captured element type against PRIMITIVE_TYPES the way
    the direct-return branch does -- the element type ('string') then got
    unconditionally prefixed into a bogus 'Autodesk.Revit.DB.string' target,
    a scalar value collection masquerading as a DB object relationship."""
    member = _member("GetSequenceNames", "IList<string>", declaring_type="Autodesk.Revit.DB.Element")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.Element", known_type_short_names=set())

    assert candidate is None


def test_generic_collection_of_doubles_is_not_classified_as_a_db_reference():
    member = _member("GetSampleValues", "ICollection<double>", declaring_type="Autodesk.Revit.DB.Element")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.Element", known_type_short_names=set())

    assert candidate is None


def test_generic_collection_of_strings_with_name_match_uses_name_hint_not_bogus_target():
    """Even when a collection-of-primitives member's name matches a
    relationship keyword, the primitive element type must never leak into
    candidate_target_type -- the name-derived target hint (or None) is used
    instead, same as the existing name_only_candidate path for scalar
    returns."""
    member = _member("GetMaterialNames", "IList<string>", declaring_type="Autodesk.Revit.DB.Element")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.Element", known_type_short_names=set())

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.USES_MATERIAL
    assert candidate.edge_confidence is ConfidenceLabel.NAME_ONLY_CANDIDATE
    assert candidate.candidate_target_type == "Autodesk.Revit.DB.Material"


def test_generic_collection_of_unresolved_db_type_still_needs_runtime_validation():
    """Non-primitive, non-ElementId generic collections must keep their
    existing needs_runtime_validation behavior -- only primitive element
    types are demoted out of the DB-object-reference path."""
    member = _member("GetCurveLoops", "IList<CurveLoopThing>", declaring_type="Autodesk.Revit.DB.Element")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.Element", known_type_short_names=set())

    assert candidate is not None
    assert candidate.edge_confidence is ConfidenceLabel.NEEDS_RUNTIME_VALIDATION
    assert candidate.candidate_target_type == "Autodesk.Revit.DB.CurveLoopThing"


def test_color_plane_transform_are_treated_as_value_objects_not_relationships():
    """Color/Plane/Transform/BoundingBoxXYZ/CurveLoop/Outline are geometry
    and value types, not persistent DB objects -- same category as the
    pre-existing XYZ/UV entries in PRIMITIVE_TYPES. A direct-return property
    of one of these must not produce a DB-object-reference edge."""
    for value_type in ("Color", "Plane", "Transform", "BoundingBoxXYZ", "CurveLoop", "Outline"):
        member = _member("GetBoundingBox", value_type, declaring_type="Autodesk.Revit.DB.Element")
        candidate = classify_member(member, source_type="Autodesk.Revit.DB.Element", known_type_short_names={value_type})

        assert candidate is None, f"{value_type} should not produce an edge candidate"


def test_forge_type_id_and_failure_definition_id_are_treated_as_value_objects():
    """Regression test for the two dominant clusters found by
    unknown_pareto.py against a real 2024 crawl: ForgeTypeId (4031 edges,
    26 distinct source types) and FailureDefinitionId (2067 edges, 166
    distinct source types) together were 71% of every unknown edge in that
    crawl. Neither identifies a relationship to another BIM object -- a
    ForgeTypeId names a unit/spec/parameter type, a FailureDefinitionId
    names a warning/failure code -- so a direct-return property of one must
    not produce a DB-object-reference edge, same as Color/Plane/etc."""
    for identifier_type in ("ForgeTypeId", "FailureDefinitionId"):
        member = _member("GetDefaultLengthUnit", identifier_type, declaring_type="Autodesk.Revit.DB.BaseImportOptions")
        candidate = classify_member(member, source_type="Autodesk.Revit.DB.BaseImportOptions", known_type_short_names={identifier_type})

        assert candidate is None, f"{identifier_type} should not produce an edge candidate"


def test_smaller_identifier_and_geometry_value_types_are_excluded():
    """The smaller siblings of the ForgeTypeId/FailureDefinitionId pattern
    (opaque identifier/descriptor wrapper types) and of the Color/Plane
    geometry pattern (further geometry value types) -- all confirmed
    present in the same real crawl's unknown_pareto.py breakdown -- must
    also not produce DB-object-reference edges."""
    for value_type in (
        "ExternalServiceId", "ExternalResourceType", "IFCAnyHandle", "IFCData",
        "ModelPath", "FormatOptions", "FailureMessage", "FailureResolutionType",
        "Curve", "Solid", "GeometryElement", "GeometryObject", "Face", "CurveArrArray", "Polyloop",
    ):
        member = _member("SomeProperty", value_type, declaring_type="Autodesk.Revit.DB.Element")
        candidate = classify_member(member, source_type="Autodesk.Revit.DB.Element", known_type_short_names={value_type})

        assert candidate is None, f"{value_type} should not produce an edge candidate"


def test_type_id_property_name_is_classified_as_type_of():
    """Regression test: the original '^(Type|GetTypeId)$' rule missed the
    dominant real naming convention entirely -- a real 2024 crawl's
    UNKNOWN_ELEMENTID_REFERENCE 'Type' cluster (9 edges, 9 distinct source
    types) was 100% literally named 'TypeId' (e.g. DirectShape.TypeId),
    none matching the pre-existing pattern at all."""
    member = _member("TypeId", "ElementId", declaring_type="Autodesk.Revit.DB.DirectShape")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.DirectShape", known_type_short_names=set())

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.TYPE_OF
    assert candidate.edge_confidence is ConfidenceLabel.ELEMENTID_WITH_STRONG_NAME


def test_view_id_property_name_is_classified_as_references():
    """Evidence from a real 2024 crawl: 12 UNKNOWN_ELEMENTID_REFERENCE
    edges across 12 distinct source types, all named exactly
    'ViewId'/'GetViewId' (e.g. BIMExportOptions.ViewId,
    ElevationMarker.GetViewId), zero counterexamples -- same evidence shape
    as the existing Document/GetDocument REFERENCES rule."""
    member = _member("ViewId", "ElementId", declaring_type="Autodesk.Revit.DB.BIMExportOptions")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.BIMExportOptions", known_type_short_names=set())

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.REFERENCES
    assert candidate.candidate_target_type == "Autodesk.Revit.DB.View"

    member2 = _member("GetViewId", "ElementId", declaring_type="Autodesk.Revit.DB.ElevationMarker")
    candidate2 = classify_member(member2, source_type="Autodesk.Revit.DB.ElevationMarker", known_type_short_names=set())

    assert candidate2 is not None
    assert candidate2.candidate_edge_type is EdgeType.REFERENCES
    assert candidate2.candidate_target_type == "Autodesk.Revit.DB.View"


def test_demoted_value_type_does_not_fall_through_to_name_only_candidate():
    """Regression test (PR review finding): demoting FailureDefinitionId
    into PRIMITIVE_TYPES stopped it from producing a direct-return edge,
    but a real BuiltInFailures.* field name like
    'HighestAssociatedLevelBelowLowestAssociatedLevel' still matches the
    'Level' keyword -- without a guard, classify_member fell through to
    the name-only branch and emitted a false ASSIGNED_TO_LEVEL -> Level
    edge, exactly the noise this demotion was meant to remove, just
    relabeled as a specific (and more misleading) edge type instead of
    an honest UNKNOWN_*. A member returning a known value/identifier type
    must produce no edge at all, regardless of keyword collisions in its
    name."""
    member = _member(
        "HighestAssociatedLevelBelowLowestAssociatedLevel",
        "FailureDefinitionId",
        declaring_type="Autodesk.Revit.DB.BuiltInFailures.LevelFailures",
    )
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.BuiltInFailures.LevelFailures", known_type_short_names=set())

    assert candidate is None


def test_demoted_value_type_collection_does_not_fall_through_to_name_only_candidate():
    """Same regression as above, for the generic-collection-of-value-type
    shape: a collection of FailureDefinitionId whose method name matches a
    keyword must also produce no edge, not a name_only_candidate one."""
    member = _member(
        "GetLevelFailures",
        "IList<FailureDefinitionId>",
        declaring_type="Autodesk.Revit.DB.Whatever",
    )
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.Whatever", known_type_short_names=set())

    assert candidate is None


def test_bare_scalar_primitive_still_allows_name_only_candidate():
    """The name-only-fallthrough guard must only apply to concrete
    value/identifier types (PRIMITIVE_TYPES minus _TRUE_SCALAR_PRIMITIVES),
    not genuine C# scalars -- a bare bool/int/string is intentionally still
    eligible for a weak name_only_candidate guess (rule 5 of
    docs/edge_taxonomy_v0.md's precedence list); this must keep working."""
    member = _member("PrimaryDesignOption", "bool", declaring_type="Autodesk.Revit.DB.DesignOption")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.DesignOption", known_type_short_names=set())

    assert candidate is not None
    assert candidate.edge_confidence is ConfidenceLabel.NAME_ONLY_CANDIDATE


def test_curve_array_is_treated_as_a_value_object():
    """CurveArray is the legacy pre-CurveLoop geometry container -- same
    'value type, not reference-bearing' category as the already-demoted
    Curve/CurveLoop/CurveArrArray."""
    member = _member("GetProfile", "CurveArray", declaring_type="Autodesk.Revit.DB.Element")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.Element", known_type_short_names={"CurveArray"})

    assert candidate is None


def test_direct_return_type_with_conflicting_name_keyword_falls_back_to_unknown():
    """Regression test: a real (non-demoted) DB object type whose member
    name coincidentally matches a keyword implying a *different* concrete
    target must not produce a type-incoherent edge (e.g. an ASSIGNED_TO_LEVEL
    edge whose target is actually FilterRule, not Level). direct_return_type
    is documented as the strongest static signal available -- the compiler
    guarantees the actual return type -- so a conflicting name-based guess
    must lose and fall back to the honest UNKNOWN_DB_OBJECT_REFERENCE bucket
    instead. This was silently producing wrong specific edges before: a real
    2024 crawl's ASSIGNED_TO_LEVEL/HOSTED_BY/USES_MATERIAL/etc. counts each
    dropped 20-70% once this fallback was added, meaning a meaningful
    fraction of those "confident" buckets were actually this kind of
    coincidental name collision."""
    member = _member("LevelOfDetailFilterRule", "FilterRule", declaring_type="Autodesk.Revit.DB.Whatever")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.Whatever", known_type_short_names={"FilterRule"})

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.UNKNOWN_DB_OBJECT_REFERENCE
    assert candidate.candidate_target_type == "Autodesk.Revit.DB.FilterRule"
    assert candidate.edge_confidence is ConfidenceLabel.DIRECT_RETURN_TYPE


def test_direct_return_type_with_no_target_hint_keyword_is_unaffected():
    """A name-keyword match whose target_hint is None (a relationship
    category without one fixed target type, e.g. HOSTED_BY/TAGS_ELEMENT/
    MEMBER_OF_GROUP/DEPENDS_ON) has nothing to conflict with -- the actual
    return type is a perfectly valid target for that category, and this
    case must keep working exactly as before."""
    member = _member("GetHostedElement", "Wall", declaring_type="Autodesk.Revit.DB.Whatever")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.Whatever", known_type_short_names={"Wall"})

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.HOSTED_BY
    assert candidate.candidate_target_type == "Autodesk.Revit.DB.Wall"


def test_direct_return_type_with_matching_target_hint_is_unaffected():
    """When the name-matched target_hint and the actual return type agree
    (the common, intended case -- e.g. FamilyInstance.Symbol -> FamilySymbol),
    behavior must be unchanged."""
    member = _member("Symbol", "FamilySymbol", declaring_type="Autodesk.Revit.DB.FamilyInstance")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.FamilyInstance", known_type_short_names={"FamilySymbol"})

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.INSTANCE_OF
    assert candidate.candidate_target_type == "Autodesk.Revit.DB.FamilySymbol"
