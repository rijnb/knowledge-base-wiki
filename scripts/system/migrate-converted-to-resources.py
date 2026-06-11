#!/usr/bin/env python3
"""migrate-converted-to-resources — one-time migration to the _resources layout.

Migrates the LEGACY conversion layout:
    dir/<name>.<ext>                 (original non-Markdown file)
    dir/converted/<stem>.md          (converted Markdown, or <name>.<ext>.md)
to the CURRENT layout:
    dir/_resources/<name>.<ext>      (original, moved)
    dir/<stem>.md                    (companion: frontmatter + ![[embed]] +
                                      extracted text in a collapsed callout)

The migration is designed so that a vault that is clean according to
wiki-doctor before the migration is still clean afterwards:

  1. ORIGINALS are found via the converted note's `source:` frontmatter,
     then by exact name, then by fuzzy (normalized) name matching — searched
     in the converted/ dir's parent, in converted/ itself, and in an existing
     _resources/ sibling.  Each original is claimed by at most one note.
  2. Originals already inside a resource directory (a `_resources/` dir or a
     `*.resources/` dir) are NOT moved again — the companion is written next
     to them.  No nested `_resources/_resources` is ever created.
  3. Converted notes with no surviving original are moved up one level as
     standalone notes (content unchanged) instead of being skipped.
  4. Non-Markdown leftovers in converted/ (OCR page images, .txt sidecars)
     are moved out alongside the originals; junk (.DS_Store, *.swp) is
     deleted.  converted/ directories are always emptied and removed.
  5. Every move is recorded in a move map, and ALL Markdown files under
     raw/ and wiki/ are scanned: wikilinks, embeds, and markdown links that
     would break because of a move are rewritten to the new location
     (resolution mirrors wiki-doctor's own logic).  `source:` frontmatter
     lines holding a moved path as plain text are updated as well.
  6. wiki/log.jsonl entries whose `file` was moved are REWRITTEN IN PLACE
     (backup at wiki/log.jsonl.bak); new entries are appended only for files
     that have no entry yet, so the log gains no stale or duplicate entries.

The script is a DRY RUN by default — pass --apply to actually modify files.

EXIT CODES
  0  success (or nothing to migrate)
  1  one or more files could not be migrated, or an argument error

EXAMPLES
  # Preview the migration
  python3 scripts/system/migrate-converted-to-resources.py

  # Perform the migration
  python3 scripts/system/migrate-converted-to-resources.py --apply

  # Migrate a different tree, without touching wiki/log.jsonl
  python3 scripts/system/migrate-converted-to-resources.py --root archive --no-log --apply
"""

import argparse
import filecmp
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, quote

# Reuse the exact link regexes and name normalization that wiki-doctor uses,
# so "what we rewrite" and "what the doctor checks" can never drift apart.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.links import (  # noqa: E402
    CURLY_TO_STRAIGHT,
    RE_IMAGE_EMBED,
    RE_MDIMAGE,
    RE_MDLINK,
    RE_WIKILINK,
    is_external,
)
from lib.resolve import KNOWN_EXTENSIONS, normalize_name  # noqa: E402


# ---------------------------------------------------------------------------
# Logging helpers (same conventions as the convert-*-to-md.py scripts)
# ---------------------------------------------------------------------------

_WARNINGS: list[str] = []
_ERRORS: list[str] = []

JUNK_NAMES = {".DS_Store"}
JUNK_SUFFIXES = {".swp"}


def _log(tag: str, msg: str, file=None) -> None:
    print(f"  {tag} {msg}", file=file or sys.stdout)


def warn(msg: str) -> None:
    _log("[WARN]", msg)
    _WARNINGS.append(msg)


def error(msg: str) -> None:
    _log("[ERROR]", msg, file=sys.stderr)
    _ERRORS.append(msg)


def ok(msg: str) -> None:
    _log("[OK]", msg)


def info(msg: str) -> None:
    _log("[INFO]", msg)


# ---------------------------------------------------------------------------
# Markdown restructuring
# ---------------------------------------------------------------------------

def split_frontmatter(text: str) -> tuple[str | None, str]:
    """Return (frontmatter-without-delimiters, body) or (None, text)."""
    if text.startswith("---\n") or text.startswith("---\r\n"):
        end = text.find("\n---", 3)
        if end != -1:
            fm = text[4:end]
            body = text[end + 4:]
            # Drop the newline that terminated the closing delimiter
            if body.startswith("\n"):
                body = body[1:]
            return fm, body
    return None, text


_HEADER_FENCE_FIRST_LINE = re.compile(r"^(Date|From|To|CC|BCC|Subject):")


def split_preamble(body: str) -> tuple[str, str]:
    """Split off a leading H1 and/or email header code fence.

    These stay outside the "Extracted text" callout, matching the output of
    the convert-*-to-md.py scripts.  Returns (preamble, rest).
    """
    lines = body.lstrip("\n").splitlines()
    pre: list[str] = []
    i = 0

    if i < len(lines) and lines[i].startswith("# "):
        pre.append(lines[i])
        i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1

    if i < len(lines) and lines[i].strip() == "```":
        j = i + 1
        if j < len(lines) and _HEADER_FENCE_FIRST_LINE.match(lines[j].strip()):
            k = j
            while k < len(lines) and lines[k].strip() != "```":
                k += 1
            if k < len(lines):
                if pre:
                    pre.append("")
                pre.extend(lines[i:k + 1])
                i = k + 1
                while i < len(lines) and not lines[i].strip():
                    i += 1
                # Drop a horizontal-rule separator that followed the header
                if i < len(lines) and lines[i].strip() == "---":
                    i += 1
                    while i < len(lines) and not lines[i].strip():
                        i += 1

    return "\n".join(pre), "\n".join(lines[i:]).rstrip()


def extracted_text_callout(text: str) -> str:
    """Wrap text in a collapsed Obsidian callout block."""
    lines = ["> [!ocr-extractor]- Extracted text"]
    for line in (text.splitlines() or [""]):
        lines.append(("> " + line).rstrip())
    return "\n".join(lines)


def rewrite_frontmatter(fm: str | None, source_rel: str, now_str: str) -> str:
    """Return frontmatter (without delimiters) with `source:` pointing at
    source_rel (the original, relative to the companion's directory);
    create minimal frontmatter when absent."""
    source_line = f'source: "{source_rel}"'
    if fm is None:
        return f"{source_line}\nconverted: {now_str}"
    out: list[str] = []
    replaced = False
    for line in fm.splitlines():
        if line.startswith("source:"):
            out.append(source_line)
            replaced = True
        else:
            out.append(line)
    if not replaced:
        out.append(source_line)
    return "\n".join(out)


def build_companion(legacy_text: str, original_name: str, source_rel: str,
                    now_str: str) -> str:
    fm, body = split_frontmatter(legacy_text)
    preamble, rest = split_preamble(body)
    parts = [
        "---",
        rewrite_frontmatter(fm, source_rel, now_str),
        "---",
        "",
        f"![[{original_name}]]",
    ]
    if preamble:
        parts += ["", preamble]
    parts += ["", extracted_text_callout(rest), ""]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Original discovery
# ---------------------------------------------------------------------------

_SOURCE_LINE = re.compile(r'^source:\s*"?([^"\n]*?)"?\s*$')


def frontmatter_source(md: Path) -> str | None:
    """Return the `source:` frontmatter value of a converted note, if any."""
    try:
        with md.open(encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i > 30:
                    break
                m = _SOURCE_LINE.match(line.rstrip())
                if m and m.group(1).strip():
                    return m.group(1).strip()
    except OSError:
        pass
    return None


def _original_search_dirs(conv_dir: Path) -> list[Path]:
    parent = conv_dir.parent
    dirs = [parent, conv_dir]
    res = parent / "_resources"
    if res.is_dir():
        dirs.append(res)
    return dirs


def _candidate_originals(conv_dir: Path) -> list[Path]:
    """All non-Markdown files an original could be, for this converted/ dir."""
    cands: list[Path] = []
    for d in _original_search_dirs(conv_dir):
        try:
            for p in sorted(d.iterdir()):
                if p.is_file() and p.suffix.lower() != ".md" \
                        and p.name not in JUNK_NAMES \
                        and p.suffix.lower() not in JUNK_SUFFIXES:
                    cands.append(p)
        except OSError as exc:
            error(f"cannot list {d}: {exc}")
    return cands


def find_original_exact(md: Path, root: Path, claimed: set[Path]) -> Path | None:
    """Find the original via `source:` frontmatter or exact name match."""
    conv_dir = md.parent
    parent = conv_dir.parent

    src = frontmatter_source(md)
    if src:
        src_path = Path(src)
        for cand in (root / src_path, parent / src_path, conv_dir / src_path,
                     parent / src_path.name, conv_dir / src_path.name,
                     parent / "_resources" / src_path.name):
            if cand.is_file() and cand.suffix.lower() != ".md":
                cand = cand.resolve()
                if cand not in claimed:
                    return cand

    stem = md.stem
    for p in _candidate_originals(conv_dir):
        if (p.name == stem or p.stem == stem) and p.resolve() not in claimed:
            return p.resolve()
    return None


def find_original_fuzzy(md: Path, claimed: set[Path]) -> Path | None:
    """Fuzzy match: normalized stem/name equality, unique result required."""
    stem = md.stem
    keys = {normalize_name(stem)}
    # attachment-style note "y.pdf.md": also try without the inner extension
    inner = Path(stem)
    if inner.suffix:
        keys.add(normalize_name(inner.stem))
    matches = []
    for p in _candidate_originals(md.parent):
        if p.resolve() in claimed:
            continue
        if normalize_name(p.name) in keys or normalize_name(p.stem) in keys:
            matches.append(p)
    if len(matches) == 1:
        return matches[0].resolve()
    return None


# ---------------------------------------------------------------------------
# Placement
# ---------------------------------------------------------------------------

def is_resource_dir(d: Path, root: Path) -> bool:
    """True when d already is a resource directory: named `_resources`, a
    `*.resources` dir, or anything below an `_resources` directory."""
    try:
        parts = d.relative_to(root).parts
    except ValueError:
        parts = d.parts
    return "_resources" in parts or d.name.endswith(".resources")


def numbered_fallback(target: Path) -> Path:
    for n in range(2, 100):
        cand = target.with_name(f"{target.stem} {n}{target.suffix}")
        if not cand.exists():
            return cand
    raise RuntimeError(f"no free name near {target}")


def references_source(md_path: Path, src_name: str) -> bool:
    """True if md_path's frontmatter `source:` field references src_name
    (same rule as the convert scripts and the batch scanner)."""
    try:
        with md_path.open(encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i > 20:
                    break
                if line.startswith("source:") and src_name in line:
                    return True
    except OSError:
        pass
    return False


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------

class Plan:
    """Collected actions, all paths relative to root (POSIX strings)."""

    def __init__(self, root: Path):
        self.root = root
        self.move_original: list[tuple[str, str]] = []      # (old, new) — may be old==new (stays)
        self.companions: list[tuple[str, str, str, str]] = []  # (legacy_md, companion, original_new, source_rel)
        self.reuse_companion: list[tuple[str, str]] = []    # (legacy_md, existing companion)
        self.standalone: list[tuple[str, str]] = []         # (legacy_md, new)
        self.dup_delete: list[tuple[str, str]] = []         # (legacy_md, surviving twin)
        self.artifacts: list[tuple[str, str]] = []          # (old, new)
        self.junk: list[str] = []                           # deleted outright
        self.conv_dirs: list[Path] = []

    def rel(self, p: Path) -> str:
        return p.relative_to(self.root).as_posix()

    def move_map(self) -> dict[str, str]:
        mm: dict[str, str] = {}
        for old, new in self.move_original:
            if old != new:
                mm[old] = new
        for legacy, companion, _orig, _src in self.companions:
            mm[legacy] = companion
        for legacy, existing in self.reuse_companion:
            mm[legacy] = existing
        for legacy, new in self.standalone:
            if legacy != new:
                mm[legacy] = new
        for legacy, twin in self.dup_delete:
            mm[legacy] = twin
        for old, new in self.artifacts:
            if old != new:
                mm[old] = new
        return mm


def plan_migration(root: Path, conv_dirs: list[Path]) -> Plan:
    plan = Plan(root)
    plan.conv_dirs = conv_dirs
    claimed: set[Path] = set()
    planned_targets: set[Path] = set()  # files we will create/move to

    def free_target(target: Path) -> Path:
        while target.exists() or target in planned_targets:
            target = numbered_fallback(target)
        planned_targets.add(target)
        return target

    # Pass 1: exact/source matches; pass 2: fuzzy for the rest.
    md_original: dict[Path, Path | None] = {}
    all_mds: list[Path] = []
    for conv_dir in conv_dirs:
        for md in sorted(conv_dir.glob("*.md")):
            all_mds.append(md)
            orig = find_original_exact(md, root, claimed)
            if orig is not None:
                claimed.add(orig)
            md_original[md] = orig
    for md in all_mds:
        if md_original[md] is None:
            orig = find_original_fuzzy(md, claimed)
            if orig is not None:
                claimed.add(orig)
                md_original[md] = orig

    for conv_dir in conv_dirs:
        parent = conv_dir.parent
        for md in sorted(conv_dir.glob("*.md")):
            original = md_original[md]
            if original is None:
                # Standalone: keep the note, move it up one level.
                target = parent / md.name
                if target.exists() and filecmp.cmp(md, target, shallow=False):
                    plan.dup_delete.append((plan.rel(md), plan.rel(target)))
                    continue
                target = free_target(target)
                plan.standalone.append((plan.rel(md), plan.rel(target)))
                continue

            odir = original.parent
            # Where does the original end up, and where does the companion go?
            if odir == conv_dir:
                base = parent
                dest_dir = parent if is_resource_dir(parent, root) else parent / "_resources"
                moved = dest_dir / original.name
            elif odir.name == "_resources":
                base = odir.parent
                moved = original
            elif is_resource_dir(odir, root):
                base = odir
                moved = original
            else:
                base = odir
                moved = odir / "_resources" / original.name

            if moved != original:
                moved = free_target(moved)

            # Companion: prefer <stem>.md, else <name>.md; reuse an existing
            # companion for the same original; otherwise pick a free name.
            stem_md = base / (original.stem + ".md")
            name_md = base / (original.name + ".md")
            target: Path | None = None
            reused = False
            for cand in (stem_md, name_md):
                if cand.exists() and references_source(cand, original.name):
                    plan.reuse_companion.append((plan.rel(md), plan.rel(cand)))
                    plan.move_original.append((plan.rel(original), plan.rel(moved)))
                    reused = True
                    break
                if not cand.exists() and cand not in planned_targets:
                    target = cand
                    break
            if reused:
                continue
            if target is None:
                target = free_target(stem_md)
            else:
                planned_targets.add(target)

            source_rel = os.path.relpath(str(moved), str(base)).replace(os.sep, "/")
            plan.companions.append(
                (plan.rel(md), plan.rel(target), plan.rel(moved), source_rel))
            plan.move_original.append((plan.rel(original), plan.rel(moved)))

        # Everything else inside converted/ (recursively): junk or artifact.
        for dirpath, _dirnames, filenames in os.walk(conv_dir):
            d = Path(dirpath)
            for fname in filenames:
                p = d / fname
                if p.parent == conv_dir and p.suffix.lower() == ".md":
                    continue  # handled above
                if p.resolve() in claimed:
                    continue  # an original inside converted/, already planned
                if fname in JUNK_NAMES or p.suffix.lower() in JUNK_SUFFIXES:
                    plan.junk.append(plan.rel(p))
                    continue
                dest_dir = parent if is_resource_dir(parent, root) else parent / "_resources"
                rel_in_conv = p.relative_to(conv_dir)
                target = dest_dir / rel_in_conv
                if target.exists() and target.is_file() \
                        and filecmp.cmp(p, target, shallow=False):
                    plan.dup_delete.append((plan.rel(p), plan.rel(target)))
                    continue
                target = free_target(target)
                plan.artifacts.append((plan.rel(p), plan.rel(target)))

    return plan


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------

def apply_plan(plan: Plan, *, apply: bool, now_str: str, quiet: bool) -> bool:
    root = plan.root
    okay = True

    def move(old_rel: str, new_rel: str, label: str) -> bool:
        old, new = root / old_rel, root / new_rel
        if old_rel == new_rel:
            return True
        if not apply:
            if not quiet:
                info(f"[dry-run] would move {label} '{old_rel}' → '{new_rel}'")
            return True
        try:
            new.parent.mkdir(parents=True, exist_ok=True)
            old.rename(new)
            return True
        except OSError as exc:
            error(f"cannot move '{old_rel}' → '{new_rel}': {exc}")
            return False

    for old, new in plan.move_original:
        okay &= move(old, new, "original")

    for legacy, companion, original_new, source_rel in plan.companions:
        md = root / legacy
        try:
            legacy_text = md.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            error(f"cannot read {legacy}: {exc}")
            okay = False
            continue
        content = build_companion(
            legacy_text, Path(original_new).name, source_rel, now_str)
        if not apply:
            if not quiet:
                info(f"[dry-run] would write companion '{companion}', delete '{legacy}'")
            continue
        try:
            (root / companion).write_text(content, encoding="utf-8")
            md.unlink()
            if not quiet:
                ok(f"companion '{companion}' (original at '{original_new}')")
        except OSError as exc:
            error(f"migration failed for {legacy}: {exc}")
            okay = False

    for legacy, existing in plan.reuse_companion:
        if not apply:
            if not quiet:
                info(f"[dry-run] would delete '{legacy}' (companion '{existing}' already exists)")
            continue
        try:
            (root / legacy).unlink()
            if not quiet:
                ok(f"removed '{legacy}' — already covered by companion '{existing}'")
        except OSError as exc:
            error(f"cannot remove {legacy}: {exc}")
            okay = False

    for legacy, new in plan.standalone:
        if move(legacy, new, "standalone note") and apply and not quiet:
            ok(f"standalone note '{new}' (no original found)")

    for legacy, twin in plan.dup_delete:
        if not apply:
            if not quiet:
                info(f"[dry-run] would delete '{legacy}' (identical to '{twin}')")
            continue
        try:
            (root / legacy).unlink()
            if not quiet:
                ok(f"removed duplicate '{legacy}' (identical to '{twin}')")
        except OSError as exc:
            error(f"cannot remove {legacy}: {exc}")
            okay = False

    for old, new in plan.artifacts:
        okay &= move(old, new, "artifact")

    for junk_rel in plan.junk:
        if not apply:
            if not quiet:
                info(f"[dry-run] would delete junk '{junk_rel}'")
            continue
        try:
            (root / junk_rel).unlink()
        except OSError as exc:
            error(f"cannot delete junk {junk_rel}: {exc}")
            okay = False

    # Remove the (now empty) converted/ directories, deepest first.
    for conv_dir in sorted(plan.conv_dirs, key=lambda d: len(d.parts), reverse=True):
        if not apply:
            continue
        try:
            for dirpath, dirnames, filenames in os.walk(conv_dir, topdown=False):
                if filenames:
                    raise OSError(f"unexpected leftovers: {', '.join(filenames[:5])}")
                for dn in dirnames:
                    (Path(dirpath) / dn).rmdir()
            conv_dir.rmdir()
        except OSError as exc:
            error(f"'{conv_dir.relative_to(root)}' not removed: {exc}")
            okay = False

    return okay


# ---------------------------------------------------------------------------
# Link rewriting
# ---------------------------------------------------------------------------

class VaultState:
    """Set-based model of the post-migration vault, used to mirror
    wiki-doctor's link resolution without re-walking the filesystem
    (and to support --dry-run, where nothing has moved yet)."""

    def __init__(self, vault_root: Path, move_map: dict[str, str]):
        self.move_map = move_map
        old_files: set[str] = set()
        for top in ("raw", "wiki"):
            top_dir = vault_root / top
            if not top_dir.is_dir():
                continue
            for dirpath, _dirnames, filenames in os.walk(top_dir):
                base = Path(dirpath)
                for fname in filenames:
                    old_files.add((base / fname).relative_to(vault_root).as_posix())
        # Old state = on-disk state at scan time (dry run: nothing moved yet).
        new_files = {move_map.get(f, f) for f in old_files}
        self.new_files = new_files
        self.new_dirs: set[str] = set()
        for f in new_files:
            p = Path(f).parent
            while p != Path("."):
                self.new_dirs.add(p.as_posix())
                p = p.parent
        self.md_stems: set[str] = set()
        skip_names = {"SKILL.md", "index.md", "_index.md", "START_HERE.md"}
        for f in new_files:
            p = Path(f)
            if p.suffix != ".md" or p.name in skip_names or f == "wiki/log.md":
                continue
            if any(part.startswith(".") for part in p.parts[:-1]):
                continue
            self.md_stems.add(p.stem)
        self.new_suffixes: set[str] = set()
        for f in new_files:
            parts = f.split("/")
            for i in range(len(parts)):
                self.new_suffixes.add("/".join(parts[i:]).translate(CURLY_TO_STRAIGHT))
        # suffix → old paths that moved (for finding rewrite candidates)
        self.old_suffix_map: dict[str, list[str]] = {}
        for old in move_map:
            parts = old.split("/")
            for i in range(len(parts)):
                key = "/".join(parts[i:]).translate(CURLY_TO_STRAIGHT)
                self.old_suffix_map.setdefault(key, []).append(old)

    # -- resolution in the NEW state (mirrors lib.resolve.resolve_wikilink) --

    def wikilink_resolves(self, target: str) -> bool:
        candidate = Path(target)
        has_known_ext = candidate.suffix.lower() in KNOWN_EXTENSIONS
        if target in self.new_files or target.rstrip("/") in self.new_dirs:
            return True
        if not has_known_ext:
            for ext in KNOWN_EXTENSIONS:
                if (target + ext) in self.new_files:
                    return True
        elif (target + ".md") in self.new_files:
            return True
        if candidate.parent != Path("."):
            for top in ("wiki", "raw"):
                t = f"{top}/{target}"
                if t in self.new_files or t in self.new_dirs:
                    return True
                if not has_known_ext:
                    for ext in KNOWN_EXTENSIONS:
                        if (t + ext) in self.new_files:
                            return True
                elif (t + ".md") in self.new_files:
                    return True
        if candidate.parent == Path("."):
            stem = candidate.stem if has_known_ext else candidate.name
            if stem in self.md_stems:
                return True
        normalized = target[2:] if target.startswith("./") else target
        normalized = normalized.translate(CURLY_TO_STRAIGHT)
        if normalized in self.new_suffixes or (normalized + ".md") in self.new_suffixes:
            return True
        return False

    def mdlink_resolves(self, target: str, file_dir: str) -> bool:
        for base in (file_dir, ""):
            p = os.path.normpath(os.path.join(base, target)).replace(os.sep, "/")
            if p in self.new_files or (p + ".md") in self.new_files:
                return True
        return False

    # -- rewrite candidates from the OLD state --

    def find_moved(self, target: str, file_old_dir: str) -> str | None:
        """Return the NEW path for a link target that referred to a moved
        file, or None when the target doesn't match any moved file."""
        normalized = target[2:] if target.startswith("./") else target
        normalized = normalized.translate(CURLY_TO_STRAIGHT)
        cands: list[str] = []
        for form in (normalized, normalized + ".md"):
            if form in self.move_map:
                return self.move_map[form]
            for top in ("wiki", "raw"):
                t = f"{top}/{form}"
                if t in self.move_map:
                    return self.move_map[t]
            # relative to the file's own (old) directory
            rel = os.path.normpath(os.path.join(file_old_dir, form)).replace(os.sep, "/")
            if rel in self.move_map:
                return self.move_map[rel]
            cands.extend(self.old_suffix_map.get(form, []))
        if not cands:
            return None
        # Prefer the moved file whose old path shares the longest common
        # directory prefix with the linking file.
        def score(old: str) -> tuple[int, int]:
            a, b = old.split("/"), file_old_dir.split("/")
            common = 0
            for x, y in zip(a, b):
                if x != y:
                    break
                common += 1
            return (common, -len(old))
        best = max(sorted(set(cands)), key=score)
        return self.move_map[best]


def rewrite_links(vault_root: Path, state: VaultState, *, apply: bool,
                  quiet: bool) -> tuple[int, int]:
    """Rewrite links that broke because of the migration. Returns
    (files_changed, links_rewritten)."""
    move_map = state.move_map
    reverse_map = {v: k for k, v in move_map.items()}
    files_changed = 0
    links_rewritten = 0

    md_files: list[Path] = []
    for top in ("raw", "wiki"):
        top_dir = vault_root / top
        if top_dir.is_dir():
            md_files.extend(p for p in top_dir.rglob("*.md") if p.is_file())

    for md_file in sorted(md_files):
        rel = md_file.relative_to(vault_root).as_posix()
        if not apply and rel in move_map:
            continue  # dry run: this legacy file will be replaced/deleted
        # Resolve relative links against the file's post-migration location;
        # resolve rewrite candidates against its pre-migration location.
        new_rel = move_map.get(rel, rel)
        new_dir = Path(new_rel).parent.as_posix()
        old_dir = Path(reverse_map.get(rel, rel)).parent.as_posix()
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        edits: list[tuple[int, int, str]] = []  # (start, end, replacement)

        def handle_wikilink(m: re.Match) -> None:
            target = m.group(1).strip()
            if not target or target.startswith("#") or is_external(target):
                return
            if state.wikilink_resolves(target):
                return
            new = state.find_moved(target, old_dir)
            if new is None:
                return
            if new.endswith(".md") and not target.endswith(".md"):
                new = new[:-3]
            edits.append((m.start(1), m.end(1), new))

        def handle_mdlink(m: re.Match) -> None:
            raw_target = m.group(1).strip()
            if not raw_target or raw_target.startswith("#") or is_external(raw_target):
                return
            target = unquote(raw_target)
            if state.mdlink_resolves(target, new_dir):
                return
            # candidates relative to the old location, then root-relative
            new = None
            for base in (old_dir, ""):
                p = os.path.normpath(os.path.join(base, target)).replace(os.sep, "/")
                if p in move_map:
                    new = move_map[p]
                    break
                if (p + ".md") in move_map:
                    new = move_map[p + ".md"]
                    break
            if new is None:
                return
            if "%" in raw_target:
                new = quote(new, safe="/!$&'()*+,:;=@~-._")
            edits.append((m.start(1), m.end(1), new))

        for m in RE_WIKILINK.finditer(content):
            handle_wikilink(m)
        for m in RE_IMAGE_EMBED.finditer(content):
            handle_wikilink(m)
        for m in RE_MDLINK.finditer(content):
            handle_mdlink(m)
        for m in RE_MDIMAGE.finditer(content):
            handle_mdlink(m)

        # Plain-text `source:` frontmatter lines holding a moved path.
        for m in re.finditer(r'(?m)^source:\s*"?([^"\n]+?)"?\s*$', content):
            val = m.group(1).strip()
            val_norm = val[2:] if val.startswith("./") else val
            mapped = move_map.get(val_norm)
            if mapped is None:
                rel_old = os.path.normpath(os.path.join(old_dir, val_norm)).replace(os.sep, "/")
                if rel_old in move_map:
                    new_abs = move_map[rel_old]
                    mapped = os.path.relpath(new_abs, new_dir).replace(os.sep, "/")
                    if mapped.startswith("../"):
                        mapped = new_abs
            if mapped and mapped != val:
                edits.append((m.start(1), m.end(1), mapped))

        if not edits:
            continue
        edits.sort()
        out: list[str] = []
        pos = 0
        for start, end, repl in edits:
            if start < pos:
                continue  # overlapping (shouldn't happen)
            out.append(content[pos:start])
            out.append(repl)
            pos = end
        out.append(content[pos:])
        files_changed += 1
        links_rewritten += len(edits)
        if apply:
            md_file.write_text("".join(out), encoding="utf-8")
        if not quiet:
            tag = "" if apply else "[dry-run] "
            info(f"{tag}rewrote {len(edits)} link(s) in '{rel}'")

    return files_changed, links_rewritten


# ---------------------------------------------------------------------------
# wiki/log.jsonl
# ---------------------------------------------------------------------------

def update_log(log_path: Path, plan: Plan, move_map: dict[str, str],
               *, apply: bool, now_str: str) -> None:
    """Rewrite moved paths inside existing log entries and append entries
    only for migrated files that have none, so the log gains no stale or
    duplicate entries."""
    lines: list[str] = []
    present: set[str] = set()
    rewritten = 0
    if log_path.exists():
        with log_path.open(encoding="utf-8") as f:
            for raw in f:
                line = raw.rstrip("\n")
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    lines.append(line)
                    continue
                file_field = entry.get("file")
                if file_field:
                    norm = Path(file_field).as_posix()
                    if norm in move_map:
                        entry["file"] = move_map[norm]
                        line = json.dumps(entry, ensure_ascii=False)
                        rewritten += 1
                    present.add(Path(entry["file"]).as_posix())
                lines.append(line)

    to_append: list[tuple[str, str]] = []

    def queue(path: str, summary: str) -> None:
        if path not in present:
            to_append.append((path, summary))
            present.add(path)

    for old, new in plan.move_original:
        queue(new, "Source file moved to _resources during legacy-layout migration.")
    for _legacy, companion, _orig, _src in plan.companions:
        queue(companion, "Companion created from legacy converted/ Markdown during migration.")
    for _legacy, new in plan.standalone:
        queue(new, "Converted note kept as standalone during legacy-layout "
                   "migration (original gone).")

    if not apply:
        info(f"[dry-run] would rewrite {rewritten} log entry/entries and "
             f"append {len(to_append)} to {log_path}")
        return

    for path, summary in to_append:
        lines.append(json.dumps({
            "date": now_str,
            "session": 0,
            "file": path,
            "summary": summary,
            "pages_created": [],
            "pages_updated": [],
        }, ensure_ascii=False))

    log_path.parent.mkdir(parents=True, exist_ok=True)
    if log_path.exists():
        backup = log_path.with_suffix(log_path.suffix + ".bak")
        backup.write_bytes(log_path.read_bytes())
    with log_path.open("w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")
    ok(f"log updated: {rewritten} entry/entries rewritten, "
       f"{len(to_append)} appended ({log_path})")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="migrate-converted-to-resources.py",
        description="One-time migration from the legacy dir/converted/<stem>.md "
                    "layout to dir/_resources/<name> + companion dir/<stem>.md. "
                    "Rewrites links and wiki/log.jsonl entries that point at "
                    "migrated files. Dry run by default; pass --apply to modify files.",
    )
    parser.add_argument("--root", metavar="DIR", default="raw",
                        help="tree to scan for converted/ directories (default: raw)")
    parser.add_argument("--log", metavar="FILE", default="wiki/log.jsonl",
                        help="ingestion log to update (default: wiki/log.jsonl)")
    parser.add_argument("--no-log", action="store_true",
                        help="do not update the ingestion log")
    parser.add_argument("--no-link-rewrite", action="store_true",
                        help="do not rewrite links pointing at migrated files")
    parser.add_argument("--quiet", action="store_true",
                        help="suppress per-file output")
    parser.add_argument("--apply", action="store_true",
                        help="actually move/write/delete files (default: dry run)")
    args = parser.parse_args()

    scan_root = Path(args.root)
    if not scan_root.is_dir():
        print(f"[ERROR] root directory not found: {args.root}", file=sys.stderr)
        sys.exit(1)
    vault_root = Path.cwd()

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conv_dirs = sorted(d for d in scan_root.rglob("converted") if d.is_dir())
    if not conv_dirs:
        print(f"[INFO] no converted/ directories found under {scan_root} — nothing to migrate")
        sys.exit(0)

    print(f"planning migration of {len(conv_dirs)} converted/ director(ies) …")
    plan = plan_migration(vault_root, [(vault_root / d).resolve() for d in conv_dirs])
    move_map = plan.move_map()
    # The converted/ directories disappear; map directory links to the parent.
    for d in plan.conv_dirs:
        rel = d.relative_to(vault_root).as_posix()
        move_map.setdefault(rel, Path(rel).parent.as_posix())

    n_moves = sum(1 for o, n in plan.move_original if o != n)
    info(f"plan: {len(plan.companions)} companion(s), "
         f"{len(plan.reuse_companion)} already-covered, "
         f"{len(plan.standalone)} standalone, {len(plan.dup_delete)} duplicate(s), "
         f"{n_moves} original move(s), {len(plan.artifacts)} artifact(s), "
         f"{len(plan.junk)} junk file(s)")

    # Build the resolution model BEFORE touching the filesystem.
    state = VaultState(vault_root, move_map)

    okay = apply_plan(plan, apply=args.apply, now_str=now_str, quiet=args.quiet)

    if not args.no_link_rewrite:
        files_changed, links = rewrite_links(
            vault_root, state, apply=args.apply, quiet=args.quiet)
        label = "" if args.apply else "[dry-run] "
        info(f"{label}links: {links} rewritten in {files_changed} file(s)")

    if not args.no_log:
        update_log(Path(args.log), plan, move_map, apply=args.apply, now_str=now_str)

    label = "[dry-run] " if not args.apply else ""
    n_migrated = (len(plan.companions) + len(plan.reuse_companion)
                  + len(plan.standalone) + len(plan.dup_delete))
    print(
        f"\n[INFO] {label}done: {n_migrated} converted note(s) migrated"
        + (f", {len(_WARNINGS)} warning(s)" if _WARNINGS else "")
        + (f", {len(_ERRORS)} error(s)" if _ERRORS else "")
    )
    if _ERRORS or not okay:
        sys.exit(1)


if __name__ == "__main__":
    main()
