"""Tests for ground_truth.py (docs/dll_reflection_v0.md, Stage B).

``fixtures/ground_truth_manifest_2024.json`` was originally a **synthetic** manifest,
hand-authored to match Stage A's documented output schema before any real reflection had
ever run in this project. `reflect_revit_api.ps1` has since run for real against an actual
Revit 2024 install (see docs/crawl_notes.md), and a few of this fixture's originally-guessed
values turned out to disagree with the real compiled API -- corrected here to the confirmed
real values rather than left as plausible-but-wrong:

- ``Material``'s real ``Cut``/``Surface``/``Background``/``ForegroundPatternId`` properties
  and ``Room.Number``'s real declaring type (``SpatialElement``) were both originally guessed
  correctly (confirmed unchanged).
- ``Element.ChangeTypeId``'s static overload really returns
  ``IDictionary<ElementId,ElementId>`` (an old-to-new id map), not the originally-guessed
  ``ICollection<ElementId>``.
- ``ViewSheet.GetAllPlacedViews`` really returns ``ISet<ElementId>``, not the
  originally-guessed ``ICollection<ElementId>``.

Everything else in this fixture remains unconfirmed against the real API and should still be
read as plausible-but-not-verified, not fact -- this fixture verifies cross_validate_dll's
diffing logic against a schema-conformant manifest, not the real Revit API's actual shape,
except for the specific fields called out above.
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
        # Real multi-type-argument generic (Element.ChangeTypeId's static overload really
        # returns this -- confirmed against a real Revit 2024 manifest, see the module
        # docstring), in the flat Type.ToString() form reflect_revit_api.ps1 actually emits.
        (
            "System.Collections.Generic.IDictionary`2[Autodesk.Revit.DB.ElementId,Autodesk.Revit.DB.ElementId]",
            "IDictionary<ElementId,ElementId>",
        ),
        # The same real type, in the comma-space docs-prose form Sandcastle commonly uses
        # between generic arguments (crawl_notes.md's confirmed real title text,
        # "ChangeTypeId Method (Document, ICollection(ElementId), ElementId)", uses the same
        # comma-space convention) -- must normalize identically to the reflection form above,
        # not be treated as a different type purely over whitespace.
        ("IDictionary(ElementId, ElementId)", "IDictionary<ElementId,ElementId>"),
        # void canonicalization: classify.classify_member preserves the docs-parsed literal
        # C# return type "void" for a void method whose name still matches a relationship
        # keyword (e.g. SetMaterialId/SetDefaultFamilyTypeId), while
        # reflect_revit_api.ps1 maps a real void method's reflected return type to manifest
        # return_type: null -- both must normalize to the same "" or a real void method
        # falsely reports SIGNATURE_MISMATCH.
        ("void", ""),
        ("System.Void", ""),
        # A by-ref (out/ref) parameter: reflect_revit_api.ps1 emits "out <FullTypeName>" /
        # "ref <FullTypeName>" (ParameterInfo.IsOut + GetElementType()), matching how
        # parse.py's _parse_member_signature keeps the C# out/ref keyword as part of the
        # docs-side parameter type string (e.g. "out ModelCurveArray") -- this is a plain
        # pass-through of the existing namespace-reduction logic, not new special-casing.
        ("out Autodesk.Revit.DB.ModelCurveArray", "out ModelCurveArray"),
        ("out ModelCurveArray", "out ModelCurveArray"),
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


def test_load_manifest_tolerates_leading_utf8_bom(tmp_path):
    """Windows PowerShell 5.1's Set-Content/Out-File -Encoding utf8 always prepends a BOM
    (Microsoft's about_character_encoding docs confirm this is unconditional on that host) --
    a manifest written that way, or hand-edited in an editor that defaults to BOM-prefixed
    UTF-8, must still parse rather than failing with json.loads' "Unexpected UTF-8 BOM".
    reflect_revit_api.ps1 itself now writes without a BOM either way, but this loader stays
    tolerant of one regardless of what produced the file.
    """
    bom_path = tmp_path / "manifest_with_bom.json"
    bom_path.write_bytes(b"\xef\xbb\xbf" + _FIXTURE_PATH.read_bytes())

    manifest = load_manifest(bom_path)

    assert manifest.revit_version == "2024"
    assert {t.full_type_name for t in manifest.types} >= {"Autodesk.Revit.DB.Element"}


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
    """docs form ISet(ElementId) vs. the manifest's real CLR reflection form
    (Type.ToString(), e.g. "ISet`1[...]") must normalize to the same
    canonical shape rather than falsely reporting SIGNATURE_MISMATCH. (A
    real Revit 2024 run confirmed GetAllPlacedViews actually returns
    ISet<ElementId>, not the originally-guessed ICollection<ElementId> --
    see the module docstring.)
    """
    node = _node("Autodesk.Revit.DB.ViewSheet")
    edge = _edge(
        "Autodesk.Revit.DB.ViewSheet",
        "GetAllPlacedViews",
        "ISet(ElementId)",
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
# overload (returning ElementId) and a static
# Document/ICollection<ElementId>/ElementId overload -- which a real Revit
# 2024 run confirmed returns IDictionary<ElementId,ElementId> (an
# old-to-new id map), not the originally-guessed ICollection<ElementId>; see
# the module docstring. The multi-arg static overload is listed *first* in
# the fixture JSON deliberately, so these tests fail if the code ever goes
# back to using whichever same-named member happens to come first in the
# manifest.


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
    -- and normalizes both a docs-form generic collection arg (the
    ICollection(ElementId) parameter) and, more importantly, a real
    multi-type-argument generic *return* type
    (IDictionary(ElementId, ElementId), confirmed real -- see the module
    docstring) written with the comma-space docs prose commonly uses
    between generic arguments, vs. the manifest's comma-only reflection
    form -- these must normalize to the same shape rather than falsely
    reporting SIGNATURE_MISMATCH purely over comma-spacing.
    """
    node = _node("Autodesk.Revit.DB.Element")
    edge = _edge(
        "Autodesk.Revit.DB.Element",
        "ChangeTypeId",
        "IDictionary(ElementId, ElementId)",
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


# -- void return / by-ref parameter canonicalization ----------------------------


def test_edge_signature_confirmed_for_void_method_matched_by_keyword(manifest):
    """A void method whose *name* still matches a relationship keyword (e.g.
    SetMaterialId/SetDefaultFamilyTypeId) is still emitted as an EdgeCandidate by
    classify.classify_member, with the docs-parsed literal C# return type "void"
    preserved verbatim (classify.py's PRIMITIVE_TYPES set treats "void" as a real
    string, not a missing value) -- while reflect_revit_api.ps1 maps a real void
    method's reflected return type to manifest return_type: null. Confirmed on a
    real Revit 2024 run that this mismatch falsely reported SIGNATURE_MISMATCH.
    """
    node = _node("Autodesk.Revit.DB.Element")
    edge = _edge(
        "Autodesk.Revit.DB.Element",
        "SetWorksetId",
        "void",
        parameter_types=["Autodesk.Revit.DB.WorksetId"],
        member_kind=MemberKind.METHOD,
    )
    report = cross_validate_dll([node], [edge], manifest)

    assert edge.dll_signature_verified is True
    assert report.edge_results[0].status is EdgeVerificationStatus.SIGNATURE_CONFIRMED


def test_edge_signature_confirmed_for_out_parameter(manifest):
    """docs form "out ModelCurveArray" (parse.py keeps the C# out/ref keyword as
    part of the parameter type string) vs. the manifest's real by-ref reflection
    form must normalize to the same canonical shape. reflect_revit_api.ps1 emits
    "out <FullTypeName>" (via ParameterInfo.IsOut + ParameterType.GetElementType())
    rather than the bare CLR "<FullTypeName>&" ToString() form for this reason --
    confirmed on a real Revit 2024 run that the bare "&" form falsely reported
    SIGNATURE_MISMATCH for every out/ref overload.
    """
    node = _node("Autodesk.Revit.DB.Element")
    edge = _edge(
        "Autodesk.Revit.DB.Element",
        "TryGetModelCurves",
        "System.Boolean",
        parameter_types=["out ModelCurveArray"],
        member_kind=MemberKind.METHOD,
    )
    report = cross_validate_dll([node], [edge], manifest)

    assert edge.dll_signature_verified is True
    assert report.edge_results[0].status is EdgeVerificationStatus.SIGNATURE_CONFIRMED


def test_dll_semantic_verified_is_never_set(manifest):
    """Reserved field -- docs/dll_reflection_v0.md is explicit this stays
    untouched until a later runtime-verification stage exists.
    """
    node = _node("Autodesk.Revit.DB.FamilyInstance")
    edge = _edge("Autodesk.Revit.DB.FamilyInstance", "Symbol", "Autodesk.Revit.DB.FamilySymbol")
    cross_validate_dll([node], [edge], manifest)

    assert edge.dll_semantic_verified is None
