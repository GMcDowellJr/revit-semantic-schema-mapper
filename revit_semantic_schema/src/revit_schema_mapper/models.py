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
    UNKNOWN = "unknown"


class MemberKind(str, Enum):
    PROPERTY = "property"
    METHOD = "method"


class IsElementCandidate(str, Enum):
    TRUE = "true"
    FALSE = "false"
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
    evidence: list[str]
    source_url: str


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
