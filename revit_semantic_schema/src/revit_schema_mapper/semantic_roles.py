"""A second, coarser lens on the core subgraph: domain-recognizable
*semantic roles* (``View``, ``Family``, ``Room / Space``, ``Failures``, ...)
instead of ``class_role``'s more structural buckets (``element_subtype``,
``utility_class``), aggregated into role -> relationship -> role flows plus
a role x relationship-type heatmap.

This answers a different question than ``graph.py``/``community.py``: not
"what does the raw 330-node type graph look like" (which needs domain
familiarity to read anything into the clustering), but "how do the
*categories* of the Revit API relate to each other" -- closer to how a
human would sketch the domain model by hand. Every aggregated flow keeps a
``drilldown`` back to the real underlying edges (member name, confidence,
source doc link), so this stays consistent with the rest of the project's
"candidate schema, always traceable to evidence" premise.

``classify_api_role`` is a heuristic, and a coarser one than ``class_role``
-- e.g. ``FamilyInstance`` (a placed instance) and ``Family``/``FamilySymbol``
(family *definitions*) both land in the "Family" role bucket, because the
check is just a name match. That's an intentional simplification for
readability, not a claim that those are the same concept -- as always,
treat this as a candidate lens, not verified fact.
"""

from __future__ import annotations

import html
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from .models import GraphEdge, GraphNode

ROLE_ORDER: list[str] = [
    "Document",
    "Element",
    "ElementType",
    "View",
    "ViewSheet",
    "Family",
    "FamilySymbol",
    "Parameter",
    "Category",
    "Material",
    "Level",
    "Phase",
    "Workset",
    "Group / Assembly",
    "Room / Space",
    "Annotation / Tag",
    "Geometry",
    "Failures",
    "Options / Settings",
    "Utility / Collector",
    "Other",
]

# Spread across the hue wheel rather than clustered (several of these are
# thematically "the model backbone" and an earlier pass picked near-identical
# blues for all of them, e.g. Level/Material/Workset/Phase) -- every role box
# is always direct-labeled with its name (see render_html), so color here is
# a supplementary/orienting channel, not the sole identity carrier the way
# dataviz's validated 8-slot categorical set is for a bounded dimension; 21
# roles is inherently beyond what that set can cover distinctly.
ROLE_COLORS: dict[str, str] = {
    "Document": "#e0507f",
    "Element": "#ff6f61",
    "ElementType": "#ffb000",
    "View": "#22a78b",
    "ViewSheet": "#0fc4c4",
    "Family": "#8c73df",
    "FamilySymbol": "#b565d6",
    "Parameter": "#e0a11a",
    "Category": "#c9c02a",
    "Material": "#2e87e6",
    "Level": "#4fd1c5",
    "Phase": "#6a5acd",
    "Workset": "#3577c8",
    "Group / Assembly": "#69b85a",
    "Room / Space": "#3fae5c",
    "Annotation / Tag": "#a783ff",
    "Geometry": "#5fa8d3",
    "Failures": "#ff5f7e",
    "Options / Settings": "#c9a0ff",
    "Utility / Collector": "#7c8798",
    "Other": "#4d5a6e",
}

RELATION_FAMILY: dict[str, str] = {
    "HAS_PARAMETER": "Data / Definition",
    "HAS_CATEGORY": "Data / Definition",
    "USES_MATERIAL": "Physical / Material",
    "USES_FILL_PATTERN": "Physical / Material",
    "USES_LINE_PATTERN": "Physical / Material",
    "ASSIGNED_TO_LEVEL": "Spatial / Level",
    "ASSIGNED_TO_PHASE": "Lifecycle / Phase",
    "ASSIGNED_TO_DESIGN_OPTION": "Design Options",
    "HOSTED_BY": "Model Structure",
    "DEPENDS_ON": "Model Structure",
    "TYPE_OF": "Model Structure",
    "INSTANCE_OF": "Model Structure",
    "BELONGS_TO_FAMILY": "Model Structure",
    "PLACED_ON_SHEET": "Documentation",
    "TAGS_ELEMENT": "Annotation",
    "REFERENCES": "Referencing",
    "OWNED_BY_WORKSET": "Collaboration",
    "MEMBER_OF_GROUP": "Grouping",
    "MEMBER_OF_ASSEMBLY": "Grouping",
    "CONTROLLED_BY_TEMPLATE": "View Control",
    "RETURNS_ELEMENT_IDS": "Referencing",
}

FAMILY_COLORS: dict[str, str] = {
    "Data / Definition": "#f05d9b",
    "Physical / Material": "#4aa3ff",
    "Spatial / Level": "#4cc7ff",
    "Lifecycle / Phase": "#3f8cff",
    "Model Structure": "#28c2a0",
    "Documentation": "#27c7d9",
    "Annotation": "#a783ff",
    "Referencing": "#f0ae24",
    "Collaboration": "#72c95f",
    "Grouping": "#76d06b",
    "View Control": "#7f8cff",
    "Design Options": "#b09cff",
    "Other": "#7c8798",
}


def _short_name(node_id: str) -> str:
    return node_id.rsplit(".", 1)[-1]


def classify_api_role(node: GraphNode) -> str:
    """Heuristic semantic role bucket -- see the module docstring for the
    tradeoffs this makes (coarser and occasionally ambiguous, by design, in
    exchange for buckets a Revit user actually recognizes).
    """
    name = node.short_name or _short_name(node.id)
    base = node.base_type or ""
    class_role = node.class_role or ""

    if name == "Document" or name.endswith("Document"):
        return "Document"
    if name == "ViewSheet":
        return "ViewSheet"
    if name == "View" or name.startswith("View") or base.startswith("View"):
        return "View"
    if "FamilySymbol" in name or (name.endswith("Type") and "Family" in base):
        return "FamilySymbol"
    if name == "Family" or name.endswith("Family") or "Family" in name:
        return "Family"
    if "Parameter" in name or name in {"Definition", "ExternalDefinition", "InternalDefinition"}:
        return "Parameter"
    if "Category" in name or name in {"Categories", "BuiltInCategory"}:
        return "Category"
    if "Material" in name:
        return "Material"
    if "Level" in name:
        return "Level"
    if "Phase" in name:
        return "Phase"
    if "Workset" in name:
        return "Workset"
    if "Assembly" in name or "Group" in name:
        return "Group / Assembly"
    if name in {"Room", "Space", "Area"} or "Room" in name or "Space" in name or name.endswith("Area"):
        return "Room / Space"
    if "Tag" in name or "Annotation" in name or name in {"IndependentTag", "TextNote", "Dimension"}:
        return "Annotation / Tag"
    if name in {"XYZ", "UV", "Curve", "Line", "Arc", "Solid", "Face", "Edge", "Mesh", "Plane", "Transform", "BoundingBoxXYZ"} or "Geometry" in name:
        return "Geometry"
    if "Failure" in name or "Failures" in name:
        return "Failures"

    if class_role == "element_subtype":
        return "Element"
    if class_role == "element_type":
        return "ElementType"
    if class_role == "options_class":
        return "Options / Settings"
    if class_role == "utility_class":
        return "Utility / Collector"

    return "Other"


def relation_family(edge_type: str) -> str:
    return RELATION_FAMILY.get(edge_type, "Other")


@dataclass
class RoleSummary:
    role: str
    source_weight: int
    target_weight: int
    weight: int
    color: str


@dataclass
class RelationshipSummary:
    relationship: str
    weight: int
    family: str
    color: str


@dataclass
class Triple:
    source_role: str
    relationship: str
    target_role: str
    weight: int


@dataclass
class HeatmapCell:
    source_role: str
    relationship: str
    weight: int


@dataclass
class EdgeExample:
    source: str
    source_short: str
    source_role: str
    relationship: str
    target: str
    target_short: str
    target_role: str
    member_name: str
    member_kind: str
    confidence: str
    confidence_tier: str
    target_resolution: str
    source_url: str
    evidence: list[str] = field(default_factory=list)


@dataclass
class SemanticRelationshipMap:
    roles: list[RoleSummary]
    relationships: list[RelationshipSummary]
    sankey: list[Triple]
    heatmap: list[HeatmapCell]
    drilldown: dict[str, list[EdgeExample]]
    role_order: list[str]
    relationship_order: list[str]
    relationship_counts_total: dict[str, int]
    included_edge_count: int
    total_edge_count: int


def _ordered_roles(roles: set[str]) -> list[str]:
    return [r for r in ROLE_ORDER if r in roles] + sorted(roles - set(ROLE_ORDER))


def aggregate_graph(
    nodes: list[GraphNode],
    edges: list[GraphEdge],
    *,
    top_relationships: int | None = 12,
    min_weight: int = 1,
    max_examples: int = 80,
) -> SemanticRelationshipMap:
    """Aggregate the core subgraph into role -> relationship -> role
    triples plus a role x relationship heatmap.

    ``top_relationships`` caps how many distinct relationship *types* are
    kept (by edge count, most common first) -- a full run's ~20 relationship
    types would make the diagram unreadable. The rest aren't hidden
    silently: ``relationship_counts_total`` and the returned
    ``included_edge_count``/``total_edge_count`` let a caller (or the
    rendered page's footer) disclose exactly how much was left out.
    """
    nodes_by_id = {n.id: n for n in nodes}
    role_by_id = {n.id: classify_api_role(n) for n in nodes}

    usable_edges = [e for e in edges if e.source in nodes_by_id and e.target is not None and e.target in nodes_by_id]
    rel_counts = Counter(e.edge_type.value for e in usable_edges)
    kept_relationships = (
        {r for r, _ in rel_counts.most_common(top_relationships)} if top_relationships else set(rel_counts)
    )

    triple_counts: Counter[tuple[str, str, str]] = Counter()
    heatmap_counts: Counter[tuple[str, str]] = Counter()
    source_role_counts: Counter[str] = Counter()
    target_role_counts: Counter[str] = Counter()
    relationship_counts: Counter[str] = Counter()
    drilldown: dict[str, list[EdgeExample]] = defaultdict(list)
    included_edge_count = 0

    for e in usable_edges:
        rel = e.edge_type.value
        if rel not in kept_relationships:
            continue
        s_role = role_by_id[e.source]
        t_role = role_by_id[e.target]

        triple_counts[(s_role, rel, t_role)] += 1
        heatmap_counts[(s_role, rel)] += 1
        source_role_counts[s_role] += 1
        target_role_counts[t_role] += 1
        relationship_counts[rel] += 1
        included_edge_count += 1

        key = f"{s_role}|{rel}|{t_role}"
        if len(drilldown[key]) < max_examples:
            s_node, t_node = nodes_by_id[e.source], nodes_by_id[e.target]
            drilldown[key].append(
                EdgeExample(
                    source=e.source,
                    source_short=s_node.short_name,
                    source_role=s_role,
                    relationship=rel,
                    target=e.target,
                    target_short=t_node.short_name,
                    target_role=t_role,
                    member_name=e.member_name,
                    member_kind=e.member_kind.value,
                    confidence=e.confidence.value,
                    confidence_tier=e.confidence_tier.value,
                    target_resolution=e.target_resolution.value,
                    source_url=e.source_url or s_node.source_url,
                    evidence=list(e.evidence),
                )
            )

    triples = [
        Triple(source_role=s, relationship=r, target_role=t, weight=w)
        for (s, r, t), w in triple_counts.items()
        if w >= min_weight
    ]
    triples.sort(key=lambda t: (-t.weight, t.source_role, t.relationship, t.target_role))

    roles = _ordered_roles(set(source_role_counts) | set(target_role_counts))
    relationships = [r for r, _ in relationship_counts.most_common()]

    role_summaries = [
        RoleSummary(
            role=role,
            source_weight=source_role_counts.get(role, 0),
            target_weight=target_role_counts.get(role, 0),
            weight=source_role_counts.get(role, 0) + target_role_counts.get(role, 0),
            color=ROLE_COLORS.get(role, ROLE_COLORS["Other"]),
        )
        for role in roles
    ]
    relationship_summaries = [
        RelationshipSummary(
            relationship=rel,
            weight=relationship_counts[rel],
            family=relation_family(rel),
            color=FAMILY_COLORS.get(relation_family(rel), FAMILY_COLORS["Other"]),
        )
        for rel in relationships
    ]
    heatmap = [HeatmapCell(source_role=s, relationship=r, weight=w) for (s, r), w in heatmap_counts.items()]
    heatmap.sort(key=lambda c: (roles.index(c.source_role), relationships.index(c.relationship)))

    return SemanticRelationshipMap(
        roles=role_summaries,
        relationships=relationship_summaries,
        sankey=triples,
        heatmap=heatmap,
        drilldown=dict(drilldown),
        role_order=roles,
        relationship_order=relationships,
        relationship_counts_total=dict(rel_counts),
        included_edge_count=included_edge_count,
        total_edge_count=len(usable_edges),
    )


def _esc(x) -> str:
    return html.escape(str(x), quote=True)


def _fmt(n: int | float) -> str:
    return f"{int(n):,}"


def _bezier_path(x1: float, y1: float, x2: float, y2: float) -> str:
    dx = abs(x2 - x1) * 0.48
    return f"M {x1:.1f},{y1:.1f} C {x1+dx:.1f},{y1:.1f} {x2-dx:.1f},{y2:.1f} {x2:.1f},{y2:.1f}"


def _opacity_for_weight(w: int, max_w: int) -> float:
    return 0.5 if max_w <= 0 else 0.18 + 0.58 * math.sqrt(w / max_w)


def _width_for_weight(w: int, max_w: int) -> float:
    return 1.0 if max_w <= 0 else 1.0 + 17.0 * math.sqrt(w / max_w)


def render_html(data: SemanticRelationshipMap, *, revit_version: str) -> str:
    """Render ``data`` as a self-contained SVG dashboard: role -> relationship
    -> role Sankey bands, a role x relationship heatmap, and click-to-drilldown
    back to the real underlying edges. No CDN dependency -- plain SVG/CSS/JS.
    """
    roles = data.role_order
    rels = data.relationship_order
    role_info = {r.role: r for r in data.roles}
    rel_info = {r.relationship: r for r in data.relationships}
    triples = data.sankey
    heatmap = data.heatmap

    # Height is derived from the actual role/relationship/heatmap row counts,
    # not a constant -- a fixed viewBox clipped role rows past the 13th and
    # heatmap rows past the 18th on a real crawl (up to 21 roles), silently
    # hiding part of the aggregate rather than just looking cramped.
    W = 1680
    left_x, rel_x, right_x = 85, 680, 1165
    row_h = 43
    top_y = 150
    role_box_w = 235
    rel_box_w = 245

    role_y = {r: top_y + i * row_h for i, r in enumerate(roles)}
    rel_y = {r: top_y + i * row_h for i, r in enumerate(rels)}

    families: list[str] = []
    for rel in rels:
        fam = relation_family(rel)
        if fam not in families:
            families.append(fam)
    legend_families = families[:8]

    sankey_bottom = top_y + max(len(roles), len(rels), 1) * row_h + 35
    content_y = sankey_bottom + 90
    cell_h = 18
    heatmap_bottom = content_y + max(len(roles), 1) * cell_h
    legend_rows = math.ceil(len(legend_families) / 2) if legend_families else 1
    legend_bottom = content_y + 60 + legend_rows * 28
    H = max(940, heatmap_bottom + 70, legend_bottom + 40)

    max_w = max([t.weight for t in triples] or [1])

    flow_svg = []
    for t in sorted(triples, key=lambda t: t.weight):
        if t.source_role not in role_y or t.relationship not in rel_y or t.target_role not in role_y:
            continue
        color = rel_info.get(t.relationship, RelationshipSummary("", 0, "Other", FAMILY_COLORS["Other"])).color
        key = f"{t.source_role}|{t.relationship}|{t.target_role}"
        sw = _width_for_weight(t.weight, max_w)
        op = _opacity_for_weight(t.weight, max_w)
        y_s = role_y[t.source_role] + 18
        y_r = rel_y[t.relationship] + 18
        y_t = role_y[t.target_role] + 18
        flow_svg.append(
            f'<path class="flow" data-key="{_esc(key)}" data-title="{_esc(t.source_role)} → {_esc(t.relationship)} → {_esc(t.target_role)} ({t.weight})" '
            f'd="{_bezier_path(left_x + role_box_w, y_s, rel_x, y_r)}" '
            f'stroke="{color}" stroke-width="{sw:.2f}" stroke-opacity="{op:.3f}" />'
        )
        flow_svg.append(
            f'<path class="flow" data-key="{_esc(key)}" data-title="{_esc(t.source_role)} → {_esc(t.relationship)} → {_esc(t.target_role)} ({t.weight})" '
            f'd="{_bezier_path(rel_x + rel_box_w, y_r, right_x, y_t)}" '
            f'stroke="{color}" stroke-width="{sw:.2f}" stroke-opacity="{op:.3f}" />'
        )

    role_svg = []
    for r in roles:
        info = role_info[r]
        y = role_y[r]
        color = info.color
        role_svg.append(
            f'<g class="role role-source" data-role="{_esc(r)}">'
            f'<rect x="{left_x}" y="{y}" width="{role_box_w}" height="35" rx="7" fill="#101b2e" stroke="#2a3a56" />'
            f'<rect x="{left_x}" y="{y}" width="42" height="35" rx="7" fill="{color}" opacity="0.92" />'
            f'<text x="{left_x+54}" y="{y+23}" class="label">{_esc(r)}</text>'
            f'<text x="{left_x+role_box_w-10}" y="{y+23}" text-anchor="end" class="muted">{_fmt(info.source_weight)}</text>'
            f"</g>"
        )
        role_svg.append(
            f'<g class="role role-target" data-role="{_esc(r)}">'
            f'<rect x="{right_x}" y="{y}" width="{role_box_w}" height="35" rx="7" fill="#101b2e" stroke="#2a3a56" />'
            f'<rect x="{right_x}" y="{y}" width="42" height="35" rx="7" fill="{color}" opacity="0.92" />'
            f'<text x="{right_x+54}" y="{y+23}" class="label">{_esc(r)}</text>'
            f'<text x="{right_x+role_box_w-10}" y="{y+23}" text-anchor="end" class="muted">{_fmt(info.target_weight)}</text>'
            f"</g>"
        )

    rel_svg = []
    for r in rels:
        info = rel_info[r]
        y = rel_y[r]
        color = info.color
        rel_svg.append(
            f'<g class="relationship" data-rel="{_esc(r)}">'
            f'<rect x="{rel_x}" y="{y}" width="{rel_box_w}" height="35" rx="7" fill="#101b2e" stroke="#2a3a56" />'
            f'<rect x="{rel_x}" y="{y}" width="6" height="35" rx="3" fill="{color}" />'
            f'<text x="{rel_x+20}" y="{y+23}" class="label small">{_esc(r)}</text>'
            f'<text x="{rel_x+rel_box_w-10}" y="{y+23}" text-anchor="end" class="muted">{_fmt(info.weight)}</text>'
            f"</g>"
        )

    hm = {(c.source_role, c.relationship): c.weight for c in heatmap}
    hm_max = max(hm.values() or [1])
    hm_x, hm_y = 700, content_y
    cell_w = min(62, (W - hm_x - 70) / max(1, len(rels)))
    row_label_w = 92
    heat_svg = [
        f'<text x="{hm_x}" y="{hm_y-48}" class="section-title">RELATIONSHIP MATRIX HEATMAP</text>',
        f'<text x="{hm_x}" y="{hm_y-27}" class="muted">Source role × relationship type; brighter cells mean more candidate edges.</text>',
    ]
    for j, rel in enumerate(rels):
        x = hm_x + row_label_w + j * cell_w + cell_w * 0.5
        short = rel.replace("ASSIGNED_TO_", "→").replace("MEMBER_OF_", "MEMBER_").replace("CONTROLLED_BY_", "CTRL_")
        if len(short) > 12:
            short = short[:11] + "…"
        heat_svg.append(
            f'<text x="{x:.1f}" y="{hm_y-8}" text-anchor="middle" class="hm-col" transform="rotate(-35 {x:.1f},{hm_y-8})">{_esc(short)}</text>'
        )
    for i, role in enumerate(roles):
        y = hm_y + i * cell_h
        heat_svg.append(f'<text x="{hm_x+row_label_w-8}" y="{y+13}" text-anchor="end" class="hm-row">{_esc(role)}</text>')
        for j, rel in enumerate(rels):
            x = hm_x + row_label_w + j * cell_w
            w = hm.get((role, rel), 0)
            intensity = 0 if hm_max == 0 else math.sqrt(w / hm_max)
            alpha = 0.12 + 0.86 * intensity if w else 0.10
            fill = "#f05d9b" if w else "#1a2440"
            key_prefix = f"{role}|{rel}|"
            heat_svg.append(
                f'<rect class="heat" data-role="{_esc(role)}" data-rel="{_esc(rel)}" data-key-prefix="{_esc(key_prefix)}" '
                f'x="{x:.1f}" y="{y:.1f}" width="{cell_w-2:.1f}" height="{cell_h-2}" rx="2" '
                f'fill="{fill}" opacity="{alpha:.3f}"><title>{_esc(role)} × {_esc(rel)}: {w}</title></rect>'
            )

    legend_svg = []
    lx, ly = 85, content_y
    legend_svg.append(f'<rect x="{lx}" y="{ly}" width="555" height="{60 + legend_rows * 28 + 20}" rx="12" class="panel" />')
    legend_svg.append(f'<text x="{lx+20}" y="{ly+30}" class="section-title">LEGEND</text>')
    for i, fam in enumerate(legend_families):
        x = lx + 22 + (i % 2) * 260
        y = ly + 60 + (i // 2) * 28
        legend_svg.append(
            f'<line x1="{x}" y1="{y}" x2="{x+42}" y2="{y}" stroke="{FAMILY_COLORS.get(fam, "#7c8798")}" stroke-width="6" stroke-linecap="round" />'
        )
        legend_svg.append(f'<text x="{x+58}" y="{y+5}" class="muted">{_esc(fam)}</text>')

    drilldown_json = {
        key: [
            {
                "source": ex.source,
                "source_short": ex.source_short,
                "relationship": ex.relationship,
                "target_short": ex.target_short,
                "member_name": ex.member_name,
                "member_kind": ex.member_kind,
                "confidence_tier": ex.confidence_tier,
                "source_url": ex.source_url,
            }
            for ex in examples
        ]
        for key, examples in data.drilldown.items()
    }
    json_data = _json_dumps(drilldown_json)

    total_rel_types = len(data.relationship_counts_total)
    displayed_rel_types = len(rels)
    title = f"Revit {revit_version} API Relationship Map"

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)}</title>
<style>
  :root {{
    --bg: #07101f;
    --panel: #0c1729;
    --text: #f4f7fb;
    --muted: #93a4bd;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--text); font-family: -apple-system, "Segoe UI", ui-sans-serif, system-ui, sans-serif; }}
  .wrap {{ min-width: 1200px; overflow-x: auto; }}
  svg {{ width: 100%; height: auto; display: block; background: radial-gradient(circle at 40% 20%, #10233a 0, #07101f 45%, #050b16 100%); }}
  .title {{ font-size: 40px; font-weight: 800; fill: #f8fbff; letter-spacing: -1px; }}
  .subtitle {{ font-size: 18px; fill: #b6aaff; }}
  .section-title {{ fill: #dfe8f7; font-size: 13px; font-weight: 800; letter-spacing: .8px; }}
  .label {{ fill: #f4f7fb; font-size: 15px; font-weight: 650; }}
  .label.small {{ font-size: 13px; }}
  .muted {{ fill: var(--muted); font-size: 13px; }}
  .hm-row {{ fill: #d4deee; font-size: 10px; }}
  .hm-col {{ fill: #9fb0ca; font-size: 9px; }}
  .panel {{ fill: rgba(12,23,41,.88); stroke: #2b405f; }}
  .flow {{ fill: none; stroke-linecap: round; cursor: pointer; mix-blend-mode: screen; }}
  .flow:hover, .flow.active {{ stroke-opacity: .95 !important; }}
  .role, .relationship, .heat {{ cursor: pointer; }}
  .role:hover rect:first-child, .relationship:hover rect:first-child {{ stroke: #7f9ac3; }}
  .heat:hover {{ stroke: #f8fbff; stroke-width: 1.5px; }}
  .kpi-number {{ fill: #f05d9b; font-size: 27px; font-weight: 800; }}
  .kpi-label {{ fill: #d5def0; font-size: 12px; }}
  aside {{ position: fixed; right: 18px; bottom: 18px; width: 470px; max-height: 64vh; overflow: auto; background: rgba(8,16,30,.96); border: 1px solid #314765; border-radius: 14px; padding: 16px 18px; box-shadow: 0 18px 55px rgba(0,0,0,.38); display: none; }}
  aside.show {{ display: block; }}
  aside h2 {{ margin: 0 0 4px; font-size: 18px; }}
  aside .sub {{ color: var(--muted); font-size: 12px; margin-bottom: 12px; }}
  aside table {{ width: 100%; border-collapse: collapse; font-size: 12px; }}
  aside td {{ border-top: 1px solid #1e2f49; padding: 7px 4px; vertical-align: top; }}
  aside a {{ color: #7ed6ff; text-decoration: none; }}
  aside code {{ color: #ffd27a; }}
  .close {{ float: right; cursor: pointer; color: var(--muted); font-size: 20px; }}
</style>
</head>
<body>
<div class="wrap">
<svg viewBox="0 0 {W} {H}" role="img" aria-label="Semantic Revit API relationship map">
  <text x="32" y="58" class="title">{_esc(title)}</text>
  <text x="32" y="87" class="subtitle">semantic relationship lens — role → relationship → role</text>

  <g>
    <rect x="1060" y="26" width="170" height="72" rx="12" class="panel" />
    <text x="1120" y="58" class="kpi-number">{_fmt(len(roles))}</text><text x="1120" y="80" class="kpi-label">Semantic roles</text>
    <rect x="1250" y="26" width="170" height="72" rx="12" class="panel" />
    <text x="1310" y="58" class="kpi-number" fill="#27c2a0">{_fmt(displayed_rel_types)}</text><text x="1310" y="80" class="kpi-label">Relationship types</text>
    <rect x="1440" y="26" width="190" height="72" rx="12" class="panel" />
    <text x="1502" y="58" class="kpi-number" fill="#a783ff">{_fmt(data.included_edge_count)}</text><text x="1502" y="80" class="kpi-label">Included edges</text>
  </g>

  <text x="{left_x}" y="128" class="section-title">SOURCE API ROLES</text>
  <text x="{rel_x}" y="128" class="section-title">RELATIONSHIP TYPES</text>
  <text x="{right_x}" y="128" class="section-title">TARGET API ROLES</text>

  <g id="flows">{''.join(flow_svg)}</g>
  <g id="roles">{''.join(role_svg)}</g>
  <g id="relationships">{''.join(rel_svg)}</g>

  <g id="legend">{''.join(legend_svg)}</g>
  <g id="heatmap">{''.join(heat_svg)}</g>

  <text x="32" y="{H-24}" class="muted">Candidate semantic lens over graph_core.json (confidence_tier: core only) -- not verified against live Revit runtime behavior. Showing {displayed_rel_types} of {total_rel_types} relationship types ({_fmt(data.included_edge_count)} of {_fmt(data.total_edge_count)} core edges).</text>
</svg>
</div>

<aside id="detail"><span class="close" onclick="hideDetail()">×</span><h2 id="detail-title"></h2><div id="detail-sub" class="sub"></div><div id="detail-body"></div></aside>
<script id="semantic-data" type="application/json">{json_data}</script>
<script>
const DATA = JSON.parse(document.getElementById('semantic-data').textContent);
const detail = document.getElementById('detail');
const titleEl = document.getElementById('detail-title');
const subEl = document.getElementById('detail-sub');
const bodyEl = document.getElementById('detail-body');

function hideDetail() {{ detail.classList.remove('show'); }}
function escHtml(s) {{ return String(s ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}}[ch])); }}
function recordsForKey(key) {{ return DATA[key] || []; }}
function recordsForPrefix(prefix) {{
  const out = [];
  for (const [k, rows] of Object.entries(DATA)) {{ if (k.startsWith(prefix)) out.push(...rows); }}
  return out;
}}
function showRecords(label, rows) {{
  titleEl.textContent = label;
  subEl.textContent = `${{rows.length}} stored examples shown; counts may be higher in the aggregate.`;
  const sample = rows.slice(0, 40);
  bodyEl.innerHTML = '<table>' + sample.map(r => `
    <tr>
      <td><code>${{escHtml(r.source_short)}}.${{escHtml(r.member_name || '(member)')}}</code><br/>
      <span class="sub">${{escHtml(r.relationship)}} → ${{escHtml(r.target_short)}} · ${{escHtml(r.member_kind)}} · ${{escHtml(r.confidence_tier)}}</span></td>
      <td style="width:54px">${{r.source_url ? `<a href="${{escHtml(r.source_url)}}" target="_blank" rel="noopener">docs</a>` : ''}}</td>
    </tr>`).join('') + '</table>';
  detail.classList.add('show');
}}

document.querySelectorAll('.flow').forEach(el => {{
  el.addEventListener('click', () => {{
    document.querySelectorAll('.flow').forEach(f => f.classList.remove('active'));
    el.classList.add('active');
    const key = el.dataset.key;
    showRecords(key.replaceAll('|', ' → '), recordsForKey(key));
  }});
}});

document.querySelectorAll('.heat').forEach(el => {{
  el.addEventListener('click', () => {{
    const prefix = el.dataset.keyPrefix;
    showRecords(`${{el.dataset.role}} × ${{el.dataset.rel}}`, recordsForPrefix(prefix));
  }});
}});

document.querySelectorAll('.relationship').forEach(el => {{
  el.addEventListener('click', () => {{
    const rel = el.dataset.rel;
    const rows = [];
    for (const [k, recs] of Object.entries(DATA)) {{ if (k.includes(`|${{rel}}|`)) rows.push(...recs); }}
    showRecords(rel, rows);
  }});
}});
</script>
</body>
</html>
"""


def _json_dumps(obj) -> str:
    # Defensive: a literal "</script" substring anywhere in this payload
    # (e.g. inside a source_url) would close the <script> tag early as far
    # as the HTML parser is concerned, regardless of JS/JSON string quoting.
    return json.dumps(obj, separators=(",", ":")).replace("</", "<\\/")
