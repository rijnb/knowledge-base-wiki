"""Human-readable formatting for scan results."""


def format_text(result: dict) -> str:
    lines = []
    s = result["summary"]
    lines.append(f"Checked {s['files_checked']} files, {s['links_checked']} links — "
                 f"{s['broken']} broken, {s['skipped_external']} external skipped.")
    if s.get("fixed_links"):
        lines.append(f"Fixed {s['fixed_links']} link(s) in {s['fixed_files']} file(s).")
    if s.get("fm_deleted_links"):
        lines.append(f"Removed {s['fm_deleted_links']} frontmatter broken link(s) in {s['fm_deleted_files']} file(s).")
    if s.get("removed_links"):
        lines.append(f"Marked {s['removed_links']} broken link(s) in {s['removed_files']} file(s).")
    if s.get("raw_refs_wikilinked"):
        lines.append(f"Wikilinked {s['raw_refs_wikilinked']} raw/ reference(s) in {s['raw_refs_files_changed']} file(s).")
    elif s.get("raw_refs_pending"):
        lines.append(f"Raw/ references to wikilink: {s['raw_refs_pending']} in {s['raw_refs_pending_files']} file(s) (use --fix-simple-errors to apply).")
    if s.get("log_pruned_dropped") or s.get("log_pruned_malformed") or s.get("log_pruned_duplicates"):
        parts = [f"kept {s.get('log_pruned_kept', 0)}", f"dropped {s.get('log_pruned_dropped', 0)}"]
        if s.get("log_pruned_duplicates"):
            parts.append(f"{s['log_pruned_duplicates']} duplicate(s)")
        if s.get("log_pruned_malformed"):
            parts.append(f"{s['log_pruned_malformed']} malformed")
        lines.append(f"Pruned wiki/log.jsonl: {', '.join(parts)}. Backup at wiki/log.jsonl.bak.")
    elif s.get("log_pruned_pending"):
        lines.append(f"wiki/log.jsonl has {s['log_pruned_pending']} stale/duplicate entry/entries (use --fix-simple-errors to prune).")
    if s.get("loose_moved") or s.get("loose_converted") or s.get("loose_skipped"):
        lines.append(f"Loose files: {s.get('loose_moved', 0)} moved to _resources, "
                     f"{s.get('loose_converted', 0)} converted, {s.get('loose_skipped', 0)} skipped.")
    elif s.get("loose_pending"):
        lines.append(f"Loose non-markdown files: {s['loose_pending']} "
                     f"(use --fix-simple-errors to relocate into _resources/ and convert).")
    if s.get("loose_warning"):
        lines.append(f"WARNING: {s['loose_warning']}")
    if s.get("attachments_moved") or s.get("attachments_skipped"):
        lines.append(f"Misplaced attachments: {s.get('attachments_moved', 0)} moved to "
                     f"the note's _resources, {s.get('attachments_skipped', 0)} skipped.")
    elif s.get("attachments_pending"):
        lines.append(f"Misplaced attachments: {s['attachments_pending']} "
                     f"(use --fix-simple-errors to relocate into the note's own _resources/).")
    if s.get("attachment_warning"):
        lines.append(f"WARNING: {s['attachment_warning']}")
    lines.append("")

    if result["errors"]:
        lines.append("ERRORS:")
        for e in result["errors"]:
            lines.append(f"  ! {e}")
        lines.append("")

    if not result["broken_links"]:
        lines.append("No broken links found.")
    else:
        lines.append("BROKEN LINKS:")
        for b in result["broken_links"]:
            lines.append(f"{b['line']}: {b['file']}")
            lines.append(f"    type  : {b['type']}")
            lines.append(f"    reason: {b['reason']}")
            raw_display = b['raw'][2:] if b['raw'].startswith('[[') else b['raw']
            lines.append(f"    raw   : {raw_display}")
            lines.append(f"    target: {b['target']}")
            if "suggested_fix" in b:
                suffix = " (fixed)" if b.get("fixed") else " (use --fix-simple-errors to apply)"
                lines.append(f"    suggested_fix: {b['suggested_fix']}{suffix}")
            if b.get("removed"):
                lines.append("    action: marked as broken in file")
        lines.append("")

    if "orphans" in result:
        lines.append("")
        os_ = result["orphans"]
        os_s = result.get("orphan_summary", {})
        fix = result.get("orphan_fix")
        if fix:
            parts = [f"{fix['orphans_resolved']} orphan(s) resolved via wiki links"]
            if fix.get("orphans_acknowledged"):
                parts.append(f"{fix['orphans_acknowledged']} acknowledged via raw reference (orphan: false added)")
            lines.append(f"ORPHAN FIX: {', '.join(parts)}; "
                         f"{fix['fixed_references']} reference(s) linked in {fix['files_changed']} file(s).")
        lines.append(f"ORPHAN CHECK: {os_s.get('wiki_pages_checked', '?')} pages checked, "
                     f"{os_s.get('orphans_found', len(os_))} orphan(s) remaining.")
        if os_:
            lines.append("ORPHANS (no incoming links except from index pages):")
            for o in os_:
                lines.append(f"  {o}")
        else:
            lines.append("No orphan pages found.")

    if "stubs" in result:
        lines.append("")
        st_ = result["stubs"]
        st_s = result.get("stub_summary", {})
        lines.append(f"STUB CHECK: {st_s.get('wiki_pages_checked', '?')} pages checked, "
                     f"{st_s.get('stubs_found', len(st_))} stub(s) found.")
        if st_:
            lines.append("STUBS (thin pages not yet acknowledged with stub: true):")
            for s in st_:
                lines.append(f"  {s}")
        else:
            lines.append("No stub pages found.")

    if "frontmatter_issues" in result:
        lines.append("")
        fm = result["frontmatter_issues"]
        fm_s = result.get("frontmatter_summary", {})
        lines.append(f"FRONTMATTER CHECK: {fm_s.get('wiki_pages_checked', '?')} pages checked, "
                     f"{fm_s.get('frontmatter_errors', 0)} error(s), "
                     f"{fm_s.get('frontmatter_warnings', 0)} warning(s).")
        if fm:
            lines.append("FRONTMATTER ISSUES:")
            for i in fm:
                lines.append(f"  {i['file']}: [{i['severity']}] {i['reason']}")
        else:
            lines.append("No frontmatter issues found.")

    if "footnote_issues" in result:
        lines.append("")
        fn = result["footnote_issues"]
        fn_s = result.get("footnote_summary", {})
        lines.append(f"FOOTNOTE CHECK: {fn_s.get('wiki_pages_checked', '?')} pages checked, "
                     f"{fn_s.get('footnote_errors', 0)} error(s), "
                     f"{fn_s.get('footnote_warnings', 0)} warning(s).")
        if fn:
            lines.append("FOOTNOTE ISSUES (refs and definitions must match within a page):")
            for i in fn:
                lines.append(f"  {i['file']}:{i['line']}: [{i['severity']}] {i['reason']}")
        else:
            lines.append("No footnote issues found.")

    if "loose_files" in result:
        lines.append("")
        lf = result["loose_files"]
        lf_s = result.get("loose_summary", {})
        lines.append(f"LOOSE FILE CHECK: {lf_s.get('loose_found', len(lf))} "
                     f"loose non-markdown file(s) found.")
        if lf:
            lines.append("LOOSE FILES (non-markdown outside _resources/; "
                         "--fix-simple-errors relocates via Obsidian CLI and converts):")
            for f in lf:
                lines.append(f"  {f}")
        else:
            lines.append("No loose files found.")

    if "misplaced_attachments" in result:
        lines.append("")
        ma = result["misplaced_attachments"]
        ma_s = result.get("attachment_summary", {})
        lines.append(f"ATTACHMENT PLACEMENT CHECK: {ma_s.get('notes_scanned', '?')} "
                     f"raw/INBOX note(s) scanned, "
                     f"{ma_s.get('misplaced_found', len(ma))} misplaced attachment(s) found.")
        if ma:
            lines.append("MISPLACED ATTACHMENTS (linked from raw/ or INBOX/ notes but "
                         "stored outside the note's own _resources/; "
                         "--fix-simple-errors relocates via Obsidian CLI):")
            for m in ma:
                lines.append(f"  {m['file']}:{m['line']}")
                lines.append(f"    target  : {m['target']}")
                lines.append(f"    found at: {m['resolved']}")
                lines.append(f"    expected: {m['expected_dir']}/")
        else:
            lines.append("No misplaced attachments found.")

    if "legacy_converted" in result:
        lines.append("")
        lc = result["legacy_converted"]
        lc_s = result.get("legacy_summary", {})
        mig = result.get("legacy_migration")
        if mig and mig.get("ran"):
            status = "succeeded" if mig.get("returncode") == 0 else f"exited with status {mig.get('returncode')}"
            lines.append(f"LEGACY MIGRATION: migrate-converted-to-resources.py --apply {status}.")
        lines.append(f"LEGACY LAYOUT CHECK: {lc_s.get('converted_dirs_found', len(lc))} "
                     f"legacy converted/ directory(ies) remaining.")
        if lc:
            lines.append("LEGACY converted/ DIRECTORIES (superseded by the _resources layout):")
            for d in lc:
                lines.append(f"  {d}")
            lines.append("  Migrate with: python3 scripts/system/migrate-converted-to-resources.py --apply")
        else:
            lines.append("No legacy converted/ directories found.")

    if "orphan_attachments" in result:
        lines.append("")
        oa = result["orphan_attachments"]
        oa_s = result.get("orphan_attachment_summary", {})
        lines.append(f"ORPHAN ATTACHMENT CHECK: {oa_s.get('attachments_scanned', '?')} "
                     f"file(s) in vault-root _resources/ scanned, "
                     f"{oa_s.get('orphan_attachments_found', len(oa))} orphan(s) found.")
        if oa:
            lines.append("ORPHAN ATTACHMENTS (in vault-root _resources/, referenced by no note; "
                         "review and delete or relocate manually):")
            for f in oa:
                lines.append(f"  {f}")
        else:
            lines.append("No orphan attachments found.")

    if "accent_duplicates" in result:
        lines.append("")
        ad = result["accent_duplicates"]
        ad_s = result.get("accent_duplicate_summary", {})
        lines.append(f"ACCENT DUPLICATE CHECK: {ad_s.get('accent_duplicates_found', len(ad))} "
                     f"filename group(s) differing only by accents/diacritics.")
        if ad:
            lines.append("ACCENT DUPLICATES (same page under accented and plain names; "
                         "merge into the ASCII-named file):")
            for g in ad:
                keep = g.get("keep")
                lines.append(f"  keep    : {keep if keep else '(no ASCII-named file — rename needed)'}")
                for d in g["duplicates"]:
                    lines.append(f"  merge in: {d}")
        else:
            lines.append("No accent-duplicate filenames found.")

    # Issues summary — shown at the end
    has_issues = (result["broken_links"] or result.get("orphans") or result.get("stubs")
                  or result.get("frontmatter_issues") or result.get("footnote_issues")
                  or result.get("legacy_converted") or result.get("loose_files")
                  or result.get("accent_duplicates")
                  or result.get("orphan_attachments")
                  or result.get("misplaced_attachments"))
    if has_issues:
        lines.append("")
        lines.append("ISSUES SUMMARY:")
        if result["broken_links"]:
            by_type: dict = {}
            for b in result["broken_links"]:
                t = b["type"]
                if t not in by_type:
                    by_type[t] = {"found": 0, "fixed": 0, "remaining": 0}
                by_type[t]["found"] += 1
                if b.get("fixed") or b.get("fm_deleted"):
                    by_type[t]["fixed"] += 1
                else:
                    by_type[t]["remaining"] += 1
            total_fixed = sum(v["fixed"] for v in by_type.values())
            total_remaining = sum(v["remaining"] for v in by_type.values())
            lines.append(f"  broken links : {len(result['broken_links'])} found, {total_fixed} fixed, {total_remaining} remaining")
            for t in sorted(by_type):
                v = by_type[t]
                lines.append(f"     {t:<10}: {v['found']} found, {v['fixed']} fixed, {v['remaining']} remaining")
        if "orphans" in result:
            os_s = result.get("orphan_summary", {})
            fix = result.get("orphan_fix")
            n_found = os_s.get("orphans_found", len(result["orphans"]))
            if fix:
                resolved = fix.get("orphans_resolved", 0)
                ack = fix.get("orphans_acknowledged", 0)
                remaining = n_found - resolved
                detail = f"{resolved} resolved"
                if ack:
                    detail += f", {ack} acknowledged"
                detail += f", {remaining} remaining"
                lines.append(f"  orphans      : {n_found} found, {detail}")
            else:
                lines.append(f"  orphans      : {n_found} found")
        if "stubs" in result:
            st_s = result.get("stub_summary", {})
            n_found = st_s.get("stubs_found", len(result["stubs"]))
            lines.append(f"  stubs        : {n_found} found")
        if "frontmatter_issues" in result:
            fm_s = result.get("frontmatter_summary", {})
            n_err = fm_s.get("frontmatter_errors", 0)
            n_warn = fm_s.get("frontmatter_warnings", 0)
            lines.append(f"  frontmatter  : {n_err} error(s), {n_warn} warning(s)")
        if "footnote_issues" in result:
            fn_s = result.get("footnote_summary", {})
            n_err = fn_s.get("footnote_errors", 0)
            n_warn = fn_s.get("footnote_warnings", 0)
            lines.append(f"  footnotes    : {n_err} error(s), {n_warn} warning(s)")
        if result.get("loose_files"):
            lf_s = result.get("loose_summary", {})
            n_loose = lf_s.get("loose_found", len(result["loose_files"]))
            lines.append(f"  loose files  : {n_loose} found "
                         f"(use --fix-simple-errors to relocate and convert)")
        if result.get("misplaced_attachments"):
            ma_s = result.get("attachment_summary", {})
            n_ma = ma_s.get("misplaced_found", len(result["misplaced_attachments"]))
            lines.append(f"  misplaced attachments: {n_ma} found "
                         f"(use --fix-simple-errors to relocate)")
        if result.get("legacy_converted"):
            lc_s = result.get("legacy_summary", {})
            n_dirs = lc_s.get("converted_dirs_found", len(result["legacy_converted"]))
            lines.append(f"  legacy layout: {n_dirs} converted/ dir(s) to migrate "
                         f"(run scripts/system/migrate-converted-to-resources.py --apply)")
        if result.get("accent_duplicates"):
            ad_s = result.get("accent_duplicate_summary", {})
            n_ad = ad_s.get("accent_duplicates_found", len(result["accent_duplicates"]))
            lines.append(f"  accent duplicates: {n_ad} filename group(s) to merge "
                         f"into their ASCII-named files")
        if result.get("orphan_attachments"):
            oa_s = result.get("orphan_attachment_summary", {})
            n_oa = oa_s.get("orphan_attachments_found", len(result["orphan_attachments"]))
            lines.append(f"  orphan attachments: {n_oa} unreferenced file(s) in "
                         f"vault-root _resources/ (review manually)")

    if result.get("recommendations"):
        lines.append("")
        lines.append("RECOMMENDATIONS:")
        for rec in result["recommendations"]:
            skill = rec.get("skill")
            suffix = f" or ask for `{skill}`" if skill else ""
            lines.append(f"  - {rec['message']} Run: {rec['command']}{suffix}.")

    return "\n".join(lines)
