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
