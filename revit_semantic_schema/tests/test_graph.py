from revit_schema_mapper import graph
from revit_schema_mapper.models import (
    ClassRole,
    ConfidenceLabel,
    ConfidenceTier,
    EdgeCandidate,
    EdgeType,
    IsElementCandidate,
    Kind,
    MemberKind,
    NodeCandidate,
    TargetResolution,
)


def _node(full_type_name: str, short_name: str | None = None) -> NodeCandidate:
    return NodeCandidate(
        full_type_name=full_type_name,
        short_name=short_name or full_type_name.rsplit(".", 1)[-1],
        kind=Kind.CLASS,
        namespace="Autodesk.Revit.DB",
        base_type=None,
        inheritance_chain=[],
        is_element_candidate=IsElementCandidate.UNKNOWN,
        class_role=ClassRole.UNKNOWN,
        evidence=[],
        source_url="https://www.revitapidocs.com/2024/x.htm",
    )


def _edge(
    source_type: str,
    target: str | None,
    edge_type: EdgeType,
    confidence: ConfidenceLabel,
) -> EdgeCandidate:
    return EdgeCandidate(
        source_type=source_type,
        member_name="SomeMember",
        member_kind=MemberKind.PROPERTY,
        raw_signature="x",
        return_type=target,
        parameter_types=[],
        candidate_target_type=target,
        candidate_edge_type=edge_type,
        edge_confidence=confidence,
        evidence=[],
        source_url="https://www.revitapidocs.com/2024/x.htm",
    )


def test_exact_target_resolves_to_matching_node():
    nodes = [_node("Autodesk.Revit.DB.View")]
    edges = [_edge("Autodesk.Revit.DB.View", "Autodesk.Revit.DB.View", EdgeType.CONTROLLED_BY_TEMPLATE, ConfidenceLabel.ELEMENTID_WITH_STRONG_NAME)]

    result = graph.build_graph(nodes, edges)

    assert result.edges[0].target == "Autodesk.Revit.DB.View"
    assert result.edges[0].target_resolution is TargetResolution.EXACT
    assert result.external_node_count == 0


def test_unresolved_target_falls_back_to_unambiguous_short_name():
    """A real crawl found candidate_target_type computed as the top-level
    namespace (Autodesk.Revit.DB.Room) while the actual crawled node lived
    in a sub-namespace (Autodesk.Revit.DB.Architecture.Room) -- see
    docs/crawl_notes.md. The resolver must still connect these when exactly
    one node shares the short name.
    """
    nodes = [_node("Autodesk.Revit.DB.Architecture.Room", short_name="Room"), _node("Autodesk.Revit.DB.SomeType")]
    edges = [_edge("Autodesk.Revit.DB.SomeType", "Autodesk.Revit.DB.Room", EdgeType.UNKNOWN_DB_OBJECT_REFERENCE, ConfidenceLabel.DIRECT_RETURN_TYPE)]

    result = graph.build_graph(nodes, edges)

    assert result.edges[0].target == "Autodesk.Revit.DB.Architecture.Room"
    assert result.edges[0].target_resolution is TargetResolution.SHORT_NAME_FALLBACK
    assert result.external_node_count == 0


def test_ambiguous_short_name_is_not_used_as_fallback():
    """Two distinct real nodes sharing a short name must not be merged --
    an unresolved target stays external rather than guessing which one it
    meant.
    """
    nodes = [
        _node("Autodesk.Revit.DB.Architecture.Room", short_name="Room"),
        _node("Autodesk.Revit.DB.Mechanical.Room", short_name="Room"),
        _node("Autodesk.Revit.DB.SomeType"),
    ]
    edges = [_edge("Autodesk.Revit.DB.SomeType", "Autodesk.Revit.DB.Room", EdgeType.UNKNOWN_DB_OBJECT_REFERENCE, ConfidenceLabel.DIRECT_RETURN_TYPE)]

    result = graph.build_graph(nodes, edges)

    assert result.edges[0].target == "Autodesk.Revit.DB.Room"
    assert result.edges[0].target_resolution is TargetResolution.EXTERNAL
    assert result.external_node_count == 1


def test_external_target_creates_deduped_stub_node():
    nodes = [_node("Autodesk.Revit.DB.SomeType")]
    edges = [
        _edge("Autodesk.Revit.DB.SomeType", "Autodesk.Revit.DB.ForgeTypeId", EdgeType.UNKNOWN_DB_OBJECT_REFERENCE, ConfidenceLabel.DIRECT_RETURN_TYPE),
        _edge("Autodesk.Revit.DB.SomeType", "Autodesk.Revit.DB.ForgeTypeId", EdgeType.UNKNOWN_DB_OBJECT_REFERENCE, ConfidenceLabel.DIRECT_RETURN_TYPE),
    ]

    result = graph.build_graph(nodes, edges)

    external_nodes = [n for n in result.nodes if n.external]
    assert len(external_nodes) == 1
    assert external_nodes[0].id == "Autodesk.Revit.DB.ForgeTypeId"
    assert external_nodes[0].short_name == "ForgeTypeId"


def test_edge_with_no_target_type_gets_none_resolution():
    nodes = [_node("Autodesk.Revit.DB.SomeType")]
    edges = [_edge("Autodesk.Revit.DB.SomeType", None, EdgeType.HAS_PARAMETER, ConfidenceLabel.NAME_ONLY_CANDIDATE)]

    result = graph.build_graph(nodes, edges)

    assert result.edges[0].target is None
    assert result.edges[0].target_resolution is TargetResolution.NONE


def test_unknown_edge_type_is_pinned_to_unverified_reference_regardless_of_confidence():
    """UNKNOWN_* edge types mean 'definitely a reference, no specific
    relationship identified' -- their edge_confidence can still be
    direct_return_type (the return type itself is certain), but that must
    not promote them into the 'core' tier, or 'core' would be dominated by
    relationships that carry no actual semantics (~77% of edges in a real
    full crawl were UNKNOWN_DB_OBJECT_REFERENCE with direct_return_type).
    """
    edge = _edge("Autodesk.Revit.DB.SomeType", "Autodesk.Revit.DB.Color", EdgeType.UNKNOWN_DB_OBJECT_REFERENCE, ConfidenceLabel.DIRECT_RETURN_TYPE)

    assert graph.confidence_tier(edge) is ConfidenceTier.UNVERIFIED_REFERENCE


def test_needs_runtime_validation_is_its_own_tier_even_for_a_specific_edge_type():
    edge = _edge("Autodesk.Revit.DB.SomeType", "Autodesk.Revit.DB.Level", EdgeType.ASSIGNED_TO_LEVEL, ConfidenceLabel.NEEDS_RUNTIME_VALIDATION)

    assert graph.confidence_tier(edge) is ConfidenceTier.NEEDS_VALIDATION


def test_core_confidence_with_specific_edge_type_is_core_tier():
    edge = _edge("Autodesk.Revit.DB.FamilyInstance", "Autodesk.Revit.DB.FamilySymbol", EdgeType.INSTANCE_OF, ConfidenceLabel.DIRECT_RETURN_TYPE)

    assert graph.confidence_tier(edge) is ConfidenceTier.CORE


def test_name_only_candidate_is_likely_tier():
    edge = _edge("Autodesk.Revit.DB.Element", "Autodesk.Revit.DB.Workset", EdgeType.OWNED_BY_WORKSET, ConfidenceLabel.NAME_ONLY_CANDIDATE)

    assert graph.confidence_tier(edge) is ConfidenceTier.LIKELY


def test_filter_core_keeps_only_core_edges_and_their_referenced_nodes():
    nodes = [_node("Autodesk.Revit.DB.FamilyInstance"), _node("Autodesk.Revit.DB.FamilySymbol"), _node("Autodesk.Revit.DB.Unrelated")]
    edges = [
        _edge("Autodesk.Revit.DB.FamilyInstance", "Autodesk.Revit.DB.FamilySymbol", EdgeType.INSTANCE_OF, ConfidenceLabel.DIRECT_RETURN_TYPE),
        _edge("Autodesk.Revit.DB.Unrelated", "Autodesk.Revit.DB.FamilySymbol", EdgeType.UNKNOWN_DB_OBJECT_REFERENCE, ConfidenceLabel.DIRECT_RETURN_TYPE),
    ]

    result = graph.build_graph(nodes, edges)
    core_nodes, core_edges = graph.filter_core(result)

    assert len(core_edges) == 1
    assert core_edges[0].edge_type == EdgeType.INSTANCE_OF
    core_node_ids = {n.id for n in core_nodes}
    assert core_node_ids == {"Autodesk.Revit.DB.FamilyInstance", "Autodesk.Revit.DB.FamilySymbol"}


def test_dangling_source_is_still_resolved_and_not_left_as_raw_string():
    """A truncated crawl can produce an edge whose source_type was never
    itself classified into a node -- the source should still resolve
    consistently (falling back to an external stub) rather than being a
    bare string that doesn't match anything in result.nodes.
    """
    nodes = [_node("Autodesk.Revit.DB.FamilySymbol")]
    edges = [_edge("Autodesk.Revit.DB.NeverCrawledType", "Autodesk.Revit.DB.FamilySymbol", EdgeType.INSTANCE_OF, ConfidenceLabel.DIRECT_RETURN_TYPE)]

    result = graph.build_graph(nodes, edges)

    node_ids = {n.id for n in result.nodes}
    assert result.edges[0].source in node_ids


def test_apply_communities_sets_community_id_on_core_nodes_only():
    """Communities are detected over the core-tier subgraph -- a node only
    reachable via an UNKNOWN_* (unverified_reference) edge shouldn't get a
    community_id, since it was never part of what was clustered.
    """
    nodes = [
        _node("Autodesk.Revit.DB.FamilyInstance"),
        _node("Autodesk.Revit.DB.FamilySymbol"),
        _node("Autodesk.Revit.DB.Orphan"),
    ]
    edges = [
        _edge("Autodesk.Revit.DB.FamilyInstance", "Autodesk.Revit.DB.FamilySymbol", EdgeType.INSTANCE_OF, ConfidenceLabel.DIRECT_RETURN_TYPE),
        _edge("Autodesk.Revit.DB.Orphan", "Autodesk.Revit.DB.FamilySymbol", EdgeType.UNKNOWN_DB_OBJECT_REFERENCE, ConfidenceLabel.DIRECT_RETURN_TYPE),
    ]

    result = graph.build_graph(nodes, edges)
    graph.apply_communities(result)

    by_id = {n.id: n for n in result.nodes}
    assert by_id["Autodesk.Revit.DB.FamilyInstance"].community_id is not None
    assert by_id["Autodesk.Revit.DB.FamilySymbol"].community_id is not None
    assert by_id["Autodesk.Revit.DB.Orphan"].community_id is None
    assert len(result.communities) == 1
    assert result.communities[0].size == 2


def test_apply_communities_with_no_core_edges_produces_no_communities():
    nodes = [_node("Autodesk.Revit.DB.A"), _node("Autodesk.Revit.DB.B")]
    edges = [_edge("Autodesk.Revit.DB.A", "Autodesk.Revit.DB.B", EdgeType.UNKNOWN_DB_OBJECT_REFERENCE, ConfidenceLabel.DIRECT_RETURN_TYPE)]

    result = graph.build_graph(nodes, edges)
    graph.apply_communities(result)

    assert result.communities == []
    assert all(n.community_id is None for n in result.nodes)


def test_filter_core_excludes_core_tier_edges_with_no_target():
    """A method like GetDependentElements matches a relationship keyword
    (core-tier confidence) but ElementId erases which type it points at, so
    candidate_target_type is None -- classify.py never had a target to
    record. graph.json should still say "high-confidence, target unknown,"
    but graph_core.json promises a loadable node/edge graph, so an edge
    with no target at all must not appear in it.
    """
    nodes = [_node("Autodesk.Revit.DB.AssemblyInstance")]
    edges = [
        _edge("Autodesk.Revit.DB.AssemblyInstance", None, EdgeType.MEMBER_OF_GROUP, ConfidenceLabel.ELEMENTID_COLLECTION_WITH_STRONG_NAME),
    ]

    result = graph.build_graph(nodes, edges)

    assert result.edges[0].confidence_tier is ConfidenceTier.CORE
    core_nodes, core_edges = graph.filter_core(result)
    assert core_edges == []
    assert core_nodes == []


def test_filter_core_keeps_core_edges_that_do_have_a_target():
    nodes = [_node("Autodesk.Revit.DB.FamilyInstance"), _node("Autodesk.Revit.DB.FamilySymbol")]
    edges = [_edge("Autodesk.Revit.DB.FamilyInstance", "Autodesk.Revit.DB.FamilySymbol", EdgeType.INSTANCE_OF, ConfidenceLabel.DIRECT_RETURN_TYPE)]

    result = graph.build_graph(nodes, edges)
    core_nodes, core_edges = graph.filter_core(result)

    assert len(core_edges) == 1
    assert {n.id for n in core_nodes} == {"Autodesk.Revit.DB.FamilyInstance", "Autodesk.Revit.DB.FamilySymbol"}


def test_build_graph_carries_dll_and_revitlookup_fields_onto_graph_edge_and_node():
    """Stage B (docs/dll_reflection_v0.md cross_validate_dll) and Stage C
    (cross_validate_revitlookup) annotate EdgeCandidate/NodeCandidate in
    place, but until graph.py explicitly copies those fields onto
    GraphEdge/GraphNode, graph.json/graph_core.json silently drop them --
    a downstream consumer reading only the materialized graph would never
    see cross-validation evidence that candidate_edges.json/
    node_type_candidates.json already carry.
    """
    node = _node("Autodesk.Revit.DB.FamilyInstance")
    node.dll_type_verified = True

    edge = _edge("Autodesk.Revit.DB.FamilyInstance", "Autodesk.Revit.DB.FamilySymbol", EdgeType.INSTANCE_OF, ConfidenceLabel.DIRECT_RETURN_TYPE)
    edge.dll_signature_verified = True
    edge.dll_relationship_scope = "declared"
    edge.dll_semantic_verified = None
    edge.dll_verified_status = "signature_verified_declared"
    edge.revitlookup_referenced = True
    edge.revitlookup_requires_document_context = False

    result = graph.build_graph([node], [edge])

    graph_node = next(n for n in result.nodes if n.id == "Autodesk.Revit.DB.FamilyInstance")
    assert graph_node.dll_type_verified is True

    graph_edge = result.edges[0]
    assert graph_edge.dll_signature_verified is True
    assert graph_edge.dll_relationship_scope == "declared"
    assert graph_edge.dll_verified_status == "signature_verified_declared"
    assert graph_edge.revitlookup_referenced is True
    assert graph_edge.revitlookup_requires_document_context is False


def test_missing_source_does_not_fall_back_to_an_unrelated_same_named_node():
    """If Autodesk.Revit.DB.Architecture.Room's own class page failed to
    crawl (so it's absent from node_candidates), but some unrelated type
    also happens to be named 'Room', a missing source must become an
    external stub -- not get its edges silently rewritten onto that
    unrelated node. The short-name fallback is only safe for targets, where
    classify.py already confirmed the name refers to a real type.
    """
    nodes = [_node("Autodesk.Revit.DB.Mechanical.Room", short_name="Room")]
    edges = [_edge("Autodesk.Revit.DB.Architecture.Room", None, EdgeType.HAS_PARAMETER, ConfidenceLabel.NAME_ONLY_CANDIDATE)]

    result = graph.build_graph(nodes, edges)

    assert result.edges[0].source == "Autodesk.Revit.DB.Architecture.Room"
    external_ids = {n.id for n in result.nodes if n.external}
    assert "Autodesk.Revit.DB.Architecture.Room" in external_ids
