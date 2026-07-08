"""Stage B of DLL reflection cross-validation -- see docs/dll_reflection_v0.md.

Loads a ``ground_truth_manifest_<version>.json`` (Stage A's output: every
type/member Autodesk.Revit.DB's compiled assemblies actually expose,
produced by .NET reflection on a Windows machine with Revit installed) and
cross-checks it against this project's own docs-derived
``NodeCandidate``/``EdgeCandidate`` lists, mutating each candidate's
``dll_*`` fields in place (see models.py) the same way
``graph.apply_communities`` mutates ``GraphNode.community_id`` in place.

This module never touches a real DLL or a Windows machine itself -- it only
reads a manifest JSON someone else already produced. Cross-validation is a
separate, explicit, opt-in pass layered on top of an existing crawl, not
mixed into crawl.py/parse.py/classify.py.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from .models import EdgeCandidate, NodeCandidate


# -- manifest shape (Stage A's output contract) ------------------------------


@dataclass
class ManifestParameter:
    name: str
    type: str


@dataclass
class ManifestMember:
    name: str
    kind: str  # "property" | "method"
    declaring_type: str
    return_type: Optional[str] = None
    parameters: list[ManifestParameter] = field(default_factory=list)
    is_static: bool = False


@dataclass
class ManifestType:
    full_type_name: str
    assembly: str
    kind: str
    is_abstract: bool
    base_type: Optional[str]
    inheritance_chain: list[str]
    implemented_interfaces: list[str]
    members: list[ManifestMember]
    enum_members: list[str] = field(default_factory=list)


@dataclass
class GroundTruthManifest:
    revit_version: str
    generated_at: str
    namespace_prefix: str
    assemblies_scanned: list[dict]
    types: list[ManifestType]


def load_manifest(path: Path) -> GroundTruthManifest:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    types = [
        ManifestType(
            full_type_name=t["full_type_name"],
            assembly=t["assembly"],
            kind=t["kind"],
            is_abstract=t.get("is_abstract", False),
            base_type=t.get("base_type"),
            inheritance_chain=t.get("inheritance_chain", []),
            implemented_interfaces=t.get("implemented_interfaces", []),
            members=[
                ManifestMember(
                    name=m["name"],
                    kind=m["kind"],
                    declaring_type=m["declaring_type"],
                    return_type=m.get("return_type"),
                    parameters=[ManifestParameter(name=p["name"], type=p["type"]) for p in m.get("parameters", [])],
                    is_static=m.get("is_static", False),
                )
                for m in t.get("members", [])
            ],
            enum_members=t.get("enum_members", []),
        )
        for t in raw["types"]
    ]
    return GroundTruthManifest(
        revit_version=raw["revit_version"],
        generated_at=raw.get("generated_at", ""),
        namespace_prefix=raw.get("namespace_prefix", ""),
        assemblies_scanned=raw.get("assemblies_scanned", []),
        types=types,
    )


# -- signature normalization --------------------------------------------------
#
# Docs-scraped and reflection-derived type-name strings are never
# byte-identical even when they describe the same real member (see
# docs/dll_reflection_v0.md, "Normalization is the hard part, not the
# lookup"). Two known sources of disagreement this handles:
#
#   1. Generic syntax: Sandcastle docs render "ICollection(ElementId)";
#      .NET reflection gives "ICollection`1[ElementId]", or, fully
#      assembly-qualified, "ICollection`1[[Autodesk.Revit.DB.ElementId,
#      RevitAPI, Version=..., Culture=..., PublicKeyToken=...]]".
#   2. Namespace qualification: docs and reflection can disagree on how
#      fully-qualified a type name is (graph.py's confirmed
#      Autodesk.Revit.DB.Room vs. Autodesk.Revit.DB.Architecture.Room case).
#
# This is deliberately not a full CLR type-name parser -- it handles single-
# level generics (a collection of a plain type), which covers every real
# case seen so far (ElementId collections). A deeply nested multi-type-arg
# generic is not specifically handled and would need this function extended
# and re-tested, not silently trusted.

_BACKTICK_ARITY_RE = re.compile(r"`\d+")
_ASSEMBLY_QUALIFIED_INNER_RE = re.compile(r"\[\[([^\[\],]+)(?:,[^\[\]]*)?\]\]")
_GENERIC_PARENS_RE = re.compile(r"^([\w.]+)\(([^()]*)\)$")
_NAMESPACE_SEGMENT_RE = re.compile(r"\b[A-Za-z_][\w.]*\.[A-Za-z_]\w*\b")


def normalize_type_name(raw: Optional[str]) -> str:
    """Canonical form for comparing a docs-derived type-name string against
    a reflection-derived one -- see the module-level note above. Both sides
    of a comparison must go through this, not just one.
    """
    if not raw:
        return ""
    s = raw.strip()
    s = _BACKTICK_ARITY_RE.sub("", s)
    # CLR assembly-qualified generic arg -> just the type name:
    # Foo[[Bar.Baz, RevitAPI, Version=...]] -> Foo[Bar.Baz]
    s = _ASSEMBLY_QUALIFIED_INNER_RE.sub(lambda m: f"[{m.group(1)}]", s)
    # CLR generic brackets -> angle brackets, matching Sandcastle's own convention.
    s = s.replace("[", "<").replace("]", ">")
    # Sandcastle's docs-only generic parens, e.g. ICollection(ElementId) ->
    # ICollection<ElementId> -- only when the *entire* string is exactly
    # Name(Args): an overload's parenthesized parameter list is a different
    # shape this function never sees (it only ever normalizes one
    # already-isolated return/parameter type string, never a raw signature).
    m = _GENERIC_PARENS_RE.match(s)
    if m:
        s = f"{m.group(1)}<{m.group(2)}>"
    # Reduce every dotted, namespace-qualified identifier to its short name
    # -- the same short-name bridge already used for type/target resolution
    # elsewhere in this project (graph._Resolver), applied here to signature
    # comparison instead of node/edge target resolution.
    s = _NAMESPACE_SEGMENT_RE.sub(lambda m: m.group(0).rsplit(".", 1)[-1], s)
    return s


# -- type resolution (mirrors graph._Resolver's exact/short-name algorithm) --


class _ManifestTypeResolver:
    """Resolves a type-name string to a ``ManifestType``: exact match first,
    then an unambiguous short-name fallback -- the same two-pass algorithm
    ``graph._Resolver`` already uses for ``candidate_target_type`` resolution,
    reapplied here over manifest types instead of ``NodeCandidate``s (a
    different collection, so the resolver itself isn't reused directly, but
    the algorithm -- and the reason for it, see graph._Resolver's docstring
    on the confirmed Autodesk.Revit.DB.Room vs. ...Architecture.Room mismatch
    -- is exactly the same).
    """

    def __init__(self, manifest_types: list[ManifestType]) -> None:
        self._by_full_name = {t.full_type_name: t for t in manifest_types}
        by_short: dict[str, list[str]] = {}
        for t in manifest_types:
            by_short.setdefault(t.full_type_name.rsplit(".", 1)[-1], []).append(t.full_type_name)
        self._unambiguous_by_short = {short: names[0] for short, names in by_short.items() if len(names) == 1}

    def resolve(self, full_type_name: str) -> tuple[Optional[ManifestType], str]:
        exact = self._by_full_name.get(full_type_name)
        if exact is not None:
            return exact, "exact"
        short = full_type_name.rsplit(".", 1)[-1]
        fallback_name = self._unambiguous_by_short.get(short)
        if fallback_name is not None:
            return self._by_full_name[fallback_name], "short_name_fallback"
        return None, "none"


def _find_member(
    manifest_type: ManifestType, member_name: str, types_by_full_name: dict[str, ManifestType]
) -> Optional[ManifestMember]:
    """Look up ``member_name`` on ``manifest_type`` itself first, falling
    back to every type in its ``inheritance_chain`` -- generalizing
    ``pipeline._build_known_edge_report``'s exact mechanism (checking a
    fixed nine hand-picked members against a type-or-its-known-ancestors) to
    every edge, per docs/dll_reflection_v0.md.

    Checking ``manifest_type.members`` first also covers a manifest whose
    producer already flattened inherited members into every type's own list
    (true .NET reflection with ``FlattenHierarchy`` does this) -- the
    ancestor walk below is what still finds the member for a manifest that
    doesn't.
    """
    for m in manifest_type.members:
        if m.name == member_name:
            return m
    for ancestor_name in manifest_type.inheritance_chain:
        ancestor = types_by_full_name.get(ancestor_name)
        if ancestor is None:
            continue
        for m in ancestor.members:
            if m.name == member_name:
                return m
    return None


# -- report shape --------------------------------------------------------------


class TypeVerificationStatus(str, Enum):
    CONFIRMED = "confirmed"
    DOC_ONLY = "doc_only"


class EdgeVerificationStatus(str, Enum):
    SIGNATURE_CONFIRMED = "signature_confirmed"
    SIGNATURE_MISMATCH = "signature_mismatch"
    MEMBER_NOT_FOUND = "member_not_found"


@dataclass
class TypeVerificationResult:
    full_type_name: str
    status: TypeVerificationStatus
    matched_manifest_type: Optional[str]
    resolution: str  # "exact" | "short_name_fallback" | "none"


@dataclass
class EdgeVerificationResult:
    source_type: str
    member_name: str
    status: EdgeVerificationStatus
    relationship_scope: Optional[str]  # "declared" | "inherited" | None
    expected_return_type: Optional[str]
    actual_return_type: Optional[str]
    actual_declaring_type: Optional[str]
    note: str


@dataclass
class GroundTruthReport:
    revit_version: str
    type_results: list[TypeVerificationResult]
    edge_results: list[EdgeVerificationResult]
    # Manifest types with no matching NodeCandidate at all -- an undocumented
    # type, or a crawl coverage gap (docs/dll_reflection_v0.md's DLL_ONLY).
    dll_only_types: list[str]


def cross_validate_dll(
    node_candidates: list[NodeCandidate],
    edge_candidates: list[EdgeCandidate],
    manifest: GroundTruthManifest,
) -> GroundTruthReport:
    """Cross-check ``node_candidates``/``edge_candidates`` against
    ``manifest``, mutating each candidate's ``dll_*`` fields in place (see
    models.py) and returning a ``GroundTruthReport`` with the full detail
    (which kind of ``False`` each was) for ``ground_truth_report.json``.
    """
    resolver = _ManifestTypeResolver(manifest.types)
    types_by_full_name = {t.full_type_name: t for t in manifest.types}

    type_results: list[TypeVerificationResult] = []
    # Keyed by NodeCandidate.full_type_name (not the manifest's own name) so
    # the edge loop below can look a source_type up directly by the same
    # string an EdgeCandidate actually carries, without re-running short-name
    # resolution for every edge whose source was already resolved here.
    resolved_by_node_name: dict[str, ManifestType] = {}
    matched_manifest_names: set[str] = set()

    for node in node_candidates:
        manifest_type, resolution = resolver.resolve(node.full_type_name)
        node.dll_type_verified = manifest_type is not None
        if manifest_type is not None:
            resolved_by_node_name[node.full_type_name] = manifest_type
            matched_manifest_names.add(manifest_type.full_type_name)
        type_results.append(
            TypeVerificationResult(
                full_type_name=node.full_type_name,
                status=TypeVerificationStatus.CONFIRMED if manifest_type is not None else TypeVerificationStatus.DOC_ONLY,
                matched_manifest_type=manifest_type.full_type_name if manifest_type is not None else None,
                resolution=resolution,
            )
        )

    dll_only_types = sorted(t.full_type_name for t in manifest.types if t.full_type_name not in matched_manifest_names)

    edge_results: list[EdgeVerificationResult] = []
    for edge in edge_candidates:
        manifest_type = resolved_by_node_name.get(edge.source_type)
        if manifest_type is None:
            # source_type didn't match any already-resolved NodeCandidate --
            # can still happen for an edge whose own type page failed to
            # crawl/parse this run. Re-resolve independently rather than
            # assuming "not found": the question here is purely "does this
            # member exist in the compiled API", not "is this a trustworthy
            # edge source" (contrast graph._Resolver.resolve's source-vs-
            # target distinction, which doesn't apply to this lookup).
            manifest_type, _ = resolver.resolve(edge.source_type)

        if manifest_type is None:
            edge.dll_signature_verified = False
            edge.dll_relationship_scope = None
            edge.dll_verified_status = "member_not_found"
            edge_results.append(
                EdgeVerificationResult(
                    source_type=edge.source_type,
                    member_name=edge.member_name,
                    status=EdgeVerificationStatus.MEMBER_NOT_FOUND,
                    relationship_scope=None,
                    expected_return_type=edge.return_type,
                    actual_return_type=None,
                    actual_declaring_type=None,
                    note="source type itself was not found in the DLL manifest (DOC_ONLY) -- cannot verify any of its members",
                )
            )
            continue

        member = _find_member(manifest_type, edge.member_name, types_by_full_name)
        if member is None:
            edge.dll_signature_verified = False
            edge.dll_relationship_scope = None
            edge.dll_verified_status = "member_not_found"
            edge_results.append(
                EdgeVerificationResult(
                    source_type=edge.source_type,
                    member_name=edge.member_name,
                    status=EdgeVerificationStatus.MEMBER_NOT_FOUND,
                    relationship_scope=None,
                    expected_return_type=edge.return_type,
                    actual_return_type=None,
                    actual_declaring_type=None,
                    note="not found on the resolved type or anywhere in its inheritance_chain in the DLL manifest",
                )
            )
            continue

        relationship_scope = "declared" if member.declaring_type == manifest_type.full_type_name else "inherited"
        expected_return = normalize_type_name(edge.return_type)
        actual_return = normalize_type_name(member.return_type)
        expected_params = [normalize_type_name(p) for p in edge.parameter_types]
        actual_params = [normalize_type_name(p.type) for p in member.parameters]
        signature_matches = expected_return == actual_return and expected_params == actual_params

        edge.dll_signature_verified = signature_matches
        edge.dll_relationship_scope = relationship_scope
        edge.dll_verified_status = f"signature_verified_{relationship_scope}" if signature_matches else "signature_mismatch"

        edge_results.append(
            EdgeVerificationResult(
                source_type=edge.source_type,
                member_name=edge.member_name,
                status=EdgeVerificationStatus.SIGNATURE_CONFIRMED if signature_matches else EdgeVerificationStatus.SIGNATURE_MISMATCH,
                relationship_scope=relationship_scope,
                expected_return_type=edge.return_type,
                actual_return_type=member.return_type,
                actual_declaring_type=member.declaring_type,
                note=(
                    f"member exists ({relationship_scope}); normalized signature matches"
                    if signature_matches
                    else f"member exists ({relationship_scope}) but normalized signature differs: "
                    f"docs return type `{edge.return_type}` (normalized `{expected_return}`), "
                    f"DLL return type `{member.return_type}` (normalized `{actual_return}`)"
                ),
            )
        )

    return GroundTruthReport(
        revit_version=manifest.revit_version,
        type_results=type_results,
        edge_results=edge_results,
        dll_only_types=dll_only_types,
    )
