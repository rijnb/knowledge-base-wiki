#!/usr/bin/env python3
"""Add migration-baseline entries to wiki/log.jsonl for existing raw files.

This is for adopting the framework around an existing raw/ + wiki/ corpus.
It records current raw files as already present before migration, so the next
ordinary ingest run does not try to re-ingest the entire historical corpus.

Dry-run by default; pass --apply to append entries.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

SOURCE_EXTENSIONS = {".md", ".pdf", ".doc", ".docx", ".txt", ".vtt", ".eml", ".html"}
INGEST_FALSE_RE = re.compile(
    r'''^\s*ingest\s*:\s*(?:"false"|'false'|false)\s*(?:#.*)?$''',
    re.IGNORECASE,
)
WIKILINK_RE = re.compile(r"!?\[\[((?:[^\]|\n\\]|\\(?!\|)|\](?!\]))+)")
MDLINK_RE = re.compile(r"!?\[[^\]\n]*\]\(((?:[^()#\n]|\([^()\n]*\))+?)(?:#[^)]*)?\)")
SOURCE_RE = re.compile(r"^\s*source\s*:\s*(.+?)\s*(?:#.*)?$")
EXTERNAL_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _content_hash(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return "sha256:" + h.hexdigest()
    except OSError:
        return None


def _frontmatter_lines(path: Path) -> list[str]:
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            if f.readline().strip() != "---":
                return []
            lines = []
            for line in f:
                if line.strip() in ("---", "..."):
                    return lines
                lines.append(line.rstrip("\n"))
    except OSError:
        pass
    return []


def _has_ingest_false(path: Path) -> bool:
    if path.suffix.lower() != ".md":
        return False
    return any(INGEST_FALSE_RE.match(line) for line in _frontmatter_lines(path))


def _strip_target(target: str) -> str:
    target = target.strip()
    if not target:
        return ""
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1].strip()
    if (target.startswith('"') and target.endswith('"')) or (
        target.startswith("'") and target.endswith("'")
    ):
        target = target[1:-1].strip()
    target = unquote(target).replace("\\", "/")
    target = target.split("#", 1)[0].split("?", 1)[0]
    if not target or target.startswith("#") or EXTERNAL_RE.match(target):
        return ""
    return target


def _link_targets(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    targets = []
    targets.extend(m.group(1) for m in WIKILINK_RE.finditer(text))
    targets.extend(m.group(1) for m in MDLINK_RE.finditer(text))
    for line in _frontmatter_lines(path):
        m = SOURCE_RE.match(line)
        if m:
            targets.append(m.group(1))
    return targets


def _candidate_paths(root: Path) -> list[Path]:
    raw = root / "raw"
    if not raw.is_dir():
        return []
    return sorted(
        path
        for path in raw.rglob("*")
        if path.is_file() and path.suffix.lower() in SOURCE_EXTENSIONS
    )


def _resolve_linked_raw_files(target: str, note_dir: Path, candidates: set[Path], root: Path) -> set[Path]:
    target = _strip_target(target)
    if not target:
        return set()

    raw_paths = []
    if os.path.isabs(target):
        raw_paths.append(Path(target))
    elif target.startswith("raw/"):
        raw_paths.append(root / target)
    else:
        raw_paths.append(note_dir / target)

    resolved = set()
    for raw_path in raw_paths:
        variants = [raw_path]
        if raw_path.suffix == "":
            variants.extend(raw_path.with_suffix(ext) for ext in SOURCE_EXTENSIONS)
        for variant in variants:
            try:
                candidate = variant.resolve()
            except OSError:
                continue
            if candidate in candidates:
                resolved.add(candidate)
    return resolved


def _protected_paths(root: Path, candidates: list[Path]) -> tuple[set[Path], list[dict]]:
    candidate_set = {path.resolve() for path in candidates}
    protected = set()
    notes = []
    for path in candidates:
        if not _has_ingest_false(path):
            continue
        resolved_path = path.resolve()
        note_dir = path.parent
        linked = set()
        for target in _link_targets(path):
            linked.update(_resolve_linked_raw_files(target, note_dir, candidate_set, root))
        linked.discard(resolved_path)
        protected.add(resolved_path)
        protected.update(linked)
        notes.append({
            "file": _rel(path, root),
            "linked_count": len(linked),
        })
    return protected, notes


def _existing_log_state(log_path: Path) -> tuple[set[str], set[str]]:
    paths = set()
    hashes = set()
    if not log_path.is_file():
        return paths, hashes
    try:
        for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            file_path = item.get("file")
            if isinstance(file_path, str) and file_path:
                paths.add(file_path)
            file_hash = item.get("hash")
            if isinstance(file_hash, str) and file_hash:
                hashes.add(file_hash)
    except OSError:
        pass
    return paths, hashes


def build_entries(root: Path, log_path: Path) -> dict:
    candidates = _candidate_paths(root)
    protected, protected_notes = _protected_paths(root, candidates)
    existing_paths, existing_hashes = _existing_log_state(log_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    entries = []
    skipped_existing = 0
    skipped_protected = 0
    read_errors = []

    for path in candidates:
        resolved = path.resolve()
        rel = _rel(path, root)
        if resolved in protected:
            skipped_protected += 1
            continue
        file_hash = _content_hash(path)
        if file_hash is None:
            read_errors.append(rel)
            continue
        if rel in existing_paths or file_hash in existing_hashes:
            skipped_existing += 1
            continue
        try:
            mtime = int(path.stat().st_mtime)
        except OSError:
            read_errors.append(rel)
            continue
        entries.append({
            "date": now,
            "session": "migration-baseline",
            "file": rel,
            "summary": "Existing raw file baselined during migration; not ingested by this run.",
            "pages_created": [],
            "pages_updated": [],
            "hash": file_hash,
            "mtime": mtime,
            "migration_baseline": True,
        })

    return {
        "summary": {
            "raw_files_checked": len(candidates),
            "entries_to_add": len(entries),
            "skipped_existing": skipped_existing,
            "skipped_protected": skipped_protected,
            "read_errors": len(read_errors),
            "protected_notes": len(protected_notes),
        },
        "entries": entries,
        "protected_notes": protected_notes,
        "read_errors": read_errors,
    }


def backup_log(log_path: Path, backup_dir: Path) -> Path | None:
    """Copy the existing log into backup_dir before appending. No-op if absent."""
    if not log_path.is_file():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / (log_path.name + ".bak")
    shutil.copy2(log_path, backup_path)
    return backup_path


def write_entries(log_path: Path, entries: list[dict]) -> None:
    if not entries:
        return
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Match the canonical ingest log writer: insertion order, no sorted keys,
    # so migration rows are byte-consistent with the rest of log.jsonl.
    try:
        with log_path.open("a", encoding="utf-8") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        raise RuntimeError(f"failed to append to {log_path}: {exc}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Baseline existing raw files in wiki/log.jsonl for migration.",
    )
    parser.add_argument("--root", default=".", help="Vault root to scan.")
    parser.add_argument("--log", default="wiki/log.jsonl", help="Log path, relative to root unless absolute.")
    parser.add_argument("--apply", action="store_true", help="Append baseline entries to the log.")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.root).resolve()
    log_path = Path(args.log)
    if not log_path.is_absolute():
        log_path = root / log_path
    result = build_entries(root, log_path)
    if args.apply:
        backup_log(log_path, root / ".wiki-scratch")
        try:
            write_entries(log_path, result["entries"])
        except RuntimeError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
    result["applied"] = args.apply
    result["log_path"] = _rel(log_path, root) if log_path.is_relative_to(root) else str(log_path)

    if args.format == "json":
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        summary = result["summary"]
        mode = "APPLIED" if args.apply else "DRY-RUN"
        print(f"Migration raw log baseline ({mode})")
        print(f"  raw files checked : {summary['raw_files_checked']}")
        print(f"  entries to add    : {summary['entries_to_add']}")
        print(f"  skipped existing  : {summary['skipped_existing']}")
        print(f"  skipped protected : {summary['skipped_protected']}")
        print(f"  protected notes   : {summary['protected_notes']}")
        print(f"  read errors       : {summary['read_errors']}")
        print(f"  log path          : {result['log_path']}")
    return 1 if result["summary"]["read_errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
