import json

import pytest

from revit_schema_mapper.crawl import CrawlConfig, Crawler, RobotsDisallowedError


def _prime_cache(crawler: Crawler, url: str, content: str) -> None:
    crawler.config.cache_dir.mkdir(parents=True, exist_ok=True)
    crawler._cache_path(url).write_text(content, encoding="utf-8")


def _namespace_tree() -> list[dict]:
    # Modeled on the real namespace_2024_min.json excerpt shared by a user
    # with live access -- see docs/crawl_notes.md.
    return [
        {
            "title": "Namespaces",
            "tag": "Namespace",
            "children": [
                {
                    "title": "Autodesk.Revit.ApplicationServices Namespace",
                    "tag": "Namespace",
                    "children": [
                        {"title": "Application Class", "href": "app-class.htm", "tag": "Class"},
                    ],
                },
                {
                    "title": "Autodesk.Revit.DB Namespace",
                    "tag": "Namespace",
                    "children": [
                        {
                            "title": "Wall Class",
                            "href": "wall-class.htm",
                            "tag": "Class",
                            "children": [
                                {"title": "Wall Members", "href": "wall-members.htm", "tag": "Members"},
                                {
                                    "title": "Wall Methods",
                                    "href": "wall-methods.htm",
                                    "tag": "Methods",
                                    "children": [
                                        {
                                            "title": "Create Method",
                                            "href": "create-overview.htm",
                                            "tag": "Method",
                                            "folder": True,
                                            "children": [
                                                {"title": "Create Method (Document, Curve)", "href": "create-1.htm", "tag": "Method"},
                                                {"title": "Create Method (Document, Curve, ElementId)", "href": "create-2.htm", "tag": "Method"},
                                            ],
                                        },
                                    ],
                                },
                                {
                                    "title": "Wall Properties",
                                    "href": "wall-properties.htm",
                                    "tag": "Properties",
                                    "children": [
                                        {"title": "Width Property", "href": "width-property.htm", "tag": "Property"},
                                    ],
                                },
                            ],
                        },
                    ],
                },
                {
                    "title": "Autodesk.Revit.DB.Architecture Namespace",
                    "tag": "Namespace",
                    "children": [
                        {"title": "Room Class", "href": "room-class.htm", "tag": "Class"},
                    ],
                },
            ],
        }
    ]


def test_discover_via_namespace_json_filters_by_namespace_and_flattens(tmp_path):
    config = CrawlConfig(version="2024", namespace_prefix="Autodesk.Revit.DB", cache_dir=tmp_path / "cache")
    crawler = Crawler(config)
    _prime_cache(crawler, crawler.namespace_json_url(), json.dumps(_namespace_tree()))

    entries, notes = crawler.discover_via_namespace_json()

    assert notes == []
    urls = {e["url"] for e in entries}

    # In scope: Autodesk.Revit.DB itself, including nested Members/Methods
    # and each overload of an overloaded method.
    assert "https://www.revitapidocs.com/2024/wall-class.htm" in urls
    assert "https://www.revitapidocs.com/2024/wall-members.htm" in urls
    assert "https://www.revitapidocs.com/2024/wall-methods.htm" in urls
    assert "https://www.revitapidocs.com/2024/create-overview.htm" in urls
    assert "https://www.revitapidocs.com/2024/create-1.htm" in urls
    assert "https://www.revitapidocs.com/2024/create-2.htm" in urls

    # In scope: a dotted sub-namespace of the configured prefix.
    assert "https://www.revitapidocs.com/2024/room-class.htm" in urls

    # Out of scope: a sibling namespace that doesn't match the prefix.
    assert "https://www.revitapidocs.com/2024/app-class.htm" not in urls

    wall_class_entry = next(e for e in entries if e["url"].endswith("wall-class.htm"))
    assert wall_class_entry["discovered_via"] == "namespace_json:Class"
    assert wall_class_entry["link_text"] == "Wall Class"

    # The bug this covers: a Property/Method page discovered directly via the
    # namespace JSON (never reached by following a class's Members-page link)
    # must still carry its declaring type, computed at flatten time.
    by_url = {e["url"]: e for e in entries}
    assert by_url["https://www.revitapidocs.com/2024/width-property.htm"]["declaring_type_hint"] == "Autodesk.Revit.DB.Wall"
    assert by_url["https://www.revitapidocs.com/2024/create-1.htm"]["declaring_type_hint"] == "Autodesk.Revit.DB.Wall"
    assert by_url["https://www.revitapidocs.com/2024/create-2.htm"]["declaring_type_hint"] == "Autodesk.Revit.DB.Wall"
    assert by_url["https://www.revitapidocs.com/2024/create-overview.htm"]["declaring_type_hint"] == "Autodesk.Revit.DB.Wall"
    # Sub-namespace types get their own (correct) declaring type, not the
    # enclosing prefix's.
    assert by_url["https://www.revitapidocs.com/2024/room-class.htm"].get("declaring_type_hint") == "Autodesk.Revit.DB.Architecture.Room"


def test_discover_via_namespace_json_no_matching_namespace(tmp_path):
    config = CrawlConfig(version="2024", namespace_prefix="Autodesk.Revit.DB", cache_dir=tmp_path / "cache")
    crawler = Crawler(config)
    tree = [{"title": "Namespaces", "children": [{"title": "SomeOther Namespace", "children": []}]}]
    _prime_cache(crawler, crawler.namespace_json_url(), json.dumps(tree))

    entries, notes = crawler.discover_via_namespace_json()

    assert entries == []
    assert len(notes) == 1
    assert "no namespace node" in notes[0]


def test_discover_targeted_finds_classes_across_namespaces_and_reports_missing(tmp_path):
    config = CrawlConfig(version="2024", namespace_prefix="Autodesk.Revit.DB", cache_dir=tmp_path / "cache")
    crawler = Crawler(config)
    _prime_cache(crawler, crawler.namespace_json_url(), json.dumps(_namespace_tree()))

    targets = [
        "Autodesk.Revit.ApplicationServices.Application",  # different namespace entirely
        "Autodesk.Revit.DB.Wall",
        "Autodesk.Revit.DB.Architecture.Room",  # sub-namespace
        "Autodesk.Revit.DB.DoesNotExist",  # deliberately missing
    ]

    entries, found, notes = crawler.discover_targeted(targets)

    assert found == {
        "Autodesk.Revit.ApplicationServices.Application": True,
        "Autodesk.Revit.DB.Wall": True,
        "Autodesk.Revit.DB.Architecture.Room": True,
        "Autodesk.Revit.DB.DoesNotExist": False,
    }
    assert len(notes) == 1
    assert "Autodesk.Revit.DB.DoesNotExist" in notes[0]

    urls = {e["url"] for e in entries}
    assert "https://www.revitapidocs.com/2024/app-class.htm" in urls
    assert "https://www.revitapidocs.com/2024/wall-class.htm" in urls
    assert "https://www.revitapidocs.com/2024/wall-members.htm" in urls
    assert "https://www.revitapidocs.com/2024/room-class.htm" in urls

    by_url = {e["url"]: e for e in entries}
    assert by_url["https://www.revitapidocs.com/2024/wall-properties.htm"]["declaring_type_hint"] == "Autodesk.Revit.DB.Wall"


def test_discover_targeted_all_missing(tmp_path):
    config = CrawlConfig(version="2024", namespace_prefix="Autodesk.Revit.DB", cache_dir=tmp_path / "cache")
    crawler = Crawler(config)
    _prime_cache(crawler, crawler.namespace_json_url(), json.dumps(_namespace_tree()))

    entries, found, notes = crawler.discover_targeted(["Autodesk.Revit.DB.Nope"])

    assert entries == []
    assert found == {"Autodesk.Revit.DB.Nope": False}
    assert any("not found" in n for n in notes)


def test_discover_index_merges_namespace_json_results(tmp_path):
    config = CrawlConfig(version="2024", namespace_prefix="Autodesk.Revit.DB", cache_dir=tmp_path / "cache")
    crawler = Crawler(config)
    _prime_cache(crawler, crawler.namespace_json_url(), json.dumps(_namespace_tree()))
    # Prime every fallback strategy's URL too (empty/no anchors) so this test
    # makes zero real network calls -- it only cares that discover_index
    # surfaces the namespace_json entries alongside whatever else runs.
    root_url = crawler.version_root_url()
    _prime_cache(crawler, root_url, "<html><body></body></html>")
    for toc_name in ("toc.js", "webtoc.xml", "toc.json", "toc.html"):
        _prime_cache(crawler, root_url + toc_name, "")
    _prime_cache(crawler, "https://www.revitapidocs.com/sitemap.xml", "")

    entries = crawler.discover_index()

    urls = {e["url"] for e in entries}
    assert "https://www.revitapidocs.com/2024/wall-class.htm" in urls


def test_discover_index_finds_urls_in_real_sitemap_xml(tmp_path):
    config = CrawlConfig(version="2024", namespace_prefix="Autodesk.Revit.DB", cache_dir=tmp_path / "cache")
    crawler = Crawler(config)
    _prime_cache(crawler, crawler.namespace_json_url(), json.dumps([]))
    root_url = crawler.version_root_url()
    _prime_cache(crawler, root_url, "<html><body></body></html>")
    for toc_name in ("toc.js", "webtoc.xml", "toc.json", "toc.html"):
        _prime_cache(crawler, root_url + toc_name, "")
    # A sitemap.xml lists pages as <url><loc>...</loc></url>, not <a href> --
    # this is genuine XML, not HTML with anchor tags.
    sitemap_xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        "<url><loc>https://www.revitapidocs.com/2024/wall-class.htm</loc></url>"
        "<url><loc>https://www.revitapidocs.com/2023/other-version.htm</loc></url>"
        "</urlset>"
    )
    _prime_cache(crawler, "https://www.revitapidocs.com/sitemap.xml", sitemap_xml)

    entries = crawler.discover_index()

    urls = {e["url"] for e in entries}
    assert "https://www.revitapidocs.com/2024/wall-class.htm" in urls
    assert "https://www.revitapidocs.com/2023/other-version.htm" not in urls


def test_links_from_sitemap_xml_ignores_malformed_content(tmp_path):
    config = CrawlConfig(version="2024", namespace_prefix="Autodesk.Revit.DB", cache_dir=tmp_path / "cache")
    crawler = Crawler(config)

    assert crawler._links_from_sitemap_xml("not xml at all", "https://www.revitapidocs.com/sitemap.xml") == {}


def test_fetch_raises_when_robots_txt_disallows_path(tmp_path):
    config = CrawlConfig(version="2024", namespace_prefix="Autodesk.Revit.DB", cache_dir=tmp_path / "cache")
    crawler = Crawler(config)
    crawler._parse_robots_text("User-agent: *\nDisallow: /2024/blocked-class.htm\n")

    with pytest.raises(RobotsDisallowedError):
        crawler.fetch("https://www.revitapidocs.com/2024/blocked-class.htm")


def test_fetch_allows_path_robots_txt_does_not_disallow(tmp_path, monkeypatch):
    """Exercises the real (non-cached) fetch path end-to-end -- including
    _ensure_robots_loaded and can_fetch -- for a URL robots.txt doesn't
    disallow, without making a real network call.
    """
    from revit_schema_mapper.http_compat import FetchResult

    config = CrawlConfig(version="2024", namespace_prefix="Autodesk.Revit.DB", cache_dir=tmp_path / "cache")
    crawler = Crawler(config)
    crawler._parse_robots_text("User-agent: *\nDisallow: /2024/blocked-class.htm\n")
    monkeypatch.setattr(crawler.client, "get", lambda url, timeout=30: FetchResult(text="<html></html>", status_code=200))

    assert crawler.fetch("https://www.revitapidocs.com/2024/allowed-class.htm") == "<html></html>"


def test_fetch_does_not_check_robots_txt_for_already_cached_urls(tmp_path):
    """Serving already-cached content doesn't re-hit the server, so it
    shouldn't require (or be blocked by) a robots.txt check.
    """
    config = CrawlConfig(version="2024", namespace_prefix="Autodesk.Revit.DB", cache_dir=tmp_path / "cache")
    crawler = Crawler(config)
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/wall-class.htm", "<html></html>")

    assert crawler.fetch("https://www.revitapidocs.com/2024/wall-class.htm") == "<html></html>"
    assert crawler._robots is None  # never touched -- cache hit returned before any robots check


def test_robots_txt_crawl_delay_raises_effective_throttle(tmp_path):
    config = CrawlConfig(version="2024", namespace_prefix="Autodesk.Revit.DB", cache_dir=tmp_path / "cache", throttle_seconds=1.0)
    crawler = Crawler(config)

    crawler._parse_robots_text("User-agent: *\nCrawl-delay: 5\n")

    assert crawler.config.throttle_seconds == 5.0


def test_robots_txt_unreachable_allows_fetch_rather_than_blocking_everything(tmp_path):
    """Regression test: urllib.robotparser.RobotFileParser.can_fetch() returns
    False unconditionally until .read() (not .parse()) sets last_checked, so
    naively doing `self._robots = RobotFileParser()` on a fetch failure (with
    no rules parsed and no allow_all set) silently disallowed every single
    fetch -- the opposite of the intended "treat unreachable robots.txt as
    unrestricted" behavior.
    """
    config = CrawlConfig(version="2024", namespace_prefix="Autodesk.Revit.DB", cache_dir=tmp_path / "cache")
    crawler = Crawler(config)

    # Do NOT prime robots.txt in the cache and do NOT call _parse_robots_text
    # -- _ensure_robots_loaded's real (network) fetch will fail in the test
    # sandbox, exercising the except branch.
    crawler._ensure_robots_loaded()

    assert crawler._robots is not None
    assert crawler._robots.can_fetch("AnyAgent/1.0", "https://www.revitapidocs.com/2024/wall-class.htm") is True


def test_parsed_robots_txt_with_no_matching_rules_allows_fetch(tmp_path):
    """Regression test for the same can_fetch()-needs-last_checked pitfall,
    on the success path: parsing real robots.txt text that simply doesn't
    disallow anything must not leave every URL blocked.
    """
    config = CrawlConfig(version="2024", namespace_prefix="Autodesk.Revit.DB", cache_dir=tmp_path / "cache")
    crawler = Crawler(config)

    crawler._parse_robots_text("User-agent: *\nDisallow:\n")

    assert crawler._robots.can_fetch(config.namespace_prefix, "https://www.revitapidocs.com/2024/wall-class.htm") is True


def test_robots_txt_crawl_delay_does_not_lower_configured_throttle(tmp_path):
    config = CrawlConfig(version="2024", namespace_prefix="Autodesk.Revit.DB", cache_dir=tmp_path / "cache", throttle_seconds=10.0)
    crawler = Crawler(config)

    crawler._parse_robots_text("User-agent: *\nCrawl-delay: 2\n")

    assert crawler.config.throttle_seconds == 10.0
