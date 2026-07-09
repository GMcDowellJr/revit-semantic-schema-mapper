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


def test_bare_view_property_name_is_classified_as_references():
    """Evidence from a real crawl's candidate_edges.json: 6
    UNKNOWN_DB_OBJECT_REFERENCE edges across 6 distinct source types, all
    named exactly 'View' (Control.View, Dimension.View, Options.View,
    SpatialElementTag.View, Events.ViewPrintedEventArgs.View,
    Events.ViewPrintingEventArgs.View), all already direct_return_type
    confidence, zero counterexamples."""
    member = _member("View", "View", declaring_type="Autodesk.Revit.DB.Control")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.Control", known_type_short_names={"View"})

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.REFERENCES
    assert candidate.edge_confidence is ConfidenceLabel.DIRECT_RETURN_TYPE
    assert candidate.candidate_target_type == "Autodesk.Revit.DB.View"


def test_bare_view_reference_keeps_direct_return_type_confidence_in_scoped_crawl():
    """Regression test: a scoped/targeted crawl that never independently
    crawls View's own type page must not silently degrade this to
    name_only_candidate -- same shape as
    test_document_reference_keeps_direct_return_type_confidence_in_scoped_crawl."""
    member = _member("View", "View", declaring_type="Autodesk.Revit.DB.Dimension")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.Dimension", known_type_short_names=set())

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.REFERENCES
    assert candidate.edge_confidence is ConfidenceLabel.DIRECT_RETURN_TYPE
    assert candidate.candidate_target_type == "Autodesk.Revit.DB.View"


def test_location_property_name_is_classified_as_references():
    """Evidence from a real crawl's candidate_edges.json: 7
    UNKNOWN_DB_OBJECT_REFERENCE edges across 7 distinct source types, all
    named exactly 'Location' (AssemblyInstance/Element/FamilyInstance/Group/
    ModelText/SpatialElement/SpatialElementTag.Location) -- Element is the
    base declaring type, the rest are overrides of it; AssemblyInstance's
    docs describe it as 'the physical location of the assembly instance' --
    zero counterexamples."""
    member = _member("Location", "Location", declaring_type="Autodesk.Revit.DB.AssemblyInstance")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.AssemblyInstance", known_type_short_names={"Location"})

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.REFERENCES
    assert candidate.edge_confidence is ConfidenceLabel.DIRECT_RETURN_TYPE
    assert candidate.candidate_target_type == "Autodesk.Revit.DB.Location"


def test_location_reference_keeps_direct_return_type_confidence_in_scoped_crawl():
    """Regression test: same shape as
    test_bare_view_reference_keeps_direct_return_type_confidence_in_scoped_crawl,
    for the Location rule."""
    member = _member("Location", "Location", declaring_type="Autodesk.Revit.DB.Element")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.Element", known_type_short_names=set())

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.REFERENCES
    assert candidate.edge_confidence is ConfidenceLabel.DIRECT_RETURN_TYPE
    assert candidate.candidate_target_type == "Autodesk.Revit.DB.Location"


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


def _method_member(name, return_type, declaring_type="Autodesk.Revit.DB.Whatever"):
    return MemberInfo(
        name=name,
        kind=MemberKind.METHOD,
        declaring_type=declaring_type,
        raw_signature=f"public {return_type} {name}()",
        return_type=return_type,
        source_url="https://www.revitapidocs.com/2027/fake.htm",
    )


def test_workset_id_is_classified_as_owned_by_workset():
    """Regression test: WorksetId is a typed identifier (like ElementId,
    but purpose-built for worksets) whose own type unambiguously names its
    target -- no member-name matching needed. Evidence from a real 2024
    crawl: 11 edges, 10 distinct source types, all named exactly
    'WorksetId'/'GetWorksetId'. Before this rule, these fell through the
    new direct-return conflict check (return type 'WorksetId' != target
    'Workset') into UNKNOWN_DB_OBJECT_REFERENCE -- correct in the general
    case, but WorksetId is a deliberate, blessed exception."""
    member = _member("WorksetId", "WorksetId", declaring_type="Autodesk.Revit.DB.Element")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.Element", known_type_short_names={"WorksetId"})

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.OWNED_BY_WORKSET
    assert candidate.candidate_target_type == "Autodesk.Revit.DB.Workset"
    assert candidate.edge_confidence is ConfidenceLabel.DIRECT_RETURN_TYPE

    method_member = _method_member("GetWorksetId", "WorksetId", declaring_type="Autodesk.Revit.DB.Document")
    method_candidate = classify_member(method_member, source_type="Autodesk.Revit.DB.Document", known_type_short_names={"WorksetId"})

    assert method_candidate is not None
    assert method_candidate.candidate_edge_type is EdgeType.OWNED_BY_WORKSET
    assert method_candidate.candidate_target_type == "Autodesk.Revit.DB.Workset"


def test_workset_id_rule_fires_even_when_worksetid_itself_was_not_crawled():
    """Regression test (PR review finding): _TYPED_ID_TARGETS must not be
    gated behind is_direct_db_object's known_type_short_names/
    KNOWN_REFERENCE_TYPES check. DEFAULT_TARGET_CLASSES (a scoped/targeted
    crawl) parses Element.WorksetId without necessarily also crawling
    WorksetId's own type page -- known_type_short_names deliberately omits
    'WorksetId' here to simulate that. Before the fix, is_direct_db_object
    was False in this case, so the typed-ID rule (nested under it) never
    fired, and the member fell through to a much weaker name_only_candidate
    guess -- kept out of graph_core.json's CORE tier even though the type
    itself is unambiguous evidence."""
    member = _member("WorksetId", "WorksetId", declaring_type="Autodesk.Revit.DB.Element")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.Element", known_type_short_names={"Element"})

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.OWNED_BY_WORKSET
    assert candidate.candidate_target_type == "Autodesk.Revit.DB.Workset"
    assert candidate.edge_confidence is ConfidenceLabel.DIRECT_RETURN_TYPE


def test_keyword_rules_fire_in_scoped_crawls_even_when_their_own_target_type_is_uncrawled():
    """Regression test (PR review finding): the same crawl-dependency bug
    _TYPED_ID_TARGETS was fixed for also affected any ordinary keyword rule
    whose target_hint happens to equal the actual return type -- e.g. a
    scoped/targeted crawl that parses FamilyInstance/ExtensibleStorage.Entity
    but never crawls Room's/Schema's own type page left known_type_short_names
    without "Room"/"Schema", so is_direct_db_object was False and these
    confirmed direct-return relationships fell back to a weak
    name_only_candidate guess. Generalized fix: a keyword match whose own
    hardcoded target_hint agrees exactly with the actual return type is
    self-confirming evidence, independent of known_type_short_names, for
    any rule -- not just a fixed whitelist."""
    room_member = _member("Room", "Room", declaring_type="Autodesk.Revit.DB.FamilyInstance")
    room_candidate = classify_member(room_member, source_type="Autodesk.Revit.DB.FamilyInstance", known_type_short_names={"FamilyInstance"})

    assert room_candidate is not None
    assert room_candidate.candidate_edge_type is EdgeType.REFERENCES
    assert room_candidate.candidate_target_type == "Autodesk.Revit.DB.Architecture.Room"
    assert room_candidate.edge_confidence is ConfidenceLabel.DIRECT_RETURN_TYPE

    schema_member = _member("Schema", "Schema", declaring_type="Autodesk.Revit.DB.ExtensibleStorage.Entity")
    schema_candidate = classify_member(schema_member, source_type="Autodesk.Revit.DB.ExtensibleStorage.Entity", known_type_short_names={"Entity"})

    assert schema_candidate is not None
    assert schema_candidate.candidate_edge_type is EdgeType.REFERENCES
    assert schema_candidate.candidate_target_type == "Autodesk.Revit.DB.ExtensibleStorage.Schema"
    assert schema_candidate.edge_confidence is ConfidenceLabel.DIRECT_RETURN_TYPE


def test_scoped_crawl_fix_does_not_weaken_the_conflict_fallback():
    """Regression guard: name_match_confirms_return_type must only fire
    when target_hint exactly equals the actual return type -- a real
    conflict (e.g. a FilterRule-returning member whose name coincidentally
    matches the 'Level' keyword) must still fall back to
    UNKNOWN_DB_OBJECT_REFERENCE, not be waved through by the new check."""
    member = _member("LevelOfDetailFilterRule", "FilterRule", declaring_type="Autodesk.Revit.DB.Whatever")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.Whatever", known_type_short_names={"FilterRule"})

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.UNKNOWN_DB_OBJECT_REFERENCE
    assert candidate.candidate_target_type == "Autodesk.Revit.DB.FilterRule"


def test_factory_method_produces_no_edge():
    """Regression test: a 'Create*' method constructs a brand-new object --
    it isn't a relationship of source_type, even though it's declared on
    it (usually a factory/utility class). Evidence from a real 2024 crawl:
    ParameterFilterRuleFactory.CreateBeginsWithRule -> FilterRule,
    ConnectorElement.CreateCableTrayConnector -> ConnectorElement,
    AssemblyViewUtils.CreatePartList -> ViewSchedule."""
    member = _method_member("CreateBeginsWithRule", "FilterRule", declaring_type="Autodesk.Revit.DB.ParameterFilterRuleFactory")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.ParameterFilterRuleFactory", known_type_short_names={"FilterRule"})

    assert candidate is None


def test_created_phase_id_property_is_not_treated_as_a_factory_method():
    """Regression guard: the factory-method suppression's negative
    lookahead must not catch 'Created*' (a real past-tense property naming
    convention, e.g. Element.CreatedPhaseId) just because it starts with
    the same six letters as 'Create'."""
    member = _member("CreatedPhaseId", "ElementId", declaring_type="Autodesk.Revit.DB.Element")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.Element", known_type_short_names=set())

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.ASSIGNED_TO_PHASE
    assert candidate.candidate_target_type == "Autodesk.Revit.DB.Phase"


def test_fluent_setter_returning_own_type_produces_no_edge():
    """Regression test: a 'Set*' method that returns its own declaring type
    is a fluent/builder setter returning `this` for chaining, not a
    relationship to another object of the same type. Evidence from a real
    2024 crawl: OverrideGraphicSettings.SetCutBackgroundPatternColor (and four
    sibling Set* methods), all -> the same OverrideGraphicSettings type."""
    member = _method_member(
        "SetCutBackgroundPatternColor", "OverrideGraphicSettings", declaring_type="Autodesk.Revit.DB.OverrideGraphicSettings"
    )
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.OverrideGraphicSettings", known_type_short_names={"OverrideGraphicSettings"})

    assert candidate is None


def test_self_referential_property_is_not_treated_as_a_fluent_setter():
    """Regression guard: the fluent-setter suppression must only apply to
    'Set*'-named METHODs, not PROPERTYs -- a genuine self-referential
    relationship (e.g. a Group's parent Group) must not be suppressed just
    because its return type happens to equal its own declaring type."""
    member = _member("ParentGroup", "Group", declaring_type="Autodesk.Revit.DB.Group")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.Group", known_type_short_names={"Group"})

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.MEMBER_OF_GROUP


def test_room_keyword_is_classified_as_references():
    """Evidence from a real 2024 crawl: 7 edges across 4 distinct source
    types (FamilyInstance.Room/.FromRoom/.ToRoom, Document.GetRoomAtPoint),
    3 of 7 independently corroborated by RevitLookup, zero apparent
    counterexamples -- same evidence shape as the existing Document/ViewId
    REFERENCES rules."""
    for name in ("Room", "FromRoom", "ToRoom"):
        member = _member(name, "Room", declaring_type="Autodesk.Revit.DB.FamilyInstance")
        candidate = classify_member(member, source_type="Autodesk.Revit.DB.FamilyInstance", known_type_short_names={"Room"})

        assert candidate is not None, f"{name} should produce an edge"
        assert candidate.candidate_edge_type is EdgeType.REFERENCES
        assert candidate.candidate_target_type == "Autodesk.Revit.DB.Architecture.Room"

    method_member = _method_member("GetRoomAtPoint", "Room", declaring_type="Autodesk.Revit.DB.Document")
    method_candidate = classify_member(method_member, source_type="Autodesk.Revit.DB.Document", known_type_short_names={"Room"})

    assert method_candidate is not None
    assert method_candidate.candidate_edge_type is EdgeType.REFERENCES
    assert method_candidate.candidate_target_type == "Autodesk.Revit.DB.Architecture.Room"


def test_self_returning_method_produces_no_edge_regardless_of_name():
    """Regression test: the fluent/builder-method suppression was
    originally scoped to a 'Set*' name prefix, but a real 2024/2025/2026
    crawl showed FilteredElementCollector's entire query-builder API uses
    other verb prefixes for the exact same self-returning-method pattern
    (12/12 edges in that cluster, zero counterexamples) -- the name-prefix
    requirement was dropped, keeping only the MemberKind.METHOD +
    self-return check."""
    for name in ("ContainedInDesignOption", "Excluding", "IntersectWith", "OfCategory", "OfCategoryId"):
        member = _method_member(name, "FilteredElementCollector", declaring_type="Autodesk.Revit.DB.FilteredElementCollector")
        candidate = classify_member(member, source_type="Autodesk.Revit.DB.FilteredElementCollector", known_type_short_names={"FilteredElementCollector"})

        assert candidate is None, f"{name} should not produce an edge"


def test_link_load_result_is_treated_as_a_value_object():
    """LinkLoadResult describes the outcome of a link load/reload operation
    -- an operation-status object, not a BIM relationship. Evidence, stable
    across a real 2024/2025/2026 crawl: CADLinkType.LoadFrom/.Reload,
    LinkLoadContent.GetLinkLoadResult."""
    member = _method_member("Reload", "LinkLoadResult", declaring_type="Autodesk.Revit.DB.CADLinkType")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.CADLinkType", known_type_short_names={"LinkLoadResult"})

    assert candidate is None


def test_schema_property_is_classified_as_references():
    """Entity.Schema/Field.Schema/Field.SubSchema are a genuine 'this
    object's structure is defined by this Schema' relationship -- but the
    rule uses an exact match, not a bare substring, because
    Schema.ListSchemas/Schema.Lookup (static registry/lookup utilities on
    Schema itself) are a different pattern that a bare 'Schema' substring
    would have incorrectly swept up too."""
    member = _member("Schema", "Schema", declaring_type="Autodesk.Revit.DB.ExtensibleStorage.Entity")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.ExtensibleStorage.Entity", known_type_short_names={"Schema"})

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.REFERENCES
    assert candidate.candidate_target_type == "Autodesk.Revit.DB.ExtensibleStorage.Schema"

    sub_member = _member("SubSchema", "Schema", declaring_type="Autodesk.Revit.DB.ExtensibleStorage.Field")
    sub_candidate = classify_member(sub_member, source_type="Autodesk.Revit.DB.ExtensibleStorage.Field", known_type_short_names={"Schema"})

    assert sub_candidate is not None
    assert sub_candidate.candidate_edge_type is EdgeType.REFERENCES
    assert sub_candidate.candidate_target_type == "Autodesk.Revit.DB.ExtensibleStorage.Schema"


def test_list_schemas_utility_method_is_not_matched_by_schema_keyword():
    """Regression guard: 'ListSchemas' must not match the exact-match
    Schema/SubSchema keyword rule (it isn't named exactly 'Schema' or
    'SubSchema') -- it's a static registry lookup, not an instance
    relationship. In this particular case it's declared on Schema itself
    and also returns Schema, so it's independently suppressed by the
    self-returning-method check rather than falling into
    UNKNOWN_DB_OBJECT_REFERENCE -- either outcome is correct, this test
    just pins the actual (no-edge) behavior."""
    member = _method_member("ListSchemas", "Schema", declaring_type="Autodesk.Revit.DB.ExtensibleStorage.Schema")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.ExtensibleStorage.Schema", known_type_short_names={"Schema"})

    assert candidate is None


def test_room_and_schema_use_their_real_sub_namespace_not_a_bare_db_prefix():
    """Regression test (PR review finding): most _NAME_KEYWORD_RULES target
    hints (Level, Phase, Workset, Material, ...) happen to live directly
    under Autodesk.Revit.DB, so classify_member's blind
    "Autodesk.Revit.DB.{target}" prefixing was correct for them by
    coincidence, not by design. Room's and Schema's real fully-qualified
    names are Autodesk.Revit.DB.Architecture.Room and
    Autodesk.Revit.DB.ExtensibleStorage.Schema (pipeline.DEFAULT_TARGET_CLASSES) --
    before this fix, candidate_target_type was the bogus
    "Autodesk.Revit.DB.Room"/"Autodesk.Revit.DB.Schema", which doesn't
    correspond to any real crawled type, wrong in candidate_edges.json even
    before graph._Resolver gets a chance to (sometimes) paper over it via
    short-name fallback."""
    room_member = _member("Room", "Room", declaring_type="Autodesk.Revit.DB.FamilyInstance")
    room_candidate = classify_member(room_member, source_type="Autodesk.Revit.DB.FamilyInstance", known_type_short_names={"Room"})

    assert room_candidate is not None
    assert room_candidate.candidate_target_type == "Autodesk.Revit.DB.Architecture.Room"

    schema_member = _member("Schema", "Schema", declaring_type="Autodesk.Revit.DB.ExtensibleStorage.Entity")
    schema_candidate = classify_member(schema_member, source_type="Autodesk.Revit.DB.ExtensibleStorage.Entity", known_type_short_names={"Schema"})

    assert schema_candidate is not None
    assert schema_candidate.candidate_target_type == "Autodesk.Revit.DB.ExtensibleStorage.Schema"


def test_sketch_suffix_is_classified_as_depends_on():
    """Evidence from a real 2024 crawl: 10 edges across 5 distinct source
    types (Blend.BottomSketch/.TopSketch, Extrusion.Sketch, Revolution.Sketch,
    Sweep.PathSketch/.ProfileSketch, SweptBlend.BottomSketch/.PathSketch/
    .TopSketch), zero apparent counterexamples -- the profile/path that
    defines each solid's shape. Ends-with (not a bare substring) so it
    doesn't also catch SketchPlane (a distinct real type, handled by its
    own exact-match rule below) or unrelated coincidences like
    View.GetSketchyLines."""
    for name in ("Sketch", "BottomSketch", "TopSketch", "PathSketch", "ProfileSketch"):
        member = _member(name, "Sketch", declaring_type="Autodesk.Revit.DB.Extrusion")
        candidate = classify_member(member, source_type="Autodesk.Revit.DB.Extrusion", known_type_short_names={"Sketch"})

        assert candidate is not None, f"{name} should produce an edge"
        assert candidate.candidate_edge_type is EdgeType.DEPENDS_ON
        assert candidate.candidate_target_type == "Autodesk.Revit.DB.Sketch"


def test_sketch_plane_exact_match_is_classified_as_references_not_depends_on():
    """Evidence from a real 2024 crawl: 4 edges across 4 distinct source
    types (CurveByPoints.SketchPlane, CurveElement.SketchPlane,
    Sketch.SketchPlane, View.SketchPlane), all named exactly 'SketchPlane',
    zero counterexamples. SketchPlane is a distinct real DB type (a work
    plane), not a kind of Sketch -- must be checked before the 'Sketch$'
    rule and must not fall through to it."""
    member = _member("SketchPlane", "SketchPlane", declaring_type="Autodesk.Revit.DB.CurveElement")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.CurveElement", known_type_short_names={"SketchPlane"})

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.REFERENCES
    assert candidate.candidate_target_type == "Autodesk.Revit.DB.SketchPlane"


def test_get_sketchy_lines_is_not_matched_by_either_sketch_rule():
    """Regression guard: View.GetSketchyLines returns
    ViewDisplaySketchyLines (a graphics-style enum for dashed/sketchy line
    rendering), nothing to do with geometry sketches -- a real member found
    while investigating the Sketch/SketchPlane clusters via a broad
    substring search that also happened to catch this unrelated
    coincidence. Neither the 'Sketch$' nor '^SketchPlane$' rule may match
    'GetSketchyLines'."""
    member = _method_member("GetSketchyLines", "ViewDisplaySketchyLines", declaring_type="Autodesk.Revit.DB.View")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.View", known_type_short_names={"ViewDisplaySketchyLines"})

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.UNKNOWN_DB_OBJECT_REFERENCE
    assert candidate.candidate_target_type == "Autodesk.Revit.DB.ViewDisplaySketchyLines"


def test_link_element_id_with_strong_name_uses_elementid_treatment():
    """Regression test: LinkElementId is a general-purpose ID wrapper, the
    same structural role as bare ElementId (Revit uses it wherever a
    reference might cross into a linked document) -- not a fixed-target
    typed ID like WorksetId, since its siblings
    (GetRodAttachedElementId/NumberedElementId/GetSourceElementIds) have
    different real targets. Evidence: NumberSystem.PlacementLevelId returns
    LinkElementId and its docs literally say "The id of the base level of
    stairs..." -- a real ASSIGNED_TO_LEVEL relationship that the
    direct-return-object path's target_hint-vs-return-type conflict check
    was incorrectly rejecting (LinkElementId can never equal a target
    name). Must get elementid_with_strong_name treatment, the same as bare
    ElementId, not fall back to the direct-object conflict check."""
    member = _member("PlacementLevelId", "LinkElementId", declaring_type="Autodesk.Revit.DB.NumberSystem")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.NumberSystem", known_type_short_names={"LinkElementId"})

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.ASSIGNED_TO_LEVEL
    assert candidate.candidate_target_type == "Autodesk.Revit.DB.Level"
    assert candidate.edge_confidence is ConfidenceLabel.ELEMENTID_WITH_STRONG_NAME


def test_link_element_id_with_no_name_hint_is_unknown_elementid_reference():
    """Real LinkElementId cluster members whose names don't match any
    keyword (Part.GetSourceElementIds's siblings NumberedElementId,
    GetRodAttachedElementId -- confirmed heterogeneous by reading their
    actual docs prose, deliberately left unmapped) must still fall back to
    UNKNOWN_ELEMENTID_REFERENCE, exactly like a bare unmatched ElementId
    does."""
    member = _member("NumberedElementId", "LinkElementId", declaring_type="Autodesk.Revit.DB.NumberSystem")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.NumberSystem", known_type_short_names={"LinkElementId"})

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.UNKNOWN_ELEMENTID_REFERENCE
    assert candidate.candidate_target_type is None


def test_collection_of_link_element_id_uses_elementid_collection_treatment():
    """Part.GetSourceElementIds returns ICollection<LinkElementId> -- must
    get the same elementid-collection treatment as ICollection<ElementId>
    (RETURNS_ELEMENT_IDS when no name hint matches, as here), not fall
    through to the unresolved-generic-collection/needs_runtime_validation
    path."""
    member = _method_member("GetSourceElementIds", "ICollection<LinkElementId>", declaring_type="Autodesk.Revit.DB.Part")
    candidate = classify_member(member, source_type="Autodesk.Revit.DB.Part", known_type_short_names={"LinkElementId"})

    assert candidate is not None
    assert candidate.candidate_edge_type is EdgeType.RETURNS_ELEMENT_IDS
    assert candidate.edge_confidence is ConfidenceLabel.UNKNOWN_REFERENCE
