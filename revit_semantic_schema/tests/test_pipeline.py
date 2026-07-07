import json

import pytest

from revit_schema_mapper import export
from revit_schema_mapper import pipeline as pipeline_module
from revit_schema_mapper.crawl import CrawlConfig, Crawler
from revit_schema_mapper.models import (
    ApiPage,
    ClassRole,
    ConfidenceLabel,
    EdgeCandidate,
    EdgeType,
    IsElementCandidate,
    Kind,
    MemberInfo,
    MemberKind,
    NodeCandidate,
)
from revit_schema_mapper.pipeline import (
    _build_known_edge_report,
    _crawl_and_parse,
    run_discovery,
    run_graph_only,
    run_pipeline,
    run_targeted_pipeline,
)

_WIDGET_NAMESPACE_TREE = [
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


def test_run_discovery_reports_page_count_without_fetching_pages(tmp_path):
    """run_discovery should report the full page count discover_index finds
    (e.g. so a user can gauge a full run's scale up front) without fetching
    any of the individual class/property/method pages themselves.
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
    root_url = crawler.version_root_url()
    _prime_cache(crawler, root_url, "<html><body></body></html>")
    for toc_name in ("toc.js", "webtoc.xml", "toc.json", "toc.html"):
        _prime_cache(crawler, root_url + toc_name, "")
    _prime_cache(crawler, "https://www.revitapidocs.com/sitemap.xml", "")
    # Deliberately do NOT prime widget-class.htm/widget-properties.htm/
    # symbol-property.htm -- discovery must not need to fetch them.

    result = run_discovery(config, output_dir)

    urls = {e["url"] for e in result.raw_index_entries}
    assert urls == {
        "https://www.revitapidocs.com/2024/widget-class.htm",
        "https://www.revitapidocs.com/2024/widget-properties.htm",
        "https://www.revitapidocs.com/2024/symbol-property.htm",
    }
    assert result.counts_by_source["namespace_json"] == 3
    assert (output_dir / "raw_index.json").exists()


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


def test_crawl_and_parse_calls_checkpoint_periodically_with_growing_state(tmp_path):
    """checkpoint() must be called multiple times during a crawl (not just
    once at the very end) with real, growing snapshots of progress so far --
    this is what lets a long-running full crawl leave inspectable, current
    output on disk throughout, instead of only after everything finishes.
    """
    output_dir = tmp_path / "output"
    config = CrawlConfig(version="2024", namespace_prefix="Autodesk.Revit.DB", cache_dir=output_dir / "cache")
    crawler = Crawler(config)

    _prime_cache(crawler, crawler.namespace_json_url(), json.dumps(_WIDGET_NAMESPACE_TREE))
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/widget-class.htm", _CLASS_HTML)
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/widget-properties.htm", _PROPERTIES_INDEX_HTML)
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/symbol-property.htm", _PROPERTY_HTML)

    entries, _ = crawler.discover_via_namespace_json()
    by_url = {e["url"]: e for e in entries}

    calls: list[tuple[int, int]] = []

    def spy_checkpoint(pages, failed_urls, is_final=False):
        calls.append((len(pages), len(failed_urls)))

    # checkpoint_min_interval_seconds=0 disables the wall-clock gate (see
    # test_crawl_and_parse_checkpoint_is_rate_limited_by_wall_clock_time
    # below), so this isolates the page-count cadence.
    pages, failed_urls = _crawl_and_parse(
        crawler, config, by_url, checkpoint=spy_checkpoint, checkpoint_interval=1, checkpoint_min_interval_seconds=0
    )

    assert len(pages) == 2  # Widget class page + Symbol property page (the Properties index page isn't itself a page)
    assert len(calls) == 3  # checkpoint_interval=1, 3 total pages fetched
    # Not every snapshot shows the same count -- proves these are real
    # incremental snapshots taken while the crawl was still in progress,
    # not the same final state recorded three times.
    assert len({c[0] for c in calls}) > 1


def test_crawl_and_parse_checkpoint_is_rate_limited_by_wall_clock_time(tmp_path):
    """Regression test: checkpoint() runs a full classify+export pass over
    everything parsed so far, so its cost grows with page count. Gating it
    purely by checkpoint_interval (a page count) meant a large crawl's total
    checkpoint overhead grew roughly quadratically -- verified against a real
    ~23k-page crawl, a single classify+export pass took ~15s, and firing
    that every 25 pages (~930 times) projected to well over an hour of pure
    overhead. checkpoint_min_interval_seconds must suppress periodic firing
    faster than that, regardless of how small checkpoint_interval is.
    """
    output_dir = tmp_path / "output"
    config = CrawlConfig(version="2024", namespace_prefix="Autodesk.Revit.DB", cache_dir=output_dir / "cache")
    crawler = Crawler(config)

    _prime_cache(crawler, crawler.namespace_json_url(), json.dumps(_WIDGET_NAMESPACE_TREE))
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/widget-class.htm", _CLASS_HTML)
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/widget-properties.htm", _PROPERTIES_INDEX_HTML)
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/symbol-property.htm", _PROPERTY_HTML)

    entries, _ = crawler.discover_via_namespace_json()
    by_url = {e["url"]: e for e in entries}

    calls: list[tuple[int, int]] = []

    def spy_checkpoint(pages, failed_urls, is_final=False):
        calls.append((len(pages), len(failed_urls)))

    # checkpoint_interval=1 would fire on every single page (as proven
    # above) if not for the time gate; a large checkpoint_min_interval_seconds
    # must suppress all of that periodic firing within this fast test run.
    _crawl_and_parse(
        crawler, config, by_url, checkpoint=spy_checkpoint, checkpoint_interval=1, checkpoint_min_interval_seconds=9999
    )

    assert calls == []


def test_checkpoint_cooldown_starts_after_export_finishes_not_before(tmp_path, monkeypatch):
    """Regression test: last_checkpoint_time must be recorded after
    checkpoint() returns, not before checkpoint() is called. A slow export
    (the case checkpoint_min_interval_seconds exists to protect against --
    e.g. serializing a large crawl can itself take longer than the
    configured minimum interval) would otherwise count its own duration as
    cooldown time, letting the very next page-count boundary fire another
    full checkpoint immediately and collapsing back toward every-interval
    exports -- the exact overhead this rate limit exists to prevent.
    """

    class FakeClock:
        def __init__(self):
            self.now = 0.0

        def monotonic(self):
            self.now += 1.0  # every call simulates a small amount of wall-clock passing
            return self.now

        def jump(self, seconds):
            self.now += seconds

    fake_clock = FakeClock()
    monkeypatch.setattr(pipeline_module.time, "monotonic", fake_clock.monotonic)

    output_dir = tmp_path / "output"
    config = CrawlConfig(version="2024", namespace_prefix="Autodesk.Revit.DB", cache_dir=output_dir / "cache")
    crawler = Crawler(config)

    _prime_cache(crawler, crawler.namespace_json_url(), json.dumps(_WIDGET_NAMESPACE_TREE))
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/widget-class.htm", _CLASS_HTML)
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/widget-properties.htm", _PROPERTIES_INDEX_HTML)
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/symbol-property.htm", _PROPERTY_HTML)

    entries, _ = crawler.discover_via_namespace_json()
    by_url = {e["url"]: e for e in entries}

    calls: list[int] = []

    def spy_checkpoint(pages, failed_urls, is_final=False):
        calls.append(len(calls))
        if len(calls) == 1:
            fake_clock.jump(5.0)  # simulate a slow export exceeding checkpoint_min_interval_seconds

    _crawl_and_parse(
        crawler, config, by_url, checkpoint=spy_checkpoint, checkpoint_interval=1, checkpoint_min_interval_seconds=2.0
    )

    # Only one checkpoint should fire during the loop: the page-count
    # boundary immediately after the slow export must not re-fire just
    # because the export's own duration was mistakenly counted as cooldown.
    assert len(calls) == 1


def test_progress_log_reports_recent_rate_and_eta(tmp_path, monkeypatch, caplog):
    """The periodic progress log should report a rate/ETA computed from a
    trailing window of recent throughput (the last few progress lines), not
    the cumulative average since the crawl started -- some pages really are
    faster than others (a cache hit vs. a fresh throttled fetch, a small
    property page vs. a large members-index page), so an ETA based on a
    single running average would lag behind how fast the crawl is actually
    going right now. See test_progress_rate_tracker_smooths_a_single_slow_interval
    for the windowing/smoothing behavior itself, isolated from a real crawl.
    """

    class FakeClock:
        def __init__(self):
            self.now = 0.0

        def monotonic(self):
            self.now += 1.0  # every call simulates 1s of wall-clock passing
            return self.now

    monkeypatch.setattr(pipeline_module.time, "monotonic", FakeClock().monotonic)

    output_dir = tmp_path / "output"
    config = CrawlConfig(version="2024", namespace_prefix="Autodesk.Revit.DB", cache_dir=output_dir / "cache")
    crawler = Crawler(config)

    _prime_cache(crawler, crawler.namespace_json_url(), json.dumps(_WIDGET_NAMESPACE_TREE))
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/widget-class.htm", _CLASS_HTML)
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/widget-properties.htm", _PROPERTIES_INDEX_HTML)
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/symbol-property.htm", _PROPERTY_HTML)

    entries, _ = crawler.discover_via_namespace_json()
    by_url = {e["url"]: e for e in entries}

    with caplog.at_level("INFO", logger="revit_schema_mapper.pipeline"):
        _crawl_and_parse(crawler, config, by_url, checkpoint=None, checkpoint_interval=1)

    progress_lines = [m for m in caplog.messages if m.startswith("progress:")]
    assert len(progress_lines) == 3  # 3 total pages (class, properties-index, property), checkpoint_interval=1

    # Every fetch is a cache hit under the fake clock (no throttling), so the
    # simulated rate is a deterministic, constant 1 page/s throughout --
    # letting the ETA at each line be checked exactly against the queue
    # length remaining at that point (3, then 2, then 1 -> 2s, 1s, 0s).
    assert "2 queued" in progress_lines[0]
    assert "1.00 pages/s (recent avg)" in progress_lines[0]
    assert "1.00 pages/s (overall)" in progress_lines[0]
    assert "ETA 2s" in progress_lines[0]

    assert "1 queued" in progress_lines[1]
    assert "ETA 1s" in progress_lines[1]

    assert "0 queued" in progress_lines[2]
    assert "ETA 0s" in progress_lines[2]


def test_progress_rate_tracker_smooths_a_single_slow_interval():
    """Regression test for the exact complaint that motivated the trailing
    window: a plain single-interval rate whipsaws the ETA (e.g. 40min one
    progress line, 7 hours the next) whenever one batch happens to be much
    slower/faster than its neighbor. A window of 3 is used here (instead of
    the real _PROGRESS_RATE_WINDOW=5) purely to keep the sample count small
    and the arithmetic easy to check by hand; the behavior being tested --
    a slow interval keeps dragging the rate down for `window` more samples,
    then the rate recovers once that sample ages out of the window -- is the
    same regardless of window size.
    """
    from revit_schema_mapper.pipeline import _ProgressRateTracker

    tracker = _ProgressRateTracker(window=3, start_time=0.0)

    # One page took 100s (e.g. a slow, uncached first fetch) -- rate crashes.
    assert tracker.record(now=100.0, visited=1) == pytest.approx(1 / 100)
    # Genuinely fast pages follow (1 page/s each), but the slow sample is
    # still inside the window (maxlen = window + 1 = 4 samples, and it isn't
    # exceeded until the 5th .record() call below), so the reported rate
    # stays well below the pages' *actual* current speed for a few samples...
    assert tracker.record(now=101.0, visited=2) == pytest.approx(2 / 101)
    assert tracker.record(now=102.0, visited=3) == pytest.approx(3 / 102)
    assert tracker.record(now=103.0, visited=4) == pytest.approx(4 / 103)
    # ...until the slow sample finally ages out of the window -- at which
    # point the rate jumps straight to the true, current 1 page/s instead of
    # creeping up gradually, and stays there for later fast samples too.
    assert tracker.record(now=104.0, visited=5) == pytest.approx(1.0)
    assert tracker.record(now=105.0, visited=6) == pytest.approx(1.0)


def test_format_duration_reports_unknown_for_non_finite_or_negative():
    from revit_schema_mapper.pipeline import _format_duration

    assert _format_duration(None) == "unknown"
    assert _format_duration(float("inf")) == "unknown"
    assert _format_duration(-1.0) == "unknown"
    assert _format_duration(45.0) == "45s"
    assert _format_duration(125.0) == "2m05s"
    assert _format_duration(7384.0) == "2h03m"


def test_crawl_and_parse_writes_final_checkpoint_on_interrupt(tmp_path, monkeypatch):
    """A KeyboardInterrupt (or any BaseException) that escapes the crawl loop
    must trigger one last checkpoint call reflecting whatever was parsed so
    far, and then propagate -- not get swallowed -- so an interrupted crawl
    still leaves current output on disk instead of nothing at all.
    """
    output_dir = tmp_path / "output"
    config = CrawlConfig(version="2024", namespace_prefix="Autodesk.Revit.DB", cache_dir=output_dir / "cache")
    crawler = Crawler(config)

    _prime_cache(crawler, crawler.namespace_json_url(), json.dumps(_WIDGET_NAMESPACE_TREE))
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/widget-class.htm", _CLASS_HTML)
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/widget-properties.htm", _PROPERTIES_INDEX_HTML)
    # Deliberately do NOT prime symbol-property.htm -- fetching it raises below.

    entries, _ = crawler.discover_via_namespace_json()
    by_url = {e["url"]: e for e in entries}

    real_fetch = crawler.fetch

    def fetch_then_interrupt(url):
        if url.endswith("symbol-property.htm"):
            raise KeyboardInterrupt()
        return real_fetch(url)

    monkeypatch.setattr(crawler, "fetch", fetch_then_interrupt)

    calls: list[tuple[int, int]] = []

    def spy_checkpoint(pages, failed_urls, is_final=False):
        calls.append((len(pages), len(failed_urls)))

    with pytest.raises(KeyboardInterrupt):
        _crawl_and_parse(crawler, config, by_url, checkpoint=spy_checkpoint, checkpoint_interval=1)

    assert len(calls) >= 1
    # The final call is the except-BaseException handler's checkpoint, fired
    # after widget-class.htm finished parsing but before the interrupt hit
    # on symbol-property.htm.
    assert calls[-1][0] == 1


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
    assert (output_dir / "graph.html").exists()


def test_label_communities_llm_only_fires_on_the_final_checkpoint(tmp_path, monkeypatch):
    """A long crawl's periodic checkpoints must not each re-trigger the
    opt-in OpenRouter labeling call -- that has a real per-call cost, and
    would otherwise multiply with every checkpoint of a multi-hour crawl.
    Only the guaranteed final checkpoint should request LLM labels.
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

    calls = []
    real_apply_communities = pipeline_module.apply_communities

    def spy_apply_communities(result, *, use_llm_labels, model, api_key):
        calls.append(use_llm_labels)
        real_apply_communities(result, use_llm_labels=False, model=model, api_key=api_key)

    monkeypatch.setattr(pipeline_module, "apply_communities", spy_apply_communities)

    run_targeted_pipeline(
        config,
        output_dir,
        target_full_type_names=["Autodesk.Revit.DB.View"],
        known_edge_checks=[],
        checkpoint_interval=1,
        checkpoint_min_interval_seconds=0,
        label_communities_llm=True,
        openrouter_api_key="fake-key-not-actually-used",
    )

    assert len(calls) >= 1
    assert calls[-1] is True
    assert all(c is False for c in calls[:-1])


_WALL_CLASS_HTML_NO_INLINE_TABLE = """
<html><body>
<h1 id="PageHeader">Wall Class</h1>
<div id="TopicPathClassic"><a href="/2024/ns_db.htm">Autodesk.Revit.DB</a> Namespace</div>
<div class="syntax"><pre class="typeSignature">public class Wall : HostObject</pre></div>
</body></html>
"""

_WALL_MEMBERS_HTML_WITH_INHERITED_ROW = """
<html><body>
<div id="TopicPathClassic"><a href="/2024/ns_db.htm">Autodesk.Revit.DB</a> Namespace</div>
<h4 id="api-title" class="truncate"> Wall Members </h4>
<div id="mainBody">
<h1 class="heading">Methods</h1>
<table class="members" id="memberList">
<tr><th>Icon</th><th>Name</th><th>Description</th></tr>
<tr data="public;inherited;notNetfw;"><td><img></td><td><a href="arephasesmodifiable.htm">ArePhasesModifiable</a></td><td>Returns true if... (Inherited from <a href="element.htm">Element</a>.)</td></tr>
</table>
</div>
</body></html>
"""

_ARE_PHASES_MODIFIABLE_PROPERTY_HTML = """
<html><body>
<h4 id="api-title" class="truncate"> ArePhasesModifiable Method </h4>
<div id="mainBody">
<div class="summary"><p>Returns true if the properties CreatedPhaseId and DemolishedPhaseId can be modified.</p></div>
<div class="syntax"><pre class="typeSignature">public bool ArePhasesModifiable()</pre></div>
</div>
</body></html>
"""


def test_targeted_crawl_of_wall_alone_attributes_inherited_member_to_element(tmp_path):
    """Regression test for the exact scenario described in review: a Wall
    Members page lists an inherited method (ArePhasesModifiable, inherited
    from Element per the real data="...;inherited;..." markup), but the
    crawl's target list (or a --max-pages-truncated namespace_json result)
    does not include Element at all. The inherited member's page must still
    be attributed to Element, not falsely emitted as
    Autodesk.Revit.DB.Wall.ArePhasesModifiable.
    """
    output_dir = tmp_path / "output"
    config = CrawlConfig(version="2024", namespace_prefix="Autodesk.Revit.DB", cache_dir=output_dir / "cache")
    crawler = Crawler(config)

    # Only Wall is in the namespace_json tree -- Element is deliberately
    # absent, as if truncated by --max-pages or simply out of scope for this
    # targeted crawl.
    tree = [
        {
            "title": "Namespaces",
            "children": [
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
                            ],
                        },
                    ],
                },
            ],
        }
    ]

    _prime_cache(crawler, crawler.namespace_json_url(), json.dumps(tree))
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/wall-class.htm", _WALL_CLASS_HTML_NO_INLINE_TABLE)
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/wall-members.htm", _WALL_MEMBERS_HTML_WITH_INHERITED_ROW)
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/arephasesmodifiable.htm", _ARE_PHASES_MODIFIABLE_PROPERTY_HTML)

    result = run_targeted_pipeline(config, output_dir, target_full_type_names=["Autodesk.Revit.DB.Wall"], known_edge_checks=[])

    # known_edge_checks=[] must mean zero checks, not a silent fallback to
    # DEFAULT_KNOWN_EDGE_CHECKS.
    assert result.known_edge_report == []

    are_phases_pages = [p for p in result.pages if p.full_type_name.endswith(".ArePhasesModifiable")]
    assert len(are_phases_pages) == 1
    assert are_phases_pages[0].declaring_type == "Autodesk.Revit.DB.Element"
    assert are_phases_pages[0].full_type_name != "Autodesk.Revit.DB.Wall.ArePhasesModifiable"

    # No edge/node output should ever claim Wall declares this method.
    assert not any(e.source_type == "Autodesk.Revit.DB.Wall" and e.member_name == "ArePhasesModifiable" for e in result.edge_candidates)


def test_preseeded_inherited_member_url_gets_corrected_by_members_page_parse(tmp_path):
    """Regression test: the namespace JSON's flatten structurally nests every
    page it finds under whichever type node contains it (see
    Crawler._flatten_namespace_node), which doesn't know about inheritance --
    if it lists ArePhasesModifiable directly under Wall's own subtree (as
    real API-doc TOCs commonly do, mirroring what the Members page displays),
    the URL lands in by_url with declaring_type_hint="...Wall" *before* the
    real Wall Members page is ever fetched. When that page's row parse later
    identifies the true owner (Element), the earlier hint must be corrected
    in place, not left stale just because the URL was already known --
    otherwise the member is fetched with the wrong declaring type as soon as
    its turn in the queue comes up.
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
                            "title": "Wall Class",
                            "href": "wall-class.htm",
                            "tag": "Class",
                            "children": [
                                {"title": "Wall Members", "href": "wall-members.htm", "tag": "Members"},
                                # The JSON structurally nests this inherited
                                # method under Wall too, same as the real
                                # Members page lists it -- this is the stale
                                # pre-seed the fix must correct.
                                {"title": "ArePhasesModifiable Method", "href": "arephasesmodifiable.htm", "tag": "Method"},
                            ],
                        },
                    ],
                },
            ],
        }
    ]

    _prime_cache(crawler, crawler.namespace_json_url(), json.dumps(tree))
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/wall-class.htm", _WALL_CLASS_HTML_NO_INLINE_TABLE)
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/wall-members.htm", _WALL_MEMBERS_HTML_WITH_INHERITED_ROW)
    _prime_cache(crawler, "https://www.revitapidocs.com/2024/arephasesmodifiable.htm", _ARE_PHASES_MODIFIABLE_PROPERTY_HTML)

    result = run_targeted_pipeline(config, output_dir, target_full_type_names=["Autodesk.Revit.DB.Wall"], known_edge_checks=[])

    # known_edge_checks=[] must mean zero checks, not a silent fallback to
    # DEFAULT_KNOWN_EDGE_CHECKS.
    assert result.known_edge_report == []

    are_phases_pages = [p for p in result.pages if p.full_type_name.endswith(".ArePhasesModifiable")]
    assert len(are_phases_pages) == 1
    assert are_phases_pages[0].declaring_type == "Autodesk.Revit.DB.Element"

    assert not any(e.source_type == "Autodesk.Revit.DB.Wall" and e.member_name == "ArePhasesModifiable" for e in result.edge_candidates)


def _member_page(declaring_type: str, member_name: str, return_type: str = "string") -> ApiPage:
    member = MemberInfo(
        name=member_name,
        kind=MemberKind.PROPERTY,
        declaring_type=declaring_type,
        raw_signature=f"public {return_type} {member_name} {{ get; }}",
        return_type=return_type,
        source_url="https://www.revitapidocs.com/2024/fake.htm",
    )
    return ApiPage(
        revit_version="2024",
        namespace="Autodesk.Revit.DB.Architecture",
        type_name=member_name,
        full_type_name=f"{declaring_type}.{member_name}",
        kind=Kind.PROPERTY,
        declaring_type=declaring_type,
        members=[member],
        source_url=member.source_url,
    )


def _node_candidate(full_type_name: str, inheritance_chain: list) -> NodeCandidate:
    return NodeCandidate(
        full_type_name=full_type_name,
        short_name=full_type_name.rsplit(".", 1)[-1],
        kind=Kind.CLASS,
        namespace=full_type_name.rsplit(".", 1)[0],
        base_type=inheritance_chain[0] if inheritance_chain else None,
        inheritance_chain=inheritance_chain,
        is_element_candidate=IsElementCandidate.UNKNOWN,
        class_role=ClassRole.UNKNOWN,
        evidence=[],
        source_url="https://www.revitapidocs.com/2024/fake.htm",
    )


def test_known_edge_report_resolves_member_found_under_different_declaring_type():
    """Regression test for a real finding from a live crawl: Room.Number is
    actually declared on the intermediate base class SpatialElement
    (Room -> SpatialElement -> Element), not on Room itself. Our own
    inherited-member attribution correctly resolves it there, but the
    known-edge report was reporting this as "NOT CRAWLED" (a coverage gap)
    when it had, in fact, been crawled and correctly attributed -- just not
    to the type the check happened to name.
    """
    pages = [_member_page("Autodesk.Revit.DB.Architecture.SpatialElement", "Number")]
    node_candidates = [_node_candidate("Autodesk.Revit.DB.Architecture.Room", ["SpatialElement"])]
    checks = [("Autodesk.Revit.DB.Architecture.Room", "Number")]

    report = _build_known_edge_report(pages, edge_candidates=[], node_candidates=node_candidates, checks=checks)

    assert len(report) == 1
    result = report[0]
    assert result.member_found is True
    assert result.actual_declaring_type == "Autodesk.Revit.DB.Architecture.SpatialElement"
    assert "found declared on Autodesk.Revit.DB.Architecture.SpatialElement" in result.note
    # Room.Number is in _EXPECTED_NO_EDGE -- still correctly flagged as
    # expected-no-edge even though it resolved to a different declaring type.
    assert "expected: no relationship edge" in result.note


def test_known_edge_report_rejects_same_named_member_on_unrelated_type():
    """The cross-type fallback must be restricted to declaring_type's own
    confirmed inheritance chain -- a same-named member on some unrelated
    crawled type (a coincidence, not evidence of inheritance) must not be
    reported as if it satisfied the check; that would hide a genuine
    coverage gap instead of reporting it honestly. Before this fix, any
    same-named member anywhere in the crawl would have matched here.
    """
    pages = [_member_page("Autodesk.Revit.DB.Wall", "Number")]  # unrelated type, coincidentally same member name
    node_candidates = [_node_candidate("Autodesk.Revit.DB.Architecture.Room", ["SpatialElement"])]  # Wall is not in Room's chain
    checks = [("Autodesk.Revit.DB.Architecture.Room", "Number")]

    report = _build_known_edge_report(pages, edge_candidates=[], node_candidates=node_candidates, checks=checks)

    result = report[0]
    assert result.member_found is False
    assert result.actual_declaring_type is None
    assert "not crawled/parsed" in result.note


def _edge_candidate(source_type: str, target: str, edge_type: EdgeType, confidence: ConfidenceLabel) -> EdgeCandidate:
    return EdgeCandidate(
        source_type=source_type,
        member_name="SomeMember",
        member_kind=MemberKind.PROPERTY,
        raw_signature="x",
        return_type=target,
        parameter_types=[],
        candidate_target_type=target,
        candidate_edge_type=edge_type,
        edge_confidence=confidence,
        evidence=[],
        source_url="https://www.revitapidocs.com/2024/fake.htm",
    )


def test_run_graph_only_rebuilds_graph_and_refreshes_summary_without_crawling(tmp_path):
    """--graph-only's whole point is to skip crawling/parsing entirely --
    this only touches node_type_candidates.json/candidate_edges.json/
    summary.md on disk, never Crawler/CrawlConfig.
    """
    nodes = [_node_candidate("Autodesk.Revit.DB.View", []), _node_candidate("Autodesk.Revit.DB.ViewSheet", [])]
    edges = [_edge_candidate("Autodesk.Revit.DB.View", "Autodesk.Revit.DB.ViewSheet", EdgeType.PLACED_ON_SHEET, ConfidenceLabel.DIRECT_RETURN_TYPE)]
    export.write_node_candidates(tmp_path, nodes)
    export.write_edge_candidates(tmp_path, edges)
    (tmp_path / "summary.md").write_text("# Old summary\n\n## 14. Knowledge graph materialization\n\nSTALE\n", encoding="utf-8")

    result = run_graph_only(tmp_path, revit_version="2024")

    assert len(result.nodes) == 2
    assert len(result.edges) == 1

    graph_json = json.loads((tmp_path / "graph.json").read_text())
    assert graph_json["metadata"]["edge_count"] == 1
    core_json = json.loads((tmp_path / "graph_core.json").read_text())
    assert core_json["metadata"]["edge_count"] == 1

    summary_text = (tmp_path / "summary.md").read_text()
    assert "STALE" not in summary_text
    assert "# Old summary" in summary_text
    assert summary_text.count("## 14. Knowledge graph materialization") == 1


def test_known_edge_report_genuinely_missing_member_is_not_confused_with_cross_type_match():
    # No member named "Number" anywhere at all -- must stay a real "not found".
    pages = [_member_page("Autodesk.Revit.DB.Wall", "Width")]
    node_candidates = [_node_candidate("Autodesk.Revit.DB.Architecture.Room", ["SpatialElement"])]
    checks = [("Autodesk.Revit.DB.Architecture.Room", "Number")]

    report = _build_known_edge_report(pages, edge_candidates=[], node_candidates=node_candidates, checks=checks)

    result = report[0]
    assert result.member_found is False
    assert result.actual_declaring_type is None
    assert "not crawled/parsed" in result.note
