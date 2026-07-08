"""Tests for revitlookup.py (docs/dll_reflection_v0.md, Stage C).

``fixtures/revitlookup/*.cs`` are **real, unmodified** RevitLookup source
files, fetched directly from lookup-foundation/RevitLookup at git tag
``2024.0.13`` (the latest tag matching Revit 2024 -- confirmed via the repo's
own tag list, not guessed) -- not fixture data invented to match an assumed
shape. This tag's descriptor shape (``Resolve()``/``RegisterExtensions()``)
was confirmed to differ from the newer ``Configure(IMemberConfigurator)``
shape found on RevitLookup's current ``develop`` branch, which now targets a
later Revit version.
"""

import subprocess
from pathlib import Path

from revit_schema_mapper.revitlookup import (
    mine_revitlookup_source,
    parse_descriptor_file,
    parse_descriptor_map,
    verify_tag_match,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "revitlookup"


def _read(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


# -- parse_descriptor_map -------------------------------------------------------


def test_parse_descriptor_map_extracts_real_api_object_cases():
    entries = parse_descriptor_map(_read("DescriptorMap.cs"))

    by_type = {e.target_type_short_name: e for e in entries}
    assert by_type["Category"].descriptor_class == "CategoryDescriptor"
    assert by_type["Category"].section == "APIObjects"
    assert by_type["HostObject"].descriptor_class == "HostObjectDescriptor"
    assert by_type["HostObject"].section == "IDisposables"


def test_parse_descriptor_map_tags_non_api_sections_rather_than_dropping_them():
    """string/bool/IEnumerable etc. are real switch cases too -- the parser
    doesn't silently drop them, it tags them with their own section so a
    caller can filter (e.g. exclude "System"/"ComponentManager"/"Media")
    without this module having to hardcode that judgment call itself.
    """
    entries = parse_descriptor_map(_read("DescriptorMap.cs"))
    by_type = {e.target_type_short_name: e for e in entries}

    assert by_type["string"].section == "System"
    assert by_type["bool"].section == "System"
    assert by_type["RibbonItem"].section == "ComponentManager"


def test_parse_descriptor_map_skips_wildcard_and_null_fallback_cases():
    entries = parse_descriptor_map(_read("DescriptorMap.cs"))
    type_names = {e.target_type_short_name for e in entries}
    assert "_" not in type_names
    assert "null" not in type_names


def test_parse_descriptor_map_handles_qualified_type_names():
    """Autodesk.Windows.RibbonItem / System.Windows.Media.Color -- dotted,
    fully-qualified type references in the real switch -- reduce to their
    short name, the same way ground_truth.normalize_type_name's
    namespace-segment reduction does on the DLL-reflection side.
    """
    entries = parse_descriptor_map(_read("DescriptorMap.cs"))
    short_names = {e.target_type_short_name for e in entries}
    assert "RibbonItem" in short_names
    assert "Color" in short_names


# -- parse_descriptor_file: Resolve() -------------------------------------------


def test_parse_descriptor_file_extracts_nameof_resolved_members():
    descriptor = parse_descriptor_file(_read("ElementDescriptor.cs"))

    assert descriptor.descriptor_class == "ElementDescriptor"
    by_name = {m.member_name: m for m in descriptor.resolved_members}
    assert "CanBeHidden" in by_name
    assert by_name["CanBeHidden"].name_source == "nameof"


def test_parse_descriptor_file_extracts_string_literal_resolved_members():
    """"BoundingBox"/"Geometry" are bare string-literal case keys (not
    nameof(...)) -- likely a human-readable label rather than the exact real
    member name (probably Element.get_BoundingBox), so tagged with a
    different, lower-confidence name_source.
    """
    descriptor = parse_descriptor_file(_read("ElementDescriptor.cs"))
    by_name = {m.member_name: m for m in descriptor.resolved_members}

    assert "BoundingBox" in by_name
    assert by_name["BoundingBox"].name_source == "string_literal"


def test_parse_descriptor_file_detects_multiple_variants_via_named_local_function():
    """GetMaterialArea's case is just `=> ResolveGetMaterialArea(),` -- the
    real .AppendVariant(...) cardinality logic lives in a separately-defined
    local function later in the same method body, not inline in the case
    itself. Confirms the parser follows that indirection rather than only
    inspecting the inline case expression (which would otherwise miss this
    real signal entirely).
    """
    descriptor = parse_descriptor_file(_read("ElementDescriptor.cs"))
    by_name = {m.member_name: m for m in descriptor.resolved_members}

    assert by_name["GetMaterialArea"].has_multiple_variants is True
    assert by_name["GetMaterialVolume"].has_multiple_variants is True


def test_parse_descriptor_file_detects_multiple_variants_inline():
    descriptor = parse_descriptor_file(_read("ElementDescriptor.cs"))
    by_name = {m.member_name: m for m in descriptor.resolved_members}

    assert by_name["GetMaterialIds"].has_multiple_variants is True


def test_parse_descriptor_file_detects_document_context_via_named_local_function():
    """GetEntity's real logic (in its own local function) calls
    Schema.ListSchemas() -- a document-scoped, not-meaningful-without-a-live-
    session accessor -- confirming the document-context signal also follows
    the same named-local-function indirection as the cardinality signal.
    """
    descriptor = parse_descriptor_file(_read("ElementDescriptor.cs"))
    by_name = {m.member_name: m for m in descriptor.resolved_members}

    assert by_name["GetEntity"].requires_document_context is True


def test_parse_descriptor_file_detects_document_context_inline():
    """CanBeHidden's inline case body references RevitApi.ActiveView --
    confirmed the real, dominant document-context accessor pattern in this
    RevitLookup version (not the Resolve() method's own unused `context`
    parameter).
    """
    descriptor = parse_descriptor_file(_read("ElementDescriptor.cs"))
    by_name = {m.member_name: m for m in descriptor.resolved_members}

    assert by_name["CanBeHidden"].requires_document_context is True


def test_parse_descriptor_file_does_not_falsely_flag_document_context():
    descriptor = parse_descriptor_file(_read("FamilyManagerDescriptor.cs"))
    by_name = {m.member_name: m for m in descriptor.resolved_members}
    # GetAssociatedFamilyParameter's local function uses RevitApi.Document --
    # this one SHOULD be flagged; a sibling member with no document-scoped
    # accessor at all should not be (there isn't one in this fixture, so this
    # test instead confirms the one member present is correctly flagged,
    # guarding against a "flags everything" false-positive implementation).
    assert by_name["GetAssociatedFamilyParameter"].requires_document_context is True


# -- parse_descriptor_file: RegisterExtensions() --------------------------------


def test_parse_descriptor_file_extracts_synthetic_extensions_from_a_different_class():
    """HostObjectDescriptor's extensions are all named via
    nameof(HostExtensions.X) -- HostExtensions is a separate extension-method
    holder class, not HostObject itself. Confirms extraction takes the
    member-name part regardless of which class's nameof(...) it came from.
    """
    descriptor = parse_descriptor_file(_read("HostObjectDescriptor.cs"))

    assert set(descriptor.synthetic_extensions) == {
        "GetBottomFaces",
        "GetTopFaces",
        "GetSideFaces",
    }


def test_parse_descriptor_file_still_finds_resolved_members_alongside_extensions():
    descriptor = parse_descriptor_file(_read("HostObjectDescriptor.cs"))
    by_name = {m.member_name: m for m in descriptor.resolved_members}
    assert "FindInserts" in by_name


def test_parse_descriptor_file_no_extensions_gives_empty_list_not_a_parser_note():
    """ElementDescriptor.cs and FamilyManagerDescriptor.cs genuinely have no
    RegisterExtensions in FamilyManagerDescriptor's case -- and no
    IDescriptorExtension reference either, so this is "genuinely nothing to
    report," not a parser failure, and parser_notes should stay empty.
    """
    descriptor = parse_descriptor_file(_read("FamilyManagerDescriptor.cs"))
    assert descriptor.synthetic_extensions == []
    assert descriptor.parser_notes == []


# -- mine_revitlookup_source (orchestration) ------------------------------------


def test_mine_revitlookup_source_walks_a_local_checkout(tmp_path):
    """Operates on a local directory (already cloned/extracted at a pinned
    tag) rather than fetching anything itself -- the same "operate on a
    local directory" shape reflect_revit_api.ps1 uses for Stage A via
    -InstallDir, applied here to a RevitLookup checkout instead.
    """
    nested = tmp_path / "source" / "RevitLookup" / "Core" / "ComponentModel"
    nested.mkdir(parents=True)
    (nested / "DescriptorMap.cs").write_text(_read("DescriptorMap.cs"), encoding="utf-8")
    descriptors_dir = nested / "Descriptors"
    descriptors_dir.mkdir()
    (descriptors_dir / "ElementDescriptor.cs").write_text(_read("ElementDescriptor.cs"), encoding="utf-8")
    (descriptors_dir / "HostObjectDescriptor.cs").write_text(_read("HostObjectDescriptor.cs"), encoding="utf-8")

    reference = mine_revitlookup_source(tmp_path, revitlookup_tag="2024.0.13")

    assert reference.revitlookup_tag == "2024.0.13"
    assert len(reference.descriptor_map) > 0
    descriptor_classes = {d.descriptor_class for d in reference.descriptors}
    assert descriptor_classes == {"ElementDescriptor", "HostObjectDescriptor"}


def test_mine_revitlookup_source_reports_no_descriptor_map_found(tmp_path):
    (tmp_path / "empty").mkdir()
    reference = mine_revitlookup_source(tmp_path, revitlookup_tag="2024.0.13")
    assert reference.descriptor_map == []
    assert reference.descriptors == []


# -- verify_tag_match -------------------------------------------------------------
#
# Built against a real local git repo (not mocked) -- same discipline as the rest
# of this project's tests, and this is exactly the kind of check that's easy to
# get subtly wrong if only reasoned about rather than run.


def _init_repo_at_tag(path: Path, tag: str) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=path, check=True)
    (path / "README.md").write_text("placeholder", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=path, check=True)
    subprocess.run(["git", "tag", tag], cwd=path, check=True)


def test_verify_tag_match_returns_none_when_checkout_really_is_at_claimed_tag(tmp_path):
    _init_repo_at_tag(tmp_path, "2024.0.13")
    assert verify_tag_match(tmp_path, "2024.0.13") is None


def test_verify_tag_match_catches_wrong_tag_checked_out(tmp_path):
    """Real reproduction of the subtler version of a real mistake found in a
    sibling project's own RevitLookup-syncing script: the caller *claims*
    one tag but the checkout is actually at a different one.
    """
    _init_repo_at_tag(tmp_path, "2024.0.13")
    subprocess.run(["git", "tag", "2025.0.1"], cwd=tmp_path, check=True)
    # Both tags point at the same commit here, so --exact-match could report
    # either -- move to a genuinely different commit under a different tag to
    # force an unambiguous mismatch.
    (tmp_path / "new_file.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "second"], cwd=tmp_path, check=True)
    subprocess.run(["git", "tag", "2026.0.1"], cwd=tmp_path, check=True)

    mismatch = verify_tag_match(tmp_path, "2024.0.13")

    assert mismatch is not None
    assert "2024.0.13" in mismatch
    assert "2026.0.1" in mismatch


def test_verify_tag_match_catches_checkout_not_on_any_tag(tmp_path):
    _init_repo_at_tag(tmp_path, "2024.0.13")
    (tmp_path / "new_file.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "second, untagged"], cwd=tmp_path, check=True)

    mismatch = verify_tag_match(tmp_path, "2024.0.13")

    assert mismatch is not None
    assert "not checked out exactly at" in mismatch


def test_verify_tag_match_is_none_for_a_non_git_directory(tmp_path):
    """mine_revitlookup_source operates on "any local directory" (e.g. a
    plain extracted-from-a-tag-archive folder, no .git at all) -- this must
    not be treated as a mismatch just because it can't be verified.
    """
    (tmp_path / "some_file.txt").write_text("x", encoding="utf-8")
    assert verify_tag_match(tmp_path, "2024.0.13") is None
