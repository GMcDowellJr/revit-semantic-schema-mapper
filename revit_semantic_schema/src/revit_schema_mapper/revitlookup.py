"""Stage C of docs/dll_reflection_v0.md: mines RevitLookup's own descriptor
*source* for a third, independent static evidence layer -- see that doc's
"Stage C" section.

This module never touches Revit, RevitLookup itself, or a compiled DLL -- it's
static text-parsing of RevitLookup's own public C# source
(MIT-licensed, lookup-foundation/RevitLookup), the same kind of exercise as
parsing revitapidocs.com's HTML (crawl.py/parse.py) or reflecting over a
compiled assembly (reflect_revit_api.ps1).

**Version pinning matters.** RevitLookup tags releases per Revit year
(``<year>.<major>.<minor>``, e.g. ``2024.0.13``) and its ``develop`` branch
tracks whatever the *next* Revit version is (at time of writing, 2027) --
mining ``develop`` describes a later Revit version's API surface, not the one
any given ``ground_truth_manifest_<version>.json`` was reflected from. This
module's parsing rules were confirmed directly against the real source at tag
``2024.0.13`` (the latest tag matching Revit 2024): a class implementing
``IDescriptorResolver``/``IDescriptorExtension`` with a
``Resolve(Document context, string target, ParameterInfo[] parameters)``
method (a ``target switch`` on ``nameof(Type.Member)``/string-literal cases)
and a ``RegisterExtensions(IExtensionManager manager)`` method. **This is not
the shape found on ``develop``** as of this writing, which has been
refactored to a fluent ``Configure(IMemberConfigurator configuration)`` /
``.Member()``/``.Extension()`` API instead -- confirmed by direct comparison,
not assumed. Whichever tag is mined must be recorded (``revitlookup_tag``
below) and re-synced deliberately, matching the same version each time a
consumer expects, not silently re-pointed at whatever's newest.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# -- output shape -------------------------------------------------------------


@dataclass
class DescriptorMapEntry:
    """One case of ``DescriptorMap.FindDescriptor``'s switch: a real (or
    UI/BCL) type RevitLookup's authors judged worth a hand-written descriptor.
    ``section`` is the file's own ``//SectionName`` comment header the case
    fell under (e.g. ``APIObjects``, ``IDisposables``, ``System``,
    ``ComponentManager``) -- an explicit, checkable fact carried straight from
    the source rather than a hardcoded include/exclude list this module would
    otherwise need to guess and maintain separately.
    """

    target_type_short_name: str
    descriptor_class: str
    section: str


@dataclass
class ResolvedMember:
    """One ``nameof(Type.Member)`` (or bare string-literal) case inside a
    descriptor's ``Resolve()`` switch -- RevitLookup's authors judged this
    member's return value doesn't speak for itself generically. Absence of a
    member here proves nothing (RevitLookup doesn't special-case everything)
    -- this is a positive-only corroboration signal, never evidence an edge
    that's absent here is wrong.
    """

    member_name: str
    # "nameof": the case key came from `nameof(Type.Member)`, compiler-checked
    # against a real member of *some* type (not necessarily the descriptor's
    # own target type -- see synthetic_extensions). "string_literal": a bare
    # quoted string (e.g. "BoundingBox" for Element.get_BoundingBox) -- likely
    # a human-readable label for a real member rather than its exact runtime
    # name, so treat this as a lower-confidence signal than "nameof".
    name_source: str
    # Textual proxy, not exhaustive (see docs/dll_reflection_v0.md's own
    # caution on this): true if the case body (or a named local function it
    # calls) references a known document/view-scoped accessor
    # (RevitApi.Document, RevitApi.ActiveView, .Document, a worksharing/
    # schema collector, etc.) -- "this edge is real, but incomplete without a
    # live document," the same signal docs/confidence_model_v0.md's
    # needs_runtime_validation describes.
    requires_document_context: bool
    # True if the case body (or a named local function it calls) builds more
    # than one result via .AppendVariant(...) -- the same "cardinality is
    # per-item, not a single value" reasoning the design doc describes via
    # CompoundStructureDescriptor's per-layer resolution.
    has_multiple_variants: bool


@dataclass
class RevitLookupDescriptor:
    descriptor_class: str
    resolved_members: list[ResolvedMember] = field(default_factory=list)
    # Names registered via RegisterExtensions -- these do NOT exist on the
    # real compiled type at all (they're RevitLookup's own UI convenience,
    # often wrapping an *extension method*, not a member of the target type
    # itself -- e.g. HostObjectDescriptor's extensions all come from a
    # separate `HostExtensions` class). Must stay excluded from anything
    # compared against a DLL reflection manifest: Stage B would otherwise see
    # one as a "member," fail to find it (it was never in the compiled
    # assembly), and misreport MEMBER_NOT_FOUND for what's actually just a
    # UI convenience, not a real crawl gap.
    synthetic_extensions: list[str] = field(default_factory=list)
    # Explicit, checkable acknowledgment of what this parser couldn't
    # confidently extract from this specific file -- e.g. a class that
    # implements IDescriptorResolver but whose Resolve() method didn't match
    # this parser's assumed signature/shape. An empty resolved_members list
    # should be distinguishable in the output from "genuinely nothing
    # special-cased" vs. "the parser didn't recognize this file's shape" --
    # this field is exactly that distinction, per docs/dll_reflection_v0.md's
    # "Stage C's C#-parsing surface" open question.
    parser_notes: list[str] = field(default_factory=list)


@dataclass
class RevitLookupReference:
    revitlookup_tag: str
    descriptor_map: list[DescriptorMapEntry] = field(default_factory=list)
    descriptors: list[RevitLookupDescriptor] = field(default_factory=list)


# -- DescriptorMap.cs parsing --------------------------------------------------

_SECTION_RE = re.compile(r"^\s*//\s*(\w+)\s*$")
_SWITCH_ARM_RE = re.compile(
    r"^\s*(?P<type>[A-Za-z_][\w.]*)"
    r"(?:\s+value)?"
    r"(?:\s+when\s+.*?)?"
    r"\s*=>\s*new\s+(?P<descriptor>[A-Za-z_]\w*)\s*\("
)
_SKIP_TYPE_TOKENS = {"null", "_"}
# `using Alias = Fully.Qualified.Name;` -- confirmed a real, non-trivial case in
# DescriptorMap.cs: `using RevitApplication = Autodesk.Revit.ApplicationServices.
# Application;`, then `RevitApplication value when ... => new
# ApplicationDescriptor(value),` in the switch itself. Naively taking
# "RevitApplication".rsplit(".", 1)[-1] gives "RevitApplication" -- not the real
# CLR short name "Application" -- which would never short-name-match against a
# DLL manifest's own type list. Some aliases (e.g. `using RibbonItem =
# Autodesk.Revit.UI.RibbonItem;`) happen to already equal the real short name,
# but that's not something to rely on for every alias.
_USING_ALIAS_RE = re.compile(r"^\s*using\s+(\w+)\s*=\s*([\w.]+)\s*;\s*$", re.MULTILINE)


def _parse_using_aliases(text: str) -> dict[str, str]:
    """Maps each ``using Alias = Fully.Qualified.Name;`` directive's alias to
    the real CLR short name it stands for.
    """
    return {alias: qualified.rsplit(".", 1)[-1] for alias, qualified in _USING_ALIAS_RE.findall(text)}


def parse_descriptor_map(text: str) -> list[DescriptorMapEntry]:
    """Parse ``DescriptorMap.cs``'s ``FindDescriptor`` switch into one entry
    per case. Every case is returned, tagged with its own ``//SectionName``
    comment header (``System``/``Root``/``APIObjects``/``IDisposables``/
    ``Internal``/``Media``/``ComponentManager``/``Unknown``, confirmed real
    section names at tag 2024.0.13) -- filtering to "real Autodesk.Revit.DB
    types only" is left to the caller (e.g. by excluding known non-API
    sections, or by short-name-resolving each entry against an actual DLL
    manifest's own type list the same way ground_truth._ManifestTypeResolver
    already does), since which sections count as "real API" is a judgment
    call that could shift release to release and shouldn't be silently baked
    into this parser.
    """
    aliases = _parse_using_aliases(text)
    entries: list[DescriptorMapEntry] = []
    section = "Unlabeled"
    for line in text.splitlines():
        section_match = _SECTION_RE.match(line)
        if section_match:
            section = section_match.group(1)
            continue
        arm_match = _SWITCH_ARM_RE.match(line)
        if not arm_match:
            continue
        type_token = arm_match.group("type")
        if type_token in _SKIP_TYPE_TOKENS:
            continue
        # A bare (non-dotted) token that's a known using-alias resolves to the
        # real short name it stands for; anything else (including an
        # already-dotted token like "Autodesk.Windows.RibbonItem", which never
        # matches an alias key since C# alias names are always simple
        # identifiers) is unaffected and just takes its own last dotted segment.
        resolved_token = aliases.get(type_token, type_token)
        short_name = resolved_token.rsplit(".", 1)[-1]
        entries.append(
            DescriptorMapEntry(
                target_type_short_name=short_name,
                descriptor_class=arm_match.group("descriptor"),
                section=section,
            )
        )
    return entries


# -- per-descriptor-file parsing ----------------------------------------------

_CLASS_NAME_RE = re.compile(r"\bclass\s+(\w+)")
_RESOLVE_SIG_RE = re.compile(
    r"\bResolve\s*\(\s*Document\s+(?P<context_param>\w+)\s*,\s*string\s+\w+\s*,\s*ParameterInfo\[\]\s+\w+\s*\)\s*\{"
)
_REGISTER_EXTENSIONS_SIG_RE = re.compile(r"\bRegisterExtensions\s*\(\s*IExtensionManager\s+\w+\s*\)\s*\{")
# The optional `when <guard>` clause (e.g. real ParameterDescriptor.cs:
# `nameof(Parameter.ClearValue) when parameters.Length == 0 => ...`) uses the
# same non-greedy `.*?` (not `[^=]*?`) as _SWITCH_ARM_RE below, for the same
# reason: a guard condition routinely contains `==` (e.g. `parameters.Length
# == 0`), and an exclude-`=`-characters class can't match through that.
_CASE_START_RE = re.compile(
    r'(?:nameof\(\s*(?:[\w.]+\.)?(?P<nameof_member>\w+)\s*\)|"(?P<literal>[^"]+)")'
    r"(?:\s+when\s+.*?)?"
    r"\s*=>"
)
_BARE_CALL_RE = re.compile(r"^\s*(\w+)\(\)\s*,?\s*$")
_EXTENSION_NAME_RE = re.compile(r'\.Name\s*=\s*(?:nameof\(\s*(?:[\w.]+\.)?(\w+)\s*\)|"([^"]+)")\s*;')

# Textual proxies for "this only makes sense with a live document open" --
# confirmed real accessors at tag 2024.0.13 (RevitApi.ActiveView/.Document are
# the dominant pattern in ElementDescriptor.cs/FamilyManagerDescriptor.cs, which
# don't reference the Resolve() method's own `context` parameter at all -- but
# some real files do use it directly instead, e.g. DocumentDescriptor.cs's
# `nameof(Document.GetUnusedElements) => ResolveSet.Append(context
# .GetUnusedElements(...))`. That parameter's name isn't always literally
# "context" (not confirmed to be fixed across every descriptor), so it's
# detected from the real Resolve(...) signature via _RESOLVE_SIG_RE's
# `context_param` group and checked for separately, not hardcoded here.
_DOCUMENT_CONTEXT_MARKERS = (
    "RevitApi.Document",
    "RevitApi.ActiveView",
    ".Document",
    "FilteredWorksetCollector",
    "Schema.ListSchemas",
)


def _extract_balanced_block(text: str, open_brace_index: int) -> str:
    """Given the index of an opening ``{``, return the substring from there
    through its matching closing ``}`` (inclusive), tracking brace depth --
    the brace-matching analog of parse.py's paren-depth-tracking
    ``_split_top_level_commas``/``_strip_trailing_overload_signature``, since
    a naive regex can't correctly bound a block containing nested braces.
    """
    depth = 0
    for i in range(open_brace_index, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[open_brace_index : i + 1]
    return text[open_brace_index:]


def _find_method_body(text: str, signature_re: re.Pattern[str]) -> Optional[str]:
    match = signature_re.search(text)
    if not match:
        return None
    open_brace_index = match.end() - 1  # signature_re's own trailing "{"
    return _extract_balanced_block(text, open_brace_index)


def _find_local_function_body(method_text: str, function_name: str) -> Optional[str]:
    """A case whose inline expression is just a bare call to a local helper
    function (e.g. ``=> ResolveGetMaterialArea(),``) has its real logic --
    and the document-context/cardinality signals this module looks for --
    defined *after* the switch, as a separate local function in the same
    method body, not inline in the case itself (confirmed real shape in
    ElementDescriptor.cs). Finds that function's own body so its signals
    aren't silently missed.
    """
    func_re = re.compile(r"\b" + re.escape(function_name) + r"\s*\(\s*\)\s*\{")
    match = func_re.search(method_text)
    if not match:
        return None
    return _extract_balanced_block(method_text, match.end() - 1)


def _detect_signals(body: str, context_param: str) -> tuple[bool, bool]:
    requires_document_context = any(marker in body for marker in _DOCUMENT_CONTEXT_MARKERS) or f"{context_param}." in body
    has_multiple_variants = ".AppendVariant(" in body
    return requires_document_context, has_multiple_variants


def _parse_resolve_method(method_text: str, context_param: str) -> list[ResolvedMember]:
    case_starts = list(_CASE_START_RE.finditer(method_text))
    members: list[ResolvedMember] = []
    for i, case_match in enumerate(case_starts):
        end = case_starts[i + 1].start() if i + 1 < len(case_starts) else len(method_text)
        inline_body = method_text[case_match.end() : end]

        nameof_member = case_match.group("nameof_member")
        if nameof_member is not None:
            member_name = nameof_member
            name_source = "nameof"
        else:
            member_name = case_match.group("literal")
            name_source = "string_literal"

        search_body = inline_body
        bare_call = _BARE_CALL_RE.match(inline_body)
        if bare_call:
            local_body = _find_local_function_body(method_text, bare_call.group(1))
            if local_body is not None:
                search_body = inline_body + local_body

        requires_document_context, has_multiple_variants = _detect_signals(search_body, context_param)
        members.append(
            ResolvedMember(
                member_name=member_name,
                name_source=name_source,
                requires_document_context=requires_document_context,
                has_multiple_variants=has_multiple_variants,
            )
        )
    return members


def parse_descriptor_file(text: str) -> RevitLookupDescriptor:
    """Parse a single descriptor ``.cs`` file (e.g. ``ElementDescriptor.cs``)
    into its resolved members and synthetic extensions. Honest about what it
    couldn't confidently extract via ``parser_notes`` rather than silently
    reporting an empty list for a file this parser's assumed shape doesn't
    match -- see the design doc's "Stage C's C#-parsing surface" open
    question.
    """
    class_match = _CLASS_NAME_RE.search(text)
    descriptor_class = class_match.group(1) if class_match else "<unknown>"

    parser_notes: list[str] = []
    if class_match is None:
        parser_notes.append("could not find a 'class <Name>' declaration in this file")

    resolved_members: list[ResolvedMember] = []
    resolve_sig_match = _RESOLVE_SIG_RE.search(text)
    resolve_body = _find_method_body(text, _RESOLVE_SIG_RE)
    if resolve_body is not None:
        context_param = resolve_sig_match.group("context_param") if resolve_sig_match else "context"
        resolved_members = _parse_resolve_method(resolve_body, context_param)
    elif "IDescriptorResolver" in text:
        parser_notes.append(
            "file references IDescriptorResolver but Resolve(Document, string, ParameterInfo[]) "
            "method body was not found in the expected shape"
        )

    synthetic_extensions: list[str] = []
    extensions_body = _find_method_body(text, _REGISTER_EXTENSIONS_SIG_RE)
    if extensions_body is not None:
        for match in _EXTENSION_NAME_RE.finditer(extensions_body):
            name = match.group(1) or match.group(2)
            synthetic_extensions.append(name)
    elif "IDescriptorExtension" in text:
        parser_notes.append(
            "file references IDescriptorExtension but RegisterExtensions(IExtensionManager) "
            "method body was not found in the expected shape"
        )

    return RevitLookupDescriptor(
        descriptor_class=descriptor_class,
        resolved_members=resolved_members,
        synthetic_extensions=synthetic_extensions,
        parser_notes=parser_notes,
    )


# -- orchestration -------------------------------------------------------------


def mine_revitlookup_source(source_dir: Path, revitlookup_tag: str) -> RevitLookupReference:
    """Mine a local checkout of RevitLookup (already cloned/extracted at
    ``revitlookup_tag`` -- this function never fetches anything itself,
    matching reflect_revit_api.ps1's own "operate on a local directory"
    shape for Stage A) into a ``RevitLookupReference``.

    ``source_dir`` is expected to be the repository root (or any ancestor of
    ``source/RevitLookup/Core/ComponentModel``) -- confirmed real layout at
    tag 2024.0.13; a differently-laid-out tag would need this adjusted, not
    silently assumed to still match.
    """
    descriptor_map_path = _find_first(source_dir, "DescriptorMap.cs")
    descriptor_map: list[DescriptorMapEntry] = []
    if descriptor_map_path is not None:
        descriptor_map = parse_descriptor_map(descriptor_map_path.read_text(encoding="utf-8"))

    descriptor_files = sorted(source_dir.rglob("*Descriptor.cs"))
    descriptors = [parse_descriptor_file(path.read_text(encoding="utf-8")) for path in descriptor_files]

    return RevitLookupReference(
        revitlookup_tag=revitlookup_tag,
        descriptor_map=descriptor_map,
        descriptors=descriptors,
    )


def _find_first(root: Path, filename: str) -> Optional[Path]:
    return next(root.rglob(filename), None)


def load_revitlookup_reference(path: Path) -> RevitLookupReference:
    """Inverse of ``mine_revitlookup_source``'s own ``_main`` writer -- loads
    a ``revitlookup_reference_<version>.json`` back into a
    ``RevitLookupReference`` for ``ground_truth.cross_validate_revitlookup``
    to consume. Always written by this module's own ``_main`` (pure Python,
    ``Path.write_text``), never by anything on Windows/PowerShell, so unlike
    ``ground_truth.load_manifest`` there's no real BOM risk to guard against.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    descriptor_map = [
        DescriptorMapEntry(
            target_type_short_name=e["target_type_short_name"],
            descriptor_class=e["descriptor_class"],
            section=e["section"],
        )
        for e in raw.get("descriptor_map", [])
    ]
    descriptors = [
        RevitLookupDescriptor(
            descriptor_class=d["descriptor_class"],
            resolved_members=[
                ResolvedMember(
                    member_name=m["member_name"],
                    name_source=m["name_source"],
                    requires_document_context=m["requires_document_context"],
                    has_multiple_variants=m["has_multiple_variants"],
                )
                for m in d.get("resolved_members", [])
            ],
            synthetic_extensions=d.get("synthetic_extensions", []),
            parser_notes=d.get("parser_notes", []),
        )
        for d in raw.get("descriptors", [])
    ]
    return RevitLookupReference(
        revitlookup_tag=raw["revitlookup_tag"],
        descriptor_map=descriptor_map,
        descriptors=descriptors,
    )


# -- CLI ------------------------------------------------------------------------
#
# A standalone entry point, not wired into `python -m revit_schema_mapper`'s own
# argument parser -- Stage B's own `--cross-validate-dll` flag was never added
# there either (see docs/dll_reflection_v0.md's "Workflow once built"), so this
# matches that same not-yet-integrated state rather than getting ahead of it.
# Mirrors reflect_revit_api.ps1's own shape: operates on a local directory,
# writes one JSON file, prints a one-line summary.


def verify_tag_match(source_dir: Path, claimed_tag: str) -> Optional[str]:
    """Best-effort check that ``source_dir`` is actually checked out at
    ``claimed_tag``, since ``mine_revitlookup_source`` itself just trusts and
    records whatever tag string the caller passes without otherwise
    verifying it. ``--tag`` being a required argument with no default (see
    ``_main`` below) already rules out the *root* version of a real mistake
    found in a sibling project's own RevitLookup-syncing script (a hardcoded
    ``BRANCH = "develop"`` constant, silently re-pointing every sync at
    whatever Revit version RevitLookup currently targets) -- but a caller
    could still pass ``--tag 2024.0.13`` while ``--source-dir`` is actually
    sitting on ``develop`` (forgot to ``git checkout`` first, or checked out
    the wrong tag), producing output that *claims* to be 2024.0.13 but isn't.

    Also refuses if the working tree is at the right tag but *dirty*
    (uncommitted changes or untracked files) -- ``git describe --exact-match``
    only checks which commit ``HEAD`` is at, not whether the working tree
    still matches that commit's real content. A checkout that's exactly at
    ``2024.0.13`` but has a locally-modified or added descriptor file would
    otherwise pass the tag check while still mining content that was never
    actually part of that tag.

    Returns a human-readable mismatch description if ``source_dir`` is a git
    working tree and either its checked-out ref does not match ``claimed_tag``
    or the working tree is dirty, or ``None`` if it matches and is clean --
    or if it can't be verified at all (git isn't installed, or ``source_dir``
    isn't a git checkout, e.g. a plain extracted-from-a-tag-archive
    directory) -- an unverifiable checkout isn't treated as an error, since
    operating on "any local directory" (not necessarily a git clone) is this
    module's whole point.
    """
    import subprocess

    def _run(*args: str) -> Optional[subprocess.CompletedProcess[str]]:
        try:
            return subprocess.run(
                ["git", "-C", str(source_dir), *args],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    is_repo = _run("rev-parse", "--is-inside-work-tree")
    if is_repo is None or is_repo.returncode != 0 or is_repo.stdout.strip() != "true":
        return None  # not a git checkout at all -- can't verify, not an error

    describe = _run("describe", "--tags", "--exact-match")
    if describe is None or describe.returncode != 0:
        branch = _run("rev-parse", "--abbrev-ref", "HEAD")
        current = branch.stdout.strip() if branch is not None and branch.returncode == 0 else "<unknown>"
        return (
            f"--tag {claimed_tag!r} was given, but {source_dir} is not checked out exactly at "
            f"that tag (currently on {current!r}) -- refusing to trust the claimed tag label."
        )
    actual_tag = describe.stdout.strip()
    if actual_tag != claimed_tag:
        return (
            f"--tag {claimed_tag!r} was given, but {source_dir} is actually at tag {actual_tag!r} "
            f"-- refusing to trust the claimed tag label."
        )

    status = _run("status", "--porcelain")
    if status is not None and status.returncode == 0 and status.stdout.strip():
        return (
            f"{source_dir} is checked out at tag {claimed_tag!r}, but the working tree has "
            f"uncommitted changes or untracked files -- refusing to trust that the mined "
            f"content actually matches the tag:\n{status.stdout.rstrip()}"
        )
    return None


def _main() -> None:
    import argparse
    import dataclasses

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, help="Local checkout of RevitLookup, already at --tag")
    parser.add_argument("--tag", required=True, help="RevitLookup git tag this checkout is at (e.g. 2024.0.13) -- recorded verbatim, never inferred")
    parser.add_argument(
        "--out",
        required=True,
        help=(
            "Path to write the reference JSON to -- name it "
            "revitlookup_reference_<version>.json (e.g. revitlookup_reference_2024.json), matching "
            "ground_truth_manifest_<version>.json's own convention, since both are meant to be "
            "pulled out of outputs/revit_<version>/ and compared/shared standalone across versions"
        ),
    )
    args = parser.parse_args()

    source_dir = Path(args.source_dir)
    mismatch = verify_tag_match(source_dir, args.tag)
    if mismatch is not None:
        raise SystemExit(f"Error: {mismatch}")

    reference = mine_revitlookup_source(source_dir, revitlookup_tag=args.tag)
    Path(args.out).write_text(json.dumps(dataclasses.asdict(reference), indent=2), encoding="utf-8")

    total_resolved = sum(len(d.resolved_members) for d in reference.descriptors)
    total_extensions = sum(len(d.synthetic_extensions) for d in reference.descriptors)
    print(
        f"Wrote {args.out}: {len(reference.descriptor_map)} descriptor_map entries, "
        f"{len(reference.descriptors)} descriptor files ({total_resolved} resolved members, "
        f"{total_extensions} synthetic extensions)"
    )


if __name__ == "__main__":
    _main()
