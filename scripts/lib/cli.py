"""Command-line entry point — argparse, dispatch, and exit codes."""

import argparse
import json
import sys
from pathlib import Path

from .checks.legacy import check_legacy_converted, run_migration
from .checks.loose import check_loose_files
from .checks.orphans import check_orphans, fix_orphans
from .checks.stubs import check_stubs
from .checks.vault import check_vault
from .report import format_text
from .tui.app import run_interactive
from .tui.dialogs import ask_run_auto_fixes, ask_run_migration, run_scan_with_dialog


def parse_args():
    parser = argparse.ArgumentParser(
        prog="wiki-doctor.py",
        description=(
            "Scan Markdown files for broken internal and external links.\n"
            "Output is structured JSON (default) or human-readable text, "
            "designed for AI consumption."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan vault rooted at the script's parent directory:
  python3 wiki-doctor.py

  # Scan a specific vault directory:
  python3 wiki-doctor.py /path/to/vault

  # Human-readable output:
  python3 wiki-doctor.py --format text

  # Include external HTTP link checks:
  python3 wiki-doctor.py --external --timeout 10

  # Skip image embeds in checks (they're checked by default):
  python3 wiki-doctor.py --no-include-images

  # Skip frontmatter links (e.g. author: [[Name]] in raw/clips):
  python3 wiki-doctor.py --skip-frontmatter

  # Show suggested fixes for broken wikilinks, then apply them:
  python3 wiki-doctor.py --format text
  python3 wiki-doctor.py --fix-simple-errors

  # Batch mode (no TUI, output only):
  python3 wiki-doctor.py --batch-mode --format text

  # Combine options:
  python3 wiki-doctor.py --external --skip-frontmatter --format text /path/to/vault
        """,
    )
    parser.add_argument(
        "root",
        nargs="?",
        default=None,
        help="Root directory of the vault (default: parent of this script's directory)",
    )
    parser.add_argument(
        "--external",
        action="store_true",
        help="Also check HTTP/HTTPS links (requires network access; slow)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=5,
        metavar="N",
        help="Timeout in seconds for external HTTP requests (default: 5)",
    )
    parser.add_argument(
        "--no-include-images",
        action="store_false",
        dest="include_images",
        default=True,
        help="Skip image embed checks (![[...]] and ![alt](...)). Embeds are checked by default.",
    )
    parser.add_argument(
        "--format",
        choices=["json", "text"],
        default="text",
        help="Output format: 'text' for humans (default), 'json' for AI",
    )
    parser.add_argument(
        "--skip-frontmatter",
        action="store_true",
        help="Do not check links inside YAML frontmatter (useful to ignore author/tag references)",
    )
    parser.add_argument(
        "--remove-broken-links",
        action="store_true",
        dest="remove_broken_links",
        help=(
            "Rewrite broken WikiLinks in-place to mark them visually. "
            "[[broken]] becomes [[broken|(broken link) broken]] and "
            "[[broken|text]] becomes [[broken|(broken link) text]], "
            "preserving the original target while flagging it in the display text."
        ),
    )
    parser.add_argument(
        "--fix-simple-errors",
        action="store_true",
        dest="fix_simple_errors",
        help=(
            "Rewrite broken WikiLinks where a unique normalized match is found "
            "(characters like ':' are often replaced by '_' in filenames or omitted "
            "in link text); normalize curly quotes; wikilink bare/backticked raw/ "
            "references; and prune wiki/log.jsonl in place (backup at "
            "wiki/log.jsonl.bak), dropping entries whose 'file' no longer exists "
            "and collapsing duplicate entries for the same file (keeping the latest)."
            " Also relocates loose non-markdown files in raw/, wiki/ and INBOX/ "
            "into sibling _resources/ directories via the Obsidian CLI (requires "
            "Obsidian running; clash-safe renaming) and converts them to companion "
            ".md notes."
        ),
    )
    parser.add_argument(
        "--fix-orphans",
        action="store_true",
        dest="fix_orphans",
        help=(
            "For each orphaned Wiki page, find plain-text references to its name in wiki/ "
            "files and replace them with WikiLinks. Only modifies files inside wiki/."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress messages written to stderr",
    )
    parser.add_argument(
        "--batch-mode",
        action="store_true",
        dest="batch_mode",
        help=(
            "Disable the interactive TUI and output results in text/JSON format only. "
            "By default, an interactive TUI opens after scanning to fix broken links one by one."
        ),
    )
    return parser, parser.parse_args()


def main():
    parser, args = parse_args()

    # Determine root directory
    if args.root:
        root = Path(args.root).resolve()
    else:
        # Default: parent of the 'scripts' directory (i.e., the vault root)
        script_dir = Path(__file__).resolve().parent.parent
        if script_dir.name == "scripts":
            root = script_dir.parent
        else:
            root = script_dir

    if not root.exists():
        msg = f"Error: directory does not exist: {root}"
        if args.format == "json":
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(msg, file=sys.stderr)
        sys.exit(1)

    if not root.is_dir():
        msg = f"Error: not a directory: {root}"
        if args.format == "json":
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(msg, file=sys.stderr)
        sys.exit(1)

    # Legacy converted/ layout: detect before scanning (a migration moves files
    # around, so it must happen before links are resolved). In interactive mode
    # offer to run the migration script; in batch mode it is reported only.
    legacy_result = check_legacy_converted(root, args.quiet)
    migration_result = None
    if not args.batch_mode and legacy_result["legacy_converted"]:
        if ask_run_migration(legacy_result["legacy_converted"]):
            migration_result = run_migration(root)
            if migration_result.get("error"):
                print(migration_result["error"], file=sys.stderr)
            else:
                for stream in ("stdout", "stderr"):
                    text = migration_result.get(stream, "")
                    if text.strip():
                        print(text.rstrip(),
                              file=sys.stderr if stream == "stderr" else sys.stdout)
            legacy_result = check_legacy_converted(root, quiet=True)

    auto_fix_applied = False
    try:
        if not args.batch_mode:
            result = run_scan_with_dialog(root, args)
            has_fixable = (
                any("suggested_fix" in b for b in result["broken_links"])
                or bool(result.get("orphans"))
                or result.get("raw_refs_pending", 0) > 0
                or result.get("log_pruned_pending", 0) > 0
                or result.get("loose_pending", 0) > 0
            )
            if has_fixable:
                auto_fix_applied = ask_run_auto_fixes()
                if auto_fix_applied:
                    args.fix_simple_errors = True
                    args.fix_orphans = True
                    result = run_scan_with_dialog(root, args)
        else:
            result = check_vault(root, args)
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        msg = f"Unexpected error: {e}"
        if args.format == "json":
            print(json.dumps({"error": msg}, indent=2))
        else:
            print(msg, file=sys.stderr)
        sys.exit(1)

    result["legacy_converted"] = legacy_result["legacy_converted"]
    result["legacy_summary"] = legacy_result["summary"]
    if migration_result is not None:
        result["legacy_migration"] = {
            "ran": migration_result.get("ran", False),
            "returncode": migration_result.get("returncode"),
        }

    if args.batch_mode:
        if getattr(args, "fix_simple_errors", False):
            # Keep only the links that REMAIN broken (not actually fixed, not
            # frontmatter-deleted). summary.fixed_links already reports the fixes,
            # so a fully-fixed run must report 0 remaining broken and exit 0.
            result["broken_links"] = [
                b for b in result["broken_links"]
                if not b.get("fixed") and not b.get("fm_deleted")
            ]
            result["summary"]["broken"] = len(result["broken_links"])

        orphan_result = check_orphans(root, args.quiet)
        result["orphans"] = orphan_result["orphans"]
        result["orphan_summary"] = orphan_result["summary"]

        stub_result = check_stubs(root, args.quiet)
        result["stubs"] = stub_result["stubs"]
        result["stub_summary"] = stub_result["summary"]

        # After check_vault: with --fix-simple-errors this reports what REMAINS loose.
        loose_result = check_loose_files(root, args.quiet)
        result["loose_files"] = loose_result["loose_files"]
        result["loose_summary"] = loose_result["summary"]

        if getattr(args, "fix_orphans", False) and orphan_result["orphans"]:
            fix_result = fix_orphans(orphan_result["orphans"], root, args.quiet)
            result["orphan_fix"] = fix_result
            if fix_result["orphans_resolved"] > 0:
                updated = check_orphans(root, quiet=True)
                result["orphans"] = updated["orphans"]
                result["orphan_summary"] = updated["summary"]

    has_issues = (
        result["summary"]["broken"] > 0
        or result.get("orphan_summary", {}).get("orphans_found", 0) > 0
        or result.get("stub_summary", {}).get("stubs_found", 0) > 0
        or result.get("legacy_summary", {}).get("converted_dirs_found", 0) > 0
        or result.get("loose_summary", {}).get("loose_found", 0) > 0
    )

    if not args.batch_mode:
        broken_for_review = result["broken_links"]
        if auto_fix_applied:
            broken_for_review = [b for b in broken_for_review if not b.get("fixed") and not b.get("fm_deleted")]
        run_interactive(broken_for_review, result.get("orphans", []), result.get("stubs", []), root)
    elif args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(format_text(result))

    if args.batch_mode and has_issues:
        print("\nTip: run without --batch-mode to review and fix issues interactively.", file=sys.stderr)

    # Exit code: 0 = clean, 1 = issues found, 2 = errors
    if result.get("errors"):
        sys.exit(2)
    if has_issues:
        sys.exit(1)
    sys.exit(0)
