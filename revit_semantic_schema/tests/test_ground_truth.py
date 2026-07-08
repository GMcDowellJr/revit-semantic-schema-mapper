"""Tests for ground_truth.py (docs/dll_reflection_v0.md, Stage B).

``fixtures/ground_truth_manifest_2024.json`` is a **synthetic** manifest,
hand-authored to match Stage A's documented output schema -- it was never
produced by reflecting over a real compiled RevitAPI.dll, because no such
reflection has ever run in this project. Its values are chosen to be
*plausible*, several directly informed by real findings recorded in
docs/crawl_notes.md (e.g. Material's real Cut/SurfaceBackground/Foreground
PatternId properties, Room.Number's declaring type, the Element.ChangeTypeId
overload pair) -- but those findings themselves came from a live crawl of
revitapidocs.com's HTML, not from DLL reflection. Docs and the compiled API
disagreeing is the entire reason Stage A exists, so nothing in this fixture
should be read as a confirmed fact about the real Revit API: it only
verifies that cross_validate_dll's diffing logic is correct against *some*
schema-conformant manifest, independent of whether that manifest's content
ever matches a real one.
"""

from pathlib import Path

import pytest

from revit_schema_mapper import ground_truth
from revit_schema_mapper.ground_truth import (
    EdgeVerificationStatus,
    ManifestMember,
    ManifestType,
    TypeVerificationStatus,
    cross_validate_dll,
    load_manifest,
    normalize_type_name,
)
from revit_schema_mapper.models import (
    ClassRole,
    ConfidenceLabel,
    EdgeCandidate,
    EdgeType,
    IsElementCandidate,
    Kind,
    MemberKind,
    NodeCandidate,
)

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ground_truth_manifest_2024.json"


def _node(full_type_name: str) -> NodeCandidate:
    return NodeCandidate(
        full_type_name=full_type_name,
        short_name=full_type_name.rsplit(".", 1)[-1],
        kind=Kind.CLASS,
        namespace=full_type_name.rsplit(".", 1)[0],
        base_type=None,
        inheritance_chain=[],
        is_element_candidate=IsElementCandidate.UNKNOWN,
        class_role=ClassRole.UNKNOWN,
        evidence=[],
        source_url="https://www.revitapidocs.com/2024/x.htm",
    )


def _edge(
    source_type: str,
    member_name: str,
    return_type: str | None,
    *,
    parameter_types: list[str] | None = None,
    member_kind: MemberKind = MemberKind.PROPERTY,
) -> EdgeCandidate:
    return EdgeCandidate(
        source_type=source_type,
        member_name=member_name,
        member_kind=member_kind,
        raw_signature=f"{member_name}()",
        return_type=return_type,
        parameter_types=parameter_types or [],
        candidate_target_type=return_type,
        candidate_edge_type=EdgeType.REFERENCES,
        edge_confidence=ConfidenceLabel.DIRECT_RETURN_TYPE,
        evidence=[],
        source_url="https://www.revitapidocs.com/2024/x.htm",
    )


# -- normalize_type_name -------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, ""),
        ("", ""),
        ("ElementId", "ElementId"),
        ("Autodesk.Revit.DB.ElementId", "ElementId"),
        ("ICollection(ElementId)", "ICollection<ElementId>"),
        ("System.Collections.Generic.ICollection`1[Autodesk.Revit.DB.ElementId]", "ICollection<ElementId>"),
        (
            "System.Collections.Generic.ICollection`1[[Autodesk.Revit.DB.ElementId, RevitAPI, "
            "Version=1.0.0.0, Culture=neutral, PublicKeyToken=null]]",
            "ICollection<ElementId>",
        ),
    ],
)
def test_normalize_type_name(raw, expected):
    assert normalize_type_name(raw) == expected


# -- load_manifest --------------------------------------------------------------


def test_load_manifest_parses_fixture():
    manifest = load_manifest(_FIXTURE_PATH)
    assert manifest.revit_version == "2024"
    assert manifest.namespace_prefix == "Autodesk.Revit.DB"
    assert {t.full_type_name for t in manifest.types} >= {
        "Autodesk.Revit.DB.Element",
        "Autodesk.Revit.DB.Architecture.Room",
        "Autodesk.Revit.DB.FamilyInstance",
    }
    room = next(t for t in manifest.types if t.full_type_name == "Autodesk.Revit.DB.Architecture.Room")
    assert room.inheritance_chain == ["Autodesk.Revit.DB.SpatialElement", "Autodesk.Revit.DB.Element"]
    view_sheet = next(t for t in manifest.types if t.full_type_name == "Autodesk.Revit.DB.ViewSheet")
    assert view_sheet.members[0].name == "GetAllPlacedViews"


# -- cross_validate_dll ---------------------------------------------------------


@pytest.fixture()
def manifest():
    return load_manifest(_FIXTURE_PATH)


def test_type_confirmed_exact_match(manifest):
    node = _node("Autodesk.Revit.DB.Material")
    report = cross_validate_dll([node], [], manifest)

    assert node.dll_type_verified is True
    assert report.type_results[0].status is TypeVerificationStatus.CONFIRMED
    assert report.type_results[0].resolution == "exact"


def test_type_confirmed_via_short_name_fallback(manifest):
    """Mirrors the confirmed real mismatch (graph._Resolver's docstring):
    an edge/node can carry Autodesk.Revit.DB.Room while the manifest (like
    the real crawl) has the fully-qualified Autodesk.Revit.DB.Architecture.Room.
    """
    node = _node("Autodesk.Revit.DB.Room")
    report = cross_validate_dll([node], [], manifest)

    assert node.dll_type_verified is True
    result = report.type_results[0]
    assert result.status is TypeVerificationStatus.CONFIRMED
    assert result.resolution == "short_name_fallback"
    assert result.matched_manifest_type == "Autodesk.Revit.DB.Architecture.Room"


def test_type_doc_only_when_not_in_manifest(manifest):
    node = _node("Autodesk.Revit.DB.RoomTag")
    report = cross_validate_dll([node], [], manifest)

    assert node.dll_type_verified is False
    assert report.type_results[0].status is TypeVerificationStatus.DOC_ONLY


def test_dll_only_types_lists_unmatched_manifest_types(manifest):
    # No NodeCandidate at all claims Autodesk.Revit.DB.WorksetId.
    report = cross_validate_dll([_node("Autodesk.Revit.DB.Material")], [], manifest)

    assert "Autodesk.Revit.DB.WorksetId" in report.dll_only_types


def test_edge_signature_confirmed_declared(manifest):
    node = _node("Autodesk.Revit.DB.FamilyInstance")
    edge = _edge("Autodesk.Revit.DB.FamilyInstance", "Symbol", "Autodesk.Revit.DB.FamilySymbol")
    report = cross_validate_dll([node], [edge], manifest)

    assert edge.dll_signature_verified is True
    assert edge.dll_relationship_scope == "declared"
    assert edge.dll_verified_status == "signature_verified_declared"
    assert report.edge_results[0].status is EdgeVerificationStatus.SIGNATURE_CONFIRMED


def test_edge_signature_confirmed_inherited_via_ancestor_walk(manifest):
    """Room.Number: the manifest's Room entry declares zero members of its
    own (forcing the inheritance_chain ancestor walk, not the flattened
    per-type members list) and Number is really declared on SpatialElement,
    two levels up -- the exact Room.Number finding from crawl_notes.md.
    """
    node = _node("Autodesk.Revit.DB.Room")  # deliberately short-qualified, see above
    edge = _edge("Autodesk.Revit.DB.Room", "Number", "System.String")
    report = cross_validate_dll([node], [edge], manifest)

    assert edge.dll_signature_verified is True
    assert edge.dll_relationship_scope == "inherited"
    assert edge.dll_verified_status == "signature_verified_inherited"
    result = report.edge_results[0]
    assert result.actual_declaring_type == "Autodesk.Revit.DB.SpatialElement"


def test_edge_signature_mismatch(manifest):
    node = _node("Autodesk.Revit.DB.FamilySymbol")
    # Real return type is Family, not FamilyInstance -- deliberately wrong.
    edge = _edge("Autodesk.Revit.DB.FamilySymbol", "Family", "Autodesk.Revit.DB.FamilyInstance")
    report = cross_validate_dll([node], [edge], manifest)

    assert edge.dll_signature_verified is False
    assert edge.dll_relationship_scope == "declared"
    assert edge.dll_verified_status == "signature_mismatch"
    assert report.edge_results[0].status is EdgeVerificationStatus.SIGNATURE_MISMATCH
    assert report.edge_results[0].actual_return_type == "Autodesk.Revit.DB.Family"


def test_edge_member_not_found_on_confirmed_type(manifest):
    """The exact Material.SurfacePatternId finding from crawl_notes.md: the
    real API only has Cut/SurfaceBackground/ForegroundPatternId.
    """
    node = _node("Autodesk.Revit.DB.Material")
    edge = _edge("Autodesk.Revit.DB.Material", "SurfacePatternId", "Autodesk.Revit.DB.ElementId")
    report = cross_validate_dll([node], [edge], manifest)

    assert edge.dll_signature_verified is False
    assert edge.dll_relationship_scope is None
    assert edge.dll_verified_status == "member_not_found"
    assert report.edge_results[0].status is EdgeVerificationStatus.MEMBER_NOT_FOUND


def test_edge_member_not_found_when_source_type_itself_is_doc_only(manifest):
    node = _node("Autodesk.Revit.DB.RoomTag")
    edge = _edge("Autodesk.Revit.DB.RoomTag", "TaggedLocalRoomId", "Autodesk.Revit.DB.ElementId")
    report = cross_validate_dll([node], [edge], manifest)

    assert edge.dll_signature_verified is False
    assert report.edge_results[0].status is EdgeVerificationStatus.MEMBER_NOT_FOUND
    assert "DOC_ONLY" in report.edge_results[0].note


def test_edge_signature_confirmed_with_generic_normalization(manifest):
    """docs form ICollection(ElementId) vs. the manifest's real CLR
    reflection form (assembly-qualified generic) must normalize to the same
    canonical shape rather than falsely reporting SIGNATURE_MISMATCH.
    """
    node = _node("Autodesk.Revit.DB.ViewSheet")
    edge = _edge(
        "Autodesk.Revit.DB.ViewSheet",
        "GetAllPlacedViews",
        "ICollection(ElementId)",
        member_kind=MemberKind.METHOD,
    )
    report = cross_validate_dll([node], [edge], manifest)

    assert edge.dll_signature_verified is True
    assert edge.dll_relationship_scope == "declared"
    assert report.edge_results[0].status is EdgeVerificationStatus.SIGNATURE_CONFIRMED


# -- overload handling ----------------------------------------------------------
#
# Element.ChangeTypeId is a real overloaded method (docs/crawl_notes.md) with
# two manifest entries sharing the same name: a single-ElementId instance
# overload and a static Document/ICollection<ElementId>/ElementId overload.
# The multi-arg static overload is listed *first* in the fixture JSON
# deliberately, so these tests fail if the code ever goes back to using
# whichever same-named member happens to come first in the manifest.


def test_edge_matches_correct_overload_by_parameter_types(manifest):
    node = _node("Autodesk.Revit.DB.Element")
    edge = _edge(
        "Autodesk.Revit.DB.Element",
        "ChangeTypeId",
        "Autodesk.Revit.DB.ElementId",
        parameter_types=["Autodesk.Revit.DB.ElementId"],
        member_kind=MemberKind.METHOD,
    )
    report = cross_validate_dll([node], [edge], manifest)

    assert edge.dll_signature_verified is True
    assert edge.dll_relationship_scope == "declared"
    result = report.edge_results[0]
    assert result.status is EdgeVerificationStatus.SIGNATURE_CONFIRMED
    assert result.actual_return_type == "Autodesk.Revit.DB.ElementId"


def test_edge_matches_other_overload_by_parameter_types(manifest):
    """Same member_name as the test above, but the *other* overload's shape
    -- and normalizes a docs-form generic collection arg while doing it.
    """
    node = _node("Autodesk.Revit.DB.Element")
    edge = _edge(
        "Autodesk.Revit.DB.Element",
        "ChangeTypeId",
        "ICollection(ElementId)",
        parameter_types=["Autodesk.Revit.DB.Document", "ICollection(ElementId)", "Autodesk.Revit.DB.ElementId"],
        member_kind=MemberKind.METHOD,
    )
    report = cross_validate_dll([node], [edge], manifest)

    assert edge.dll_signature_verified is True
    result = report.edge_results[0]
    assert result.status is EdgeVerificationStatus.SIGNATURE_CONFIRMED
    assert "2 overload(s)" in result.note


def test_edge_overload_mismatch_when_no_overload_matches(manifest):
    """Neither ChangeTypeId overload takes a single System.String -- this
    must report SIGNATURE_MISMATCH, not accidentally match either overload.
    """
    node = _node("Autodesk.Revit.DB.Element")
    edge = _edge(
        "Autodesk.Revit.DB.Element",
        "ChangeTypeId",
        "Autodesk.Revit.DB.ElementId",
        parameter_types=["System.String"],
        member_kind=MemberKind.METHOD,
    )
    report = cross_validate_dll([node], [edge], manifest)

    assert edge.dll_signature_verified is False
    assert edge.dll_verified_status == "signature_mismatch"
    result = report.edge_results[0]
    assert result.status is EdgeVerificationStatus.SIGNATURE_MISMATCH
    assert "2 overload(s)" in result.note


def test_dll_semantic_verified_is_never_set(manifest):
    """Reserved field -- docs/dll_reflection_v0.md is explicit this stays
    untouched until a later runtime-verification stage exists.
    """
    node = _node("Autodesk.Revit.DB.FamilyInstance")
    edge = _edge("Autodesk.Revit.DB.FamilyInstance", "Symbol", "Autodesk.Revit.DB.FamilySymbol")
    cross_validate_dll([node], [edge], manifest)

    assert edge.dll_semantic_verified is None
