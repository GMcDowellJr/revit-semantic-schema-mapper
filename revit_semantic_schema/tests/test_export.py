import json

from revit_schema_mapper import export
from revit_schema_mapper.models import ApiPage, ConfidenceLabel, EdgeCandidate, EdgeType, Kind, MemberInfo, MemberKind


def _edge(
    member_name: str,
    edge_type: EdgeType,
    confidence: ConfidenceLabel,
    target: str | None,
) -> EdgeCandidate:
    return EdgeCandidate(
        source_type="Autodesk.Revit.DB.SomeType",
        member_name=member_name,
        member_kind=MemberKind.PROPERTY,
        raw_signature=f"public object {member_name} {{ get; }}",
        return_type=target,
        parameter_types=[],
        candidate_target_type=target,
        candidate_edge_type=edge_type,
        edge_confidence=confidence,
        evidence=[],
        source_url="https://www.revitapidocs.com/2024/sometype-class.htm",
    )


def _page_with_doc_text() -> ApiPage:
    member = MemberInfo(
        name="Symbol",
        kind=MemberKind.PROPERTY,
        declaring_type="Autodesk.Revit.DB.FamilyInstance",
        raw_signature="public FamilySymbol Symbol { get; }",
        summary="Gets the FamilySymbol object.",
        remarks="Some copied remarks text from the docs site.",
        examples=["var symbol = instance.Symbol;"],
    )
    return ApiPage(
        revit_version="2024",
        namespace="Autodesk.Revit.DB",
        type_name="FamilyInstance",
        full_type_name="Autodesk.Revit.DB.FamilyInstance",
        kind=Kind.CLASS,
        members=[member],
        summary="A copied summary block from the docs site.",
        remarks="A copied remarks block from the docs site.",
        examples=["var x = new FamilyInstance();"],
        source_url="https://www.revitapidocs.com/2024/familyinstance-class.htm",
    )


def test_write_api_pages_redacts_doc_text_by_default(tmp_path):
    export.write_api_pages(tmp_path, [_page_with_doc_text()])

    written = json.loads((tmp_path / "api_pages.json").read_text())
    assert len(written) == 1
    page = written[0]
    assert page["summary"] == ""
    assert page["remarks"] == ""
    assert page["examples"] == []
    assert page["members"][0]["summary"] == ""
    assert page["members"][0]["remarks"] == ""
    assert page["members"][0]["examples"] == []
    # Facts, not prose, must survive redaction.
    assert page["full_type_name"] == "Autodesk.Revit.DB.FamilyInstance"
    assert page["source_url"] == "https://www.revitapidocs.com/2024/familyinstance-class.htm"
    assert page["members"][0]["name"] == "Symbol"
    assert page["members"][0]["raw_signature"] == "public FamilySymbol Symbol { get; }"


def test_write_api_pages_include_doc_text_opt_in(tmp_path):
    export.write_api_pages(tmp_path, [_page_with_doc_text()], include_doc_text=True)

    written = json.loads((tmp_path / "api_pages.json").read_text())
    page = written[0]
    assert page["summary"] == "A copied summary block from the docs site."
    assert page["members"][0]["remarks"] == "Some copied remarks text from the docs site."


def test_write_api_pages_redaction_does_not_mutate_input_pages(tmp_path):
    page = _page_with_doc_text()
    export.write_api_pages(tmp_path, [page])

    assert page.summary == "A copied summary block from the docs site."
    assert page.members[0].remarks == "Some copied remarks text from the docs site."


def test_write_summary_top_confident_prioritizes_specific_edge_types_over_unknown(tmp_path):
    """A high edge_confidence only reflects confidence in the return type, not
    in any specific relationship -- UNKNOWN_* edges (however high-confidence
    the return-type resolution is) must not crowd a genuinely-classified edge
    out of the 'Top 25 highest-confidence' listing.
    """
    unknown_edges = [
        _edge(f"Unknown{i}", EdgeType.UNKNOWN_DB_OBJECT_REFERENCE, ConfidenceLabel.DIRECT_RETURN_TYPE, "Autodesk.Revit.DB.ForgeTypeId")
        for i in range(5)
    ]
    specific_edge = _edge("GetMaterialIds", EdgeType.USES_MATERIAL, ConfidenceLabel.NAME_ONLY_CANDIDATE, "Autodesk.Revit.DB.Material")
    edges = unknown_edges + [specific_edge]

    export.write_summary(
        tmp_path,
        revit_version="2024",
        fallback_reason=None,
        raw_index_entries=[],
        pages=[],
        node_candidates=[],
        edge_candidates=edges,
        limitations=[],
        next_steps=[],
    )

    summary = (tmp_path / "summary.md").read_text()
    section_8 = summary.split("## 8. Top 25 highest-confidence candidate edges")[1].split("## 9.")[0]
    # Despite worse confidence rank (name_only_candidate vs. direct_return_type),
    # the specific USES_MATERIAL edge must appear before the UNKNOWN_* edges.
    assert section_8.index("USES_MATERIAL") < section_8.index("UNKNOWN_DB_OBJECT_REFERENCE")


def test_write_summary_unknown_target_type_breakdown(tmp_path):
    edges = [
        _edge(f"GetSpecTypeId{i}", EdgeType.UNKNOWN_DB_OBJECT_REFERENCE, ConfidenceLabel.DIRECT_RETURN_TYPE, "Autodesk.Revit.DB.ForgeTypeId")
        for i in range(3)
    ] + [
        _edge("BadViewType", EdgeType.UNKNOWN_DB_OBJECT_REFERENCE, ConfidenceLabel.DIRECT_RETURN_TYPE, "Autodesk.Revit.DB.FailureDefinitionId"),
        _edge("GetMaterialIds", EdgeType.USES_MATERIAL, ConfidenceLabel.NAME_ONLY_CANDIDATE, "Autodesk.Revit.DB.Material"),
    ]

    export.write_summary(
        tmp_path,
        revit_version="2024",
        fallback_reason=None,
        raw_index_entries=[],
        pages=[],
        node_candidates=[],
        edge_candidates=edges,
        limitations=[],
        next_steps=[],
    )

    summary = (tmp_path / "summary.md").read_text()
    section_10 = summary.split("## 10. Unknown-reference target type breakdown")[1].split("## 11.")[0]
    assert "4 total UNKNOWN_* edges" in section_10
    assert "`Autodesk.Revit.DB.ForgeTypeId`: 3" in section_10
    assert "`Autodesk.Revit.DB.FailureDefinitionId`: 1" in section_10
    # The USES_MATERIAL edge isn't UNKNOWN_* and must not appear in this breakdown.
    assert "Autodesk.Revit.DB.Material" not in section_10
