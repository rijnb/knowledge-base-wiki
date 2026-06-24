#!/usr/bin/env python3
"""Build a query-time freshness packet for retrieved Wiki pages."""

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.freshness_query import (  # noqa: E402
    build_query_packet,
    build_query_packet_from_qmd_results,
)


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _non_negative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("limit must be a non-negative integer")
    return parsed


def parse_args():
    parser = argparse.ArgumentParser(
        description="Rank retrieved canonical blocks by query-time freshness.",
    )
    parser.add_argument("--root", default=None, help="Vault root to scan.")
    parser.add_argument("--query", required=True, help="User query to classify.")
    parser.add_argument(
        "--page",
        action="append",
        default=[],
        help="Retrieved Wiki page path or WikiLink. Repeat for multiple pages.",
    )
    parser.add_argument(
        "--qmd",
        action="store_true",
        help="Run local `qmd query` first, then rank the returned Wiki pages.",
    )
    parser.add_argument(
        "--qmd-limit",
        type=_non_negative_int,
        default=15,
        help="Number of QMD results to inspect when --qmd is used (default: 15).",
    )
    parser.add_argument(
        "--collection",
        default="tomtom",
        help="QMD collection name for --qmd result resolution (default: tomtom).",
    )
    parser.add_argument(
        "--qmd-no-rerank",
        action="store_true",
        help="Pass --no-rerank to qmd for faster local candidate discovery.",
    )
    parser.add_argument(
        "--limit",
        type=_non_negative_int,
        default=10,
        help="Maximum ranked blocks to return (default: 10).",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )
    return parser.parse_args()


def _parse_qmd_files_output(output: str) -> list[str]:
    files: list[str] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped or "," not in stripped:
            continue
        score, path = stripped.split(",", 1)
        try:
            float(score)
        except ValueError:
            continue
        files.append(path.strip())
    return files


def _run_qmd_query(query: str, limit: int, collection: str, no_rerank: bool) -> list[str]:
    cmd = [
        "qmd",
        "query",
        query,
        "--format",
        "files",
        "--full-path",
        "-n",
        str(limit),
        "-c",
        collection,
    ]
    if no_rerank:
        cmd.append("--no-rerank")
    result = subprocess.run(
        cmd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"qmd query failed with exit {result.returncode}: {detail}")
    return _parse_qmd_files_output(result.stdout)


def _print_text(packet: dict) -> None:
    print("Freshness query packet")
    print(f"  query intent       : {packet['query_intent']}")
    print(f"  candidate pages    : {len(packet['candidate_pages'])}")
    print(f"  ranked blocks      : {len(packet['ranked_blocks'])} of {packet['total_ranked_blocks']}")
    print(f"  legacy pages       : {len(packet['legacy_pages'])}")
    print(f"  raw mappings       : {len(packet.get('raw_mappings', []))}")
    print(f"  raw evidence       : {len(packet.get('raw_evidence', []))}")
    for block in packet["ranked_blocks"]:
        print(
            f"  {block['rank']}. {block['id']} "
            f"[{block['status']}/{block['confidence']}, score {block['freshness_score']}]"
        )
        print(f"     page  : {block['page_path']}")
        print(f"     action: {block['freshness_action']}")
        print(f"     note  : {block['freshness_note']}")
    if packet["legacy_pages"]:
        print("  legacy page notes:")
        for page in packet["legacy_pages"]:
            print(f"    - {page['path']}: {page['reason']}")
    if packet.get("raw_mappings"):
        print("  raw mappings:")
        for mapping in packet["raw_mappings"]:
            print(
                f"    - {mapping['path']} -> "
                f"{', '.join(mapping['mapped_pages'])} ({', '.join(mapping['reasons'])})"
            )
    if packet.get("raw_evidence"):
        print("  unmapped raw evidence:")
        for raw in packet["raw_evidence"]:
            print(f"    - {raw['path']}: {raw['reason']}")


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve() if args.root else _default_root()
    try:
        pages = list(args.page)
        if args.qmd:
            qmd_files = _run_qmd_query(
                args.query,
                limit=args.qmd_limit,
                collection=args.collection,
                no_rerank=args.qmd_no_rerank,
            )
            packet = build_query_packet_from_qmd_results(
                root,
                query=args.query,
                result_files=qmd_files,
                pages=pages,
                collection=args.collection,
                limit=args.limit,
            )
        else:
            packet = build_query_packet(
                root,
                query=args.query,
                pages=pages or None,
                limit=args.limit,
            )
    except (FileNotFoundError, RuntimeError) as exc:
        if args.format == "json":
            print(json.dumps({"error": str(exc)}, indent=2))
        else:
            print(str(exc), file=sys.stderr)
        return 1

    if args.format == "json":
        print(json.dumps(packet, indent=2, ensure_ascii=False))
    else:
        _print_text(packet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
