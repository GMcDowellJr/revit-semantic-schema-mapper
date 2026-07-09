"""Shared data structures for the Revit semantic schema mapper.

Everything here is a plain dataclass so it round-trips to JSON with
``dataclasses.asdict`` and has no dependency on crawl/parse internals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Kind(str, Enum):
    CLASS = "class"
    STRUCT = "struct"
    ENUM = "enum"
    INTERFACE = "interface"
    PROPERTY = "property"
    METHOD = "method"
    CONSTRUCTOR = "constructor"
    MEMBERS_INDEX = "members_index"
    UNKNOWN = "unknown"


class MemberKind(str, Enum):
    PROPERTY = "property"
    METHOD = "method"


class IsElementCandidate(str, Enum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


class ClassRole(str, Enum):
    """A coarse structural classification of a type, orthogonal to
    ``is_element_candidate`` -- see ``classify.classify_class_role`` for the
    heuristics and docs/edge_taxonomy_v0.md for how this is used downstream.
    """

    ELEMENT_TYPE = "element_type"
    ELEMENT_SUBTYPE = "element_subtype"
    UTILITY_CLASS = "utility_class"
    OPTIONS_CLASS = "options_class"
    ENUM = "enum"
    VALUE_OBJECT = "value_object"
    UNKNOWN = "unknown"


class ConfidenceLabel(str, Enum):
    """See docs/confidence_model_v0.md for the definition of each label."""

    DIRECT_RETURN_TYPE = "direct_return_type"
    ELEMENTID_WITH_STRONG_NAME = "elementid_with_strong_name"
    ELEMENTID_COLLECTION_WITH_STRONG_NAME = "elementid_collection_with_strong_name"
    DOCS_SEMANTIC_HINT = "docs_semantic_hint"
    NAME_ONLY_CANDIDATE = "name_only_candidate"
    UNKNOWN_REFERENCE = "unknown_reference"
    NEEDS_RUNTIME_VALIDATION = "needs_runtime_validation"


class EdgeType(str, Enum):
    """See docs/edge_taxonomy_v0.md."""

    HAS_PARAMETER = "HAS_PARAMETER"
    HAS_CATEGORY = "HAS_CATEGORY"
    INSTANCE_OF = "INSTANCE_OF"
    TYPE_OF = "TYPE_OF"
    BELONGS_TO_FAMILY = "BELONGS_TO_FAMILY"
    CONTROLLED_BY_TEMPLATE = "CONTROLLED_BY_TEMPLATE"
    USES_MATERIAL = "USES_MATERIAL"
    USES_FILL_PATTERN = "USES_FILL_PATTERN"
    USES_LINE_PATTERN = "USES_LINE_PATTERN"
    PLACED_ON_SHEET = "PLACED_ON_SHEET"
    TAGS_ELEMENT = "TAGS_ELEMENT"
    HOSTED_BY = "HOSTED_BY"
    OWNED_BY_WORKSET = "OWNED_BY_WORKSET"
    ASSIGNED_TO_LEVEL = "ASSIGNED_TO_LEVEL"
    ASSIGNED_TO_PHASE = "ASSIGNED_TO_PHASE"
    ASSIGNED_TO_DESIGN_OPTION = "ASSIGNED_TO_DESIGN_OPTION"
    MEMBER_OF_GROUP = "MEMBER_OF_GROUP"
    MEMBER_OF_ASSEMBLY = "MEMBER_OF_ASSEMBLY"
    DEPENDS_ON = "DEPENDS_ON"
    REFERENCES = "REFERENCES"
    RETURNS_ELEMENT_IDS = "RETURNS_ELEMENT_IDS"
    UNKNOWN_ELEMENTID_REFERENCE = "UNKNOWN_ELEMENTID_REFERENCE"
    UNKNOWN_DB_OBJECT_REFERENCE = "UNKNOWN_DB_OBJECT_REFERENCE"


@dataclass
class ParameterInfo:
    name: str
    type: str


@dataclass
class MemberInfo:
    """A single property or method belonging to a declaring type."""

    name: str
    kind: MemberKind
    declaring_type: str
    raw_signature: str
    return_type: Optional[str] = None
    parameters: list[ParameterInfo] = field(default_factory=list)
    summary: str = ""
    remarks: str = ""
    examples: list[str] = field(default_factory=list)
    see_also: list[str] = field(default_factory=list)
    source_url: str = ""


@dataclass
class EnumMemberInfo:
    enum_name: str
    member_name: str
    numeric_value: Optional[str] = None
    description: str = ""
    source_url: str = ""


@dataclass
class ApiPage:
    """Fully parsed representation of one RevitApiDocs page."""

    revit_version: str
    namespace: str
    type_name: str
    full_type_name: str
    kind: Kind
    declaring_type: Optional[str] = None
    base_type: Optional[str] = None
    inheritance_chain: list[str] = field(default_factory=list)
    implemented_interfaces: list[str] = field(default_factory=list)
    members: list[MemberInfo] = field(default_factory=list)
    enum_members: list[EnumMemberInfo] = field(default_factory=list)
    summary: str = ""
    remarks: str = ""
    examples: list[str] = field(default_factory=list)
    see_also: list[str] = field(default_factory=list)
    source_url: str = ""
    parser_notes: list[str] = field(default_factory=list)


@dataclass
class NodeCandidate:
    full_type_name: str
    short_name: str
    kind: Kind
    namespace: str
    base_type: Optional[str]
    inheritance_chain: list[str]
    is_element_candidate: IsElementCandidate
    class_role: ClassRole
    evidence: list[str]
    source_url: str
    # Set by ground_truth.cross_validate_dll (docs/dll_reflection_v0.md, Stage B)
    # -- True once a DLL reflection manifest confirms full_type_name really
    # exists in the compiled API, False if the manifest was checked and it
    # doesn't (docs claim a type reflection can't find -- stale docs, or a
    # deprecated/renamed type), None until that optional pass ever runs.
    dll_type_verified: Optional[bool] = None


@dataclass
class EdgeCandidate:
    source_type: str
    member_name: str
    member_kind: MemberKind
    raw_signature: str
    return_type: Optional[str]
    parameter_types: list[str]
    candidate_target_type: Optional[str]
    candidate_edge_type: EdgeType
    edge_confidence: ConfidenceLabel
    evidence: list[str]
    source_url: str
    parser_notes: list[str] = field(default_factory=list)
    # The four fields below are set by ground_truth.cross_validate_dll
    # (docs/dll_reflection_v0.md, Stage B) -- a distinct "is this backed by
    # the compiled API" axis, orthogonal to edge_confidence's "how strongly
    # do the docs alone imply this" axis. All stay None until that optional
    # pass runs.
    #
    # The member exists (on the resolved type or an ancestor in its
    # inheritance_chain) with a normalized signature match (return type +
    # parameter types) -- False can mean either the member wasn't found at
    # all or it was found with a different signature; dll_verified_status
    # (and ground_truth_report.json) records which.
    dll_signature_verified: Optional[bool] = None
    # "declared" if the manifest's declaring_type for this member equals
    # source_type itself, "inherited" if it only matched via a different
    # entry in source_type's inheritance_chain -- the machine-checkable
    # signal for "this relationship probably belongs on the base type, not
    # repeated on every subclass." None when the member wasn't found at all.
    dll_relationship_scope: Optional[str] = None
    # Reserved, not set by anything yet: dll_signature_verified only proves
    # the member exists and returns the claimed type/shape, not that it
    # resolves to the claimed target type in a real document -- that needs a
    # later runtime-verification stage, out of scope here (see
    # docs/dll_reflection_v0.md).
    dll_semantic_verified: Optional[bool] = None
    # Convenience rollup ground_truth.py computes from the fields above, e.g.
    # "not_found" / "signature_mismatch" / "signature_verified_declared" /
    # "signature_verified_inherited" -- always derived, never hand-set.
    dll_verified_status: Optional[str] = None
    # Set by ground_truth.cross_validate_revitlookup (docs/dll_reflection_v0.md, Stage C) --
    # a third, independent evidence source, orthogonal to both edge_confidence (docs alone)
    # and the dll_* fields above (compiled-API signature match). True means this exact member
    # has a corroborating case in a RevitLookup descriptor's Resolve()/RegisterExtensions
    # switch (RevitLookup's authors judged it worth hand-written resolution logic) --
    # deliberately never set to False: RevitLookup doesn't special-case every real member, so
    # absence here proves nothing about the edge (see revitlookup.py's ResolvedMember
    # docstring) and must never be read as a negative signal. Stays None when this pass hasn't
    # run, when source_type has no RevitLookup descriptor at all, or when it does but this
    # member has no corroborating case.
    revitlookup_referenced: Optional[bool] = None
    # Only meaningful when revitlookup_referenced is True: whether that corroborating case's
    # body references a live-document accessor (RevitApi.Document/.ActiveView, a worksharing
    # collector, etc.) -- the same "real, but incomplete without a live document" signal
    # confidence_model_v0.md's needs_runtime_validation describes. None otherwise.
    revitlookup_requires_document_context: Optional[bool] = None


class ConfidenceTier(str, Enum):
    """A coarse, four-bucket collapse of ``ConfidenceLabel`` for graph
    consumers that just want "how much do I trust this edge" rather than the
    full seven-label model -- see ``graph.confidence_tier`` for the mapping
    rules and why ``UNKNOWN_*`` edge types are pinned to
    ``UNVERIFIED_REFERENCE`` regardless of their (return-type-only)
    confidence label.
    """

    CORE = "core"
    LIKELY = "likely"
    NEEDS_VALIDATION = "needs_validation"
    UNVERIFIED_REFERENCE = "unverified_reference"


class TargetResolution(str, Enum):
    """How ``graph.build_graph`` matched an edge's ``candidate_target_type``
    string to a node.
    """

    EXACT = "exact"
    SHORT_NAME_FALLBACK = "short_name_fallback"
    EXTERNAL = "external"
    NONE = "none"


@dataclass
class GraphNode:
    """One node in the materialized graph -- see ``graph.build_graph``.

    ``id`` is always the node's fully-qualified type name, so any edge's
    ``source``/``target`` can be resolved by a simple dict lookup on this
    field. ``external`` marks a node that was never crawled/classified --
    it exists only because some edge's ``candidate_target_type`` pointed at
    it (e.g. a type outside the crawled namespace, a misresolved generic
    element type, or a primitive that classify.py mis-qualified).
    """

    id: str
    short_name: str
    external: bool
    kind: Optional[str] = None
    namespace: Optional[str] = None
    class_role: Optional[str] = None
    is_element_candidate: Optional[str] = None
    base_type: Optional[str] = None
    source_url: str = ""
    # Set by graph.apply_communities -- scoped to the core-tier subgraph
    # (see docs/edge_taxonomy_v0.md), so most nodes outside it stay None.
    community_id: Optional[int] = None


@dataclass
class GraphEdge:
    """One edge in the materialized graph -- see ``graph.build_graph``.

    ``source``/``target`` are node ids (``GraphNode.id``); ``target`` is
    ``None`` only when the originating ``EdgeCandidate`` itself had no
    ``candidate_target_type`` at all (``target_resolution`` is then
    ``TargetResolution.NONE``).
    """

    source: str
    target: Optional[str]
    member_name: str
    member_kind: MemberKind
    edge_type: EdgeType
    confidence: ConfidenceLabel
    confidence_tier: ConfidenceTier
    target_resolution: TargetResolution
    evidence: list[str]
    source_url: str


@dataclass
class Community:
    """One structurally-detected cluster of the core subgraph -- see
    ``community.detect_communities`` and ``graph.apply_communities``.

    ``label_source`` is ``"heuristic"`` (the default, dependency-free: the
    community's most-connected member names) or ``"llm"`` (opt-in, via
    OpenRouter -- see ``community.label_communities_llm``). Never a mix
    within one community: either the LLM call for that specific community
    succeeded, or it kept its heuristic label whole.
    """

    id: int
    label: str
    label_source: str
    size: int
    member_ids: list[str]
