"""Whole-vault sweeps: curly-quote normalization, raw/ reference wikilinking, log pruning, and loose-file relocation."""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
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


# Source extensions the ingester scans (mirrors wiki-create-import-batches.sh).
_INGEST_EXTS = {".md", ".pdf", ".doc", ".docx", ".txt", ".vtt", ".eml", ".html"}


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
        try:
            p.rename(new_path)
        except OSError as e:
            # A locked file (e.g. mid-OneDrive-sync) must not abort the whole
            # fix pass — warn and skip just this one.
            print(f"  WARNING: cannot rename {p.name}: {e}", file=sys.stderr)
            continue
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
            content = md_file.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError:
            print(f"  WARNING: skipping {md_file}: not valid UTF-8", file=sys.stderr)
            continue
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
            content = md_file.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError:
            print(f"  WARNING: skipping {md_file}: not valid UTF-8", file=sys.stderr)
            continue
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

        fence_char = None  # '`' or '~' of the fence that opened the current block
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
                this_char = stripped[0]
                if fence_char is None:
                    # Opening a fenced block — remember which char opened it.
                    fence_char = this_char
                elif this_char == fence_char:
                    # Only a matching fence closes the block; a ~~~ inside a ```
                    # block (or vice versa) is just content and must not toggle.
                    fence_char = None
                new_lines.append(line)
                continue
            if fence_char is not None:
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


def _union_preserve_order(*lists: list) -> list:
    seen: set = set()
    out: list = []
    for lst in lists:
        if not isinstance(lst, list):
            continue
        for item in lst:
            key = item if isinstance(item, (str, int, float, bool, type(None))) else repr(item)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    return out


def prune_log(root: Path, quiet: bool, dry_run: bool = False) -> tuple[int, int, int, int]:
    """Drop entries from wiki/log.jsonl whose 'file' field no longer exists,
    and collapse duplicate entries that share the same 'file' value.

    For duplicates, the entry with the latest 'date' (lexicographic on the
    ISO-style timestamp, falling back to last-seen position) is kept; its
    'pages_created' and 'pages_updated' lists are merged with those from every
    other duplicate (order-preserving union) so no page references are lost.
    The merged-away entries are counted as duplicates_dropped.

    Paths are resolved relative to `root` (the vault root, parent of wiki/).
    When dry_run is False, the original log is backed up to wiki/log.jsonl.bak
    (overwritten on each run) and log.jsonl is rewritten in place. When
    dry_run is True, the file is only scanned and no backup or rewrite happens.

    Returns (kept, dropped, malformed, duplicates_dropped). If the log file
    does not exist, returns (0, 0, 0, 0) without raising.
    """
    log_path = root / "wiki" / "log.jsonl"
    if not log_path.exists():
        return 0, 0, 0, 0

    best_by_file: dict[str, dict] = {}
    dropped = malformed = duplicates = 0
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
            if not (root / file_field).exists():
                dropped += 1
                continue
            date_field = entry.get("date", "")
            prev = best_by_file.get(file_field)
            if prev is None:
                best_by_file[file_field] = {
                    "date": date_field,
                    "lineno": lineno,
                    "entry": entry,
                    "pages_created": list(entry.get("pages_created") or []),
                    "pages_updated": list(entry.get("pages_updated") or []),
                }
            else:
                duplicates += 1
                if (date_field, lineno) > (prev["date"], prev["lineno"]):
                    merged_created = _union_preserve_order(
                        prev["pages_created"], entry.get("pages_created") or []
                    )
                    merged_updated = _union_preserve_order(
                        prev["pages_updated"], entry.get("pages_updated") or []
                    )
                    best_by_file[file_field] = {
                        "date": date_field,
                        "lineno": lineno,
                        "entry": entry,
                        "pages_created": merged_created,
                        "pages_updated": merged_updated,
                    }
                else:
                    prev["pages_created"] = _union_preserve_order(
                        prev["pages_created"], entry.get("pages_created") or []
                    )
                    prev["pages_updated"] = _union_preserve_order(
                        prev["pages_updated"], entry.get("pages_updated") or []
                    )

    kept_lines: list[str] = []
    for slot in sorted(best_by_file.values(), key=lambda v: v["lineno"]):
        entry = dict(slot["entry"])
        if "pages_created" in entry or slot["pages_created"]:
            entry["pages_created"] = slot["pages_created"]
        if "pages_updated" in entry or slot["pages_updated"]:
            entry["pages_updated"] = slot["pages_updated"]
        kept_lines.append(json.dumps(entry, ensure_ascii=False))
    kept = len(kept_lines)

    if dry_run:
        return kept, dropped, malformed, duplicates

    backup_path = log_path.with_suffix(log_path.suffix + ".bak")
    shutil.copy2(log_path, backup_path)

    # Write atomically: a full temp file in the same directory, then os.replace
    # onto log.jsonl. A crash mid-write can never leave a truncated log.
    tmp_path = log_path.with_name(log_path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as dst:
        for line in kept_lines:
            dst.write(line + "\n")
    os.replace(tmp_path, log_path)

    return kept, dropped, malformed, duplicates


def _sha256_file(path: Path) -> str:
    """Return 'sha256:<hexdigest>' over the file's exact bytes."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def stamp_log_hashes(root: Path, quiet: bool, dry_run: bool = False) -> tuple[int, int]:
    """Fill missing 'hash' and 'mtime' on wiki/log.jsonl entries.

    For every entry whose 'file' still exists at its logged path and that lacks
    a 'hash' (string) or an integer 'mtime', record:
      - hash:  'sha256:<hexdigest>' over the file's exact bytes (identity).
      - mtime: int(st_mtime), a fast-path cache key for the dedup reader.

    Existing hash/mtime values are never overwritten, so the pass is idempotent
    and safe to run on every finalize. Entries whose file no longer exists at
    its logged path are left untouched (they may legitimately have been renamed
    before this feature shipped). Malformed JSON lines are preserved verbatim.

    Paths are resolved relative to `root` (the vault root, parent of wiki/).
    When dry_run is False and at least one entry changed, the original log is
    backed up to wiki/log.jsonl.bak and rewritten atomically. When dry_run is
    True, or nothing changed, the file is left untouched.

    Returns (stamped, total): entries newly stamped, and entries scanned. If the
    log file does not exist, returns (0, 0) without raising.
    """
    log_path = root / "wiki" / "log.jsonl"
    if not log_path.exists():
        return 0, 0

    out_lines: list[str] = []
    stamped = total = 0
    changed = False
    with log_path.open("r", encoding="utf-8") as src:
        for raw in src:
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                out_lines.append(line)  # leave malformed lines for prune_log to handle
                continue
            total += 1
            file_field = entry.get("file")
            needs_hash = not isinstance(entry.get("hash"), str)
            needs_mtime = not isinstance(entry.get("mtime"), int)
            if file_field and (needs_hash or needs_mtime):
                target = root / file_field
                if target.is_file():
                    try:
                        if needs_hash:
                            entry["hash"] = _sha256_file(target)
                        if needs_mtime:
                            entry["mtime"] = int(target.stat().st_mtime)
                        stamped += 1
                        changed = True
                    except OSError:
                        pass  # file vanished or unreadable mid-sweep; leave entry unstamped
            out_lines.append(json.dumps(entry, ensure_ascii=False))

    if dry_run or not changed:
        return stamped, total

    backup_path = log_path.with_suffix(log_path.suffix + ".bak")
    shutil.copy2(log_path, backup_path)
    tmp_path = log_path.with_name(log_path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as dst:
        for line in out_lines:
            dst.write(line + "\n")
    os.replace(tmp_path, log_path)

    if not quiet:
        print(f"  Stamped log.jsonl: hash/mtime added to {stamped} "
              f"entr{'y' if stamped == 1 else 'ies'}.", file=sys.stderr)
    return stamped, total


def relink_renamed_log_entries(root: Path, quiet: bool, dry_run: bool = False) -> tuple[int, int]:
    """Repoint wiki/log.jsonl entries whose source note was renamed on disk.

    The dedup reader recognizes a renamed note by its content hash, but the log
    entry still names the old file. prune_log() drops entries whose 'file' is
    missing, which would later cause the renamed note to look new and re-ingest.
    This rewrites such entries to the new path BEFORE prune can drop them.

    An entry is an "orphan" if it has a string 'hash' and its 'file' no longer
    exists at its logged path. A raw file is "unreferenced" if its vault-relative
    path is not the 'file' of any entry. For each orphan, if exactly one
    unreferenced raw file (among _INGEST_EXTS) has the same content hash, the
    entry's 'file' is rewritten to that path and its 'mtime' refreshed; the file
    is then claimed so no other orphan reuses it. A copy (old path still present)
    is never relinked; 2+ candidates is ambiguous and skipped. Malformed JSON
    lines are preserved verbatim.

    Paths resolve relative to `root`. When dry_run is False and at least one
    entry was relinked, the log is backed up to wiki/log.jsonl.bak and rewritten
    atomically. Returns (relinked, ambiguous); (0, 0) if the log is absent or
    there is nothing to relink.
    """
    log_path = root / "wiki" / "log.jsonl"
    if not log_path.exists():
        return 0, 0

    items: list[tuple[str, object]] = []  # ('raw', str) | ('entry', dict)
    entries: list[dict] = []
    with log_path.open("r", encoding="utf-8") as src:
        for raw in src:
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                items.append(("raw", line))
                continue
            items.append(("entry", entry))
            entries.append(entry)

    referenced = {e.get("file") for e in entries if e.get("file")}
    orphans = [e for e in entries
               if isinstance(e.get("hash"), str)
               and e.get("file")
               and not (root / e["file"]).exists()]
    if not orphans:
        return 0, 0

    by_hash: dict[str, list[str]] = {}
    raw_root = root / "raw"
    if raw_root.is_dir():
        for path in raw_root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in _INGEST_EXTS:
                continue
            rel = path.relative_to(root).as_posix()
            if rel in referenced:
                continue
            try:
                by_hash.setdefault(_sha256_file(path), []).append(rel)
            except OSError:
                continue

    relinked = ambiguous = 0
    used: set[str] = set()
    for entry in orphans:
        cands = [c for c in by_hash.get(entry["hash"], []) if c not in used]
        if len(cands) == 1:
            new_path = cands[0]
            entry["file"] = new_path
            try:
                entry["mtime"] = int((root / new_path).stat().st_mtime)
            except OSError:
                entry.pop("mtime", None)  # stale; stamp_log_hashes will refill it
            used.add(new_path)
            relinked += 1
        elif len(cands) > 1:
            ambiguous += 1

    if dry_run or relinked == 0:
        if not quiet and ambiguous:
            print(f"  Relink: {ambiguous} ambiguous rename(s) skipped.", file=sys.stderr)
        return relinked, ambiguous

    out_lines = [payload if kind == "raw" else json.dumps(payload, ensure_ascii=False)
                 for kind, payload in items]
    backup_path = log_path.with_suffix(log_path.suffix + ".bak")
    shutil.copy2(log_path, backup_path)
    tmp_path = log_path.with_name(log_path.name + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as dst:
        for line in out_lines:
            dst.write(line + "\n")
    os.replace(tmp_path, log_path)

    if not quiet:
        print(f"  Relinked {relinked} renamed log "
              f"entr{'y' if relinked == 1 else 'ies'}; {ambiguous} ambiguous skipped.",
              file=sys.stderr)
    return relinked, ambiguous


# ---------------------------------------------------------------------------
# Loose non-markdown files: relocate into _resources/ and convert
# ---------------------------------------------------------------------------

# Loose files with these extensions are converted by the existing pipeline
# scripts (which write their own richer companions); everything else gets the
# generic per-note companion from _write_companion(). --no-rename keeps the
# converters from raw-renaming a file Obsidian just moved (which would break
# the links Obsidian rewrote); convert-html-to-md.py never renames.
CONVERTER_BY_EXT = {
    ".eml": ["convert-eml-to-md.py", "--no-rename"],
    ".vtt": ["convert-vtt-to-md.py", "--no-rename"],
    ".html": ["convert-html-to-md.py"],
}


def _numbered_fallback(target: Path) -> Path:
    """First free 'name N.ext' near target — same convention as migrate-converted-to-resources.py."""
    for n in range(2, 100):
        cand = target.with_name(f"{target.stem} {n}{target.suffix}")
        if not cand.exists():
            return cand
    raise RuntimeError(f"no free name near {target}")


def _extract_text(path: Path) -> str:
    """Best-effort plain-text extraction for the companion callout."""
    ext = path.suffix.lower()
    if ext == ".txt":
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
    if ext == ".pdf" and shutil.which("pdftotext"):
        try:
            proc = subprocess.run(
                ["pdftotext", str(path), "-"],
                capture_output=True, text=True, timeout=120,
            )
            if proc.returncode == 0:
                return proc.stdout
        except (OSError, subprocess.TimeoutExpired):
            pass
    return ""


def _write_companion(moved: Path) -> Path:
    """Write the per-note-format companion .md one level above _resources/.

    `moved` must already live inside a _resources/ (or legacy *.resources)
    directory; the companion lands in the directory above it.
    Format per .claude/skills/wiki-ingest-per-note/SKILL.md: source/converted
    frontmatter, an embed, and the extracted text in a collapsed callout.
    """
    parent_name = moved.parent.name
    if parent_name != "_resources" and not parent_name.endswith(".resources"):
        raise ValueError(f"not inside a _resources directory: {moved}")
    companion = moved.parent.parent / (moved.stem + ".md")
    text = _extract_text(moved)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    head = [
        "---",
        f'source: "_resources/{moved.name}"',
        f"converted: {now}",
        "---",
        "",
        f"![[{moved.name}]]",
        "",
        "> [!ocr-extractor]- Extracted text",
    ]
    body = [f"> {line}".rstrip() for line in text.splitlines()] or [">"]
    companion.write_text("\n".join(head + body) + "\n", encoding="utf-8")
    return companion


def _find_obsidian_cli() -> "str | None":
    cli = shutil.which("obsidian")
    if cli:
        return cli
    # macOS app-bundle fallback when the CLI shim is not on PATH
    fallback = "/Applications/Obsidian.app/Contents/MacOS/obsidian"
    return fallback if Path(fallback).exists() else None


def _obsidian_mover(root: Path, src_rel: str, dest_rel: str) -> tuple:
    """Move a file through the Obsidian CLI so Obsidian updates its link database.

    Returns (ok, reason). The vault is addressed by its registered name, which
    equals the vault root directory name.
    """
    cli = _find_obsidian_cli()
    if cli is None:
        return False, "obsidian CLI not found (is Obsidian installed?)"
    try:
        # The Obsidian CLI takes key=value parameters (vault=, path=, to=), not --flags.
        proc = subprocess.run(
            [cli, f"vault={root.name}", "move", f"path={src_rel}", f"to={dest_rel}"],
            capture_output=True, text=True, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"obsidian CLI failed: {e}"
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        return False, detail or f"obsidian CLI exited with status {proc.returncode}"
    return True, ""


def _confirm_move(src: Path, target: Path, timeout: float) -> bool:
    """Poll until the move is visible on disk — the Obsidian CLI returns
    before the filesystem reflects the move (asynchronous, and OneDrive
    sync can add latency)."""
    deadline = time.monotonic() + timeout
    while True:
        if target.is_file() and not src.exists():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


def _obsidian_responds(cli: str, root: Path) -> bool:
    """True if a running Obsidian instance answers a trivial CLI query."""
    try:
        proc = subprocess.run(
            [cli, f"vault={root.name}", "files", "total"],
            capture_output=True, text=True, timeout=10,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _ensure_obsidian_running(cli: str, root: Path, launch_timeout: float = 20.0) -> bool:
    """Make sure Obsidian is running; launch it via the CLI binary if needed.

    The `obsidian` CLI shim is the app binary itself, so invoking it with no
    arguments starts the app. Returns True once Obsidian answers CLI queries.
    """
    if _obsidian_responds(cli, root):
        return True
    try:
        subprocess.Popen(
            [cli],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, start_new_session=True,
        )
    except OSError:
        return False
    deadline = time.monotonic() + launch_timeout
    while time.monotonic() < deadline:
        time.sleep(1.0)
        if _obsidian_responds(cli, root):
            return True
    return False


def fix_loose_files(loose_files: list, root: Path, quiet: bool,
                    mover=None, runner=None, verify_timeout: float = 5.0) -> dict:
    """Relocate loose non-markdown files into sibling _resources/ dirs and convert them.

    Moves go through the Obsidian CLI (mover) so Obsidian keeps its link
    database consistent; every move is verified on disk and files are reported
    and skipped — never moved behind Obsidian's back — when the CLI is
    unavailable or Obsidian is not running. Companions follow the per-note
    format; .eml/.vtt/.html are converted by the pipeline scripts (runner).
    Companions are deliberately NOT logged in wiki/log.jsonl so the next
    ingest batch picks them up.
    """
    warning = None
    if mover is None:
        cli = _find_obsidian_cli()
        if cli is None or (loose_files and not _ensure_obsidian_running(cli, root)):
            warning = ("Obsidian is not running and could not be started — "
                       f"{len(loose_files)} loose file(s) left in place.")
            if not quiet:
                print(f"  loose: WARNING: {warning}", file=sys.stderr)
            details = [
                {"file": f, "action": "skipped", "reason": "Obsidian unavailable"}
                for f in loose_files
            ]
            return {"moved": 0, "converted": 0, "skipped": len(loose_files),
                    "details": details, "warning": warning}
        mover = _obsidian_mover
    if runner is None:
        runner = lambda cmd, **kw: subprocess.run(  # noqa: E731
            cmd, capture_output=True, text=True, timeout=300, **kw
        )
    moved = converted = skipped = 0
    details = []
    for rel_str in loose_files:
        src = root / rel_str
        if not src.is_file():  # disappeared since the scan
            continue
        target = src.parent / "_resources" / src.name
        if target.exists():
            try:
                target = _numbered_fallback(target)
            except RuntimeError as e:
                skipped += 1
                details.append({"file": rel_str, "action": "skipped", "reason": str(e)})
                continue
        target.parent.mkdir(exist_ok=True)
        dest_rel = str(target.relative_to(root))

        ok, reason = mover(root, rel_str, dest_rel)
        if ok and not _confirm_move(src, target, verify_timeout):
            ok = False
            reason = "move not confirmed on disk (is Obsidian running?)"
        if not ok:
            skipped += 1
            details.append({"file": rel_str, "action": "skipped", "reason": reason})
            try:
                target.parent.rmdir()  # remove the _resources dir if we just created it empty
            except OSError:
                pass  # non-empty or shared — leave it
            if not quiet:
                print(f"  loose: SKIP {rel_str}: {reason}", file=sys.stderr)
            continue

        moved += 1
        detail = {"file": rel_str, "action": "moved", "to": dest_rel}
        companion = target.parent.parent / (target.stem + ".md")
        ext = target.suffix.lower()
        if companion.exists():
            detail["companion"] = "already existed"
        elif ext in CONVERTER_BY_EXT:
            conv = CONVERTER_BY_EXT[ext]
            script = root / "scripts" / "system" / conv[0]
            try:
                proc = runner([sys.executable, str(script), *conv[1:], str(target)])
                conv_ok = proc.returncode == 0
                conv_err = (proc.stderr or "").strip()
            except (OSError, subprocess.TimeoutExpired) as e:
                conv_ok, conv_err = False, str(e)
            if conv_ok:
                converted += 1
                detail["converter"] = conv[0]
            else:
                detail["conversion_error"] = conv_err or "converter failed"
        else:
            try:
                companion_path = _write_companion(target)
                converted += 1
                detail["companion"] = str(companion_path.relative_to(root))
            except OSError as e:
                detail["conversion_error"] = str(e)
        details.append(detail)
        if not quiet:
            print(f"  loose: {rel_str} → {dest_rel}", file=sys.stderr)
    return {"moved": moved, "converted": converted, "skipped": skipped,
            "details": details, "warning": warning}
