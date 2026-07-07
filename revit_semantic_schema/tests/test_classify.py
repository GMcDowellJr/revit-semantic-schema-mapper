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
