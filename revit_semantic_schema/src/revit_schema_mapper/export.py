"""Write all outputs/revit_2027/* artifacts described in the project brief."""

from __future__ import annotations

import dataclasses
import json
import re
from enum import Enum
from pathlib import Path

from . import semantic_roles
from .graph import GraphBuildResult, filter_core
from .ground_truth import GroundTruthReport
from .models import (
    ApiPage,
    ClassRole,
    ConfidenceLabel,
    EdgeCandidate,
    EdgeType,
    IsElementCandidate,
    Kind,
    MemberKind,
    NodeCandidate,
)


def _to_jsonable(obj):
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_jsonable(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    return obj


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_to_jsonable(data), indent=2, sort_keys=False), encoding="utf-8")


def write_raw_index(output_dir: Path, raw_index_entries: list[dict]) -> None:
    _write_json(output_dir / "raw_index.json", raw_index_entries)


def _redact_doc_text(page: ApiPage) -> ApiPage:
    """A copy of ``page`` with expressive documentation prose (``summary``,
    ``remarks``, full code ``examples``) blanked out.

    These fields hold copied text from Autodesk's/RevitApiDocs' documentation,
    not facts this project derives -- ``classify.py`` reads them from the
    live ``ApiPage`` objects for classification evidence (docs_semantic_hint)
    before export ever runs, so redacting only the persisted JSON doesn't
    affect classification. See docs/crawl_notes.md's data-use notes.
    """
    redacted_members = [dataclasses.replace(m, summary="", remarks="", examples=[]) for m in page.members]
    return dataclasses.replace(page, summary="", remarks="", examples=[], members=redacted_members)


def write_api_pages(output_dir: Path, pages: list[ApiPage], *, include_doc_text: bool = False) -> None:
    if not include_doc_text:
        pages = [_redact_doc_text(p) for p in pages]
    _write_json(output_dir / "api_pages.json", pages)


def write_node_candidates(output_dir: Path, nodes: list[NodeCandidate]) -> None:
    _write_json(output_dir / "node_type_candidates.json", nodes)


def read_node_candidates(output_dir: Path) -> list[NodeCandidate]:
    """Inverse of ``write_node_candidates`` -- lets ``--graph-only`` rebuild
    the graph from a previous run's output without re-crawling/re-parsing.
    """
    raw = json.loads((output_dir / "node_type_candidates.json").read_text(encoding="utf-8"))
    return [
        NodeCandidate(
            full_type_name=r["full_type_name"],
            short_name=r["short_name"],
            kind=Kind(r["kind"]),
            namespace=r["namespace"],
            base_type=r.get("base_type"),
            inheritance_chain=r.get("inheritance_chain", []),
            is_element_candidate=IsElementCandidate(r["is_element_candidate"]),
            class_role=ClassRole(r["class_role"]),
            evidence=r.get("evidence", []),
            source_url=r.get("source_url", ""),
            # Round-tripped so a second --cross-validate-dll run (or any other read of
            # this file) doesn't silently lose a previous pass's annotation -- these are
            # None until ground_truth.cross_validate_dll (Stage B) has actually run once
            # and its output been written back via write_node_candidates.
            dll_type_verified=r.get("dll_type_verified"),
        )
        for r in raw
    ]


def read_edge_candidates(output_dir: Path) -> list[EdgeCandidate]:
    """Inverse of ``write_edge_candidates`` (reads ``candidate_edges.json``,
    the union of both property/method files) -- see ``read_node_candidates``.
    """
    raw = json.loads((output_dir / "candidate_edges.json").read_text(encoding="utf-8"))
    return [
        EdgeCandidate(
            source_type=r["source_type"],
            member_name=r["member_name"],
            member_kind=MemberKind(r["member_kind"]),
            raw_signature=r["raw_signature"],
            return_type=r.get("return_type"),
            parameter_types=r.get("parameter_types", []),
            candidate_target_type=r.get("candidate_target_type"),
            candidate_edge_type=EdgeType(r["candidate_edge_type"]),
            edge_confidence=ConfidenceLabel(r["edge_confidence"]),
            evidence=r.get("evidence", []),
            source_url=r.get("source_url", ""),
            parser_notes=r.get("parser_notes", []),
            # Round-tripped -- see the matching comment in read_node_candidates above.
            dll_signature_verified=r.get("dll_signature_verified"),
            dll_relationship_scope=r.get("dll_relationship_scope"),
            dll_semantic_verified=r.get("dll_semantic_verified"),
            dll_verified_status=r.get("dll_verified_status"),
        )
        for r in raw
    ]


def write_edge_candidates(output_dir: Path, edges: list[EdgeCandidate]) -> None:
    properties = [e for e in edges if e.member_kind is MemberKind.PROPERTY]
    methods = [e for e in edges if e.member_kind is MemberKind.METHOD]
    _write_json(output_dir / "property_relationship_candidates.json", properties)
    _write_json(output_dir / "method_relationship_candidates.json", methods)
    _write_json(output_dir / "candidate_edges.json", edges)


def write_enum_catalogs(output_dir: Path, pages: list[ApiPage]) -> None:
    catalog: dict[str, list[dict]] = {}
    for page in pages:
        if not page.enum_members:
            continue
        catalog.setdefault(page.type_name, [])
        catalog[page.type_name].extend(_to_jsonable(page.enum_members))
    _write_json(output_dir / "enum_catalogs.json", catalog)


_GRAPH_VIEWER_TEMPLATE_PATH = Path(__file__).parent / "graph_viewer_template.html"


def write_graph_html(output_dir: Path, result: GraphBuildResult, *, revit_version: str) -> None:
    """Write ``graph.html``: a self-contained, dependency-free interactive
    viewer (canvas force-directed layout, search, community filter, node
    inspector -- no CDN scripts, so it works even opened directly from
    disk) over the same core subgraph as ``graph_core.json``.

    Node color is ``class_role`` (a fixed, validated 8-slot categorical
    palette); the Communities panel is real structural communities (see
    ``graph.apply_communities``), shown as a labeled filter list rather than
    colored, since community count is unbounded and can't be given its own
    validated hue per entry without cycling past that fixed set.
    """
    core_nodes, core_edges = filter_core(result)

    node_payload = [
        {
            "id": n.id,
            "short_name": n.short_name,
            "external": n.external,
            "kind": n.kind,
            "namespace": n.namespace,
            "class_role": n.class_role,
            "source_url": n.source_url,
            "community_id": n.community_id,
        }
        for n in core_nodes
    ]
    edge_payload = [
        {
            "source": e.source,
            "target": e.target,
            "member_name": e.member_name,
            "edge_type": e.edge_type.value,
            "confidence": e.confidence.value,
            "source_url": e.source_url,
        }
        for e in core_edges
    ]
    community_payload = [
        {"id": c.id, "label": c.label, "label_source": c.label_source, "size": c.size} for c in result.communities
    ]

    payload = json.dumps({"nodes": node_payload, "edges": edge_payload, "communities": community_payload}, separators=(",", ":"))
    # Defensive: a literal "</script" substring anywhere in this payload
    # (e.g. inside a source_url) would close the <script> tag early as far
    # as the HTML parser is concerned, regardless of JS string quoting --
    # HTML parsing happens before JS parsing.
    payload = payload.replace("</", "<\\/")

    template = _GRAPH_VIEWER_TEMPLATE_PATH.read_text(encoding="utf-8")
    html = template.replace("__GRAPH_DATA__", payload).replace("__REVIT_VERSION__", revit_version)
    (output_dir / "graph.html").write_text(html, encoding="utf-8")


def write_semantic_relationship_map(
    output_dir: Path,
    result: GraphBuildResult,
    *,
    revit_version: str,
    top_relationships: int | None = 12,
    min_weight: int = 1,
    max_examples: int = 80,
) -> None:
    """Write ``semantic_relationship_map.html``: a coarser, domain-oriented
    lens on the same core subgraph as ``graph.html`` -- role -> relationship
    -> role Sankey bands plus a role x relationship-type heatmap, both with
    click-to-drilldown back to the real underlying edges. See
    ``semantic_roles.py``'s module docstring for what this answers that the
    raw type-level graph doesn't, and the tradeoffs its role classification
    makes.
    """
    core_nodes, core_edges = filter_core(result)
    data = semantic_roles.aggregate_graph(
        core_nodes, core_edges, top_relationships=top_relationships, min_weight=min_weight, max_examples=max_examples
    )
    html = semantic_roles.render_html(data, revit_version=revit_version)
    (output_dir / "semantic_relationship_map.html").write_text(html, encoding="utf-8")


def _graph_metadata(nodes: list, edges: list, *, revit_version: str) -> dict:
    """Metadata block for a graph.json/graph_core.json -- always derived
    from the exact ``nodes``/``edges`` being written, never copied from a
    different (e.g. unfiltered) node/edge set. graph_core.json's edges are
    all confidence_tier=core by construction, but target_resolution still
    varies (a core edge can still have an external/short-name-fallback
    target) and is worth reporting accurately rather than inherited from
    the full graph.
    """
    resolution_counts: dict[str, int] = {}
    tier_counts: dict[str, int] = {}
    for e in edges:
        resolution_counts[e.target_resolution.value] = resolution_counts.get(e.target_resolution.value, 0) + 1
        tier_counts[e.confidence_tier.value] = tier_counts.get(e.confidence_tier.value, 0) + 1

    return {
        "revit_version": revit_version,
        "node_count": len(nodes),
        "edge_count": len(edges),
        "external_node_count": sum(1 for n in nodes if n.external),
        "target_resolution_counts": resolution_counts,
        "confidence_tier_counts": tier_counts,
    }


def write_graph(output_dir: Path, result: GraphBuildResult, *, revit_version: str) -> None:
    """Write ``graph.json``: the full materialized graph (see graph.py),
    plus ``graph_core.json``, the same graph filtered to just the
    high-confidence 'core' tier -- a small subgraph a downstream tool can
    trust without first re-implementing the confidence-tier filtering
    itself.

    ``result.communities`` (see ``graph.apply_communities``) is written
    identically to both files as a ``communities`` list, plus a
    ``community_count`` in each file's own metadata block. Unlike
    ``confidence_tier_counts``/``target_resolution_counts`` -- which really
    are recomputed per file, from that file's own edges -- communities are
    detected *once*, over the core subgraph, and are the same set of
    clusters regardless of which file you're reading; each node's own
    ``community_id`` (present on the node itself, in both files) is what's
    scoped to the core subgraph, not the community list.
    """
    metadata = _graph_metadata(result.nodes, result.edges, revit_version=revit_version)
    metadata["community_count"] = len(result.communities)
    _write_json(output_dir / "graph.json", {"metadata": metadata, "communities": result.communities, "nodes": result.nodes, "edges": result.edges})

    core_nodes, core_edges = filter_core(result)
    core_metadata = _graph_metadata(core_nodes, core_edges, revit_version=revit_version)
    core_metadata["community_count"] = len(result.communities)
    _write_json(
        output_dir / "graph_core.json",
        {"metadata": core_metadata, "communities": result.communities, "nodes": core_nodes, "edges": core_edges},
    )


def write_target_report(output_dir: Path, target_report: list) -> None:
    _write_json(output_dir / "target_report.json", target_report)


def write_known_edge_report(output_dir: Path, known_edge_report: list) -> None:
    _write_json(output_dir / "known_edge_report.json", known_edge_report)


_CONFIDENCE_RANK = {
    "direct_return_type": 0,
    "elementid_with_strong_name": 1,
    "elementid_collection_with_strong_name": 2,
    "docs_semantic_hint": 3,
    "name_only_candidate": 4,
    "unknown_reference": 5,
    "needs_runtime_validation": 6,
}

# Edge types that mean "definitely a DB-object/ElementId reference, but no
# keyword/docs evidence identifies which specific relationship" (see
# docs/edge_taxonomy_v0.md). High edge_confidence here reflects confidence in
# the *return type*, not in any specific relationship, so these shouldn't
# crowd out genuinely-classified edges in a "top confident" listing.
_UNKNOWN_EDGE_TYPES = {"UNKNOWN_DB_OBJECT_REFERENCE", "UNKNOWN_ELEMENTID_REFERENCE"}


def _unknown_target_type_breakdown(edge_candidates: list[EdgeCandidate], top_n: int = 15) -> list[str]:
    """For UNKNOWN_* edges, count how many share each candidate_target_type.

    A live crawl's UNKNOWN_* bucket is often dominated by a handful of
    generic identifier/spec-key types (e.g. ForgeTypeId, FailureDefinitionId)
    referenced from all over the API with no consistent name pattern -- this
    surfaces that concentration directly instead of leaving it to be found by
    manually querying candidate_edges.json.
    """
    unknown = [e for e in edge_candidates if e.candidate_edge_type.value in _UNKNOWN_EDGE_TYPES]
    if not unknown:
        return ["- (none)"]
    counts: dict[str, int] = {}
    for e in unknown:
        target = e.candidate_target_type or "(none)"
        counts[target] = counts.get(target, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    lines = [f"- {len(unknown)} total UNKNOWN_* edges, {len(counts)} distinct target type(s)"]
    for target, count in ranked[:top_n]:
        lines.append(f"  - `{target}`: {count} ({100 * count / len(unknown):.0f}%)")
    if len(ranked) > top_n:
        lines.append(f"  - ...and {len(ranked) - top_n} more target type(s)")
    return lines


def _graph_section(result: GraphBuildResult | None, *, section_number: int) -> list[str]:
    if result is None:
        return []
    core_nodes, core_edges = filter_core(result)
    tier_counts: dict[str, int] = {}
    for e in result.edges:
        tier_counts[e.confidence_tier.value] = tier_counts.get(e.confidence_tier.value, 0) + 1

    lines = [f"## {section_number}. Knowledge graph materialization", ""]
    lines.append(
        "`graph.json`/`graph_core.json` resolve each edge's `candidate_target_type` string "
        "against the crawled node set (see graph.py) instead of leaving it as a loose type name."
    )
    lines.append(f"- {len(result.nodes)} total nodes ({result.external_node_count} external -- referenced by an edge but never crawled/classified)")
    lines.append(f"- {len(result.edges)} total edges")
    lines.append("- Target resolution: " + ", ".join(f"{k}={v}" for k, v in sorted(result.target_resolution_counts.items())))
    lines.append("- Confidence tier breakdown: " + ", ".join(f"{k}={v}" for k, v in sorted(tier_counts.items())))
    lines.append(f"- `graph_core.json` (confidence_tier=core only): {len(core_nodes)} nodes, {len(core_edges)} edges")
    if result.communities:
        label_sources = {}
        for c in result.communities:
            label_sources[c.label_source] = label_sources.get(c.label_source, 0) + 1
        lines.append(
            f"- {len(result.communities)} communities detected over the core subgraph "
            f"({', '.join(f'{k}={v}' for k, v in sorted(label_sources.items()))} labels)"
        )
        top = sorted(result.communities, key=lambda c: -c.size)[:10]
        lines.append("- Largest communities:")
        lines.extend(f"  - `{c.label}` ({c.size} nodes)" for c in top)
    else:
        lines.append("- 0 communities detected (no core-tier edges, or apply_communities wasn't run)")
    lines.append("")
    return lines


_GRAPH_SECTION_HEADING_RE = re.compile(r"^## \d+\. Knowledge graph materialization\s*$", re.MULTILINE)


def refresh_graph_section_in_file(path: Path, result: GraphBuildResult, *, section_number: int) -> None:
    """Replace (or append, if absent) the 'Knowledge graph materialization'
    section of an already-written ``summary.md``/``validation_summary.md``
    with one reflecting ``result`` -- used by ``--graph-only`` so the
    summary doesn't go stale relative to a freshly recomputed graph.json
    without needing to regenerate the rest of the summary (which needs the
    full page/index data this mode deliberately skips). A no-op if ``path``
    doesn't exist, so callers can try both summary filenames unconditionally
    without knowing in advance whether this was a full or targeted run.
    """
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    match = _GRAPH_SECTION_HEADING_RE.search(text)
    if match:
        text = text[: match.start()]
    section = _graph_section(result, section_number=section_number)
    path.write_text(text.rstrip("\n") + "\n\n" + "\n".join(section) + "\n", encoding="utf-8")


def write_ground_truth_report(output_dir: Path, report: GroundTruthReport) -> None:
    _write_json(output_dir / "ground_truth_report.json", report)


def _ground_truth_section(report: GroundTruthReport | None, *, section_number: int, top_n: int = 10) -> list[str]:
    """Stage B of docs/dll_reflection_v0.md -- cross-checking the docs-derived
    node/edge candidates against a real ``ground_truth_manifest_<version>.json``
    (Stage A's .NET reflection output). ``report`` is ``None`` until
    ``--cross-validate-dll`` is actually run against this output directory (an
    entirely separate, opt-in pass -- see the module docstring on
    ``ground_truth.py``), in which case this contributes nothing rather than a
    misleading all-zero section.
    """
    if report is None:
        return []

    lines = [f"## {section_number}. DLL reflection cross-validation (Stage B)", ""]
    lines.append(
        f"Cross-checked against `ground_truth_manifest_{report.revit_version}.json` -- see "
        "docs/dll_reflection_v0.md. This is a distinct, orthogonal axis from `edge_confidence` "
        "(how strongly the docs alone imply an edge); a low-confidence docs edge can still be "
        "`signature_confirmed` here, and vice versa."
    )
    lines.append("")

    type_counts: dict[str, int] = {}
    for r in report.type_results:
        type_counts[r.status.value] = type_counts.get(r.status.value, 0) + 1
    total_types = len(report.type_results) or 1
    lines.append("### Type verification")
    for status, count in sorted(type_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"- {status}: {count} ({100 * count / total_types:.1f}%)")
    lines.append(
        f"- dll_only (in the manifest, no matching crawled type at all): {len(report.dll_only_types)}"
    )
    lines.append("")

    edge_counts: dict[str, int] = {}
    for r in report.edge_results:
        edge_counts[r.status.value] = edge_counts.get(r.status.value, 0) + 1
    total_edges = len(report.edge_results) or 1
    lines.append("### Edge verification")
    for status, count in sorted(edge_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"- {status}: {count} ({100 * count / total_edges:.1f}%)")
    scope_counts: dict[str, int] = {}
    for r in report.edge_results:
        if r.relationship_scope:
            scope_counts[r.relationship_scope] = scope_counts.get(r.relationship_scope, 0) + 1
    if scope_counts:
        lines.append("- Relationship scope (of edges with a resolved member): " + ", ".join(f"{k}={v}" for k, v in sorted(scope_counts.items())))
    lines.append("")

    doc_only = [r.full_type_name for r in report.type_results if r.status.value == "doc_only"]
    lines.append(f"### Sample doc_only types (docs claim exists, manifest disagrees) -- {len(doc_only)} total")
    if doc_only:
        lines.extend(f"- `{name}`" for name in doc_only[:top_n])
        if len(doc_only) > top_n:
            lines.append(f"- ...and {len(doc_only) - top_n} more")
    else:
        lines.append("- (none)")
    lines.append("")

    lines.append(f"### Sample dll_only types (manifest has it, never crawled) -- {len(report.dll_only_types)} total")
    if report.dll_only_types:
        lines.extend(f"- `{name}`" for name in report.dll_only_types[:top_n])
        if len(report.dll_only_types) > top_n:
            lines.append(f"- ...and {len(report.dll_only_types) - top_n} more")
    else:
        lines.append("- (none)")
    lines.append("")

    mismatches = [r for r in report.edge_results if r.status.value == "signature_mismatch"]
    lines.append(f"### Sample signature_mismatch edges -- {len(mismatches)} total")
    if mismatches:
        for r in mismatches[:top_n]:
            lines.append(f"- `{r.source_type}.{r.member_name}`: {r.note}")
        if len(mismatches) > top_n:
            lines.append(f"- ...and {len(mismatches) - top_n} more")
    else:
        lines.append("- (none)")
    lines.append("")

    return lines


_GROUND_TRUTH_SECTION_HEADING_RE = re.compile(r"^## \d+\. DLL reflection cross-validation \(Stage B\)\s*$", re.MULTILINE)


def refresh_ground_truth_section_in_file(path: Path, report: GroundTruthReport, *, section_number: int) -> None:
    """Replace (or append, if absent) the 'DLL reflection cross-validation'
    section of an already-written ``summary.md``/``validation_summary.md``
    with one reflecting ``report`` -- the same in-place-refresh pattern
    ``refresh_graph_section_in_file`` already uses for the graph section, so
    ``--cross-validate-dll`` can update a summary without needing to
    regenerate the rest of it (which needs the full page/index data this
    mode deliberately skips). A no-op if ``path`` doesn't exist.
    """
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    match = _GROUND_TRUTH_SECTION_HEADING_RE.search(text)
    if match:
        text = text[: match.start()]
    section = _ground_truth_section(report, section_number=section_number)
    if not section:
        return
    path.write_text(text.rstrip("\n") + "\n\n" + "\n".join(section) + "\n", encoding="utf-8")


def write_summary(
    output_dir: Path,
    *,
    revit_version: str,
    fallback_reason: str | None,
    raw_index_entries: list[dict],
    pages: list[ApiPage],
    node_candidates: list[NodeCandidate],
    edge_candidates: list[EdgeCandidate],
    limitations: list[str],
    next_steps: list[str],
    graph_result: GraphBuildResult | None = None,
) -> None:
    properties = [e for e in edge_candidates if e.member_kind is MemberKind.PROPERTY]
    methods = [e for e in edge_candidates if e.member_kind is MemberKind.METHOD]
    enum_member_count = sum(len(p.enum_members) for p in pages)

    # A high edge_confidence only reflects confidence in the *return type*;
    # sorting on that alone let UNKNOWN_* edges (definitely a reference, but
    # to no specific relationship) crowd out genuinely-classified ones at the
    # top of this list. Rank specific edge types first, unknown ones last,
    # confidence within each group.
    ranked = sorted(
        edge_candidates,
        key=lambda e: (e.candidate_edge_type.value in _UNKNOWN_EDGE_TYPES, _CONFIDENCE_RANK.get(e.edge_confidence.value, 99)),
    )
    top_confident = ranked[:25]
    top_uncertain = sorted(
        edge_candidates,
        key=lambda e: -_CONFIDENCE_RANK.get(e.edge_confidence.value, 0),
    )[:25]

    def _fmt_edge(e: EdgeCandidate) -> str:
        target = e.candidate_target_type or "?"
        return (
            f"- `{e.source_type}.{e.member_name}` -> **{e.candidate_edge_type.value}** -> `{target}` "
            f"(`{e.edge_confidence.value}`; return type `{e.return_type}`)"
        )

    lines = ["# Revit Semantic Schema Mapper - Run Summary", ""]
    lines.append("## 1. Crawl scope")
    lines.append(f"- Revit version: {revit_version}")
    if fallback_reason:
        lines.append(f"- Fallback reason: {fallback_reason}")
    lines.append("- Namespace: Autodesk.Revit.DB")
    lines.append("")
    lines.append("## 2. Pages discovered")
    lines.append(f"- {len(raw_index_entries)}")
    lines.append("")
    lines.append("## 3. Pages parsed")
    lines.append(f"- {len(pages)}")
    lines.append("")
    lines.append("## 4. Node candidates")
    lines.append(f"- {len(node_candidates)}")
    lines.append("")
    lines.append("## 5. Property relationship candidates")
    lines.append(f"- {len(properties)}")
    lines.append("")
    lines.append("## 6. Method relationship candidates")
    lines.append(f"- {len(methods)}")
    lines.append("")
    lines.append("## 7. Enum members extracted")
    lines.append(f"- {enum_member_count}")
    lines.append("")
    lines.append("## 8. Top 25 highest-confidence candidate edges")
    lines.extend([_fmt_edge(e) for e in top_confident] or ["- (none)"])
    lines.append("")
    lines.append("## 9. Top 25 uncertain candidates needing review")
    lines.extend([_fmt_edge(e) for e in top_uncertain] or ["- (none)"])
    lines.append("")
    lines.append("## 10. Unknown-reference target type breakdown")
    lines.append(
        "Both UNKNOWN_* edge types mean 'definitely a reference, but no keyword/docs evidence "
        "identifies which specific relationship' -- per docs/edge_taxonomy_v0.md, that's the "
        "conservative, honest label, not a bug to fix by guessing a specific type. This "
        "breakdown exists so a concentration in a few target types (e.g. a generic identifier "
        "type referenced from all over the API) is visible here instead of only discoverable by "
        "querying candidate_edges.json directly."
    )
    lines.extend(_unknown_target_type_breakdown(edge_candidates))
    lines.append("")
    lines.append("## 11. Limitations")
    lines.extend(f"- {item}" for item in limitations)
    lines.append("")
    lines.append("## 12. Recommended next steps")
    lines.extend(f"- {item}" for item in next_steps)
    lines.append("")
    lines.extend(_graph_section(graph_result, section_number=13))

    (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def write_validation_summary(
    output_dir: Path,
    *,
    revit_version: str,
    target_full_type_names: list,
    target_report: list,
    known_edge_report: list,
    raw_index_entries: list[dict],
    pages: list[ApiPage],
    node_candidates: list[NodeCandidate],
    edge_candidates: list[EdgeCandidate],
    failed_urls: list[str],
    discovery_notes: list[str],
    graph_result: GraphBuildResult | None = None,
) -> None:
    """Write ``validation_summary.md`` for a targeted validation crawl
    (``pipeline.run_targeted_pipeline``). Unlike ``write_summary``, this
    explicitly separates three distinct kinds of success/failure that are
    easy to conflate in a single page count: whether the crawler *found and
    fetched* a page (coverage), whether the parser *extracted structured
    data* from it (parser success), and how confident the classifier is in
    any relationship it produced from that data (classifier confidence).
    """
    properties = [e for e in edge_candidates if e.member_kind is MemberKind.PROPERTY]
    methods = [e for e in edge_candidates if e.member_kind is MemberKind.METHOD]

    classes_found_in_index = sum(1 for t in target_report if t.found_in_namespace_json)
    classes_parsed = sum(1 for t in target_report if t.class_page_parsed)
    total_targets = len(target_report)

    known_edges_found = sum(1 for k in known_edge_report if k.member_found)
    known_edges_with_edge = sum(1 for k in known_edge_report if k.edge_produced)

    confidence_counts: dict[str, int] = {}
    for e in edge_candidates:
        confidence_counts[e.edge_confidence.value] = confidence_counts.get(e.edge_confidence.value, 0) + 1

    class_role_counts: dict[str, int] = {}
    for n in node_candidates:
        class_role_counts[n.class_role.value] = class_role_counts.get(n.class_role.value, 0) + 1

    lines = ["# Revit Semantic Schema Mapper - Targeted Validation Crawl", ""]

    lines.append("## 1. Scope")
    lines.append(f"- Revit version: {revit_version}")
    lines.append(f"- Target classes: {total_targets}")
    lines.append(f"- Known-edge checks: {len(known_edge_report)}")
    lines.append("")

    lines.append("## 2. Crawler coverage (were pages found and fetched?)")
    lines.append(f"- {classes_found_in_index}/{total_targets} target classes found in the namespace_json tree")
    lines.append(f"- {len(raw_index_entries)} total page URLs discovered (class + Members + Methods/Properties + individual member pages)")
    lines.append(f"- {len(failed_urls)} page(s) failed to fetch or parse")
    if discovery_notes:
        lines.append("- Discovery notes:")
        lines.extend(f"  - {note}" for note in discovery_notes)
    lines.append("")

    lines.append("## 3. Parser success (did we extract structured data?)")
    lines.append(f"- {classes_parsed}/{total_targets} target classes successfully parsed into a node candidate")
    lines.append(f"- {len(pages)} total pages parsed")
    lines.append(f"- {known_edges_found}/{len(known_edge_report)} known-edge members found on a parsed page")
    pages_with_notes = [p for p in pages if p.parser_notes]
    lines.append(f"- {len(pages_with_notes)}/{len(pages)} parsed pages have at least one parser_note (a selector assumption that didn't fully hold)")
    lines.append("")

    lines.append("## 4. Classifier confidence (what did classify.py conclude, and how sure is it?)")
    lines.append(f"- {len(node_candidates)} node candidates ({dict(sorted(class_role_counts.items()))})")
    lines.append(f"- {len(properties)} property-based edge candidates, {len(methods)} method-based edge candidates")
    lines.append(f"- {known_edges_with_edge}/{len(known_edge_report)} known-edge checks produced a relationship edge")
    if confidence_counts:
        lines.append("- Edge confidence breakdown:")
        lines.extend(f"  - {label}: {count}" for label, count in sorted(confidence_counts.items(), key=lambda kv: _CONFIDENCE_RANK.get(kv[0], 99)))
    lines.append("")

    lines.append("## 5. Target class report")
    lines.append("")
    lines.append("| Target | Found in index | Class page parsed | Member pages parsed | Reason (if incomplete) |")
    lines.append("|---|---|---|---|---|")
    for t in target_report:
        lines.append(
            f"| `{t.full_type_name}` | {'yes' if t.found_in_namespace_json else '**NOT CRAWLED**'} | "
            f"{'yes' if t.class_page_parsed else 'no'} | {t.member_pages_parsed} | {t.reason or '-'} |"
        )
    lines.append("")

    lines.append("## 6. Known-edge test report")
    lines.append("")
    lines.append("| Type.Member | Member found | Edge produced | Edge type (confidence) | Note |")
    lines.append("|---|---|---|---|---|")
    for k in known_edge_report:
        edge_col = f"{k.edge_type} (`{k.edge_confidence}`)" if k.edge_type else "-"
        lines.append(
            f"| `{k.declaring_type}.{k.member_name}` | {'yes' if k.member_found else '**NOT CRAWLED**'} | "
            f"{'yes' if k.edge_produced else 'no'} | {edge_col} | {k.note} |"
        )
    lines.append("")

    lines.append("## 7. Definition-of-done checklist")
    lines.append(
        f"- [{'x' if classes_found_in_index >= 10 else ' '}] At least 10/{total_targets} target classes found "
        f"({classes_found_in_index} found in index, {classes_parsed} actually parsed)"
    )
    lines.append(f"- [{'x' if len(known_edge_report) >= 5 else ' '}] At least 5 known-edge checks reported ({len(known_edge_report)} evaluated)")
    lines.append(f"- [{'x' if properties and methods else ' '}] candidate_edges includes both property-based ({len(properties)}) and method-based ({len(methods)}) relationships")
    lines.append("- [x] This summary distinguishes crawler coverage (section 2), parser success (section 3), and classifier confidence (section 4)")
    lines.append("")

    lines.append("## 8. Limitations")
    lines.append(
        "- This report only reflects general Revit API knowledge where it is directly backed by a "
        "crawled/parsed page in this run; any target marked 'NOT CRAWLED' above has no verified data "
        "in this run, and nothing about it should be treated as fact."
    )
    lines.append(
        "- Edge classification is a static, docs-only heuristic (see classify.py); no candidate edge "
        "has been validated against a live Revit document."
    )
    lines.append("")
    lines.extend(_graph_section(graph_result, section_number=9))

    (output_dir / "validation_summary.md").write_text("\n".join(lines), encoding="utf-8")
