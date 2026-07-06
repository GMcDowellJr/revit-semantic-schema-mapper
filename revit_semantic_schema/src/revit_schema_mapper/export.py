"""Write all outputs/revit_2027/* artifacts described in the project brief."""

from __future__ import annotations

import dataclasses
import json
from enum import Enum
from pathlib import Path

from .models import ApiPage, EdgeCandidate, MemberKind, NodeCandidate


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


def write_api_pages(output_dir: Path, pages: list[ApiPage]) -> None:
    _write_json(output_dir / "api_pages.json", pages)


def write_node_candidates(output_dir: Path, nodes: list[NodeCandidate]) -> None:
    _write_json(output_dir / "node_type_candidates.json", nodes)


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


_CONFIDENCE_RANK = {
    "direct_return_type": 0,
    "elementid_with_strong_name": 1,
    "elementid_collection_with_strong_name": 2,
    "docs_semantic_hint": 3,
    "name_only_candidate": 4,
    "unknown_reference": 5,
    "needs_runtime_validation": 6,
}


def _room_investigation_section(pages: list[ApiPage]) -> str:
    room_pages = [p for p in pages if p.type_name == "Room"]
    lines = ["## Room / Room Number / Room Name investigation", ""]
    if not room_pages:
        lines.append(
            "No `Room` type page was present in this run's input set, so this section reports "
            "prior/general knowledge of the Revit API rather than a finding pulled from a "
            "crawled page. **This has not been verified against a live revitapidocs.com page "
            "in this session** (see docs/crawl_notes.md, \"Network access limitation\"). "
            "Treat the following as a hypothesis to confirm on the first real crawl, not a fact:\n"
        )
        lines.append(
            "- `Autodesk.Revit.DB.Architecture.Room` does not appear to declare its own `Name` "
            "CLR property; room name is expected to be exposed via the inherited "
            "`Element.Name` property, which is backed by the `BuiltInParameter.ROOM_NAME` "
            "parameter under the hood."
        )
        lines.append(
            "- `Room.Number` is expected to be a dedicated CLR property (not merely a "
            "`get_Parameter(BuiltInParameter.ROOM_NUMBER)` lookup), directly backed by "
            "`BuiltInParameter.ROOM_NUMBER`."
        )
        lines.append(
            "- If confirmed, this means Name and Number reach the object model through two "
            "different mechanisms (inherited base property vs. a type-specific property), even "
            "though both ultimately resolve to BuiltInParameter-backed values. The schema "
            "should keep `Room.Name`/`ROOM_NAME` and `Room.Number`/`ROOM_NUMBER` as **two "
            "distinct concepts**, not collapsed into one 'room identity' node."
        )
        lines.append(
            "- Action item for the first live crawl: fetch the `Room` class page and its "
            "`Number` property page, and check the `BuiltInParameter` enum catalog for "
            "`ROOM_NAME` and `ROOM_NUMBER` entries, to confirm or correct the above."
        )
        return "\n".join(lines)

    for page in room_pages:
        lines.append(f"Source: {page.source_url}")
        member_names = {m.name for m in page.members}
        lines.append(f"Members seen on Room page: {sorted(member_names) or 'none parsed'}")
        if "Number" in member_names:
            lines.append("- `Number` found as a distinct member on Room (supports keeping Number separate from Name).")
        if "Name" not in member_names:
            lines.append("- `Name` not found directly on Room; likely inherited from `Element.Name` (not re-declared).")
    return "\n".join(lines)


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
) -> None:
    properties = [e for e in edge_candidates if e.member_kind is MemberKind.PROPERTY]
    methods = [e for e in edge_candidates if e.member_kind is MemberKind.METHOD]
    enum_member_count = sum(len(p.enum_members) for p in pages)

    ranked = sorted(edge_candidates, key=lambda e: _CONFIDENCE_RANK.get(e.edge_confidence.value, 99))
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
    lines.append("## 10. Room / Room Number / Room Name findings")
    lines.append(_room_investigation_section(pages))
    lines.append("")
    lines.append("## 11. Limitations")
    lines.extend(f"- {item}" for item in limitations)
    lines.append("")
    lines.append("## 12. Recommended next steps")
    lines.extend(f"- {item}" for item in next_steps)
    lines.append("")

    (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
