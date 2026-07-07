from unittest.mock import patch

from revit_schema_mapper import community
from revit_schema_mapper.http_compat import HttpError
from revit_schema_mapper.models import Community, EdgeType, GraphEdge, GraphNode, MemberKind
from revit_schema_mapper.models import ConfidenceLabel, ConfidenceTier, TargetResolution


def _node(i: int) -> GraphNode:
    return GraphNode(id=f"N{i}", short_name=f"N{i}", external=False)


def _edge(a: int, b: int) -> GraphEdge:
    return GraphEdge(
        source=f"N{a}",
        target=f"N{b}",
        member_name="x",
        member_kind=MemberKind.PROPERTY,
        edge_type=EdgeType.HAS_PARAMETER,
        confidence=ConfidenceLabel.DIRECT_RETURN_TYPE,
        confidence_tier=ConfidenceTier.CORE,
        target_resolution=TargetResolution.EXACT,
        evidence=[],
        source_url="u",
    )


def test_detect_communities_separates_two_triangles_joined_by_a_bridge():
    """Two dense triangles connected by a single bridge edge is the
    textbook case a real community-detection algorithm should split
    correctly -- unlike a per-node heuristic (e.g. class_role), which has
    no notion of graph structure at all.
    """
    nodes = [_node(i) for i in range(6)]
    edges = [_edge(0, 1), _edge(1, 2), _edge(0, 2), _edge(3, 4), _edge(4, 5), _edge(3, 5), _edge(2, 3)]

    assignment = community.detect_communities(nodes, edges)

    triangle1 = {assignment["N0"], assignment["N1"], assignment["N2"]}
    triangle2 = {assignment["N3"], assignment["N4"], assignment["N5"]}
    assert len(triangle1) == 1
    assert len(triangle2) == 1
    assert triangle1 != triangle2


def test_detect_communities_is_deterministic():
    nodes = [_node(i) for i in range(6)]
    edges = [_edge(0, 1), _edge(1, 2), _edge(0, 2), _edge(3, 4), _edge(4, 5), _edge(3, 5), _edge(2, 3)]

    a = community.detect_communities(nodes, edges)
    b = community.detect_communities(nodes, edges)
    assert a == b


def test_detect_communities_excludes_isolated_nodes():
    nodes = [_node(0), _node(1), _node(2)]
    edges = [_edge(0, 1)]  # node 2 has no edges at all

    assignment = community.detect_communities(nodes, edges)

    assert "N2" not in assignment
    assert "N0" in assignment and "N1" in assignment


def test_detect_communities_empty_edges_returns_empty_mapping():
    nodes = [_node(0), _node(1)]
    assert community.detect_communities(nodes, []) == {}


def test_label_communities_heuristic_uses_most_connected_members():
    nodes = [_node(0), _node(1), _node(2)]
    # N0 has degree 2 (hub), N1 and N2 have degree 1 each
    edges = [_edge(0, 1), _edge(0, 2)]
    assignment = {"N0": 0, "N1": 0, "N2": 0}

    labels = community.label_communities_heuristic(assignment, nodes, edges, top_n=2)

    assert len(labels) == 1
    assert labels[0].label_source == "heuristic"
    assert labels[0].size == 3
    assert labels[0].label.startswith("N0")  # highest-degree member listed first


def test_label_communities_llm_success_replaces_label(monkeypatch):
    communities = [Community(id=0, label="heuristic-label", label_source="heuristic", size=2, member_ids=["N0", "N1"])]
    nodes_by_id = {"N0": _node(0), "N1": _node(1)}

    class FakeResult:
        text = '{"choices": [{"message": {"content": "Hashing And Join Keys"}}]}'

    with patch("revit_schema_mapper.community.HttpClient.post_json", return_value=FakeResult()):
        out = community.label_communities_llm(communities, nodes_by_id, model="test-model", api_key="key", throttle_seconds=0)

    assert out[0].label == "Hashing And Join Keys"
    assert out[0].label_source == "llm"


def test_label_communities_llm_falls_back_to_heuristic_on_http_error():
    communities = [Community(id=0, label="heuristic-label", label_source="heuristic", size=2, member_ids=["N0", "N1"])]
    nodes_by_id = {"N0": _node(0), "N1": _node(1)}

    with patch("revit_schema_mapper.community.HttpClient.post_json", side_effect=HttpError("network down")):
        out = community.label_communities_llm(communities, nodes_by_id, model="test-model", api_key="key", throttle_seconds=0)

    assert out[0].label == "heuristic-label"
    assert out[0].label_source == "heuristic"


def test_label_communities_llm_falls_back_to_heuristic_on_malformed_response():
    communities = [Community(id=0, label="heuristic-label", label_source="heuristic", size=2, member_ids=["N0", "N1"])]
    nodes_by_id = {"N0": _node(0), "N1": _node(1)}

    class FakeResult:
        text = "not json at all"

    with patch("revit_schema_mapper.community.HttpClient.post_json", return_value=FakeResult()):
        out = community.label_communities_llm(communities, nodes_by_id, model="test-model", api_key="key", throttle_seconds=0)

    assert out[0].label == "heuristic-label"
    assert out[0].label_source == "heuristic"


def test_label_communities_llm_one_failure_does_not_affect_other_communities():
    communities = [
        Community(id=0, label="heuristic-0", label_source="heuristic", size=1, member_ids=["N0"]),
        Community(id=1, label="heuristic-1", label_source="heuristic", size=1, member_ids=["N1"]),
    ]
    nodes_by_id = {"N0": _node(0), "N1": _node(1)}

    class FakeResult:
        text = '{"choices": [{"message": {"content": "Good Label"}}]}'

    with patch("revit_schema_mapper.community.HttpClient.post_json", side_effect=[HttpError("down"), FakeResult()]):
        out = community.label_communities_llm(communities, nodes_by_id, model="test-model", api_key="key", throttle_seconds=0)

    assert out[0].label == "heuristic-0"
    assert out[0].label_source == "heuristic"
    assert out[1].label == "Good Label"
    assert out[1].label_source == "llm"


def test_build_communities_without_llm_flag_stays_heuristic():
    nodes = [_node(0), _node(1)]
    edges = [_edge(0, 1)]

    assignment, communities = community.build_communities(nodes, edges, use_llm_labels=False)

    assert communities[0].label_source == "heuristic"


def test_build_communities_llm_flag_without_api_key_falls_back_to_heuristic(caplog):
    nodes = [_node(0), _node(1)]
    edges = [_edge(0, 1)]

    assignment, communities = community.build_communities(nodes, edges, use_llm_labels=True, api_key=None)

    assert communities[0].label_source == "heuristic"
    assert any("OPENROUTER_API_KEY" in msg for msg in caplog.text.splitlines()) or "OpenRouter" in caplog.text
