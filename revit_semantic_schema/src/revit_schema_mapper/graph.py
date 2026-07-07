"""Materialize node/edge *candidates* (classify.py's output) into an actual
graph: resolved node ids, a confidence tier per edge, and external stub nodes
for anything an edge points at that wasn't itself crawled/classified.

``node_type_candidates.json``/``candidate_edges.json`` are already almost a
graph -- the two gaps this module closes are (1) an edge's
``candidate_target_type`` is a loose type-name string, not a resolved node
id, and (2) every edge carries a seven-label ``ConfidenceLabel`` that's more
granularity than most downstream consumers want. See ``docs/edge_taxonomy_v0.md``
and ``docs/confidence_model_v0.md`` for the model this builds on.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from . import community as community_module
from .models import (
    Community,
    ConfidenceLabel,
    ConfidenceTier,
    EdgeCandidate,
    GraphEdge,
    GraphNode,
    NodeCandidate,
    TargetResolution,
)

# Mirrors export._UNKNOWN_EDGE_TYPES: a high edge_confidence on one of these
# reflects confidence in the *return type* only, not in any specific
# relationship, so they're pinned to UNVERIFIED_REFERENCE regardless of
# their confidence label -- otherwise they'd dominate the "core" tier (in a
# real full crawl, ~77% of all edges) with relationships that carry no
# actual semantics beyond "this points at some DB object."
_UNKNOWN_EDGE_TYPES = {"UNKNOWN_DB_OBJECT_REFERENCE", "UNKNOWN_ELEMENTID_REFERENCE"}

_CORE_CONFIDENCE = {
    ConfidenceLabel.DIRECT_RETURN_TYPE,
    ConfidenceLabel.ELEMENTID_WITH_STRONG_NAME,
    ConfidenceLabel.ELEMENTID_COLLECTION_WITH_STRONG_NAME,
    ConfidenceLabel.DOCS_SEMANTIC_HINT,
}


def confidence_tier(edge: EdgeCandidate) -> ConfidenceTier:
    """See the module docstring and docs/confidence_model_v0.md.

    ``needs_runtime_validation`` is checked before the UNKNOWN_* override:
    per the confidence model doc, it's a distinct "unverified" axis rather
    than a rank on the same scale, and it's more useful to a downstream
    consumer to know "this needs a live-document check" than to fold it
    into the same bucket as "no relationship semantics identified at all."
    """
    if edge.edge_confidence is ConfidenceLabel.NEEDS_RUNTIME_VALIDATION:
        return ConfidenceTier.NEEDS_VALIDATION
    if edge.candidate_edge_type.value in _UNKNOWN_EDGE_TYPES:
        return ConfidenceTier.UNVERIFIED_REFERENCE
    if edge.edge_confidence in _CORE_CONFIDENCE:
        return ConfidenceTier.CORE
    if edge.edge_confidence is ConfidenceLabel.NAME_ONLY_CANDIDATE:
        return ConfidenceTier.LIKELY
    return ConfidenceTier.UNVERIFIED_REFERENCE


@dataclass
class GraphBuildResult:
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    # Diagnostics: how target/source resolution went, for graph.json's
    # metadata block and for spotting systematic misses (e.g. a namespace
    # mis-qualification bug like the one documented in docs/crawl_notes.md
    # for Autodesk.Revit.DB.Architecture.Room) rather than one-off gaps.
    target_resolution_counts: dict[str, int] = field(default_factory=dict)
    external_node_count: int = 0
    # Populated by apply_communities -- empty until that's called.
    communities: list[Community] = field(default_factory=list)


class _Resolver:
    """Resolves a type-name string to a node id against a known set of
    crawled/classified ``NodeCandidate``s, falling back to a short-name
    match only when it's unambiguous.

    The short-name fallback exists because ``candidate_target_type`` and
    ``NodeCandidate.full_type_name`` are computed by different code paths
    (edge classification vs. node classification) and can disagree on
    namespace qualification for the exact same real type -- confirmed in a
    live crawl, where edges pointed at ``Autodesk.Revit.DB.Room`` while the
    actual crawled node was ``Autodesk.Revit.DB.Architecture.Room``. Falling
    back blindly to *any* same-named type would risk merging two distinct
    real types that happen to share a short name, so this only applies when
    exactly one node has that short name.
    """

    def __init__(self, node_candidates: list[NodeCandidate]) -> None:
        self._by_full_name = {n.full_type_name: n for n in node_candidates}
        by_short: dict[str, list[str]] = {}
        for n in node_candidates:
            by_short.setdefault(n.short_name, []).append(n.full_type_name)
        self._unambiguous_by_short = {short: names[0] for short, names in by_short.items() if len(names) == 1}
        self._external_ids: dict[str, GraphNode] = {}

    def resolve(self, type_name: str | None, *, allow_short_name_fallback: bool = True) -> tuple[str | None, TargetResolution]:
        """``allow_short_name_fallback=False`` is for resolving an edge's
        *source*: the fallback is only justified for a target, where we
        independently know (from classify.py's return-type parsing) that
        the name really does refer to a specific real type and we're just
        correcting a namespace mismatch. A source string with no exact node
        match usually just means that type's own page failed to crawl/parse
        -- falling back to *any* unrelated node that happens to share its
        short name would silently rewrite that node's edges onto the wrong
        type instead of correctly marking it external.
        """
        if not type_name:
            return None, TargetResolution.NONE
        if type_name in self._by_full_name:
            return type_name, TargetResolution.EXACT

        short = type_name.rsplit(".", 1)[-1]
        if allow_short_name_fallback:
            fallback = self._unambiguous_by_short.get(short)
            if fallback is not None:
                return fallback, TargetResolution.SHORT_NAME_FALLBACK

        if type_name not in self._external_ids:
            self._external_ids[type_name] = GraphNode(
                id=type_name,
                short_name=short,
                external=True,
            )
        return type_name, TargetResolution.EXTERNAL

    @property
    def external_nodes(self) -> list[GraphNode]:
        return list(self._external_ids.values())


def build_graph(node_candidates: list[NodeCandidate], edge_candidates: list[EdgeCandidate]) -> GraphBuildResult:
    resolver = _Resolver(node_candidates)

    graph_edges: list[GraphEdge] = []
    resolution_counts: Counter[str] = Counter()

    for edge in edge_candidates:
        # Sources are expected to already be a crawled/classified node (an
        # EdgeCandidate's source_type comes from a class/struct/interface
        # page's own members -- see classify.build_edge_candidates), but a
        # truncated/partial crawl can still leave one dangling; resolving it
        # keeps every edge endpoint backed by some node rather than a
        # silently broken reference. Unlike a target, an unresolved source
        # never falls back to a same-named node -- see _Resolver.resolve.
        source_id, _ = resolver.resolve(edge.source_type, allow_short_name_fallback=False)
        target_id, target_resolution = resolver.resolve(edge.candidate_target_type)
        resolution_counts[target_resolution.value] += 1

        graph_edges.append(
            GraphEdge(
                source=source_id or edge.source_type,
                target=target_id,
                member_name=edge.member_name,
                member_kind=edge.member_kind,
                edge_type=edge.candidate_edge_type,
                confidence=edge.edge_confidence,
                confidence_tier=confidence_tier(edge),
                target_resolution=target_resolution,
                evidence=edge.evidence,
                source_url=edge.source_url,
            )
        )

    graph_nodes: list[GraphNode] = [
        GraphNode(
            id=n.full_type_name,
            short_name=n.short_name,
            external=False,
            kind=n.kind.value,
            namespace=n.namespace,
            class_role=n.class_role.value,
            is_element_candidate=n.is_element_candidate.value,
            base_type=n.base_type,
            source_url=n.source_url,
        )
        for n in node_candidates
    ] + resolver.external_nodes

    return GraphBuildResult(
        nodes=graph_nodes,
        edges=graph_edges,
        target_resolution_counts=dict(resolution_counts),
        external_node_count=len(resolver.external_nodes),
    )


def filter_core(result: GraphBuildResult) -> tuple[list[GraphNode], list[GraphEdge]]:
    """The 'core' subgraph: edges tiered CORE only, plus just the nodes they
    actually reference (as source or target) -- not the full node set, so
    this stays a small, genuinely-trustworthy slice rather than the full
    crawl's node list with most edges missing.

    An edge can be tiered CORE (a high-confidence return type or strongly-
    named ElementId/collection) while still having no resolvable
    ``candidate_target_type`` at all -- e.g. ``GetDependentElements``, where
    the name matches a relationship keyword but ``ElementId`` erases which
    type it points at, so classify.py never had one to record. That's a
    legitimate thing for ``graph.json`` to say ("this is a confident
    relationship, target unknown"), but it isn't a graph edge -- excluded
    here so a consumer can treat ``graph_core.json`` as a genuinely loadable
    node/edge graph, with every edge in it pointing somewhere real.
    """
    core_edges = [e for e in result.edges if e.confidence_tier is ConfidenceTier.CORE and e.target is not None]
    referenced_ids = {e.source for e in core_edges} | {e.target for e in core_edges}
    core_nodes = [n for n in result.nodes if n.id in referenced_ids]
    return core_nodes, core_edges


def apply_communities(
    result: GraphBuildResult,
    *,
    use_llm_labels: bool = False,
    model: str = community_module.DEFAULT_OPENROUTER_MODEL,
    api_key: str | None = None,
) -> None:
    """Detect and label communities over ``result``'s core-tier subgraph
    (see ``filter_core``) and record them onto ``result`` in place:
    ``result.communities`` gets the labeled list, and every core-subgraph
    node's ``GraphNode.community_id`` is set to match (mutated in place, so
    it's reflected consistently in both ``graph.json`` and
    ``graph_core.json`` -- those write the same node objects, just a
    different subset -- see ``export.write_graph``).

    Nodes outside the core subgraph (and isolated core nodes with no
    surviving edge) keep ``community_id=None``: communities are only
    meaningful relative to the edges they were detected from, not a
    property of every node in the full crawl.
    """
    core_nodes, core_edges = filter_core(result)
    assignment, communities = community_module.build_communities(
        core_nodes, core_edges, use_llm_labels=use_llm_labels, model=model, api_key=api_key
    )

    nodes_by_id = {n.id: n for n in result.nodes}
    for node_id, community_id in assignment.items():
        node = nodes_by_id.get(node_id)
        if node is not None:
            node.community_id = community_id

    result.communities = communities
