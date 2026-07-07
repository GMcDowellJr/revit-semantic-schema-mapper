"""Community detection + labeling for the materialized knowledge graph.

Structural clustering is a different axis from ``class_role``:
``classify.classify_class_role`` labels each type *individually* from its
own kind/name/member shape, with no regard for how it actually connects to
other types. ``detect_communities`` instead looks at the graph's real
connectivity (see ``graph.apply_communities``, which runs this over the
core-tier subgraph -- the only edges with distinct, meaningful relationship
semantics; see docs/edge_taxonomy_v0.md) and finds groups of types that
reference each other densely -- closer to what a tool like Graphify calls a
"community."

Labeling defaults to a free, deterministic heuristic (a community's most
connected member names) -- zero dependencies, always available. An
optional, opt-in upgrade calls a cheap model through OpenRouter
(https://openrouter.ai) for a short thematic label instead. That upgrade
never breaks the pipeline: any single community's request failing (missing
key, network error, non-2xx, malformed response) just keeps that
community's heuristic label.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import time

from .http_compat import HttpClient, HttpError
from .models import Community, GraphEdge, GraphNode

logger = logging.getLogger(__name__)

# A small, historically inexpensive OpenRouter model, suitable for a short
# classification-style prompt. OpenRouter's catalog and pricing change over
# time -- treat this as a reasonable starting point, not a guarantee; pass
# --community-label-model to override it.
DEFAULT_OPENROUTER_MODEL = "openai/gpt-4o-mini"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _undirected_projection(nodes: list[GraphNode], edges: list[GraphEdge]) -> tuple[dict[str, dict[str, int]], dict[str, int], int]:
    """Build a multiplicity-weighted undirected adjacency from ``edges``,
    ignoring direction, self-loops, and any edge whose endpoint isn't in
    ``nodes`` (defensive -- callers are expected to pass a matched
    nodes/edges pair, e.g. from ``graph.filter_core``).
    """
    node_ids = {n.id for n in nodes}
    adjacency: dict[str, dict[str, int]] = {nid: {} for nid in node_ids}
    degree: dict[str, int] = {nid: 0 for nid in node_ids}
    m = 0
    for e in edges:
        a, b = e.source, e.target
        if a is None or b is None or a == b:
            continue
        if a not in node_ids or b not in node_ids:
            continue
        adjacency[a][b] = adjacency[a].get(b, 0) + 1
        adjacency[b][a] = adjacency[b].get(a, 0) + 1
        degree[a] += 1
        degree[b] += 1
        m += 1
    return adjacency, degree, m


def detect_communities(nodes: list[GraphNode], edges: list[GraphEdge], *, max_passes: int = 20) -> dict[str, int]:
    """Single-level greedy modularity optimization -- Louvain's local-move
    phase only, without the multi-level community-aggregation phase real
    Louvain repeats on top of it. That's a real simplification (this won't
    find as clean a hierarchy on a very large graph), but it's dependency-free,
    deterministic, and plenty for graphs of this size (a few hundred to a few
    thousand nodes).

    Node visit order is sorted by id, not randomized, so the same input
    always produces the same partition. Isolated nodes (no edges at all)
    are left out of the returned mapping entirely -- callers should treat a
    missing id as "no community," not community 0.

    Returns ``{node_id: community_id}``.
    """
    adjacency, degree, m = _undirected_projection(nodes, edges)
    active = sorted(nid for nid, d in degree.items() if d > 0)
    if m == 0 or not active:
        return {}

    community = {nid: i for i, nid in enumerate(active)}
    community_degree = {i: degree[nid] for nid, i in community.items()}
    two_m = 2 * m

    improved = True
    passes = 0
    while improved and passes < max_passes:
        improved = False
        passes += 1
        for nid in active:
            current = community[nid]
            k_i = degree[nid]
            community_degree[current] -= k_i

            neighbor_weight: dict[int, int] = {}
            for nb, w in adjacency[nid].items():
                c = community[nb]
                neighbor_weight[c] = neighbor_weight.get(c, 0) + w

            best_comm = current
            best_gain = neighbor_weight.get(current, 0) - community_degree.get(current, 0) * k_i / two_m
            for c, k_in in neighbor_weight.items():
                if c == current:
                    continue
                gain = k_in - community_degree.get(c, 0) * k_i / two_m
                if gain > best_gain + 1e-12:
                    best_gain = gain
                    best_comm = c

            community[nid] = best_comm
            community_degree[best_comm] = community_degree.get(best_comm, 0) + k_i
            if best_comm != current:
                improved = True

    # Renumber to consecutive ids, largest community first, ties broken by
    # lowest member id -- purely cosmetic, but keeps output deterministic.
    groups: dict[int, list[str]] = {}
    for nid, c in community.items():
        groups.setdefault(c, []).append(nid)
    ordered = sorted(groups.values(), key=lambda members: (-len(members), min(members)))
    remap: dict[str, int] = {}
    for new_id, members in enumerate(ordered):
        for nid in members:
            remap[nid] = new_id
    return remap


def label_communities_heuristic(assignment: dict[str, int], nodes: list[GraphNode], edges: list[GraphEdge], *, top_n: int = 3) -> list[Community]:
    """Dependency-free default label: a community's ``top_n`` most-connected
    member names (by degree within the same edge set used for detection),
    joined with " · " -- e.g. "View · ViewSheet · Viewport". Deterministic:
    ties broken by node id.
    """
    nodes_by_id = {n.id: n for n in nodes}
    degree: dict[str, int] = {}
    for e in edges:
        if e.source in assignment:
            degree[e.source] = degree.get(e.source, 0) + 1
        if e.target and e.target in assignment:
            degree[e.target] = degree.get(e.target, 0) + 1

    groups: dict[int, list[str]] = {}
    for nid, cid in assignment.items():
        groups.setdefault(cid, []).append(nid)

    communities: list[Community] = []
    for cid, member_ids in groups.items():
        ranked = sorted(member_ids, key=lambda nid: (-degree.get(nid, 0), nid))
        top_names = [nodes_by_id[nid].short_name for nid in ranked[:top_n] if nid in nodes_by_id]
        label = " · ".join(top_names) if top_names else f"Community {cid}"
        communities.append(Community(id=cid, label=label, label_source="heuristic", size=len(member_ids), member_ids=sorted(member_ids)))

    communities.sort(key=lambda c: (-c.size, c.id))
    return communities


def _request_label(client: HttpClient, *, model: str, api_key: str, community: Community, nodes_by_id: dict[str, GraphNode], timeout: float) -> str:
    members = [nodes_by_id[nid] for nid in community.member_ids if nid in nodes_by_id]
    listing = "\n".join(f"- {n.short_name} ({n.class_role or 'unknown'})" for n in members[:20])
    prompt = (
        "You are naming a cluster of related types from the Autodesk Revit API's object model. "
        "These types were grouped by graph community detection (they reference each other densely). "
        "Respond with ONLY a short 2-5 word thematic label for the cluster -- no punctuation, no "
        "quotes, no explanation.\n\n" + listing
    )
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 20,
        "temperature": 0.3,
    }
    result = client.post_json(
        OPENROUTER_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://github.com/GMcDowellJr/revit-semantic-schema-mapper",
            "X-Title": "Revit Semantic Schema Mapper",
        },
        json_body=body,
        timeout=timeout,
    )
    payload = json.loads(result.text)
    label = payload["choices"][0]["message"]["content"].strip().strip('"').strip("'")
    if not label:
        raise ValueError("empty label in OpenRouter response")
    return label[:80]


def label_communities_llm(
    communities: list[Community],
    nodes_by_id: dict[str, GraphNode],
    *,
    model: str,
    api_key: str,
    throttle_seconds: float = 0.6,
    timeout: float = 20.0,
) -> list[Community]:
    """Replace each community's heuristic label with a short OpenRouter-
    generated one, best-effort per community: any single request failing
    (network error, non-2xx, malformed response, timeout) leaves that
    community on its heuristic label instead of raising -- labeling is a
    nice-to-have, never a reason for the whole pipeline run to fail.
    """
    client = HttpClient(headers={"User-Agent": "revit-schema-mapper/community-labeling"})

    relabeled: list[Community] = []
    for i, community in enumerate(communities):
        if i > 0:
            time.sleep(throttle_seconds)
        try:
            label = _request_label(client, model=model, api_key=api_key, community=community, nodes_by_id=nodes_by_id, timeout=timeout)
            relabeled.append(dataclasses.replace(community, label=label, label_source="llm"))
        except (HttpError, ValueError, KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            logger.warning(
                "OpenRouter labeling failed for community %d (%r); keeping heuristic label %r",
                community.id, exc, community.label,
            )
            relabeled.append(community)
    return relabeled


def build_communities(
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    *,
    use_llm_labels: bool = False,
    model: str = DEFAULT_OPENROUTER_MODEL,
    api_key: str | None = None,
) -> tuple[dict[str, int], list[Community]]:
    """Detect communities and label them -- the single entry point
    ``graph.apply_communities`` calls. Returns ``(assignment, communities)``.

    ``use_llm_labels=True`` with no ``api_key`` logs a warning and falls
    back to heuristic labels rather than raising -- a missing/unset
    ``OPENROUTER_API_KEY`` should never turn into a failed pipeline run.
    """
    assignment = detect_communities(nodes, edges)
    communities = label_communities_heuristic(assignment, nodes, edges)

    if use_llm_labels:
        if not api_key:
            logger.warning("--label-communities-llm was set but no OpenRouter API key is configured (set OPENROUTER_API_KEY); using heuristic labels instead")
        else:
            nodes_by_id = {n.id: n for n in nodes}
            communities = label_communities_llm(communities, nodes_by_id, model=model, api_key=api_key)

    return assignment, communities
