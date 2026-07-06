"""End-to-end pipeline: crawl -> parse -> classify -> export.

This is the "one command" referenced in the project's definition of done.
See ``python -m revit_schema_mapper --help`` (src/revit_schema_mapper/__main__.py).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from . import classify, export
from .crawl import ALLOWED_HOST, CrawlConfig, Crawler
from .models import ApiPage, Kind
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


def run_pipeline(config: CrawlConfig, output_dir: Path, fallback_reason: str | None = None) -> PipelineResult:
    crawler = Crawler(config)
    output_dir.mkdir(parents=True, exist_ok=True)

    raw_index_entries = crawler.discover_index()
    by_url = {e["url"]: e for e in raw_index_entries}

    pages: list[ApiPage] = []
    failed_urls: list[str] = []
    # queue of (url, declaring_type_hint) for pages we know are member pages
    # because we found their link in a type's members table.
    member_queue: list[tuple[str, str]] = []
    visited: set[str] = set()

    def enqueue_member_links(links: list[dict], declaring_full_type_name: str, discovered_via_prefix: str) -> None:
        for link in links:
            url = link["url"]
            if urlparse(url).netloc != ALLOWED_HOST:
                # Some pages link inherited Object members (Equals, GetHashCode,
                # ToString) out to MSDN instead of rendering them as plain text;
                # out of scope by design, not a fetch failure.
                continue
            if url not in visited and url not in by_url:
                by_url[url] = {
                    "url": url,
                    "link_text": link["name"],
                    "discovered_via": f"{discovered_via_prefix}:{declaring_full_type_name}",
                }
                member_queue.append((url, declaring_full_type_name))
                queue.append(url)

    queue = list(by_url.keys())
    while queue:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        if config.max_pages is not None and len(visited) > config.max_pages:
            break

        declaring_type_hint = next((dt for u, dt in member_queue if u == url), None)
        if declaring_type_hint is None:
            # Not reached by following a class's Members-page link -- e.g.
            # discovered directly via the namespace JSON, which carries its
            # own declaring_type_hint computed at flatten time (see
            # Crawler._flatten_namespace_node).
            declaring_type_hint = by_url.get(url, {}).get("declaring_type_hint")

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
                # Reached independently (not via its class page) -- derive the
                # owning type name from this page itself rather than skipping.
                declaring_full_type_name = resolve_type_name_from_members_index(html)
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

    in_scope_pages = [p for p in pages if not p.namespace or p.namespace.startswith(config.namespace_prefix)]

    node_candidates = classify.build_node_candidates(in_scope_pages)
    edge_candidates = classify.build_edge_candidates(in_scope_pages)

    raw_index_entries = list(by_url.values())

    export.write_raw_index(output_dir, raw_index_entries)
    export.write_api_pages(output_dir, in_scope_pages)
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
    if not raw_index_entries and crawler.last_discovery_errors:
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
        raw_index_entries=raw_index_entries,
        pages=in_scope_pages,
        node_candidates=node_candidates,
        edge_candidates=edge_candidates,
        limitations=limitations,
        next_steps=next_steps,
    )

    return PipelineResult(
        raw_index_entries=raw_index_entries,
        pages=in_scope_pages,
        node_candidates=node_candidates,
        edge_candidates=edge_candidates,
        failed_urls=failed_urls,
    )
