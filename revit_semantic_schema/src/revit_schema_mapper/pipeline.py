"""End-to-end pipeline: crawl -> parse -> classify -> export.

This is the "one command" referenced in the project's definition of done.
See ``python -m revit_schema_mapper --help`` (src/revit_schema_mapper/__main__.py).

``run_targeted_pipeline`` is a second entry point: a scoped validation crawl
against a short, explicit list of target classes (see
``DEFAULT_TARGET_CLASSES``) plus a "known edge" report checking specific
expected property/method relationships (``DEFAULT_KNOWN_EDGE_CHECKS``),
instead of a broad namespace-wide crawl. Use this to validate the
crawler/parser/classifier against a small, well-understood set of real
pages before trusting a full run.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from . import classify, export
from .community import DEFAULT_OPENROUTER_MODEL
from .crawl import ALLOWED_HOST, CrawlConfig, Crawler
from .graph import GraphBuildResult, apply_communities, build_graph
from .ground_truth import GroundTruthReport, cross_validate_dll, load_manifest
from .models import ApiPage, EdgeCandidate, Kind, NodeCandidate
from .parse import (
    extract_member_links,
    find_members_page_link,
    parse_enum_page,
    parse_member_page,
    parse_members_index_page,
    parse_type_page,
    resolve_type_name_from_members_index,
    sniff_kind,
)

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    raw_index_entries: list[dict]
    pages: list[ApiPage]
    node_candidates: list
    edge_candidates: list
    failed_urls: list[str]


@dataclass
class DiscoveryResult:
    raw_index_entries: list[dict]
    discovery_errors: list[str]
    counts_by_source: dict[str, int]


def run_discovery(config: CrawlConfig, output_dir: Path | None = None) -> DiscoveryResult:
    """Run just page discovery (``Crawler.discover_index``) and report how
    many pages a full ``run_pipeline``/``run_targeted_pipeline`` call would
    need to fetch, without actually fetching/parsing any of them.

    This costs only the handful of requests discover_index itself makes
    (namespace JSON, root page, a few TOC file probes, sitemap.xml) --
    letting you check a full run's scale up front instead of discovering it
    partway through a multi-hour crawl.
    """
    crawler = Crawler(config)
    raw_index_entries = crawler.discover_index()

    counts_by_source: dict[str, int] = {}
    for entry in raw_index_entries:
        source = entry.get("discovered_via", "unknown").split(":", 1)[0]
        counts_by_source[source] = counts_by_source.get(source, 0) + 1

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
        export.write_raw_index(output_dir, raw_index_entries)

    return DiscoveryResult(
        raw_index_entries=raw_index_entries,
        discovery_errors=crawler.last_discovery_errors,
        counts_by_source=counts_by_source,
    )


def run_graph_only(
    output_dir: Path,
    revit_version: str,
    *,
    label_communities_llm: bool = False,
    community_label_model: str = DEFAULT_OPENROUTER_MODEL,
    openrouter_api_key: str | None = None,
) -> GraphBuildResult:
    """Recompute ``graph.json``/``graph_core.json``/``graph.html`` (and
    refresh the 'Knowledge graph materialization' section of whichever
    summary file exists) from an existing run's already-written
    ``node_type_candidates.json``/``candidate_edges.json`` -- no crawling,
    fetching, or re-parsing of any page.

    A full re-run reuses cached HTML (skips fetching) but still re-parses
    and re-classifies every page from scratch, which is itself the slow
    part on constrained hardware (e.g. a Raspberry Pi working through tens
    of thousands of cached pages) -- this mode is for iterating on graph.py
    (or community detection/labeling) alone without paying that cost again.
    """
    node_candidates = export.read_node_candidates(output_dir)
    edge_candidates = export.read_edge_candidates(output_dir)
    result = build_graph(node_candidates, edge_candidates)
    apply_communities(result, use_llm_labels=label_communities_llm, model=community_label_model, api_key=openrouter_api_key)

    export.write_graph(output_dir, result, revit_version=revit_version)
    export.write_graph_html(output_dir, result, revit_version=revit_version)
    export.write_semantic_relationship_map(output_dir, result, revit_version=revit_version)
    # Try both -- a no-op for whichever summary filename isn't this
    # directory's kind (full run vs. --targeted-validation).
    export.refresh_graph_section_in_file(output_dir / "summary.md", result, section_number=14)
    export.refresh_graph_section_in_file(output_dir / "validation_summary.md", result, section_number=9)

    return result


def run_cross_validate_dll(output_dir: Path, manifest_path: Path) -> GroundTruthReport:
    """Stage B of DLL reflection cross-validation (docs/dll_reflection_v0.md).

    Cross-checks an existing run's already-written ``node_type_candidates.json``/
    ``candidate_edges.json`` against ``ground_truth_manifest_<version>.json``
    (Stage A's .NET reflection output, produced separately on a Windows
    machine with Revit installed -- see ``reflect_revit_api.ps1``). Like
    ``run_graph_only``, this is a separate, explicit, opt-in pass layered on
    top of an existing crawl: no crawling, fetching, or live Revit/DLL access
    of any kind happens here, only reading two JSON files already on disk.

    ``cross_validate_dll`` mutates every candidate's ``dll_*`` fields in
    place (see models.py); those are persisted back to the same two files so
    the annotation survives past this one process, then
    ``ground_truth_report.json`` and a refreshed summary section are written
    alongside them.
    """
    node_candidates = export.read_node_candidates(output_dir)
    edge_candidates = export.read_edge_candidates(output_dir)
    manifest = load_manifest(manifest_path)

    report = cross_validate_dll(node_candidates, edge_candidates, manifest)

    export.write_node_candidates(output_dir, node_candidates)
    export.write_edge_candidates(output_dir, edge_candidates)
    export.write_ground_truth_report(output_dir, report)
    # Try both -- a no-op for whichever summary filename isn't this
    # directory's kind (full run vs. --targeted-validation), same reasoning
    # as run_graph_only's own pair of refresh calls above.
    export.refresh_ground_truth_section_in_file(output_dir / "summary.md", report, section_number=15)
    export.refresh_ground_truth_section_in_file(output_dir / "validation_summary.md", report, section_number=10)

    return report


def _crawl_and_parse(
    crawler: Crawler,
    config: CrawlConfig,
    by_url: dict[str, dict],
    checkpoint: Callable[[list[ApiPage], list[str], bool], None] | None = None,
    checkpoint_interval: int = 25,
    checkpoint_min_interval_seconds: float = 30.0,
) -> tuple[list[ApiPage], list[str]]:
    """Fetch/sniff/parse every URL in ``by_url``, following class ->
    Members-page links and enqueueing newly-discovered member pages as it
    goes. ``by_url`` is mutated in place (new entries are added for anything
    discovered along the way) -- shared by both ``run_pipeline`` (broad
    crawl) and ``run_targeted_pipeline`` (scoped validation crawl), which
    differ only in how they seed ``by_url`` and what they do with the
    results afterward.

    If ``checkpoint`` is given, a progress line is logged every
    ``checkpoint_interval`` pages, and ``checkpoint`` itself is called at
    that same cadence *but no more often than every*
    ``checkpoint_min_interval_seconds`` of wall-clock time (the caller is
    expected to export the pages/failed_urls it's given). ``checkpoint`` is
    a full classify+export pass over everything parsed so far, so its cost
    grows with page count -- gating it by ``checkpoint_interval`` alone
    would make a large crawl's *total* checkpoint overhead grow roughly
    quadratically (a fixed page-count cadence means the already-expensive
    late-run checkpoints fire just as often as the cheap early ones). Gating
    by elapsed time bounds total overhead to roughly
    ``run_duration / checkpoint_min_interval_seconds`` checkpoints,
    regardless of crawl size. ``checkpoint`` is also called once more if the
    loop exits early via an unhandled exception -- including
    KeyboardInterrupt -- so a long crawl that's interrupted partway through
    still leaves reasonably fresh, usable output on disk instead of nothing
    at all. The caller is responsible for calling ``checkpoint`` itself one
    final time after this returns normally, to export the complete result --
    this function only guarantees a checkpoint on the *abnormal*-exit path.

    ``checkpoint``'s third argument, ``is_final``, is ``False`` for every
    periodic in-loop call and ``True`` for the abnormal-exit call here (the
    last checkpoint this process will make, even if the crawl itself was
    interrupted). Callers use this to gate anything with a real per-call
    cost -- e.g. an opt-in LLM labeling request -- to just once at the end
    of a run rather than repeating it (and its cost) at every periodic
    checkpoint of a long crawl.
    """
    pages: list[ApiPage] = []
    failed_urls: list[str] = []
    # queue of (url, declaring_type_hint) for pages we know are member pages
    # because we found their link in a type's members table.
    member_queue: list[tuple[str, str]] = []
    visited: set[str] = set()

    def enqueue_member_links(links: list[dict], declaring_full_type_name: str, discovered_via_prefix: str) -> None:
        """``links`` come from ``parse.extract_member_links``/
        ``parse.parse_members_index_page``, whose row-level parsing can
        supply an explicit ``declaring_type_hint`` for a member inherited
        from a base type (e.g. ``ArePhasesModifiable`` on ``Wall``, actually
        declared on ``Element``) -- see those functions' docstrings.

        A URL can already be in ``by_url`` before that hint is known: the
        namespace JSON's flatten structurally nests every page it finds
        under whichever type node contains it (see
        ``Crawler._flatten_namespace_node``), which doesn't distinguish
        inherited from declared, so it seeds an inherited member's URL under
        the *derived* type with that type as declaring_type_hint. When the
        real Members-page row parse later resolves the true owner, that
        stale hint must be corrected in place -- not left alone just because
        the URL is already known -- or the member ends up permanently
        mis-attributed (e.g. a false ``Wall.ArePhasesModifiable``) as soon as
        it's fetched. Only correct when this call supplies its own explicit,
        row-derived hint (not the generic per-call default), and only for a
        URL not yet fetched (``visited``) -- once fetched, it's too late.
        """
        for link in links:
            url = link["url"]
            if urlparse(url).netloc != ALLOWED_HOST:
                # Some pages link inherited Object members (Equals, GetHashCode,
                # ToString) out to MSDN instead of rendering them as plain text;
                # out of scope by design, not a fetch failure.
                continue
            if url in visited:
                continue

            row_declaring_type_hint = link.get("declaring_type_hint")
            declaring_type = row_declaring_type_hint or declaring_full_type_name

            if url not in by_url:
                by_url[url] = {
                    "url": url,
                    "link_text": link["name"],
                    "discovered_via": f"{discovered_via_prefix}:{declaring_type}",
                    "declaring_type_hint": declaring_type,
                }
                member_queue.append((url, declaring_type))
                queue.append(url)
            elif row_declaring_type_hint and by_url[url].get("declaring_type_hint") != row_declaring_type_hint:
                by_url[url]["declaring_type_hint"] = row_declaring_type_hint
                by_url[url]["discovered_via"] = f"{discovered_via_prefix}:{row_declaring_type_hint}"

    queue = list(by_url.keys())
    try:
        _run_crawl_loop(
            crawler=crawler,
            config=config,
            by_url=by_url,
            queue=queue,
            visited=visited,
            member_queue=member_queue,
            pages=pages,
            failed_urls=failed_urls,
            enqueue_member_links=enqueue_member_links,
            checkpoint=checkpoint,
            checkpoint_interval=checkpoint_interval,
            checkpoint_min_interval_seconds=checkpoint_min_interval_seconds,
        )
    except BaseException:
        if checkpoint is not None:
            logger.info("crawl interrupted -- writing a final checkpoint with %d page(s) parsed so far", len(pages))
            checkpoint(pages, failed_urls, True)
        raise

    return pages, failed_urls


# Number of trailing progress-log intervals (checkpoint_interval pages
# each, 25 by default) averaged together for the ETA's "recent avg" rate.
# A single interval's rate swings wildly page-to-page (a batch that happens
# to include a large members-index page, or several fresh throttled fetches
# instead of cache hits, looks nothing like the next one) -- averaging over
# several intervals dilutes any one anomalous batch instead of letting it
# single-handedly swing the ETA (e.g. 40min one line, 7 hours the next).
_PROGRESS_RATE_WINDOW = 5


class _ProgressRateTracker:
    """Trailing-window pages/s estimator for the crawl progress log's ETA.

    Keeps the last ``window + 1`` ``(time, cumulative_pages_visited)``
    samples and reports the rate between the oldest kept sample and the
    newest one, rather than either a single noisy interval (whipsaws with
    every batch) or a whole-crawl cumulative average (never recovers from a
    slow start, and stays sluggish to react even hours into a long crawl).
    Early on, with fewer than ``window`` samples recorded, the "oldest kept
    sample" is still the crawl's start -- so the rate naturally behaves like
    a cumulative average until there's enough history to fill the window,
    then settles into a proper trailing average once it does.
    """

    def __init__(self, window: int, start_time: float):
        self._samples: deque[tuple[float, int]] = deque(maxlen=window + 1)
        self._samples.append((start_time, 0))

    def record(self, now: float, visited: int) -> float:
        """Record a new sample and return the trailing-window pages/s rate
        from the oldest sample still in the window through this one."""
        oldest_time, oldest_visited = self._samples[0]
        elapsed = now - oldest_time
        rate = (visited - oldest_visited) / elapsed if elapsed > 0 else 0.0
        self._samples.append((now, visited))
        return rate


def _count_uncached(urls: list[str], crawler: Crawler) -> int:
    """How many of ``urls`` have no cached copy on disk yet -- the ones a
    real crawl still has to spend an actual network fetch on (see
    ``_fetch_floor_eta_seconds``'s docstring for why this, not an empirical
    rate average blending in near-instant cache hits, drives the progress
    log's ETA).
    """
    return sum(1 for url in urls if not crawler.is_cached(url))


# Number of trailing *individual fresh fetches* (not progress intervals --
# these land far more often, one per uncached page rather than one per
# checkpoint_interval pages) averaged for _FetchDurationTracker. Large
# enough to smooth out one slow request without taking too long to react
# if the real per-fetch cost genuinely shifts (e.g. the site or network
# gets slower partway through a multi-hour crawl).
_FETCH_DURATION_WINDOW = 50


class _FetchDurationTracker:
    """Trailing average of how long a genuinely-fresh (not-already-cached)
    page actually takes -- fetch *and* parse together (see
    ``_run_crawl_loop``'s ``fetch_start``/``finally``) -- used to ground the
    ETA in the real per-page cost instead of assuming ``--throttle-seconds``
    alone is that cost.

    Two separate reasons ``throttle_seconds`` alone understates the true
    per-page cost, potentially by a large margin (confirmed on a real run:
    actual per-page time ran roughly double a 1.0s throttle): (1)
    ``Crawler._throttle`` only ever adds a *sleep* when a request finishes
    faster than ``throttle_seconds`` -- if the real round trip (network
    latency, TLS) already takes longer than that on its own, the throttle
    never intervenes at all; and (2) HTML parsing happens *after* the
    throttled fetch returns and is invisible to it entirely, even though
    it's real wall-clock time (non-trivial on constrained hardware).
    Averaging only over pages that weren't already cached is what matters
    here -- mixing in cache hits (near-instant) would silently pull this
    average back down toward whatever fraction of recent pages happened to
    be cached, the same dilution problem that made a blended pages/s rate a
    bad basis for the ETA in the first place (see ``_ProgressRateTracker``/
    ``_count_uncached``).
    """

    def __init__(self, window: int, fallback_seconds: float):
        self._durations: deque[float] = deque(maxlen=window)
        self._fallback_seconds = fallback_seconds

    def record(self, duration_seconds: float) -> None:
        self._durations.append(duration_seconds)

    @property
    def average_seconds(self) -> float:
        """The fallback (``--throttle-seconds``) until at least one real,
        not-already-cached fetch has actually been measured -- there's
        nothing else to base an estimate on yet, and throttle_seconds is
        at least a documented, deliberate lower bound rather than a guess.
        """
        if not self._durations:
            return self._fallback_seconds
        return sum(self._durations) / len(self._durations)


def _fetch_floor_eta_seconds(not_cached_remaining: int, avg_fetch_seconds: float) -> float:
    """ETA given how many queued URLs still need a real fetch, at
    ``avg_fetch_seconds`` each (see ``_FetchDurationTracker``) -- an
    already-cached queued URL costs effectively nothing here, since a cache
    hit returns before any network call happens at all. Still a *floor*,
    not a full prediction, in one remaining respect: pages not yet
    discovered (the crawl can enqueue new URLs as it parses class/members
    pages) obviously aren't counted, which can only push the true remaining
    time above this number, never below it.

    Deliberately not derived from a blended pages/s average across *all*
    visited pages (see ``_ProgressRateTracker``, used only for the
    informational "pages/s" figures logged alongside this): confirmed on a
    real run, a resumed crawl that starts out mostly replaying
    already-cached pages (fast) and then transitions into genuinely new,
    network-bound territory shows a sustained multi-line drop in any such
    blended average as it slowly catches up to the new reality -- that's
    not noise a wider window can smooth away, it's a real regime change a
    blended average necessarily lags behind. This floor has no such lag:
    it's grounded in which URLs are actually on disk *right now* and how
    long *actual* fresh pages (fetch and parse) have actually been taking,
    not recent history blended with cache hits.
    """
    return not_cached_remaining * avg_fetch_seconds


def _format_duration(seconds: float | None) -> str:
    """Human-readable duration for a progress-log ETA (e.g. ``"2h15m"``,
    ``"45s"``). Returns ``"unknown"`` for ``None``/negative/infinite input --
    the recent-throughput-was-zero and not-yet-measurable-first-interval
    cases -- rather than printing ``"inf"`` or a negative number.
    """
    if seconds is None or seconds == float("inf") or seconds < 0:
        return "unknown"
    total_seconds = int(seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def _run_crawl_loop(
    *,
    crawler: Crawler,
    config: CrawlConfig,
    by_url: dict[str, dict],
    queue: list[str],
    visited: set[str],
    member_queue: list[tuple[str, str]],
    pages: list[ApiPage],
    failed_urls: list[str],
    enqueue_member_links: Callable[[list[dict], str, str], None],
    checkpoint: Callable[[list[ApiPage], list[str], bool], None] | None,
    checkpoint_interval: int,
    checkpoint_min_interval_seconds: float,
) -> None:
    crawl_start_time = time.monotonic()
    last_checkpoint_time = crawl_start_time
    rate_tracker = _ProgressRateTracker(_PROGRESS_RATE_WINDOW, crawl_start_time)
    fetch_duration_tracker = _FetchDurationTracker(_FETCH_DURATION_WINDOW, config.throttle_seconds)
    while queue:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        if config.max_pages is not None and len(visited) > config.max_pages:
            break
        if len(visited) % checkpoint_interval == 0:
            now = time.monotonic()
            recent_rate = rate_tracker.record(now, len(visited))
            overall_rate = len(visited) / (now - crawl_start_time) if now > crawl_start_time else 0.0
            # queue is the current best estimate of remaining work, not a
            # fixed total -- discovering a type's Members page can enqueue
            # new member pages faster than the loop drains it, so this (and
            # the uncached count/ETA below) can grow between progress lines
            # rather than monotonically shrinking. That's an accurate
            # reflection of a crawl whose full scope isn't known upfront,
            # not a bug.
            not_cached_remaining = _count_uncached(queue, crawler)
            avg_fetch_seconds = fetch_duration_tracker.average_seconds
            eta_seconds = _fetch_floor_eta_seconds(not_cached_remaining, avg_fetch_seconds)
            logger.info(
                "progress: %d pages fetched, %d queued (%d uncached), %d parsed, %d failed -- "
                "%.2f pages/s (recent avg), %.2f pages/s (overall), ETA %s (observed floor, ~%.2fs/fetch)",
                len(visited), len(queue), not_cached_remaining, len(pages), len(failed_urls),
                recent_rate, overall_rate, _format_duration(eta_seconds), avg_fetch_seconds,
            )
            # Reuses `now` (just captured above for the progress log) rather
            # than taking a fresh reading -- the log call itself is fast
            # enough not to matter, and a second reading here would throw
            # off tests (and, in principle, real cooldown accounting) that
            # count time.monotonic() calls/deltas precisely. checkpoint()
            # itself, below, is the genuinely slow operation and still gets
            # a fresh post-call reading.
            if checkpoint is not None and now - last_checkpoint_time >= checkpoint_min_interval_seconds:
                checkpoint(pages, failed_urls, False)
                # Measured *after* checkpoint() returns, not before: a slow
                # export (the case this rate limit exists to protect --
                # e.g. serializing a large crawl can itself take longer than
                # checkpoint_min_interval_seconds) would otherwise count its
                # own duration as cooldown time, letting the very next
                # page-count boundary fire another full export immediately
                # and collapsing back toward every-interval exports.
                last_checkpoint_time = time.monotonic()

        # by_url's declaring_type_hint is checked first (and is the only one
        # enqueue_member_links corrects in place -- see its docstring), so a
        # correction made after this URL was first seeded always wins over a
        # possibly-stale member_queue entry recorded at that earlier time.
        declaring_type_hint = by_url.get(url, {}).get("declaring_type_hint")
        if declaring_type_hint is None:
            # Not reached by following a class's Members-page link and not
            # seeded via the namespace JSON either -- fall back to whatever
            # enqueue_member_links recorded at enqueue time.
            declaring_type_hint = next((dt for u, dt in member_queue if u == url), None)

        # Measured from before the fetch to after this url is fully parsed
        # below (see the `finally`) -- not just the raw HTTP fetch -- so
        # fetch_duration_tracker reflects real per-page wall-clock cost,
        # including HTML parsing (non-trivial on constrained hardware) and
        # any nested Members-page fetch+parse a class page triggers below.
        # None (not timed at all) for an already-cached url -- see
        # _FetchDurationTracker's docstring for why a near-instant cache hit
        # must never factor into this average.
        fetch_start = None if crawler.is_cached(url) else time.monotonic()

        try:
            html = crawler.fetch(url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to fetch %s: %r", url, exc)
            failed_urls.append(url)
            continue

        try:
            kind = sniff_kind(html)
            if kind in (Kind.CLASS, Kind.STRUCT, Kind.INTERFACE):
                page = parse_type_page(html, url, config.version)
                pages.append(page)
                # Defensive fallback: some pages/years may inline the table.
                enqueue_member_links(extract_member_links(html, url), page.full_type_name, "members_table_of")

                # The live site's usual layout: the class page links out to a
                # separate "<Type> Members" page rather than embedding the
                # table (see parse.find_members_page_link's docstring).
                members_url = find_members_page_link(html, url)
                if members_url and members_url not in visited:
                    try:
                        members_html = crawler.fetch(members_url)
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("failed to fetch members index page %s: %r", members_url, exc)
                    else:
                        visited.add(members_url)
                        member_links, member_notes = parse_members_index_page(members_html, members_url)
                        for note in member_notes:
                            logger.info("members index page %s: %s", members_url, note)
                        enqueue_member_links(member_links, page.full_type_name, "members_index_page_of")
            elif kind is Kind.MEMBERS_INDEX:
                # Prefer the already-known declaring_type_hint (from the
                # namespace JSON's flatten, or from following a class's
                # Members-page link) over re-deriving it from this page's own
                # HTML -- the latter depends on an embedded JSON blob that
                # isn't guaranteed present on every page/year (see
                # resolve_type_name_from_members_index's docstring), so it's
                # a fallback, not the primary source.
                declaring_full_type_name = declaring_type_hint or resolve_type_name_from_members_index(html)
                member_links, member_notes = parse_members_index_page(html, url)
                for note in member_notes:
                    logger.info("members index page %s: %s", url, note)
                enqueue_member_links(member_links, declaring_full_type_name, "members_index_page_direct")
            elif kind is Kind.ENUM:
                pages.append(parse_enum_page(html, url, config.version))
            elif kind in (Kind.PROPERTY, Kind.METHOD, Kind.CONSTRUCTOR):
                declaring_type = declaring_type_hint or ""
                if not declaring_type:
                    logger.warning("member page %s has no known declaring type; skipping", url)
                    failed_urls.append(url)
                    continue
                pages.append(parse_member_page(html, url, config.version, declaring_type))
            else:
                logger.info("unrecognized page kind for %s; skipping", url)
                failed_urls.append(url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to parse %s: %r", url, exc)
            failed_urls.append(url)
        finally:
            # Fires even on the early `continue` above (a `finally` always
            # runs when its `try` is exited, `continue`/`break`/exception
            # included) -- that iteration still genuinely spent this much
            # wall-clock time fetching/attempting to parse, so it belongs in
            # the average regardless of whether parsing itself succeeded.
            if fetch_start is not None:
                fetch_duration_tracker.record(time.monotonic() - fetch_start)


def run_pipeline(
    config: CrawlConfig,
    output_dir: Path,
    fallback_reason: str | None = None,
    include_doc_text: bool = False,
    checkpoint_interval: int = 25,
    checkpoint_min_interval_seconds: float = 30.0,
    label_communities_llm: bool = False,
    community_label_model: str = DEFAULT_OPENROUTER_MODEL,
    openrouter_api_key: str | None = None,
) -> PipelineResult:
    crawler = Crawler(config)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_index_entries = crawler.discover_index()
    by_url = {e["url"]: e for e in raw_index_entries}

    last_result: dict = {}

    def checkpoint(pages: list[ApiPage], failed_urls: list[str], is_final: bool = False) -> None:
        """Write every output file reflecting ``pages``/``failed_urls`` as
        parsed so far. Called periodically during the crawl (see
        ``_crawl_and_parse``) and once more after it returns, so a full run
        that takes hours leaves current, usable output on disk throughout --
        not just after everything finishes -- and a run that's interrupted
        partway through (including by KeyboardInterrupt) still leaves
        whatever was parsed up to that point, instead of nothing at all.

        Community *detection* and heuristic labeling are free and run every
        checkpoint. The opt-in OpenRouter labeling call has a real per-call
        cost, so it's gated to ``is_final`` -- otherwise a long crawl's
        periodic checkpoints would each re-label the (still-growing) graph
        and multiply that cost for no benefit.
        """
        in_scope_pages = [p for p in pages if not p.namespace or p.namespace.startswith(config.namespace_prefix)]

        node_candidates = classify.build_node_candidates(in_scope_pages)
        edge_candidates = classify.build_edge_candidates(in_scope_pages)
        graph_result = build_graph(node_candidates, edge_candidates)
        apply_communities(
            graph_result,
            use_llm_labels=label_communities_llm and is_final,
            model=community_label_model,
            api_key=openrouter_api_key,
        )

        raw_index = list(by_url.values())

        export.write_raw_index(output_dir, raw_index)
        export.write_api_pages(output_dir, in_scope_pages, include_doc_text=include_doc_text)
        export.write_node_candidates(output_dir, node_candidates)
        export.write_edge_candidates(output_dir, edge_candidates)
        export.write_enum_catalogs(output_dir, in_scope_pages)
        export.write_graph(output_dir, graph_result, revit_version=config.version)
        export.write_graph_html(output_dir, graph_result, revit_version=config.version)
        export.write_semantic_relationship_map(output_dir, graph_result, revit_version=config.version)

        limitations = [
            "Edge classification is a static, docs-only heuristic; no candidate edge has been "
            "validated against a live Revit document (see confidence label needs_runtime_validation).",
            "Member pages reachable only via a type's members table are discovered incrementally "
            "during parsing; a partial/interrupted crawl can under-count members for the last few "
            "types processed.",
            "Name-keyword-to-edge-type mapping (classify.py) is heuristic and English-name-based; "
            "it will misclassify or under-classify members whose names don't match the documented "
            "keyword list.",
        ]
        if failed_urls:
            limitations.append(f"{len(failed_urls)} page(s) failed to fetch or parse: {failed_urls[:10]}{' ...' if len(failed_urls) > 10 else ''}")
        if crawler.last_discovery_errors:
            limitations.append(
                f"discover_index encountered {len(crawler.last_discovery_errors)} error(s) while "
                f"finding pages to crawl (see logs for full detail): {crawler.last_discovery_errors[:5]}"
                f"{' ...' if len(crawler.last_discovery_errors) > 5 else ''}"
            )
        if not raw_index and crawler.last_discovery_errors:
            limitations.append(
                "0 pages were discovered this run. This is not 'the site has nothing under this "
                "namespace' -- discover_index's fetch attempts all failed (see the error(s) above), "
                "which most commonly means a network/proxy/TLS/reachability problem, not a parser "
                "bug."
            )

        next_steps = [
            "Run against a live revitapidocs.com session and diff parser_notes across all pages to "
            "find and fix selector assumptions that didn't hold (see docs/crawl_notes.md).",
            "Expand the name-keyword edge taxonomy with additional evidence gathered from real docs "
            "text (docs_semantic_hint) rather than name matching alone.",
            "Cross-check high-confidence candidate edges (direct_return_type, "
            "elementid_with_strong_name) against a small number of real Revit documents to promote "
            "them out of 'candidate' status.",
            "Extend to Autodesk.Revit.DB.Architecture and Autodesk.Revit.DB.Structure for "
            "Room/Space and structural element coverage once the core DB namespace is validated.",
        ]

        export.write_summary(
            output_dir,
            revit_version=config.version,
            fallback_reason=fallback_reason,
            raw_index_entries=raw_index,
            pages=in_scope_pages,
            node_candidates=node_candidates,
            edge_candidates=edge_candidates,
            limitations=limitations,
            next_steps=next_steps,
            graph_result=graph_result,
        )

        last_result["raw_index_entries"] = raw_index
        last_result["pages"] = in_scope_pages
        last_result["node_candidates"] = node_candidates
        last_result["edge_candidates"] = edge_candidates
        last_result["failed_urls"] = failed_urls

    pages, failed_urls = _crawl_and_parse(
        crawler, config, by_url, checkpoint=checkpoint, checkpoint_interval=checkpoint_interval, checkpoint_min_interval_seconds=checkpoint_min_interval_seconds
    )

    checkpoint(pages, failed_urls, True)  # guaranteed final write reflecting the complete result

    return PipelineResult(**last_result)


# -- targeted validation crawl -------------------------------------------------

DEFAULT_TARGET_CLASSES: list[str] = [
    "Autodesk.Revit.DB.Element",
    "Autodesk.Revit.DB.ElementType",
    "Autodesk.Revit.DB.View",
    "Autodesk.Revit.DB.ViewSheet",
    "Autodesk.Revit.DB.Viewport",
    "Autodesk.Revit.DB.Family",
    "Autodesk.Revit.DB.FamilySymbol",
    "Autodesk.Revit.DB.FamilyInstance",
    "Autodesk.Revit.DB.Material",
    "Autodesk.Revit.DB.FillPatternElement",
    "Autodesk.Revit.DB.LinePatternElement",
    "Autodesk.Revit.DB.ParameterFilterElement",
    "Autodesk.Revit.DB.Architecture.Room",
]

# (declaring_type, member_name) pairs to specifically check for. Room.Number
# is expected to produce NO edge (a plain string property, by design -- see
# classify.classify_member and docs/edge_taxonomy_v0.md); everything else is
# expected to produce one.
DEFAULT_KNOWN_EDGE_CHECKS: list[tuple[str, str]] = [
    ("Autodesk.Revit.DB.View", "ViewTemplateId"),
    ("Autodesk.Revit.DB.FamilyInstance", "Symbol"),
    ("Autodesk.Revit.DB.FamilySymbol", "Family"),
    ("Autodesk.Revit.DB.ViewSheet", "GetAllPlacedViews"),
    ("Autodesk.Revit.DB.Viewport", "ViewId"),
    ("Autodesk.Revit.DB.Element", "WorksetId"),
    ("Autodesk.Revit.DB.Material", "SurfacePatternId"),
    ("Autodesk.Revit.DB.Material", "CutPatternId"),
    ("Autodesk.Revit.DB.Architecture.Room", "Number"),
]

_EXPECTED_NO_EDGE: set[tuple[str, str]] = {("Autodesk.Revit.DB.Architecture.Room", "Number")}


@dataclass
class TargetReportEntry:
    full_type_name: str
    found_in_namespace_json: bool
    class_page_parsed: bool
    member_pages_parsed: int
    member_count: int
    reason: str | None = None


@dataclass
class KnownEdgeCheckResult:
    declaring_type: str
    member_name: str
    member_found: bool
    edge_produced: bool
    edge_type: str | None
    edge_confidence: str | None
    note: str
    # Set only when the member was found under a *different* declaring type
    # than expected -- e.g. Room.Number is actually declared on the
    # intermediate base class SpatialElement, not Room itself. None means
    # either an exact match or not found at all (see member_found/note).
    actual_declaring_type: str | None = None


@dataclass
class TargetedPipelineResult:
    raw_index_entries: list[dict]
    pages: list[ApiPage]
    node_candidates: list[NodeCandidate]
    edge_candidates: list[EdgeCandidate]
    failed_urls: list[str]
    target_report: list[TargetReportEntry]
    known_edge_report: list[KnownEdgeCheckResult]
    discovery_notes: list[str] = field(default_factory=list)


def _build_target_report(
    target_full_type_names: list[str],
    found_map: dict[str, bool],
    pages: list[ApiPage],
) -> list[TargetReportEntry]:
    type_pages_by_name = {p.full_type_name: p for p in pages if p.kind in (Kind.CLASS, Kind.STRUCT, Kind.ENUM, Kind.INTERFACE)}
    member_pages = [p for p in pages if p.kind in (Kind.PROPERTY, Kind.METHOD, Kind.CONSTRUCTOR)]

    results: list[TargetReportEntry] = []
    for target in target_full_type_names:
        found_in_json = found_map.get(target, False)
        class_page = type_pages_by_name.get(target)
        class_page_parsed = class_page is not None
        member_pages_for_target = [p for p in member_pages if p.declaring_type == target]
        # + any lightweight member stubs recorded directly on the class page
        # itself (the defensive inline-table fallback path in parse_type_page).
        member_count = len(member_pages_for_target) + (len(class_page.members) if class_page else 0)

        reason = None
        if not found_in_json:
            reason = "not found in the namespace_json tree -- see discovery notes"
        elif not class_page_parsed:
            reason = "found in the index but its class page failed to fetch/parse -- see failed_urls/parser_notes"

        results.append(
            TargetReportEntry(
                full_type_name=target,
                found_in_namespace_json=found_in_json,
                class_page_parsed=class_page_parsed,
                member_pages_parsed=len(member_pages_for_target),
                member_count=member_count,
                reason=reason,
            )
        )
    return results


def _short_type_name(full_or_short: str) -> str:
    return full_or_short.rsplit(".", 1)[-1]


def _build_known_edge_report(
    pages: list[ApiPage],
    edge_candidates: list[EdgeCandidate],
    node_candidates: list[NodeCandidate],
    checks: list[tuple[str, str]],
) -> list[KnownEdgeCheckResult]:
    all_members = [m for p in pages for m in p.members]
    # NodeCandidate.inheritance_chain entries are sometimes short names
    # (e.g. "Element") and sometimes fully-qualified (e.g. when the base
    # type was independently crawled), depending on how much of the chain
    # classify.py could resolve -- compare by short name to handle both.
    known_ancestor_short_names_by_type = {
        n.full_type_name: {_short_type_name(a) for a in n.inheritance_chain} for n in node_candidates
    }

    results: list[KnownEdgeCheckResult] = []
    for declaring_type, member_name in checks:
        exact_match = any(m.declaring_type == declaring_type and m.name == member_name for m in all_members)

        actual_declaring_type: str | None = None
        resolution_note = ""
        lookup_declaring_type = declaring_type
        if exact_match:
            member_found = True
        else:
            # Not found under the expected declaring type -- check whether
            # it was found under a *confirmed* base type of it instead of
            # assuming it's simply missing. A real crawl found exactly this:
            # Room.Number is actually declared on the intermediate base
            # class SpatialElement (Room -> SpatialElement -> Element),
            # which our own inherited-member attribution correctly resolves
            # to -- that should read as a confirmed fact, not a coverage
            # gap. This is deliberately restricted to declaring_type's own
            # resolved inheritance chain (not "any same-named member on any
            # crawled type") -- a common member name like "Name" or
            # "Number" appears on many unrelated types, and matching any of
            # them would misreport a genuinely missing member as found on
            # whatever unrelated type happened to share the name, hiding
            # the real coverage gap.
            known_ancestors = known_ancestor_short_names_by_type.get(declaring_type, set())
            other_match = next(
                (m for m in all_members if m.name == member_name and _short_type_name(m.declaring_type) in known_ancestors),
                None,
            )
            member_found = other_match is not None
            if other_match is not None:
                actual_declaring_type = other_match.declaring_type
                lookup_declaring_type = actual_declaring_type
                resolution_note = (
                    f"found declared on {actual_declaring_type} instead of the expected {declaring_type} "
                    "(a confirmed base type in its inheritance chain); "
                )

        edge = next(
            (e for e in edge_candidates if e.source_type == lookup_declaring_type and e.member_name == member_name),
            None,
        )
        edge_produced = edge is not None
        expected_no_edge = (declaring_type, member_name) in _EXPECTED_NO_EDGE

        if not member_found:
            note = "member page was not crawled/parsed in this run -- not a classifier problem, a coverage gap"
        elif expected_no_edge:
            note = (
                "as expected: no relationship edge (plain value property, by design)"
                if not edge_produced
                else "UNEXPECTED: an edge was produced for a member expected to have none -- check classify.py"
            )
        elif edge_produced:
            note = f"edge produced: {edge.candidate_edge_type.value} ({edge.edge_confidence.value})"
        else:
            note = "member found but no relationship edge was produced -- check classify.py's keyword/type rules"

        results.append(
            KnownEdgeCheckResult(
                declaring_type=declaring_type,
                member_name=member_name,
                member_found=member_found,
                edge_produced=edge_produced,
                edge_type=edge.candidate_edge_type.value if edge else None,
                edge_confidence=edge.edge_confidence.value if edge else None,
                note=resolution_note + note,
                actual_declaring_type=actual_declaring_type,
            )
        )
    return results


def run_targeted_pipeline(
    config: CrawlConfig,
    output_dir: Path,
    target_full_type_names: list[str] | None = None,
    known_edge_checks: list[tuple[str, str]] | None = None,
    include_doc_text: bool = False,
    checkpoint_interval: int = 25,
    checkpoint_min_interval_seconds: float = 30.0,
    label_communities_llm: bool = False,
    community_label_model: str = DEFAULT_OPENROUTER_MODEL,
    openrouter_api_key: str | None = None,
) -> TargetedPipelineResult:
    """Scoped validation crawl: fetch only the target classes' pages (class,
    Members, Methods/Properties, and every linked property/method page) via
    ``Crawler.discover_targeted``, instead of a full namespace-wide crawl.
    """
    # `or` would treat an explicitly empty list the same as "not passed" and
    # silently restore the defaults -- a caller running a focused crawl with
    # known_edge_checks=[] (no checks wanted) must get zero checks back, not
    # DEFAULT_KNOWN_EDGE_CHECKS.
    target_full_type_names = target_full_type_names if target_full_type_names is not None else DEFAULT_TARGET_CLASSES
    known_edge_checks = known_edge_checks if known_edge_checks is not None else DEFAULT_KNOWN_EDGE_CHECKS

    crawler = Crawler(config)
    output_dir.mkdir(parents=True, exist_ok=True)

    # discover_targeted already logs fetch/parse failures itself; notes here
    # also cover "target not found" cases, which aren't separately logged
    # there since they're expected/routine, not an error -- surfaced via
    # target_report/validation_summary.md instead.
    entries, found_map, discovery_notes = crawler.discover_targeted(target_full_type_names)

    by_url = {e["url"]: e for e in entries}

    last_result: dict = {}

    def checkpoint(pages: list[ApiPage], failed_urls: list[str], is_final: bool = False) -> None:
        node_candidates = classify.build_node_candidates(pages)
        edge_candidates = classify.build_edge_candidates(pages)
        graph_result = build_graph(node_candidates, edge_candidates)
        apply_communities(
            graph_result,
            use_llm_labels=label_communities_llm and is_final,
            model=community_label_model,
            api_key=openrouter_api_key,
        )

        raw_index_entries = list(by_url.values())

        target_report = _build_target_report(target_full_type_names, found_map, pages)
        known_edge_report = _build_known_edge_report(pages, edge_candidates, node_candidates, known_edge_checks)

        export.write_raw_index(output_dir, raw_index_entries)
        export.write_api_pages(output_dir, pages, include_doc_text=include_doc_text)
        export.write_node_candidates(output_dir, node_candidates)
        export.write_edge_candidates(output_dir, edge_candidates)
        export.write_enum_catalogs(output_dir, pages)
        export.write_graph(output_dir, graph_result, revit_version=config.version)
        export.write_graph_html(output_dir, graph_result, revit_version=config.version)
        export.write_semantic_relationship_map(output_dir, graph_result, revit_version=config.version)
        export.write_target_report(output_dir, target_report)
        export.write_known_edge_report(output_dir, known_edge_report)
        export.write_validation_summary(
            output_dir,
            revit_version=config.version,
            target_full_type_names=target_full_type_names,
            target_report=target_report,
            known_edge_report=known_edge_report,
            raw_index_entries=raw_index_entries,
            pages=pages,
            node_candidates=node_candidates,
            edge_candidates=edge_candidates,
            failed_urls=failed_urls,
            discovery_notes=discovery_notes,
            graph_result=graph_result,
        )

        last_result["raw_index_entries"] = raw_index_entries
        last_result["pages"] = pages
        last_result["node_candidates"] = node_candidates
        last_result["edge_candidates"] = edge_candidates
        last_result["failed_urls"] = failed_urls
        last_result["target_report"] = target_report
        last_result["known_edge_report"] = known_edge_report
        last_result["discovery_notes"] = discovery_notes

    pages, failed_urls = _crawl_and_parse(
        crawler, config, by_url, checkpoint=checkpoint, checkpoint_interval=checkpoint_interval, checkpoint_min_interval_seconds=checkpoint_min_interval_seconds
    )

    checkpoint(pages, failed_urls, True)  # guaranteed final write reflecting the complete result

    return TargetedPipelineResult(**last_result)
