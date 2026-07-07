import json

from revit_schema_mapper.crawl import CrawlConfig, Crawler
from revit_schema_mapper.models import ClassRole
from revit_schema_mapper.pipeline import run_pipeline, run_targeted_pipeline

_CLASS_HTML = """
<html><body>
<h1 id="PageHeader">Widget Class</h1>
<div id="TopicPathClassic"><a href="/2024/ns_db.htm">Autodesk.Revit.DB</a> Namespace</div>
<div class="summary"><p>A test widget, not a real Revit type.</p></div>
<div class="syntax"><pre class="typeSignature">public class Widget : Element</pre></div>
</body></html>
"""
# Deliberately no members table and no table#bottomTable "Members" link --
# on the real site not every class page's sub-nav/member table is reachable
# this way; the Symbol property below must still resolve its declaring type
# from the namespace JSON alone.

_PROPERTIES_INDEX_HTML = """
<html><body>
<h4 id="api-title" class="truncate"> Widget Properties </h4>
<div id="mainBody">
<table class="members" id="memberList">
<tr><th>Icon</th><th>Name</th><th>Description</th></tr>
<tr><td><img></td><td><a href="symbol-property.htm">Symbol</a></td><td>Gets the FamilySymbol.</td></tr>
</table>
</div>
</body></html>
"""

_PROPERTY_HTML = """
<html><body>
<h4 id="api-title" class="truncate"> Symbol Property </h4>
<div id="mainBody">
<div class="summary"><p>Gets the FamilySymbol object.</p></div>
<div class="syntax"><pre class="typeSignature">public FamilySymbol Symbol { get; }</pre></div>
</div>
</body></html>
"""


def _prime_cache(crawler: Crawler, url: str, content: str) -> None:
    crawler.config.cache_dir.mkdir(parents=True, exist_ok=True)
    crawler._cache_path(url).write_text(content, encoding="utf-8")


def test_property_discovered_only_via_namespace_json_gets_declaring_type(tmp_path):
    """Regression test for the bug where a Property/Method page discovered
    directly via the namespace JSON (rather than by following a class's
    Members-page link) had no known declaring type and was silently skipped
    as a failed page -- see docs/crawl_notes.md.
    """
    output_dir = tmp_path / "output"
    config = CrawlConfig(version="2024", namespace_prefix="Autodesk.Revit.DB", cache_dir=output_dir / "cache")
    crawler = Crawler(config)

    tree = [
        {
            "title": "Namespaces",
            "children": [
                {
                    "title": "Autodesk.Revit.DB Namespace",
                    "tag": "Namespace",
                    "children": [
                        {
                            "title": "Widget Class",
                            "href": "widget-class.htm",
                            "tag": "Class",
                            "children": [
                                {
                                    "title": "Widget Properties",
                                    "href": "widget-properties.htm",
                                    "tag": "Properties",
                                    "children": [
                                        {"title": "Symbol Property", "href": "symbol-property.htm", "tag": "Property"},
                                    ],
                                },
                            ],
                        },
                    ],
                },
            ],
        }
    ]

    _prime_cache(crawler, crawler.namespace_json_url(), json.dumps(tree))
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/widget-class.htm", _CLASS_HTML)
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/widget-properties.htm", _PROPERTIES_INDEX_HTML)
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/symbol-property.htm", _PROPERTY_HTML)

    # Fallback HTML-scraping discovery strategies: prime as empty so this
    # test makes zero real network calls.
    root_url = crawler.version_root_url()
    _prime_cache(crawler, root_url, "<html><body></body></html>")
    for toc_name in ("toc.js", "webtoc.xml", "toc.json", "toc.html"):
        _prime_cache(crawler, root_url + toc_name, "")
    _prime_cache(crawler, "https://www.revitapidocs.com/sitemap.xml", "")

    result = run_pipeline(config, output_dir)

    assert "https://www.revitapidocs.com/2024/symbol-property.htm" not in result.failed_urls

    symbol_pages = [p for p in result.pages if p.full_type_name.endswith(".Symbol")]
    assert len(symbol_pages) == 1
    assert symbol_pages[0].declaring_type == "Autodesk.Revit.DB.Widget"


_VIEW_CLASS_HTML = """
<html><body>
<h1 id="PageHeader">View Class</h1>
<div id="TopicPathClassic"><a href="/2024/ns_db.htm">Autodesk.Revit.DB</a> Namespace</div>
<div class="summary"><p>Represents a view.</p></div>
<div class="syntax"><pre class="typeSignature">public class View : Element</pre></div>
</body></html>
"""

_VIEW_MEMBERS_HTML = """
<html><body>
<h4 id="api-title" class="truncate"> View Members </h4>
<div id="mainBody">
<table class="members" id="memberList">
<tr><th>Icon</th><th>Name</th><th>Description</th></tr>
<tr><td><img></td><td><a href="viewtemplateid-property.htm">ViewTemplateId</a></td><td>Gets or sets the view template.</td></tr>
</table>
</div>
</body></html>
"""

_VIEW_TEMPLATE_ID_PROPERTY_HTML = """
<html><body>
<h4 id="api-title" class="truncate"> ViewTemplateId Property </h4>
<div id="mainBody">
<div class="summary"><p>Gets or sets the id of the view template applied to this view.</p></div>
<div class="syntax"><pre class="typeSignature">public ElementId ViewTemplateId { get; set; }</pre></div>
</div>
</body></html>
"""


def test_run_targeted_pipeline_reports_found_and_missing_targets_and_known_edges(tmp_path):
    """End-to-end test for the targeted validation crawl: one target class
    that's fully crawlable/parseable, and one that doesn't exist in the
    namespace_json tree -- both must be reported clearly, plus a known-edge
    check that should resolve to a real classify.py-produced edge.
    """
    output_dir = tmp_path / "output"
    config = CrawlConfig(version="2024", namespace_prefix="Autodesk.Revit.DB", cache_dir=output_dir / "cache")
    crawler = Crawler(config)

    tree = [
        {
            "title": "Namespaces",
            "children": [
                {
                    "title": "Autodesk.Revit.DB Namespace",
                    "tag": "Namespace",
                    "children": [
                        {
                            "title": "View Class",
                            "href": "view-class.htm",
                            "tag": "Class",
                            "children": [
                                {"title": "View Members", "href": "view-members.htm", "tag": "Members"},
                            ],
                        },
                    ],
                },
            ],
        }
    ]

    _prime_cache(crawler, crawler.namespace_json_url(), json.dumps(tree))
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/view-class.htm", _VIEW_CLASS_HTML)
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/view-members.htm", _VIEW_MEMBERS_HTML)
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/viewtemplateid-property.htm", _VIEW_TEMPLATE_ID_PROPERTY_HTML)

    targets = ["Autodesk.Revit.DB.View", "Autodesk.Revit.DB.DoesNotExist"]
    known_edge_checks = [
        ("Autodesk.Revit.DB.View", "ViewTemplateId"),
        ("Autodesk.Revit.DB.DoesNotExist", "SomeProperty"),
    ]

    result = run_targeted_pipeline(config, output_dir, target_full_type_names=targets, known_edge_checks=known_edge_checks)

    by_target = {t.full_type_name: t for t in result.target_report}
    assert by_target["Autodesk.Revit.DB.View"].found_in_namespace_json is True
    assert by_target["Autodesk.Revit.DB.View"].class_page_parsed is True
    assert by_target["Autodesk.Revit.DB.View"].member_pages_parsed == 1
    assert by_target["Autodesk.Revit.DB.View"].reason is None

    assert by_target["Autodesk.Revit.DB.DoesNotExist"].found_in_namespace_json is False
    assert by_target["Autodesk.Revit.DB.DoesNotExist"].class_page_parsed is False
    assert "not found" in by_target["Autodesk.Revit.DB.DoesNotExist"].reason

    by_check = {(k.declaring_type, k.member_name): k for k in result.known_edge_report}
    view_template_check = by_check[("Autodesk.Revit.DB.View", "ViewTemplateId")]
    assert view_template_check.member_found is True
    assert view_template_check.edge_produced is True
    assert view_template_check.edge_type == "CONTROLLED_BY_TEMPLATE"
    assert view_template_check.edge_confidence == "elementid_with_strong_name"

    missing_check = by_check[("Autodesk.Revit.DB.DoesNotExist", "SomeProperty")]
    assert missing_check.member_found is False
    assert missing_check.edge_produced is False

    # View derives from Element -> should be classified as an element subtype.
    view_node = next(n for n in result.node_candidates if n.full_type_name == "Autodesk.Revit.DB.View")
    assert view_node.class_role is ClassRole.ELEMENT_SUBTYPE

    # Output files land on disk.
    assert (output_dir / "target_report.json").exists()
    assert (output_dir / "known_edge_report.json").exists()
    assert (output_dir / "validation_summary.md").exists()
