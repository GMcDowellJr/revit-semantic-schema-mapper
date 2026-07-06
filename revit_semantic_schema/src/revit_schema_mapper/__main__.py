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
from .pipeline import run_pipeline

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
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    output_dir = Path(args.output_dir) if args.output_dir else Path(f"outputs/revit_{args.version}")
    cache_dir = Path(args.cache_dir) if args.cache_dir else output_dir / "cache"

    config = CrawlConfig(
        version=args.version,
        namespace_prefix=args.namespace_prefix,
        cache_dir=cache_dir,
        throttle_seconds=args.throttle_seconds,
        max_pages=args.max_pages,
        force_refresh=args.force_refresh,
    )

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
