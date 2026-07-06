from revit_schema_mapper.classify import classify_member
from revit_schema_mapper.models import ConfidenceLabel, EdgeType, MemberInfo, MemberKind


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
