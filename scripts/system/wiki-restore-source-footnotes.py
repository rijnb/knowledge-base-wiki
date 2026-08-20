#!/usr/bin/env python3
"""Restore per-claim source footnotes from a pre-OKF vault backup.

Joins the legacy `kb-prov-v1` provenance callouts in a backup snapshot
(anchor -> resources) with the current OKF v0.2 frontmatter
(resource -> sN id) and inserts `[^sN]` footnote refs before each block
anchor, plus a footnote-definitions block at the end of each page.

Dry-run by default; pass --apply to write. Prints a JSON report to stdout.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.source_footnotes import apply_footnotes, callout_block_sources  # noqa: E402


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Restore [^sN] source footnotes from backup provenance callouts.",
    )
    parser.add_argument(
        "--backup",
        required=True,
        help="Pre-OKF vault backup root (contains wiki/ with provenance callouts).",
    )
    parser.add_argument("--root", default=None, help="Vault root to update.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes to pages (default: dry-run, report only).",
    )
    parser.add_argument(
        "pages",
        nargs="*",
        help="Optional vault-relative page paths to restrict the run to.",
    )
    return parser.parse_args()


def restore(root: Path, backup: Path, apply: bool, only: set[str]) -> dict:
    pages: list[dict] = []
    summary: dict[str, int] = {}

    def record(page: str, action: str, **extra):
        summary[action] = summary.get(action, 0) + 1
        pages.append({"page": page, "action": action, **extra})

    for backup_path in sorted((backup / "wiki").rglob("*.md")):
        rel = backup_path.relative_to(backup).as_posix()
        if only and rel not in only:
            continue
        block_sources = callout_block_sources(
            backup_path.read_text(encoding="utf-8", errors="replace")
        )
        if not block_sources:
            continue
        current_path = root / rel
        if not current_path.is_file():
            record(rel, "missing-current")
            continue
        content = current_path.read_text(encoding="utf-8", errors="replace")
        outcome = apply_footnotes(content, block_sources)
        if outcome.action == "no-provenance":
            record(rel, "no-provenance")
            continue
        details = {
            "inserted_refs": outcome.inserted_refs,
            "added_sources": list(outcome.added_sources),
            "unmapped_anchors": list(outcome.unmapped_anchors),
            "stale_blocks": list(outcome.stale_blocks),
        }
        if outcome.content == content:
            record(rel, "unchanged", **details)
            continue
        if apply:
            current_path.write_text(outcome.content, encoding="utf-8")
            record(rel, "updated", **details)
        else:
            record(rel, "would-update", **details)

    return {"summary": summary, "pages": pages}


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve() if args.root else _default_root()
    backup = Path(args.backup).expanduser().resolve()
    if not (backup / "wiki").is_dir():
        print(f"error: no wiki/ directory under backup root {backup}", file=sys.stderr)
        return 1
    report = restore(root, backup, apply=args.apply, only=set(args.pages))
    json.dump(report, sys.stdout, indent=2, ensure_ascii=False)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
