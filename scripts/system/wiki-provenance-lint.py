#!/usr/bin/env python3
"""Validate kb-prov-v1 block provenance in wiki/ pages."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.paths import wiki_pages as _wiki_pages  # noqa: E402
from lib.provenance import validate_provenance  # noqa: E402


def _default_root() -> Path:
    return Path(__file__).resolve().parents[2]


def lint(root: Path) -> dict:
    issues = []
    files_checked = 0
    for path in _wiki_pages(root):
        files_checked += 1
        rel = str(path.relative_to(root))
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            issues.append({
                "code": "read-error",
                "message": str(exc),
                "path": rel,
                "severity": "error",
            })
            continue
        issues.extend(
            issue.as_dict()
            for issue in validate_provenance(content, path=rel)
        )
    errors = sum(1 for issue in issues if issue.get("severity", "error") == "error")
    return {
        "summary": {
            "files_checked": files_checked,
            "issues": len(issues),
            "errors": errors,
            "warnings": len(issues) - errors,
        },
        "issues": issues,
    }


def parse_args():
    parser = argparse.ArgumentParser(
        description="Validate kb-prov-v1 provenance callouts in wiki/ pages.",
    )
    parser.add_argument(
        "--root",
        default=None,
        help="Vault root to scan (default: parent of scripts/).",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve() if args.root else _default_root()
    result = lint(root)
    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        summary = result["summary"]
        print("Provenance lint")
        print(f"  files checked : {summary['files_checked']}")
        print(f"  errors        : {summary['errors']}")
        print(f"  warnings      : {summary['warnings']}")
        for issue in result["issues"]:
            path = issue.get("path", "")
            block_id = issue.get("block_id", "")
            suffix = f" ({block_id})" if block_id else ""
            severity = issue.get("severity", "error")
            print(f"  - [{severity}] {path}{suffix}: {issue['code']}: {issue['message']}")
    return 1 if result["summary"]["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
