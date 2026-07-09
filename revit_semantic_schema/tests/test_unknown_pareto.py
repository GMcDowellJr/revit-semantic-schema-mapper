from revit_schema_mapper.unknown_pareto import _normalize_member_name, build_report


def _edge(edge_type, target=None, member_name="Member", source_type="Autodesk.Revit.DB.Thing",
          confidence="unknown_reference", revitlookup=None, dll_status=None):
    return {
        "source_type": source_type,
        "member_name": member_name,
        "candidate_edge_type": edge_type,
        "candidate_target_type": target,
        "edge_confidence": confidence,
        "revitlookup_referenced": revitlookup,
        "dll_verified_status": dll_status,
    }


def test_normalize_member_name_clusters_get_and_id_variants():
    assert _normalize_member_name("OwnerViewId") == "OwnerView"
    assert _normalize_member_name("GetOwnerViewId") == "OwnerView"
    assert _normalize_member_name("SetOwnerViewId") == "OwnerView"


def test_unknown_edge_share_and_top_level_counts():
    edges = [
        _edge("UNKNOWN_DB_OBJECT_REFERENCE", target="Autodesk.Revit.DB.Category"),
        _edge("HAS_CATEGORY", target="Autodesk.Revit.DB.Category", confidence="elementid_with_strong_name"),
    ]
    report = build_report(edges)

    assert report["total_edges"] == 2
    assert report["unknown_edge_count"] == 1
    assert report["unknown_edge_share"] == 0.5
    assert report["top_level_edge_type_counts"]["UNKNOWN_DB_OBJECT_REFERENCE"] == 1


def test_unknown_db_object_reference_clusters_by_bare_target_type():
    edges = [
        _edge("UNKNOWN_DB_OBJECT_REFERENCE", target="Autodesk.Revit.DB.PlanTopology", member_name="GetTopology", source_type="A"),
        _edge("UNKNOWN_DB_OBJECT_REFERENCE", target="Autodesk.Revit.DB.PlanTopology", member_name="GetTopology", source_type="B"),
        _edge("UNKNOWN_DB_OBJECT_REFERENCE", target="Autodesk.Revit.DB.Category", member_name="AssignedCategory", source_type="C"),
    ]
    report = build_report(edges)
    clusters = {c.key: c for c in report["clusters"]["UNKNOWN_DB_OBJECT_REFERENCE"]}

    assert clusters["PlanTopology"].count == 2
    assert clusters["PlanTopology"].source_types == {"A", "B"}
    assert clusters["Category"].count == 1


def test_unknown_elementid_reference_clusters_by_normalized_member_name():
    edges = [
        _edge("UNKNOWN_ELEMENTID_REFERENCE", member_name="OwnerViewId", source_type="A"),
        _edge("UNKNOWN_ELEMENTID_REFERENCE", member_name="GetOwnerViewId", source_type="B"),
        _edge("UNKNOWN_ELEMENTID_REFERENCE", member_name="TypeId", source_type="C"),
    ]
    report = build_report(edges)
    clusters = {c.key: c for c in report["clusters"]["UNKNOWN_ELEMENTID_REFERENCE"]}

    assert clusters["OwnerView"].count == 2
    assert clusters["Type"].count == 1


def test_needs_runtime_validation_is_tracked_as_a_separate_axis():
    """An edge can be both UNKNOWN_DB_OBJECT_REFERENCE and
    needs_runtime_validation -- confidence_model_v0.md is explicit this is a
    distinct verifiability axis, not a rung on the confidence ladder, so it
    must be counted independently rather than folded into the edge-type
    clusters."""
    edges = [
        _edge("UNKNOWN_DB_OBJECT_REFERENCE", target="Autodesk.Revit.DB.Thing", confidence="needs_runtime_validation"),
    ]
    report = build_report(edges)

    assert report["needs_runtime_validation_count"] == 1
    assert len(report["needs_runtime_validation_clusters"]) == 1
    assert report["needs_runtime_validation_clusters"][0].key == "Thing"


def test_revitlookup_and_dll_signals_are_counted_per_cluster():
    edges = [
        _edge("UNKNOWN_DB_OBJECT_REFERENCE", target="Autodesk.Revit.DB.Category", revitlookup=True),
        _edge("UNKNOWN_DB_OBJECT_REFERENCE", target="Autodesk.Revit.DB.Category", dll_status="member_not_found"),
    ]
    report = build_report(edges)
    cluster = report["clusters"]["UNKNOWN_DB_OBJECT_REFERENCE"][0]

    assert cluster.revitlookup_referenced_count == 1
    assert cluster.dll_member_not_found_count == 1
