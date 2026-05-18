"""Top-level scan: walks the vault, resolves links, optionally applies fixes."""

import sys
from pathlib import Path

from ..fixers import fix_curly_quotes, fix_raw_references
from ..links import extract_links, is_external, strip_frontmatter
from ..paths import VaultIndex
from ..resolve import (
    check_external,
    find_normalized_match,
    find_whitespace_before_ext_match,
    resolve_mdlink,
    resolve_wikilink,
)
from ..rewrite import (
    delete_wikilink_in_file,
    fix_wikilinks_in_file,
    mark_broken_wikilinks_in_file,
)


def check_vault(root: Path, args) -> dict:
    errors = []
    broken = []
    total_files = 0
    total_links = 0
    skipped_external = 0

    if not root.is_dir():
        return {
            "broken_links": [],
            "summary": {"files_checked": 0, "links_checked": 0, "broken": 0, "skipped_external": 0},
            "errors": [f"Root directory not found: {root}"]
        }

    if not args.quiet:
        print(f"Scanning {root} ...", file=sys.stderr)

    vault = VaultIndex(root)
    stem_index = vault.stem_index
    norm_index = vault.norm_index
    path_suffix_set = vault.path_suffix_set
    md_files = vault.md_files

    for md_file in md_files:
        total_files += 1
        rel = md_file.relative_to(root)

        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            errors.append(f"Cannot read {rel}: {e}")
            continue

        _, fm_end_line = strip_frontmatter(content)

        for lineno, link_type, raw, target in extract_links(content, args.include_images, args.skip_frontmatter):
            total_links += 1

            # External links
            if is_external(target):
                if args.external:
                    ok, reason = check_external(target, args.timeout)
                    if not ok:
                        broken.append({
                            "file": str(rel),
                            "line": lineno,
                            "type": link_type,
                            "raw": raw,
                            "target": target,
                            "reason": reason,
                        })
                else:
                    skipped_external += 1
                continue

            # Skip empty or anchor-only targets
            if not target or target.startswith("#"):
                total_links -= 1
                continue

            # Resolve
            if link_type == "wikilink" or (link_type == "image" and "[[" in raw):
                ok = resolve_wikilink(target, root, stem_index, path_suffix_set)
            else:
                ok = resolve_mdlink(target, md_file, root, stem_index)

            if not ok:
                entry = {
                    "file": str(rel),
                    "line": lineno,
                    "type": link_type,
                    "raw": raw,
                    "target": target,
                    "reason": "file not found",
                }
                if fm_end_line and lineno <= fm_end_line:
                    entry["in_frontmatter"] = True
                if link_type == "wikilink" or (link_type == "image" and "[[" in raw):
                    fix = find_normalized_match(target, root, norm_index)
                    if not fix:
                        fix = find_whitespace_before_ext_match(target, root, path_suffix_set)
                    if fix:
                        entry["suggested_fix"] = fix
                broken.append(entry)

        if not args.quiet and total_files % 50 == 0:
            print(f"\r  {total_files} files scanned ...", end="", flush=True, file=sys.stderr)

    if not args.quiet:
        print(f"\r  {total_files} files scanned — done.        ", file=sys.stderr)

    raw_refs_pending = 0
    raw_refs_pending_files = 0
    if not getattr(args, "fix_simple_errors", False):
        raw_refs_pending_files, raw_refs_pending = fix_raw_references(
            root, quiet=True, dry_run=True
        )

    fixed_links = 0
    fixed_files = 0
    fm_deleted_links = 0
    fm_deleted_files = 0
    q_renamed = q_link_files = q_links = 0
    raw_files_changed = raw_changes = 0
    if getattr(args, "fix_simple_errors", False):
        fixes_by_file: dict = {}
        for entry in broken:
            if "suggested_fix" in entry:
                fp = root / entry["file"]
                fixes_by_file.setdefault(fp, []).append(
                    (entry["target"], entry["suggested_fix"])
                )
        for fp, fixes in fixes_by_file.items():
            seen: set = set()
            deduped = [f for f in fixes if not (f in seen or seen.add(f))]  # type: ignore[func-returns-value]
            n = fix_wikilinks_in_file(fp, deduped)
            if n:
                fixed_files += 1
                fixed_links += n
                if not args.quiet:
                    rel = fp.relative_to(root)
                    for old_t, new_t in deduped:
                        print(f"  fix: {rel}: [[{old_t}]] → [[{new_t}]]", file=sys.stderr)
        for entry in broken:
            if "suggested_fix" in entry:
                entry["fixed"] = True

        # Delete bullet lines in YAML frontmatter that contain unfixable broken wikilinks
        fm_targets_by_file: dict = {}
        for entry in broken:
            if entry.get("fixed") or not entry.get("in_frontmatter"):
                continue
            if entry["raw"].startswith("[["):
                fp = root / entry["file"]
                fm_targets_by_file.setdefault(fp, []).append(entry["target"])
        for fp, targets in fm_targets_by_file.items():
            seen: set = set()
            deduped = [t for t in targets if not (t in seen or seen.add(t))]  # type: ignore[func-returns-value]
            file_changed = False
            for target in deduped:
                changed, _ = delete_wikilink_in_file(fp, target)
                if changed:
                    fm_deleted_links += 1
                    file_changed = True
                    if not args.quiet:
                        rel = fp.relative_to(root)
                        print(f"  fix (fm delete): {rel}: [[{target}]]", file=sys.stderr)
            if file_changed:
                fm_deleted_files += 1
        for entry in broken:
            if not entry.get("fixed") and entry.get("in_frontmatter"):
                if entry["raw"].startswith("[["):
                    entry["fm_deleted"] = True

        q_renamed, q_link_files, q_links = fix_curly_quotes(root, args.quiet)
        if not args.quiet and (q_renamed or q_links):
            print(f"  Curly quotes: {q_renamed} file(s) renamed, "
                  f"{q_links} link(s) updated in {q_link_files} file(s).", file=sys.stderr)

        raw_files_changed, raw_changes = fix_raw_references(root, args.quiet)
        if not args.quiet and raw_changes:
            print(f"  Raw references: {raw_changes} reference(s) wikilinked in "
                  f"{raw_files_changed} file(s).", file=sys.stderr)

    removed_links = 0
    removed_files = 0
    if getattr(args, "remove_broken_links", False):
        targets_by_file: dict = {}
        for entry in broken:
            if entry.get("fixed"):
                continue
            if entry["raw"].startswith("[["):
                fp = root / entry["file"]
                targets_by_file.setdefault(fp, []).append(entry["target"])
        for fp, targets in targets_by_file.items():
            seen: set = set()
            deduped = [t for t in targets if not (t in seen or seen.add(t))]  # type: ignore[func-returns-value]
            n = mark_broken_wikilinks_in_file(fp, deduped)
            if n:
                removed_files += 1
                removed_links += n
        for entry in broken:
            if not entry.get("fixed") and entry["raw"].startswith("[["):
                entry["removed"] = True
        if not args.quiet and removed_links:
            print(f"  Marked {removed_links} broken link(s) in {removed_files} file(s).", file=sys.stderr)

    summary: dict = {
        "files_checked": total_files,
        "links_checked": total_links,
        "broken": len(broken),
        "skipped_external": skipped_external,
    }
    if getattr(args, "fix_simple_errors", False):
        summary["fixed_links"] = fixed_links
        summary["fixed_files"] = fixed_files
        if fm_deleted_links:
            summary["fm_deleted_links"] = fm_deleted_links
            summary["fm_deleted_files"] = fm_deleted_files
        if q_renamed or q_links:
            summary["quote_renamed_files"] = q_renamed
            summary["quote_updated_links"] = q_links
            summary["quote_updated_link_files"] = q_link_files
        if raw_changes:
            summary["raw_refs_wikilinked"] = raw_changes
            summary["raw_refs_files_changed"] = raw_files_changed
    if getattr(args, "remove_broken_links", False):
        summary["removed_links"] = removed_links
        summary["removed_files"] = removed_files
    if raw_refs_pending:
        summary["raw_refs_pending"] = raw_refs_pending
        summary["raw_refs_pending_files"] = raw_refs_pending_files

    return {
        "broken_links": broken,
        "summary": summary,
        "errors": errors,
        "raw_refs_pending": raw_refs_pending,
    }
