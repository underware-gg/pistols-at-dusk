from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import minimal8_harness as harness


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Source-side ingest and review tooling for family-backed tilesets."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser(
        "inspect-family",
        help="Export grid, cluster, semantic, and contact-sheet inspection outputs for one project family variant.",
    )
    inspect_parser.add_argument("project", nargs="?", type=Path, default=harness.DEFAULT_PROJECT)
    inspect_parser.add_argument("--tileset", required=True)
    inspect_parser.add_argument("--output-dir", type=Path, default=None)

    detect_source_layout_parser = subparsers.add_parser(
        "detect-source-layout",
        help="Suggest source-sheet ingest regions, clusters, and multi-tile components from a family variant bitmap.",
    )
    detect_source_layout_parser.add_argument("project", nargs="?", type=Path, default=harness.DEFAULT_PROJECT)
    detect_source_layout_parser.add_argument("--tileset", required=True)
    detect_source_layout_parser.add_argument("--output-dir", type=Path, default=None)

    inspect_source_cell_parser = subparsers.add_parser(
        "inspect-source-cell",
        help=(
            "Inspect one zero-based source-sheet cell through the authoritative source-layout ingest map, "
            "including its region/cluster context and any mapped family tile."
        ),
    )
    inspect_source_cell_parser.add_argument("project", nargs="?", type=Path, default=harness.DEFAULT_PROJECT)
    inspect_source_cell_parser.add_argument("--tileset", required=True)
    inspect_source_cell_parser.add_argument("--sheet-col", required=True, type=int)
    inspect_source_cell_parser.add_argument("--sheet-row", required=True, type=int)

    review_pack_parser = subparsers.add_parser(
        "export-review-pack",
        help="Export a filtered semantic tile review pack with tile copies and an annotation doc.",
    )
    review_pack_parser.add_argument("project", nargs="?", type=Path, default=harness.DEFAULT_PROJECT)
    review_pack_parser.add_argument("--tileset", required=True)
    review_pack_parser.add_argument("--output-dir", type=Path, default=None)
    review_pack_parser.add_argument("--scene", default=None)
    review_pack_parser.add_argument("--category", action="append", default=[])
    review_pack_parser.add_argument("--alias-prefix", default=None)
    review_pack_parser.add_argument("--scale", type=int, default=8)

    collection_review_parser = subparsers.add_parser(
        "export-collection-review-pack",
        help="Export a repo-backed, commit-friendly review pack for authored source-layout collections.",
    )
    collection_review_parser.add_argument("project", nargs="?", type=Path, default=harness.DEFAULT_PROJECT)
    collection_review_parser.add_argument("--tileset", required=True)
    collection_review_parser.add_argument("--output-dir", type=Path, default=None)
    collection_review_parser.add_argument("--scratch-output-dir", type=Path, default=None)
    collection_review_parser.add_argument("--slug", default=None)
    collection_review_parser.add_argument("--scale", type=int, default=8)

    validate_ingest_parser = subparsers.add_parser(
        "validate-family-ingest",
        help="Validate that every family tile has source_group, cluster_ids, meaning, and meaning_confidence coverage.",
    )
    validate_ingest_parser.add_argument("project", nargs="?", type=Path, default=harness.DEFAULT_PROJECT)
    validate_ingest_parser.add_argument("--tileset", required=True)

    audit_usage_parser = subparsers.add_parser(
        "audit-family-semantic-usage",
        help="Surface aliases and project refs that still land on non-confirmed family meanings.",
    )
    audit_usage_parser.add_argument("project", nargs="?", type=Path, default=harness.DEFAULT_PROJECT)
    audit_usage_parser.add_argument("--tileset", required=True)
    audit_usage_parser.add_argument("--layouts-dir", type=Path, default=None)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "inspect-family":
        output_dir = args.output_dir or (harness.DEFAULT_INSPECT_DIR / args.tileset)
        print(harness.inspect_family(args.project, args.tileset, output_dir))
    elif args.command == "detect-source-layout":
        output_dir = args.output_dir or (harness.DEFAULT_INSPECT_DIR / f"{args.tileset}-detected")
        print(harness.detect_family_source_layout(args.project, args.tileset, output_dir))
    elif args.command == "inspect-source-cell":
        print(
            json.dumps(
                harness.inspect_source_cell(
                    args.project,
                    args.tileset,
                    sheet_col=args.sheet_col,
                    sheet_row=args.sheet_row,
                ),
                indent=2,
            )
        )
    elif args.command == "export-review-pack":
        output_dir = args.output_dir
        if output_dir is None:
            pack_slug_parts = [args.scene or "semantic"]
            if args.category:
                pack_slug_parts.extend(args.category)
            pack_slug = harness.slugify_identifier("-".join(pack_slug_parts))
            output_dir = harness.DEFAULT_REVIEW_PACK_DIR / pack_slug
        print(
            harness.export_semantic_review_pack(
                args.project,
                args.tileset,
                output_dir,
                scene=args.scene,
                categories=args.category,
                alias_prefix=args.alias_prefix,
                scale=args.scale,
            )
        )
    elif args.command == "export-collection-review-pack":
        output_dir = args.output_dir
        if output_dir is None:
            slug = args.slug or f"{harness.slugify_identifier(args.tileset)}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            output_dir = harness.DEFAULT_COLLECTION_REVIEW_DIR / slug
        scratch_output_dir = args.scratch_output_dir
        if scratch_output_dir is None:
            scratch_output_dir = harness.DEFAULT_COLLECTION_REVIEW_SCRATCH_DIR / output_dir.name
        print(
            harness.export_collection_review_pack(
                args.project,
                args.tileset,
                output_dir,
                scale=args.scale,
                scratch_output_root=scratch_output_dir,
            )
        )
    elif args.command == "validate-family-ingest":
        report = harness.validate_family_ingest(args.project, args.tileset)
        print(json.dumps(report, indent=2))
        if not report["complete"]:
            raise SystemExit(1)
    elif args.command == "audit-family-semantic-usage":
        report = harness.audit_family_semantic_usage(args.project, args.tileset, layouts_dir=args.layouts_dir)
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
