"""Frequency (Pareto) breakdown of the generic/unknown edge buckets in an
existing ``candidate_edges.json``, to prioritize where to spend review effort.

Standalone analysis tool, not part of ``run_pipeline`` -- run it against an
already-produced ``candidate_edges.json`` (no crawl, no network):

    python -m revit_schema_mapper.unknown_pareto --candidate-edges outputs/revit_2024/candidate_edges.json

``UNKNOWN_DB_OBJECT_REFERENCE``/``UNKNOWN_ELEMENTID_REFERENCE``/``RETURNS_ELEMENT_IDS``/
``needs_runtime_validation`` are, by the taxonomy's own design
(docs/edge_taxonomy_v0.md), the deliberately-honest fallback for anything a
name-keyword rule or docs hint didn't confidently resolve. That bucket is
usually large and not uniformly distributed: a handful of target types or
member-name patterns typically account for most of it. This script groups
each bucket so the highest-count clusters -- the best return on effort for
either a new ``_NAME_KEYWORD_RULES`` entry (classify.py) or a value/identifier
demotion -- surface first, instead of reviewing thousands of edges in
crawl order.

This tool only reads and reports; it never mutates candidate_edges.json.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Edge types this script treats as "generic/unresolved" -- see
# docs/edge_taxonomy_v0.md for why these three are the deliberate fallback
# rather than a specific relationship.
_UNKNOWN_EDGE_TYPES = {
    "UNKNOWN_DB_OBJECT_REFERENCE",
    "UNKNOWN_ELEMENTID_REFERENCE",
    "RETURNS_ELEMENT_IDS",
}

# ElementId erases the target type entirely, so grouping by candidate_target_type
# is useless for these two -- group by a normalized member name instead.
_GROUP_BY_MEMBER_NAME_EDGE_TYPES = {
    "UNKNOWN_ELEMENTID_REFERENCE",
    "RETURNS_ELEMENT_IDS",
}

_NAME_NORMALIZE_RE = re.compile(r"^(Get|GetAll|Set)")
_TRAILING_ID_RE = re.compile(r"(Id|Ids)$")


def _normalize_member_name(name: str) -> str:
    """Strip Get/Set prefixes and a trailing Id/Ids suffix so
    'GetOwnerViewId' and 'OwnerViewId' cluster together -- the same
    normalization a human reviewer would do by eye when scanning for
    near-misses of existing _NAME_KEYWORD_RULES patterns."""
    stripped = _NAME_NORMALIZE_RE.sub("", name)
    stripped = _TRAILING_ID_RE.sub("", stripped)
    return stripped or name


def _bare_type_name(candidate_target_type: str | None) -> str:
    if not candidate_target_type:
        return "(none)"
    return candidate_target_type.rsplit(".", 1)[-1]


@dataclass
class _Cluster:
    key: str
    count: int = 0
    source_types: set[str] = field(default_factory=set)
    member_names: set[str] = field(default_factory=set)
    revitlookup_referenced_count: int = 0
    dll_member_not_found_count: int = 0
    examples: list[tuple[str, str]] = field(default_factory=list)  # (source_type, member_name)

    def add(self, edge: dict[str, Any]) -> None:
        self.count += 1
        self.source_types.add(edge.get("source_type", ""))
        self.member_names.add(edge.get("member_name", ""))
        if edge.get("revitlookup_referenced") is True:
            self.revitlookup_referenced_count += 1
        if edge.get("dll_verified_status") == "member_not_found":
            self.dll_member_not_found_count += 1
        if len(self.examples) < 5:
            self.examples.append((edge.get("source_type", ""), edge.get("member_name", "")))


def build_report(edges: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(edges)
    top_level = Counter(e.get("candidate_edge_type", "(missing)") for e in edges)
    confidence_counts = Counter(e.get("edge_confidence", "(missing)") for e in edges)

    unknown_count = sum(top_level[t] for t in _UNKNOWN_EDGE_TYPES)
    needs_runtime_count = sum(
        1 for e in edges if e.get("edge_confidence") == "needs_runtime_validation"
    )

    clusters_by_edge_type: dict[str, dict[str, _Cluster]] = defaultdict(dict)
    needs_runtime_clusters: dict[str, _Cluster] = {}

    for edge in edges:
        edge_type = edge.get("candidate_edge_type")
        confidence = edge.get("edge_confidence")

        if edge_type in _UNKNOWN_EDGE_TYPES:
            if edge_type in _GROUP_BY_MEMBER_NAME_EDGE_TYPES:
                key = _normalize_member_name(edge.get("member_name", ""))
            else:
                key = _bare_type_name(edge.get("candidate_target_type"))
            bucket = clusters_by_edge_type[edge_type]
            bucket.setdefault(key, _Cluster(key=key)).add(edge)

        # needs_runtime_validation is a separate axis from candidate_edge_type
        # (an edge can be e.g. UNKNOWN_DB_OBJECT_REFERENCE *and*
        # needs_runtime_validation) -- track it independently so it isn't
        # double-counted into the buckets above, per confidence_model_v0.md's
        # note that this label is a distinct verifiability axis, not a rung
        # on the same confidence ladder.
        if confidence == "needs_runtime_validation":
            key = _bare_type_name(edge.get("candidate_target_type"))
            needs_runtime_clusters.setdefault(key, _Cluster(key=key)).add(edge)

    def _sorted(clusters: dict[str, _Cluster]) -> list[_Cluster]:
        return sorted(clusters.values(), key=lambda c: c.count, reverse=True)

    return {
        "total_edges": total,
        "top_level_edge_type_counts": dict(top_level.most_common()),
        "confidence_counts": dict(confidence_counts.most_common()),
        "unknown_edge_count": unknown_count,
        "unknown_edge_share": round(unknown_count / total, 4) if total else 0.0,
        "needs_runtime_validation_count": needs_runtime_count,
        "clusters": {
            edge_type: _sorted(clusters) for edge_type, clusters in clusters_by_edge_type.items()
        },
        "needs_runtime_validation_clusters": _sorted(needs_runtime_clusters),
    }


def _print_cluster_table(title: str, clusters: list[_Cluster], top: int, min_count: int) -> None:
    shown = [c for c in clusters if c.count >= min_count][:top]
    if not shown:
        return
    print(f"\n## {title} ({len(clusters)} distinct groups)\n")
    header = f"{'count':>6}  {'distinct_types':>14}  {'revitlookup':>11}  {'dll_not_found':>13}  key / example"
    print(header)
    print("-" * len(header))
    for c in shown:
        example = c.examples[0] if c.examples else ("", "")
        print(
            f"{c.count:>6}  {len(c.source_types):>14}  {c.revitlookup_referenced_count:>11}  "
            f"{c.dll_member_not_found_count:>13}  {c.key}  (e.g. {example[0]}.{example[1]})"
        )


def _write_csv(path: Path, report: dict[str, Any]) -> None:
    rows: list[dict[str, Any]] = []
    for edge_type, clusters in report["clusters"].items():
        for c in clusters:
            rows.append(
                {
                    "group": edge_type,
                    "key": c.key,
                    "count": c.count,
                    "distinct_source_types": len(c.source_types),
                    "revitlookup_referenced_count": c.revitlookup_referenced_count,
                    "dll_member_not_found_count": c.dll_member_not_found_count,
                    "example_source_type": c.examples[0][0] if c.examples else "",
                    "example_member_name": c.examples[0][1] if c.examples else "",
                }
            )
    for c in report["needs_runtime_validation_clusters"]:
        rows.append(
            {
                "group": "needs_runtime_validation",
                "key": c.key,
                "count": c.count,
                "distinct_source_types": len(c.source_types),
                "revitlookup_referenced_count": c.revitlookup_referenced_count,
                "dll_member_not_found_count": c.dll_member_not_found_count,
                "example_source_type": c.examples[0][0] if c.examples else "",
                "example_member_name": c.examples[0][1] if c.examples else "",
            }
        )
    rows.sort(key=lambda r: r["count"], reverse=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        writer.writeheader()
        writer.writerows(rows)


def _main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--candidate-edges", required=True, help="Path to an existing candidate_edges.json")
    parser.add_argument("--top", type=int, default=25, help="Max groups to print per bucket (default 25)")
    parser.add_argument("--min-count", type=int, default=2, help="Skip groups with fewer than this many edges (default 2)")
    parser.add_argument("--csv-out", help="Optional path to also write every group as CSV, unfiltered by --top/--min-count")
    parser.add_argument("--json-out", help="Optional path to write the full report (all groups, no truncation) as JSON")
    args = parser.parse_args(argv)

    edges_path = Path(args.candidate_edges)
    edges = json.loads(edges_path.read_text(encoding="utf-8"))
    if not isinstance(edges, list):
        raise SystemExit(f"Error: {edges_path} does not contain a JSON array of edge candidates")

    report = build_report(edges)

    print(f"Total edges: {report['total_edges']}")
    print(f"Unknown/generic edges (UNKNOWN_DB_OBJECT_REFERENCE + UNKNOWN_ELEMENTID_REFERENCE + "
          f"RETURNS_ELEMENT_IDS): {report['unknown_edge_count']} ({report['unknown_edge_share']:.1%})")
    print(f"needs_runtime_validation edges (separate axis, may overlap the above): "
          f"{report['needs_runtime_validation_count']}")
    print("\nTop-level candidate_edge_type counts:")
    for edge_type, count in report["top_level_edge_type_counts"].items():
        print(f"  {count:>6}  {edge_type}")

    _print_cluster_table(
        "UNKNOWN_DB_OBJECT_REFERENCE by candidate_target_type",
        report["clusters"].get("UNKNOWN_DB_OBJECT_REFERENCE", []),
        args.top,
        args.min_count,
    )
    _print_cluster_table(
        "UNKNOWN_ELEMENTID_REFERENCE by normalized member name",
        report["clusters"].get("UNKNOWN_ELEMENTID_REFERENCE", []),
        args.top,
        args.min_count,
    )
    _print_cluster_table(
        "RETURNS_ELEMENT_IDS by normalized member name",
        report["clusters"].get("RETURNS_ELEMENT_IDS", []),
        args.top,
        args.min_count,
    )
    _print_cluster_table(
        "needs_runtime_validation by candidate_target_type",
        report["needs_runtime_validation_clusters"],
        args.top,
        args.min_count,
    )

    if args.csv_out:
        _write_csv(Path(args.csv_out), report)
        print(f"\nWrote every group (unfiltered) to {args.csv_out}")

    if args.json_out:
        # _Cluster isn't JSON-serializable as-is (has a set) -- flatten before writing.
        serializable = {
            **{k: v for k, v in report.items() if k not in ("clusters", "needs_runtime_validation_clusters")},
            "clusters": {
                edge_type: [
                    {
                        "key": c.key,
                        "count": c.count,
                        "distinct_source_types": len(c.source_types),
                        "revitlookup_referenced_count": c.revitlookup_referenced_count,
                        "dll_member_not_found_count": c.dll_member_not_found_count,
                        "examples": c.examples,
                    }
                    for c in clusters
                ]
                for edge_type, clusters in report["clusters"].items()
            },
            "needs_runtime_validation_clusters": [
                {
                    "key": c.key,
                    "count": c.count,
                    "distinct_source_types": len(c.source_types),
                    "revitlookup_referenced_count": c.revitlookup_referenced_count,
                    "dll_member_not_found_count": c.dll_member_not_found_count,
                    "examples": c.examples,
                }
                for c in report["needs_runtime_validation_clusters"]
            ],
        }
        Path(args.json_out).write_text(json.dumps(serializable, indent=2), encoding="utf-8")
        print(f"Wrote full report to {args.json_out}")


if __name__ == "__main__":
    _main(sys.argv[1:])
