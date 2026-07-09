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
    # utf-8-sig (not plain utf-8): Windows PowerShell 5.1's Set-Content/Out-File -Encoding
    # utf8 always prepends a BOM (Microsoft's own about_character_encoding docs confirm this
    # is unconditional on that host), which json.loads rejects outright ("Unexpected UTF-8
    # BOM"). reflect_revit_api.ps1 now writes without a BOM either way, but this loader stays
    # tolerant of one regardless -- a manifest hand-edited on Windows (e.g. in Notepad, which
    # still defaults to BOM-prefixed UTF-8) or produced by some future variant of Stage A
    # shouldn't fail to parse over a single invisible byte. utf-8-sig strips a leading BOM if
    # present and is otherwise identical to utf-8 for BOM-less input.
    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
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


def _dotted(full_type_name: str) -> str:
    """.NET reflection's own ``Type.FullName`` spells a nested class with
    ``+`` (``Outer+Inner``) -- confirmed real shape in a live Revit 2025
    manifest (``Autodesk.Revit.DB.BuiltInFailures+AlignmentFailures`` and
    171 similar entries, plus a handful of non-BuiltInFailures nested types
    like ``SpecTypeId.Boolean``). The docs-derived crawl side (``ApiPage``/
    ``NodeCandidate``/``EdgeCandidate.source_type``, and any docs-derived
    return/parameter type string ``normalize_type_name`` below sees) always
    uses ``.`` instead, matching how Sandcastle itself renders a nested
    type's name on revitapidocs.com. Both sides must be compared in the same
    form -- used both by ``_ManifestTypeResolver`` (type resolution) and by
    ``normalize_type_name`` (signature comparison) below, since a member's
    return/parameter type can itself be a nested type, not just its
    declaring type.
    """
    return full_type_name.replace("+", ".")


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
# This is deliberately not a full CLR type-name parser. Multi-type-argument generics (e.g.
# IDictionary<K,V>) *are* handled for the shape reflect_revit_api.ps1 actually produces --
# a flat, single-level comma-separated arg list, since Stage A always uses Type.ToString(),
# never the assembly-qualified Type.FullName, for return/parameter type strings -- confirmed
# against a real Revit 2024 manifest, where Element.ChangeTypeId's static overload really
# returns IDictionary<ElementId,ElementId>, not a single-arg collection as originally guessed.
# A hypothetical *assembly-qualified* multi-arg form (`Foo[[A, Asm,...],[B, Asm,...]]`, one
# bracket pair per arg) is still not handled correctly -- but Stage A never actually emits
# that shape, only a single-arg assembly-qualified form does that (and is handled below), so
# this isn't a live gap in this project's own pipeline. A nested generic-of-generic is also
# not specifically handled and would need this function extended and re-tested, not silently
# trusted.

_BACKTICK_ARITY_RE = re.compile(r"`\d+")
_ASSEMBLY_QUALIFIED_INNER_RE = re.compile(r"\[\[([^\[\],]+)(?:,[^\[\]]*)?\]\]")
_GENERIC_PARENS_RE = re.compile(r"^([\w.]+)\(([^()]*)\)$")
_NAMESPACE_SEGMENT_RE = re.compile(r"\b[A-Za-z_][\w.]*\.[A-Za-z_]\w*\b")
_COMMA_SPACE_RE = re.compile(r"\s*,\s*")
# Sandcastle sometimes renders a generic return/parameter type with spaces around the angle
# brackets it already uses natively (confirmed real doc text on a Revit 2025 crawl: "IList <
# ElementId >", "ICollection < string >"), rather than the parenthesized "Name(Args)" form
# _GENERIC_PARENS_RE above handles -- that regex requires the *whole* string to be exactly
# Name(Args), so it never fires for a string that already has literal "<"/">" in it, leaving
# the spaces untouched. Reflection's own Type.ToString()-derived form never has this space
# (`IList<ElementId>`), so left as-is this alone accounted for ~73% of a real Revit 2025 Stage
# B run's SIGNATURE_MISMATCH edges (1139 of 1551) -- all cosmetic, not real mismatches. Collapse
# just the whitespace touching a bracket, not whitespace generally: an out/ref parameter's
# meaningful space ("out ModelCurveArray") must survive this step untouched.
_ANGLE_BRACKET_SPACE_RE = re.compile(r"\s*([<>])\s*")
# Sandcastle renders a primitive with its C# keyword ("string", "bool", "int", ...); .NET
# reflection's Type.ToString() gives the CLR type name ("String", "Boolean", "Int32", ...) --
# confirmed real disagreement on a Revit 2025 crawl (e.g. Category.IsTagCategory's docs return
# type "bool" vs. the manifest's "Boolean"), accounting for most of the SIGNATURE_MISMATCH
# edges still remaining after the angle-bracket-spacing fix above. classify.py's own
# PRIMITIVE_TYPES set already treats both spellings of a few of these (bool/Boolean,
# string/String, ...) as equally valid primitive-type strings elsewhere in this project; this
# is the same fact, applied to signature comparison. Canonicalizing to the CLR spelling (not
# the C# keyword) since reflection's side already arrives in that form via the
# namespace-segment-reduction step above and needs no further change.
_PRIMITIVE_ALIAS_TO_CLR = {
    "bool": "Boolean",
    "byte": "Byte",
    "sbyte": "SByte",
    "char": "Char",
    "decimal": "Decimal",
    "double": "Double",
    "float": "Single",
    "int": "Int32",
    "uint": "UInt32",
    "long": "Int64",
    "ulong": "UInt64",
    "short": "Int16",
    "ushort": "UInt16",
    "object": "Object",
    "string": "String",
}
_PRIMITIVE_ALIAS_RE = re.compile(r"\b(" + "|".join(_PRIMITIVE_ALIAS_TO_CLR) + r")\b")


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
    # Collapse whitespace touching an angle bracket -- see _ANGLE_BRACKET_SPACE_RE above.
    # Deliberately only around "<"/">", not a blanket whitespace strip: an out/ref parameter's
    # own space ("out ModelCurveArray") is meaningful and must survive this step.
    s = _ANGLE_BRACKET_SPACE_RE.sub(lambda m: m.group(1), s)
    # Same CLR nested-type separator fix as _dotted()/_ManifestTypeResolver above (see that
    # docstring), applied here too: a member whose return/parameter type is itself a nested
    # Revit type reflects as "Outer+Inner" (e.g. "Autodesk.Revit.DB.SpecTypeId+Boolean"), while
    # the docs side always uses "Outer.Inner" ("Autodesk.Revit.DB.SpecTypeId.Boolean"). Without
    # this, only the docs form's leading namespace gets stripped by _NAMESPACE_SEGMENT_RE below
    # (which never matches across a "+"), leaving "SpecTypeId+Boolean" on the reflection side vs.
    # "Boolean" on the docs side -- a false SIGNATURE_MISMATCH on every edge involving a nested
    # type, not just the type-resolution false negatives _ManifestTypeResolver already fixed.
    # Must run before namespace reduction so the now-dotted string reduces the same way on
    # both sides.
    s = _dotted(s)
    # Reduce every dotted, namespace-qualified identifier to its short name
    # -- the same short-name bridge already used for type/target resolution
    # elsewhere in this project (graph._Resolver), applied here to signature
    # comparison instead of node/edge target resolution.
    s = _NAMESPACE_SEGMENT_RE.sub(lambda m: m.group(0).rsplit(".", 1)[-1], s)
    # C# keyword primitive -> CLR type name -- see _PRIMITIVE_ALIAS_TO_CLR above.
    s = _PRIMITIVE_ALIAS_RE.sub(lambda m: _PRIMITIVE_ALIAS_TO_CLR[m.group(1)], s)
    # A multi-arg generic's docs-side prose form separates arguments with whitespace around the
    # comma -- confirmed real Sandcastle title text (crawl_notes.md): "ChangeTypeId Method
    # (Document, ICollection(ElementId), ElementId)" (space after only), and, separately, a real
    # angle-bracket-form return type with space on *both* sides (confirmed on a Revit 2025 crawl:
    # "IDictionary < ExportIFCCategoryKey , ExportIFCCategoryInfo >") -- while reflection's own
    # comma-separated arg list (Type.ToString()) has no space either side. Collapse whitespace on
    # either side of a comma uniformly so a real multi-arg generic (confirmed on
    # Element.ChangeTypeId's IDictionary<ElementId,ElementId> return type) doesn't falsely report
    # SIGNATURE_MISMATCH purely over comma-spacing.
    s = _COMMA_SPACE_RE.sub(",", s)
    # "void" is not a real type either side ever has to look up -- but the two sides spell
    # "no return value" differently. classify.classify_member only requires a truthy
    # member.return_type to build an EdgeCandidate at all, so a void method whose *name*
    # still matches a relationship keyword (e.g. SetMaterialId, SetDefaultFamilyTypeId) is
    # still emitted, with the docs-parsed literal C# return type "void" preserved verbatim
    # (classify.py's own PRIMITIVE_TYPES set already treats "void" as a real, expected
    # primitive-type string, not a missing value). reflect_revit_api.ps1, on the reflection
    # side, maps ReturnType.FullName == "System.Void" to a manifest return_type of null
    # (Get-ReturnTypeString) -- so without this, "void" normalizes to the literal string
    # "void" while null normalizes to "" via the `if not raw: return ""` guard above, and a
    # real, correctly-matching void method falsely reports SIGNATURE_MISMATCH. Canonicalize
    # every void spelling (docs' "void", reflection's "System.Void" -- reduced to "Void" by
    # the namespace-segment step above -- and the already-"" no-value case) to the same "".
    if s.lower() == "void":
        return ""
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
    -- is exactly the same). Lookup keys are always ``_dotted`` first, so a
    docs-derived ``Outer.Inner`` query matches a manifest's ``Outer+Inner``.
    """

    def __init__(self, manifest_types: list[ManifestType]) -> None:
        self._by_full_name = {_dotted(t.full_type_name): t for t in manifest_types}
        by_short: dict[str, list[str]] = {}
        for t in manifest_types:
            by_short.setdefault(_dotted(t.full_type_name).rsplit(".", 1)[-1], []).append(_dotted(t.full_type_name))
        self._unambiguous_by_short = {short: names[0] for short, names in by_short.items() if len(names) == 1}

    def resolve(self, full_type_name: str) -> tuple[Optional[ManifestType], str]:
        exact = self._by_full_name.get(_dotted(full_type_name))
        if exact is not None:
            return exact, "exact"
        short = _dotted(full_type_name).rsplit(".", 1)[-1]
        fallback_name = self._unambiguous_by_short.get(short)
        if fallback_name is not None:
            return self._by_full_name[fallback_name], "short_name_fallback"
        return None, "none"


def _find_members(
    manifest_type: ManifestType, member_name: str, member_kind: str, types_by_full_name: dict[str, ManifestType]
) -> list[ManifestMember]:
    """Every member named ``member_name`` (of ``member_kind``) visible on
    ``manifest_type`` -- its own members plus every type in its
    ``inheritance_chain`` -- generalizing ``pipeline._build_known_edge_report``'s
    exact mechanism (checking a fixed nine hand-picked members against a
    type-or-its-known-ancestors) to every edge, per docs/dll_reflection_v0.md.

    Returns *all* matches, not just the first, because ``member_name`` alone
    is not a unique key: an overloaded method (e.g. ``Element.ChangeTypeId``,
    which has a single-``ElementId`` overload and a
    ``Document``/``ICollection<ElementId>``/``ElementId`` overload -- see
    docs/crawl_notes.md) produces multiple manifest entries sharing the same
    name and often the same declaring_type, distinguished only by parameter
    types. Returning just the first would make whether a given edge (itself
    naming one specific overload via its own ``parameter_types``) reports
    SIGNATURE_CONFIRMED or SIGNATURE_MISMATCH depend on manifest/reflection
    ordering rather than on which overload it actually matches --
    ``cross_validate_dll`` tries every entry this returns before concluding a
    real mismatch. Filtering by ``member_kind`` here (not just ``member_name``)
    is the same reasoning applied to the lookup key itself, per
    docs/dll_reflection_v0.md's edge key of (source_type, member_name,
    member_kind, parameter types).

    Checking ``manifest_type.members`` first also covers a manifest whose
    producer already flattened inherited members into every type's own list
    (true .NET reflection with ``FlattenHierarchy`` does this) -- the
    ancestor walk below is what still finds the member for a manifest that
    doesn't.
    """
    matches = [m for m in manifest_type.members if m.name == member_name and m.kind == member_kind]
    for ancestor_name in manifest_type.inheritance_chain:
        ancestor = types_by_full_name.get(ancestor_name)
        if ancestor is None:
            continue
        matches.extend(m for m in ancestor.members if m.name == member_name and m.kind == member_kind)
    return matches


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

        candidates = _find_members(manifest_type, edge.member_name, edge.member_kind.value, types_by_full_name)
        if not candidates:
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

        expected_return = normalize_type_name(edge.return_type)
        expected_params = [normalize_type_name(p) for p in edge.parameter_types]

        # Try every same-named overload before concluding a mismatch -- see
        # _find_members' docstring. Only the edge's own (return type,
        # parameter types) identify which specific overload it refers to;
        # matching by name alone (as a single dll_signature_verified bool
        # keyed on (source_type, member_name) would force) can't distinguish
        # them at all.
        matched = next(
            (
                c
                for c in candidates
                if normalize_type_name(c.return_type) == expected_return
                and [normalize_type_name(p.type) for p in c.parameters] == expected_params
            ),
            None,
        )

        if matched is not None:
            relationship_scope = "declared" if matched.declaring_type == manifest_type.full_type_name else "inherited"
            edge.dll_signature_verified = True
            edge.dll_relationship_scope = relationship_scope
            edge.dll_verified_status = f"signature_verified_{relationship_scope}"
            overload_note = f" ({len(candidates)} overload(s) named {edge.member_name} considered)" if len(candidates) > 1 else ""
            edge_results.append(
                EdgeVerificationResult(
                    source_type=edge.source_type,
                    member_name=edge.member_name,
                    status=EdgeVerificationStatus.SIGNATURE_CONFIRMED,
                    relationship_scope=relationship_scope,
                    expected_return_type=edge.return_type,
                    actual_return_type=matched.return_type,
                    actual_declaring_type=matched.declaring_type,
                    note=f"member exists ({relationship_scope}); normalized signature matches{overload_note}",
                )
            )
            continue

        # No candidate's signature matched -- a genuine mismatch, not an
        # artifact of manifest/reflection ordering, since every same-named,
        # same-kind member visible on this type (every overload included) was
        # tried above. Report against whichever candidate is declared
        # directly on source_type, if any, as the most representative single
        # comparison point; falls back to the first candidate otherwise.
        representative = next((c for c in candidates if c.declaring_type == manifest_type.full_type_name), candidates[0])
        relationship_scope = "declared" if representative.declaring_type == manifest_type.full_type_name else "inherited"
        edge.dll_signature_verified = False
        edge.dll_relationship_scope = relationship_scope
        edge.dll_verified_status = "signature_mismatch"
        edge_results.append(
            EdgeVerificationResult(
                source_type=edge.source_type,
                member_name=edge.member_name,
                status=EdgeVerificationStatus.SIGNATURE_MISMATCH,
                relationship_scope=relationship_scope,
                expected_return_type=edge.return_type,
                actual_return_type=representative.return_type,
                actual_declaring_type=representative.declaring_type,
                note=(
                    f"member exists ({relationship_scope}) but normalized signature differs from all "
                    f"{len(candidates)} overload(s) named {edge.member_name} found in the manifest: "
                    f"docs return type `{edge.return_type}` (normalized `{expected_return}`), params "
                    f"{expected_params} -- closest candidate DLL return type `{representative.return_type}` "
                    f"(normalized `{normalize_type_name(representative.return_type)}`)"
                ),
            )
        )

    return GroundTruthReport(
        revit_version=manifest.revit_version,
        type_results=type_results,
        edge_results=edge_results,
        dll_only_types=dll_only_types,
    )
