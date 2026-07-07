from revit_schema_mapper import semantic_roles
from revit_schema_mapper.models import (
    ConfidenceLabel,
    ConfidenceTier,
    EdgeType,
    GraphEdge,
    GraphNode,
    MemberKind,
    TargetResolution,
)


def _node(full_type_name: str, *, class_role: str | None = None, base_type: str | None = None) -> GraphNode:
    return GraphNode(
        id=full_type_name,
        short_name=full_type_name.rsplit(".", 1)[-1],
        external=False,
        kind="class",
        namespace="Autodesk.Revit.DB",
        class_role=class_role,
        base_type=base_type,
        source_url="https://www.revitapidocs.com/2024/x.htm",
    )


def _edge(source: str, target: str, edge_type: EdgeType, member_name: str = "M") -> GraphEdge:
    return GraphEdge(
        source=source,
        target=target,
        member_name=member_name,
        member_kind=MemberKind.PROPERTY,
        edge_type=edge_type,
        confidence=ConfidenceLabel.DIRECT_RETURN_TYPE,
        confidence_tier=ConfidenceTier.CORE,
        target_resolution=TargetResolution.EXACT,
        evidence=[],
        source_url="https://www.revitapidocs.com/2024/x.htm",
    )


def test_classify_api_role_specific_name_matches():
    assert semantic_roles.classify_api_role(_node("Autodesk.Revit.DB.Document")) == "Document"
    assert semantic_roles.classify_api_role(_node("Autodesk.Revit.DB.ViewSheet")) == "ViewSheet"
    assert semantic_roles.classify_api_role(_node("Autodesk.Revit.DB.View")) == "View"
    assert semantic_roles.classify_api_role(_node("Autodesk.Revit.DB.Material")) == "Material"
    assert semantic_roles.classify_api_role(_node("Autodesk.Revit.DB.Architecture.Room")) == "Room / Space"
    assert semantic_roles.classify_api_role(_node("Autodesk.Revit.DB.IndependentTag")) == "Annotation / Tag"
    assert semantic_roles.classify_api_role(_node("Autodesk.Revit.DB.XYZ")) == "Geometry"
    assert semantic_roles.classify_api_role(_node("Autodesk.Revit.DB.FailureDefinitionId")) == "Failures"


def test_classify_api_role_family_ambiguity_is_a_known_tradeoff():
    """FamilyInstance (a placed instance) lands in the same 'Family' bucket
    as Family/FamilySymbol (family *definitions*) because the check is a
    plain name match -- documenting this as expected behavior (a known
    coarsening, not something to silently 'fix' with more special cases)
    rather than letting a future change accidentally alter it unnoticed.
    """
    assert semantic_roles.classify_api_role(_node("Autodesk.Revit.DB.FamilyInstance")) == "Family"
    assert semantic_roles.classify_api_role(_node("Autodesk.Revit.DB.Family")) == "Family"
    assert semantic_roles.classify_api_role(_node("Autodesk.Revit.DB.FamilySymbol")) == "FamilySymbol"


def test_classify_api_role_falls_back_to_class_role_then_other():
    assert semantic_roles.classify_api_role(_node("Autodesk.Revit.DB.SomeWidget", class_role="element_subtype")) == "Element"
    assert semantic_roles.classify_api_role(_node("Autodesk.Revit.DB.SomeWidget", class_role="element_type")) == "ElementType"
    assert semantic_roles.classify_api_role(_node("Autodesk.Revit.DB.SomeWidget", class_role="options_class")) == "Options / Settings"
    assert semantic_roles.classify_api_role(_node("Autodesk.Revit.DB.SomeWidget", class_role="utility_class")) == "Utility / Collector"
    assert semantic_roles.classify_api_role(_node("Autodesk.Revit.DB.SomeWidget")) == "Other"


def test_relation_family_covers_every_real_edge_type():
    """Every non-UNKNOWN_* EdgeType must map to a real family, not silently
    fall back to 'Other' -- that fallback exists for edge types this
    taxonomy genuinely doesn't have an opinion on yet, not as cover for a
    missing mapping entry.
    """
    for edge_type in EdgeType:
        if "UNKNOWN" in edge_type.value:
            continue
        assert semantic_roles.relation_family(edge_type.value) != "Other", f"{edge_type.value} has no family mapping"


def test_aggregate_graph_counts_and_drilldown():
    nodes = [
        _node("Autodesk.Revit.DB.FamilyInstance"),
        _node("Autodesk.Revit.DB.FamilySymbol"),
        _node("Autodesk.Revit.DB.Material"),
    ]
    edges = [
        _edge("Autodesk.Revit.DB.FamilyInstance", "Autodesk.Revit.DB.FamilySymbol", EdgeType.INSTANCE_OF, "Symbol"),
        _edge("Autodesk.Revit.DB.FamilyInstance", "Autodesk.Revit.DB.Material", EdgeType.USES_MATERIAL, "GetMaterialIds"),
    ]

    data = semantic_roles.aggregate_graph(nodes, edges)

    assert data.included_edge_count == 2
    assert data.total_edge_count == 2
    assert set(data.role_order) == {"Family", "FamilySymbol", "Material"}
    triple_keys = {(t.source_role, t.relationship, t.target_role) for t in data.sankey}
    assert ("Family", "INSTANCE_OF", "FamilySymbol") in triple_keys
    assert ("Family", "USES_MATERIAL", "Material") in triple_keys

    key = "Family|INSTANCE_OF|FamilySymbol"
    assert key in data.drilldown
    assert data.drilldown[key][0].member_name == "Symbol"


def test_aggregate_graph_drops_edges_whose_endpoint_is_missing():
    nodes = [_node("Autodesk.Revit.DB.FamilyInstance")]
    edges = [_edge("Autodesk.Revit.DB.FamilyInstance", "Autodesk.Revit.DB.NeverListed", EdgeType.INSTANCE_OF)]

    data = semantic_roles.aggregate_graph(nodes, edges)

    assert data.included_edge_count == 0
    assert data.total_edge_count == 0


def test_aggregate_graph_top_relationships_truncation_is_disclosed():
    nodes = [_node("Autodesk.Revit.DB.A"), _node("Autodesk.Revit.DB.B")]
    edges = [
        _edge("Autodesk.Revit.DB.A", "Autodesk.Revit.DB.B", EdgeType.INSTANCE_OF, "M1"),
        _edge("Autodesk.Revit.DB.A", "Autodesk.Revit.DB.B", EdgeType.INSTANCE_OF, "M2"),
        _edge("Autodesk.Revit.DB.A", "Autodesk.Revit.DB.B", EdgeType.USES_MATERIAL, "M3"),
    ]

    data = semantic_roles.aggregate_graph(nodes, edges, top_relationships=1)

    assert data.relationship_order == ["INSTANCE_OF"]
    assert data.included_edge_count == 2
    assert data.total_edge_count == 3
    # Full counts (including the truncated relationship type) stay visible.
    assert data.relationship_counts_total == {"INSTANCE_OF": 2, "USES_MATERIAL": 1}


def test_aggregate_graph_min_weight_filters_weak_triples():
    nodes = [_node("Autodesk.Revit.DB.A"), _node("Autodesk.Revit.DB.B")]
    edges = [_edge("Autodesk.Revit.DB.A", "Autodesk.Revit.DB.B", EdgeType.INSTANCE_OF)]

    data = semantic_roles.aggregate_graph(nodes, edges, min_weight=2)

    assert data.sankey == []
    # min_weight only affects which triples are drawn, not the disclosed totals.
    assert data.included_edge_count == 1


def test_render_html_escapes_stray_script_close_sequences():
    nodes = [_node("Autodesk.Revit.DB.A"), _node("Autodesk.Revit.DB.B")]
    edges = [_edge("Autodesk.Revit.DB.A", "Autodesk.Revit.DB.B", EdgeType.INSTANCE_OF)]
    for e in edges:
        e.source_url = "https://example.com/</script><script>alert(1)</script>"

    data = semantic_roles.aggregate_graph(nodes, edges)
    html = semantic_roles.render_html(data, revit_version="2024")

    script_body = html.split("<script id=\"semantic-data\"", 1)[1]
    assert "</script" not in script_body.split("</script>", 1)[0]


def test_render_html_is_a_complete_standalone_document():
    data = semantic_roles.aggregate_graph([], [])
    html = semantic_roles.render_html(data, revit_version="2024")

    assert html.strip().startswith("<!doctype html>")
    assert "<html" in html and html.rstrip().endswith("</html>")
    assert "<head>" in html and "</head>" in html
    assert "<body>" in html and "</body>" in html
    assert "2024" in html


def test_render_html_viewbox_grows_to_fit_every_role_and_heatmap_row():
    """A fixed viewBox height clipped role rows past the 13th and heatmap
    rows past the 18th on a real crawl (up to 21 distinct roles) -- the
    viewBox must always be tall enough for every role/relationship row and
    every heatmap row this specific aggregate actually has.
    """
    n_roles = 21
    roles = [
        semantic_roles.RoleSummary(role=f"Role{i}", source_weight=1, target_weight=1, weight=2, color="#000000")
        for i in range(n_roles)
    ]
    relationships = [semantic_roles.RelationshipSummary(relationship="HAS_PARAMETER", weight=n_roles, family="Data / Definition", color="#000000")]
    data = semantic_roles.SemanticRelationshipMap(
        roles=roles,
        relationships=relationships,
        sankey=[],
        heatmap=[],
        drilldown={},
        role_order=[r.role for r in roles],
        relationship_order=["HAS_PARAMETER"],
        relationship_counts_total={"HAS_PARAMETER": n_roles},
        included_edge_count=n_roles,
        total_edge_count=n_roles,
    )

    html = semantic_roles.render_html(data, revit_version="2024")

    import re

    m = re.search(r'viewBox="0 0 (\d+) (\d+)"', html)
    assert m is not None
    H = int(m.group(2))

    role_rows_bottom = 150 + n_roles * 43 + 35
    heatmap_bottom = role_rows_bottom + 90 + n_roles * 18
    assert H >= heatmap_bottom
    assert H > 940  # this case must actually exceed the old fixed constant
