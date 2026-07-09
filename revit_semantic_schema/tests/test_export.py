import json
import shutil
import subprocess

import pytest

from revit_schema_mapper import export, graph
from revit_schema_mapper.export import _GRAPH_VIEWER_TEMPLATE_PATH
from revit_schema_mapper.models import (
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


def _node(full_type_name: str) -> NodeCandidate:
    return NodeCandidate(
        full_type_name=full_type_name,
        short_name=full_type_name.rsplit(".", 1)[-1],
        kind=Kind.CLASS,
        namespace="Autodesk.Revit.DB",
        base_type=None,
        inheritance_chain=[],
        is_element_candidate=IsElementCandidate.UNKNOWN,
        class_role=ClassRole.UNKNOWN,
        evidence=[],
        source_url="https://www.revitapidocs.com/2024/x.htm",
    )


def test_write_graph_core_metadata_reflects_only_filtered_edges(tmp_path):
    """graph_core.json's metadata must describe graph_core.json's own
    nodes/edges, not the full graph's -- a consumer sizing/validating the
    filtered file from its own metadata block would otherwise see
    confidence_tier_counts including likely/unverified_reference (edges
    that aren't actually present in graph_core.json) and an
    external_node_count computed against the full node set.
    """
    nodes = [_node("Autodesk.Revit.DB.FamilyInstance"), _node("Autodesk.Revit.DB.FamilySymbol")]
    edges = [
        _edge("Symbol", EdgeType.INSTANCE_OF, ConfidenceLabel.DIRECT_RETURN_TYPE, "Autodesk.Revit.DB.FamilySymbol"),
        _edge("GetMaterialIds", EdgeType.USES_MATERIAL, ConfidenceLabel.NAME_ONLY_CANDIDATE, "Autodesk.Revit.DB.Material"),
    ]
    for e in edges:
        e.source_type = "Autodesk.Revit.DB.FamilyInstance"

    result = graph.build_graph(nodes, edges)
    export.write_graph(tmp_path, result, revit_version="2024")

    core = json.loads((tmp_path / "graph_core.json").read_text())
    # Only the INSTANCE_OF edge is core tier (NAME_ONLY_CANDIDATE is 'likely').
    assert core["metadata"]["edge_count"] == 1
    assert core["metadata"]["confidence_tier_counts"] == {"core": 1}
    assert core["metadata"]["external_node_count"] == 0
    assert len(core["edges"]) == 1
    assert core["edges"][0]["edge_type"] == "INSTANCE_OF"


def test_write_graph_metadata_includes_corroboration_counts(tmp_path):
    """graph.json's metadata should surface Stage B/C coverage the same way
    it already surfaces target_resolution_counts/confidence_tier_counts --
    otherwise a downstream consumer has to scan every edge just to learn
    whether cross-validation ran at all.
    """
    nodes = [_node("Autodesk.Revit.DB.FamilyInstance"), _node("Autodesk.Revit.DB.FamilySymbol")]
    checked = _edge("Symbol", EdgeType.INSTANCE_OF, ConfidenceLabel.DIRECT_RETURN_TYPE, "Autodesk.Revit.DB.FamilySymbol")
    checked.source_type = "Autodesk.Revit.DB.FamilyInstance"
    checked.dll_verified_status = "signature_verified_declared"
    checked.revitlookup_referenced = True
    unchecked = _edge("GetMaterialIds", EdgeType.USES_MATERIAL, ConfidenceLabel.NAME_ONLY_CANDIDATE, "Autodesk.Revit.DB.Material")
    unchecked.source_type = "Autodesk.Revit.DB.FamilyInstance"

    result = graph.build_graph(nodes, [checked, unchecked])
    export.write_graph(tmp_path, result, revit_version="2024")

    full = json.loads((tmp_path / "graph.json").read_text())
    assert full["metadata"]["dll_verified_status_counts"] == {
        "signature_verified_declared": 1,
        "not_checked": 1,
    }
    assert full["metadata"]["revitlookup_referenced_counts"] == {
        "referenced": 1,
        "not_checked": 1,
    }


def test_read_node_candidates_round_trips_through_write(tmp_path):
    nodes = [_node("Autodesk.Revit.DB.View")]
    export.write_node_candidates(tmp_path, nodes)

    read_back = export.read_node_candidates(tmp_path)

    assert read_back == nodes


def test_read_edge_candidates_round_trips_through_write(tmp_path):
    edges = [_edge("ViewTemplateId", EdgeType.CONTROLLED_BY_TEMPLATE, ConfidenceLabel.ELEMENTID_WITH_STRONG_NAME, "Autodesk.Revit.DB.View")]
    export.write_edge_candidates(tmp_path, edges)

    read_back = export.read_edge_candidates(tmp_path)

    assert read_back == edges


def test_refresh_graph_section_replaces_stale_section_not_duplicates(tmp_path):
    summary_path = tmp_path / "summary.md"
    summary_path.write_text(
        "# Title\n\n## 14. Knowledge graph materialization\n\nSTALE CONTENT\n",
        encoding="utf-8",
    )
    nodes = [_node("Autodesk.Revit.DB.View")]
    edges = [_edge("ViewTemplateId", EdgeType.CONTROLLED_BY_TEMPLATE, ConfidenceLabel.ELEMENTID_WITH_STRONG_NAME, "Autodesk.Revit.DB.View")]
    for e in edges:
        e.source_type = "Autodesk.Revit.DB.View"
    result = graph.build_graph(nodes, edges)

    export.refresh_graph_section_in_file(summary_path, result, section_number=14)

    text = summary_path.read_text()
    assert text.count("## 14. Knowledge graph materialization") == 1
    assert "STALE CONTENT" not in text
    assert "# Title" in text


def test_refresh_graph_section_is_noop_when_file_missing(tmp_path):
    missing = tmp_path / "summary.md"
    result = graph.build_graph([], [])

    export.refresh_graph_section_in_file(missing, result, section_number=14)

    assert not missing.exists()


def test_write_graph_includes_communities_and_community_count(tmp_path):
    nodes = [_node("Autodesk.Revit.DB.FamilyInstance"), _node("Autodesk.Revit.DB.FamilySymbol")]
    edges = [_edge("Symbol", EdgeType.INSTANCE_OF, ConfidenceLabel.DIRECT_RETURN_TYPE, "Autodesk.Revit.DB.FamilySymbol")]
    for e in edges:
        e.source_type = "Autodesk.Revit.DB.FamilyInstance"

    result = graph.build_graph(nodes, edges)
    graph.apply_communities(result)
    export.write_graph(tmp_path, result, revit_version="2024")

    full = json.loads((tmp_path / "graph.json").read_text())
    core = json.loads((tmp_path / "graph_core.json").read_text())

    assert full["metadata"]["community_count"] == 1
    assert core["metadata"]["community_count"] == 1
    assert len(full["communities"]) == 1
    assert full["nodes"][0]["community_id"] is not None


def test_write_graph_html_produces_self_contained_viewer_with_embedded_data(tmp_path):
    nodes = [_node("Autodesk.Revit.DB.FamilyInstance"), _node("Autodesk.Revit.DB.FamilySymbol")]
    edges = [_edge("Symbol", EdgeType.INSTANCE_OF, ConfidenceLabel.DIRECT_RETURN_TYPE, "Autodesk.Revit.DB.FamilySymbol")]
    for e in edges:
        e.source_type = "Autodesk.Revit.DB.FamilyInstance"

    result = graph.build_graph(nodes, edges)
    graph.apply_communities(result)
    export.write_graph_html(tmp_path, result, revit_version="2024")

    html = (tmp_path / "graph.html").read_text()
    assert "<title>" in html
    assert "2024" in html
    assert "Autodesk.Revit.DB.FamilyInstance" in html
    assert "</script" not in html.split("const DATA = ")[1].split(";\n")[0]
    # no external script/style dependency -- fully self-contained
    assert "<script src=" not in html
    assert "cdn." not in html.lower()


def test_write_graph_html_escapes_stray_script_close_sequences(tmp_path):
    """A literal '</script' inside embedded data (e.g. a pathological
    source_url) would close the <script> tag early as far as the HTML
    parser is concerned, regardless of JS string quoting -- must be
    escaped in the written file regardless of where it appears in the
    payload.
    """
    nodes = [_node("Autodesk.Revit.DB.FamilyInstance"), _node("Autodesk.Revit.DB.FamilySymbol")]
    edges = [_edge("Symbol", EdgeType.INSTANCE_OF, ConfidenceLabel.DIRECT_RETURN_TYPE, "Autodesk.Revit.DB.FamilySymbol")]
    for e in edges:
        e.source_type = "Autodesk.Revit.DB.FamilyInstance"
        e.source_url = "https://example.com/</script><script>alert(1)</script>"

    result = graph.build_graph(nodes, edges)
    export.write_graph_html(tmp_path, result, revit_version="2024")

    html = (tmp_path / "graph.html").read_text()
    script_body = html.split("<script>", 1)[1].rsplit("</script>", 1)[0]
    assert "</script" not in script_body


def test_graph_html_viewer_keeps_self_loop_edges_visible(tmp_path):
    """A self-loop (factory/getter method returning its own declaring type)
    must still show up in graph.html's edge count/node degree/connections
    list -- not be silently dropped the way the original 's === t' guard
    did. Extracts and actually executes the node/edge-construction JS
    (via Node) against synthetic DATA rather than trusting the diff, since
    this is client-side behavior no Python-level test can observe.
    """
    node_bin = shutil.which("node")
    if node_bin is None:
        pytest.skip("node not available in this environment")

    template = _GRAPH_VIEWER_TEMPLATE_PATH.read_text(encoding="utf-8")
    start = template.index("const nodesById = new Map();")
    push_pos = template.index("edges.push(rec);", template.index("const edges = [];"))
    end = template.index("\n}\n", push_pos) + len("\n}\n")
    js_block = template[start:end]

    harness = f"""
const DATA = {{
  nodes: [{{ id: "A", short_name: "A", external: false, community_id: null, source_url: "" }}],
  edges: [{{ source: "A", target: "A", member_name: "Duplicate", edge_type: "TYPE_OF", confidence: "direct_return_type", source_url: "" }}],
}};
{js_block}
console.log(JSON.stringify({{
  edgeCount: edges.length,
  degree: nodes[0].degree,
  outCount: nodes[0].out.length,
  inCount: nodes[0].in.length,
}}));
"""
    result = subprocess.run([node_bin, "-e", harness], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)

    assert data["edgeCount"] == 1
    assert data["degree"] == 1
    assert data["outCount"] == 1
    assert data["inCount"] == 0


def test_write_semantic_relationship_map_produces_standalone_html(tmp_path):
    nodes = [_node("Autodesk.Revit.DB.FamilyInstance"), _node("Autodesk.Revit.DB.FamilySymbol")]
    edges = [_edge("Symbol", EdgeType.INSTANCE_OF, ConfidenceLabel.DIRECT_RETURN_TYPE, "Autodesk.Revit.DB.FamilySymbol")]
    for e in edges:
        e.source_type = "Autodesk.Revit.DB.FamilyInstance"

    result = graph.build_graph(nodes, edges)
    export.write_semantic_relationship_map(tmp_path, result, revit_version="2024")

    html = (tmp_path / "semantic_relationship_map.html").read_text()
    assert html.strip().startswith("<!doctype html>")
    assert "2024" in html
    assert "Family" in html
