"""CLI entry point: ``python -m revit_schema_mapper``.

This is the single command referenced in the project's definition of done:
it runs discovery, crawl, parse, classify, and export in one shot and is
resumable (re-running it will reuse the on-disk HTML cache and only fetch
what's missing).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .crawl import CrawlConfig
from .http_compat import HAVE_REQUESTS
from .pipeline import DEFAULT_KNOWN_EDGE_CHECKS, DEFAULT_TARGET_CLASSES, run_discovery, run_pipeline, run_targeted_pipeline

try:
    import bs4 as _bs4  # noqa: F401

    HAVE_BS4 = True
except ImportError:
    HAVE_BS4 = False

KNOWN_FALLBACK_REASON = (
    "Revit 2027 API docs were not confirmed reachable/structurally consistent at build time; "
    "falling back to 2026. Document why in docs/crawl_notes.md if this triggers for a real run."
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crawl, parse, and classify the Autodesk.Revit.DB API surface from RevitApiDocs.")
    parser.add_argument("--version", default="2027", help="Revit version path segment on revitapidocs.com (default: 2027)")
    parser.add_argument("--output-dir", default=None, help="Output directory (default: outputs/revit_<version>/ relative to repo root)")
    parser.add_argument("--cache-dir", default=None, help="HTML cache directory (default: <output-dir>/cache)")
    parser.add_argument("--namespace-prefix", default="Autodesk.Revit.DB", help="Only keep pages whose namespace starts with this prefix")
    parser.add_argument("--throttle-seconds", type=float, default=1.5, help="Minimum delay between HTTP requests")
    parser.add_argument("--max-pages", type=int, default=None, help="Cap on total pages fetched (useful for smoke tests)")
    parser.add_argument("--force-refresh", action="store_true", help="Re-fetch pages even if already cached")
    parser.add_argument("--fallback-reason", default=None, help="If set, records why this run is a documented fallback (e.g. from 2027 to 2026)")
    parser.add_argument(
        "--targeted-validation",
        action="store_true",
        help="Run a scoped validation crawl against a fixed list of target classes plus a known-edge test report, instead of a full namespace crawl",
    )
    parser.add_argument(
        "--target-classes",
        default=None,
        help="Comma-separated fully-qualified class names to use with --targeted-validation, overriding the default list",
    )
    parser.add_argument(
        "--discover-only",
        action="store_true",
        help="Only run page discovery and report how many pages a full run would need to fetch -- "
        "does not fetch/parse individual pages or write anything but raw_index.json",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    log = logging.getLogger(__name__)
    log.info("HTTP backend: %s", "requests" if HAVE_REQUESTS else "urllib.request (stdlib fallback -- requests not installed)")
    log.info("HTML backend: %s", "beautifulsoup4" if HAVE_BS4 else "html_compat (stdlib fallback -- beautifulsoup4 not installed)")

    targeted = args.targeted_validation or args.target_classes is not None

    default_output_name = f"revit_{args.version}_targeted" if targeted else f"revit_{args.version}"
    output_dir = Path(args.output_dir) if args.output_dir else Path(f"outputs/{default_output_name}")
    cache_dir = Path(args.cache_dir) if args.cache_dir else output_dir / "cache"

    config = CrawlConfig(
        version=args.version,
        namespace_prefix=args.namespace_prefix,
        cache_dir=cache_dir,
        throttle_seconds=args.throttle_seconds,
        max_pages=args.max_pages,
        force_refresh=args.force_refresh,
    )

    if args.discover_only:
        result = run_discovery(config, output_dir)
        print(f"Pages discovered: {len(result.raw_index_entries)}")
        for source, count in sorted(result.counts_by_source.items(), key=lambda kv: -kv[1]):
            print(f"  {source}: {count}")
        if result.discovery_errors:
            print(f"Discovery errors ({len(result.discovery_errors)}):")
            for err in result.discovery_errors:
                print(f"  {err}")
        print(f"Raw index written to: {output_dir / 'raw_index.json'}")
        return 0

    if targeted:
        target_classes = [t.strip() for t in args.target_classes.split(",") if t.strip()] if args.target_classes else DEFAULT_TARGET_CLASSES
        result = run_targeted_pipeline(config, output_dir, target_full_type_names=target_classes, known_edge_checks=DEFAULT_KNOWN_EDGE_CHECKS)

        targets_found = sum(1 for t in result.target_report if t.found_in_namespace_json)
        targets_parsed = sum(1 for t in result.target_report if t.class_page_parsed)
        edges_found = sum(1 for k in result.known_edge_report if k.edge_produced)
        print(f"Target classes:      {len(target_classes)} ({targets_found} found in index, {targets_parsed} parsed)")
        print(f"Known-edge checks:   {len(result.known_edge_report)} ({edges_found} produced an edge)")
        print(f"Pages discovered:    {len(result.raw_index_entries)}")
        print(f"Pages parsed:        {len(result.pages)}")
        print(f"Node candidates:     {len(result.node_candidates)}")
        print(f"Edge candidates:     {len(result.edge_candidates)}")
        print(f"Failed pages:        {len(result.failed_urls)}")
        print(f"Outputs written to: {output_dir} (see validation_summary.md)")
        return 0

    result = run_pipeline(config, output_dir, fallback_reason=args.fallback_reason)

    print(f"Pages discovered: {len(result.raw_index_entries)}")
    print(f"Pages parsed:     {len(result.pages)}")
    print(f"Node candidates:  {len(result.node_candidates)}")
    print(f"Edge candidates:  {len(result.edge_candidates)}")
    print(f"Failed pages:     {len(result.failed_urls)}")
    print(f"Outputs written to: {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
