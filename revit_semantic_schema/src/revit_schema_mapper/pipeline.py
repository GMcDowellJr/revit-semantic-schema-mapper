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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from . import classify, export
from .crawl import ALLOWED_HOST, CrawlConfig, Crawler
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


def _crawl_and_parse(
    crawler: Crawler,
    config: CrawlConfig,
    by_url: dict[str, dict],
    checkpoint: Callable[[list[ApiPage], list[str]], None] | None = None,
    checkpoint_interval: int = 25,
) -> tuple[list[ApiPage], list[str]]:
    """Fetch/sniff/parse every URL in ``by_url``, following class ->
    Members-page links and enqueueing newly-discovered member pages as it
    goes. ``by_url`` is mutated in place (new entries are added for anything
    discovered along the way) -- shared by both ``run_pipeline`` (broad
    crawl) and ``run_targeted_pipeline`` (scoped validation crawl), which
    differ only in how they seed ``by_url`` and what they do with the
    results afterward.

    If ``checkpoint`` is given, it's called every ``checkpoint_interval``
    pages with the pages/failed_urls parsed so far (the caller is expected to
    export them), and once more if the loop exits early via an unhandled
    exception -- including KeyboardInterrupt -- so a long crawl that's
    interrupted partway through still leaves reasonably fresh, usable output
    on disk instead of nothing at all. The caller is responsible for calling
    ``checkpoint`` itself one final time after this returns normally, to
    export the complete result -- this function only guarantees a checkpoint
    on the *abnormal*-exit path.
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
        )
    except BaseException:
        if checkpoint is not None:
            logger.info("crawl interrupted -- writing a final checkpoint with %d page(s) parsed so far", len(pages))
            checkpoint(pages, failed_urls)
        raise

    return pages, failed_urls


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
    checkpoint: Callable[[list[ApiPage], list[str]], None] | None,
    checkpoint_interval: int,
) -> None:
    while queue:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        if config.max_pages is not None and len(visited) > config.max_pages:
            break
        if len(visited) % checkpoint_interval == 0:
            logger.info(
                "progress: %d pages fetched, %d queued, %d parsed, %d failed",
                len(visited), len(queue), len(pages), len(failed_urls),
            )
            if checkpoint is not None:
                checkpoint(pages, failed_urls)

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


def run_pipeline(
    config: CrawlConfig,
    output_dir: Path,
    fallback_reason: str | None = None,
    include_doc_text: bool = False,
    checkpoint_interval: int = 25,
) -> PipelineResult:
    crawler = Crawler(config)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_index_entries = crawler.discover_index()
    by_url = {e["url"]: e for e in raw_index_entries}

    last_result: dict = {}

    def checkpoint(pages: list[ApiPage], failed_urls: list[str]) -> None:
        """Write every output file reflecting ``pages``/``failed_urls`` as
        parsed so far. Called periodically during the crawl (see
        ``_crawl_and_parse``) and once more after it returns, so a full run
        that takes hours leaves current, usable output on disk throughout --
        not just after everything finishes -- and a run that's interrupted
        partway through (including by KeyboardInterrupt) still leaves
        whatever was parsed up to that point, instead of nothing at all.
        """
        in_scope_pages = [p for p in pages if not p.namespace or p.namespace.startswith(config.namespace_prefix)]

        node_candidates = classify.build_node_candidates(in_scope_pages)
        edge_candidates = classify.build_edge_candidates(in_scope_pages)

        raw_index = list(by_url.values())

        export.write_raw_index(output_dir, raw_index)
        export.write_api_pages(output_dir, in_scope_pages, include_doc_text=include_doc_text)
        export.write_node_candidates(output_dir, node_candidates)
        export.write_edge_candidates(output_dir, edge_candidates)
        export.write_enum_catalogs(output_dir, in_scope_pages)

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
        )

        last_result["raw_index_entries"] = raw_index
        last_result["pages"] = in_scope_pages
        last_result["node_candidates"] = node_candidates
        last_result["edge_candidates"] = edge_candidates
        last_result["failed_urls"] = failed_urls

    pages, failed_urls = _crawl_and_parse(crawler, config, by_url, checkpoint=checkpoint, checkpoint_interval=checkpoint_interval)

    checkpoint(pages, failed_urls)  # guaranteed final write reflecting the complete result

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

    def checkpoint(pages: list[ApiPage], failed_urls: list[str]) -> None:
        node_candidates = classify.build_node_candidates(pages)
        edge_candidates = classify.build_edge_candidates(pages)

        raw_index_entries = list(by_url.values())

        target_report = _build_target_report(target_full_type_names, found_map, pages)
        known_edge_report = _build_known_edge_report(pages, edge_candidates, node_candidates, known_edge_checks)

        export.write_raw_index(output_dir, raw_index_entries)
        export.write_api_pages(output_dir, pages, include_doc_text=include_doc_text)
        export.write_node_candidates(output_dir, node_candidates)
        export.write_edge_candidates(output_dir, edge_candidates)
        export.write_enum_catalogs(output_dir, pages)
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
        )

        last_result["raw_index_entries"] = raw_index_entries
        last_result["pages"] = pages
        last_result["node_candidates"] = node_candidates
        last_result["edge_candidates"] = edge_candidates
        last_result["failed_urls"] = failed_urls
        last_result["target_report"] = target_report
        last_result["known_edge_report"] = known_edge_report
        last_result["discovery_notes"] = discovery_notes

    pages, failed_urls = _crawl_and_parse(crawler, config, by_url, checkpoint=checkpoint, checkpoint_interval=checkpoint_interval)

    checkpoint(pages, failed_urls)  # guaranteed final write reflecting the complete result

    return TargetedPipelineResult(**last_result)
