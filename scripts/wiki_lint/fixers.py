"""Whole-vault sweeps: curly-quote normalization, raw/ reference wikilinking, and log pruning."""

import json
import re
import shutil
import sys
from pathlib import Path

from .links import (
    CURLY_TO_STRAIGHT,
    RE_IMAGE_EMBED,
    RE_MDIMAGE,
    RE_MDLINK,
    RE_WIKILINK,
    _CURLY_RE,
    is_external,
)
from .paths import should_skip_md


# Wrap bare/backticked raw/ paths in wiki/ files with [[...]] wikilinks.
_RAW_PATH = r'raw/[^\n`\[\]]+?\.md'
RE_BACKTICKED_RAW = re.compile(rf'`({_RAW_PATH})`')
RE_BULLET_LINE = re.compile(r'^(\s*[-*+]\s+)(.*)$')
RE_RAW_AT_START = re.compile(rf'^({_RAW_PATH})(?=\s|$)')
RE_SOURCE_LEAD_BARE = re.compile(rf'^(\s*\*?Source:\*?\s+)({_RAW_PATH})(?=\s|$|\*)')


def fix_curly_quotes(root: Path, quiet: bool) -> tuple[int, int, int]:
    """Rename .md files whose stems contain curly quotes and fix curly quotes in all link targets.
    Returns (renamed_files, link_files_changed, links_changed)."""
    # Pass 1: rename files whose stems contain curly quotes
    renamed = 0
    for p in sorted(root.rglob("*.md")):
        if should_skip_md(p, root):
            continue
        if not _CURLY_RE.search(p.stem):
            continue
        new_stem = p.stem.translate(CURLY_TO_STRAIGHT)
        new_path = p.parent / (new_stem + ".md")
        if new_path.exists():
            if not quiet:
                print(f"  Cannot rename {p.name}: {new_path.name} already exists", file=sys.stderr)
            continue
        p.rename(new_path)
        renamed += 1
        if not quiet:
            print(f"  Renamed: {p.name} → {new_path.name}", file=sys.stderr)

    # Pass 2: fix curly quotes inside link targets across all .md files
    link_files = 0
    link_count = 0
    for md_file in sorted(root.rglob("*.md")):
        if should_skip_md(md_file, root):
            continue
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not _CURLY_RE.search(content):
            continue  # fast-path: no curly quotes anywhere in this file

        counter = [0]

        def _fix_wiki(m, _c=counter):
            inner = m.group(1)
            fixed = inner.translate(CURLY_TO_STRAIGHT)
            if fixed != inner:
                _c[0] += 1
                return f'[[{fixed}'
            return m.group(0)

        def _fix_img(m, _c=counter):
            inner = m.group(1)
            fixed = inner.translate(CURLY_TO_STRAIGHT)
            if fixed != inner:
                _c[0] += 1
                return f'![[{fixed}'
            return m.group(0)

        def _fix_md(m, _c=counter):
            target = m.group(1)
            if is_external(target) or not _CURLY_RE.search(target):
                return m.group(0)
            fixed = target.translate(CURLY_TO_STRAIGHT)
            _c[0] += 1
            offset = m.start(1) - m.start(0)
            full = m.group(0)
            return full[:offset] + fixed + full[offset + len(target):]

        new_content = RE_WIKILINK.sub(_fix_wiki, content)
        new_content = RE_IMAGE_EMBED.sub(_fix_img, new_content)
        new_content = RE_MDLINK.sub(_fix_md, new_content)
        new_content = RE_MDIMAGE.sub(_fix_md, new_content)

        if counter[0]:
            md_file.write_text(new_content, encoding="utf-8")
            link_files += 1
            link_count += counter[0]

    return renamed, link_files, link_count


def fix_raw_references(root: Path, quiet: bool, dry_run: bool = False) -> tuple[int, int]:
    """Wrap backticked or bare raw/ paths in wiki/ files with [[...]] wikilinks.

    Three passes per line (outside YAML frontmatter and fenced code blocks):
      1. Universal: any `` `raw/x.md` `` (backticked) → `[[raw/x.md]]`, anywhere.
      2. Bullet bare: at the start of a bullet item's content, a bare `raw/x.md`
         (followed by whitespace/end) is wrapped — trailing annotation preserved.
      3. Source bare: on a `Source:` line (with optional `*` italics around
         `Source:`), a bare `raw/x.md` is wrapped — trailing content preserved.

    Only modifies files inside wiki/. When dry_run=True, scans without writing —
    useful for detection-only passes. Returns
    (files_changed_or_pending, total_replacements_or_pending).
    """
    files_changed = 0
    total_changes = 0
    for md_file in sorted(root.rglob("*.md")):
        if should_skip_md(md_file, root):
            continue
        rel = md_file.relative_to(root)
        if not rel.parts or rel.parts[0] != "wiki":
            continue
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "raw/" not in content:
            continue

        lines = content.splitlines(keepends=True)

        fm_end = 0
        if lines and lines[0].strip() == "---":
            for i, line in enumerate(lines[1:], 1):
                if line.strip() in ("---", "..."):
                    fm_end = i + 1
                    break

        in_code_block = False
        changes = 0
        new_lines = []
        for i, line in enumerate(lines):
            if i < fm_end:
                new_lines.append(line)
                continue

            if line.endswith("\r\n"):
                newline = "\r\n"
                body = line[:-2]
            elif line.endswith("\n"):
                newline = "\n"
                body = line[:-1]
            else:
                newline = ""
                body = line

            stripped = body.lstrip()
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_code_block = not in_code_block
                new_lines.append(line)
                continue
            if in_code_block:
                new_lines.append(line)
                continue

            # Pass 1: universal — wrap any `raw/x.md` (backticked) with [[...]].
            new_body, n_bt = RE_BACKTICKED_RAW.subn(r'[[\1]]', body)
            line_changes = n_bt

            # Pass 2: bullet line with bare raw/x.md at start of content.
            bullet_m = RE_BULLET_LINE.match(new_body)
            if bullet_m:
                prefix, rest = bullet_m.group(1), bullet_m.group(2)
                pm = RE_RAW_AT_START.match(rest)
                if pm:
                    new_body = prefix + f"[[{pm.group(1)}]]" + rest[pm.end():]
                    line_changes += 1
            else:
                # Pass 3: Source: line with a bare raw/x.md (path may have trailing content).
                sm = RE_SOURCE_LEAD_BARE.match(new_body)
                if sm:
                    lead, path = sm.group(1), sm.group(2)
                    new_body = lead + f"[[{path}]]" + new_body[sm.end():]
                    line_changes += 1

            if line_changes:
                new_lines.append(new_body + newline)
                changes += line_changes
            else:
                new_lines.append(line)

        if changes:
            if not dry_run:
                md_file.write_text("".join(new_lines), encoding="utf-8")
                if not quiet:
                    print(f"  Raw refs: {rel} ({changes} change(s))", file=sys.stderr)
            files_changed += 1
            total_changes += changes

    return files_changed, total_changes


def prune_log(root: Path, quiet: bool, dry_run: bool = False) -> tuple[int, int, int]:
    """Drop entries from wiki/log.jsonl whose 'file' field no longer exists.

    Paths are resolved relative to `root` (the vault root, parent of wiki/).
    When dry_run is False, the original log is backed up to wiki/log.jsonl.bak
    (overwritten on each run) and log.jsonl is rewritten in place. When
    dry_run is True, the file is only scanned and no backup or rewrite happens.

    Returns (kept, dropped, malformed). If the log file does not exist, returns
    (0, 0, 0) without raising.
    """
    log_path = root / "wiki" / "log.jsonl"
    if not log_path.exists():
        return 0, 0, 0

    kept_lines: list[str] = []
    kept = dropped = malformed = 0
    with log_path.open("r", encoding="utf-8") as src:
        for lineno, raw in enumerate(src, start=1):
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                malformed += 1
                if not quiet and not dry_run:
                    print(f"  log.jsonl line {lineno}: malformed JSON ({e}); skipping",
                          file=sys.stderr)
                continue
            file_field = entry.get("file")
            if not file_field:
                dropped += 1
                continue
            if (root / file_field).exists():
                kept_lines.append(line)
                kept += 1
            else:
                dropped += 1

    if dry_run:
        return kept, dropped, malformed

    backup_path = log_path.with_suffix(log_path.suffix + ".bak")
    shutil.copy2(log_path, backup_path)

    with log_path.open("w", encoding="utf-8") as dst:
        for line in kept_lines:
            dst.write(line + "\n")

    return kept, dropped, malformed
