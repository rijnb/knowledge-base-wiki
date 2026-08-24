"""Merging and clearing the per-batch ingest files in .import/.

A parallel bulk import gives every batch session its own `.import/batch-log-N.jsonl`
to append to, so the sessions never contend for `wiki/log.jsonl`. Finalization
folds those files back into the main log; aborting an import throws them away.

Both operations used to be inline shell (`cat "${logs[@]}" >> wiki/log.jsonl`).
That could not tell a valid entry from a half-written one, fused entries across
a batch log with no trailing newline, and deleted the batch logs whether or not
the append had actually succeeded. This module does the same work with the log
treated as the durable artefact it is.
"""

import json
import os
import re
import shutil
import sys
from pathlib import Path

# 'batch-import-*.txt' deliberately also matches 'batch-import-N.claimed.txt' —
# listing both patterns separately double-counts every claimed batch.
BATCH_IMPORT_GLOB = "batch-import-*.txt"
BATCH_LOG_GLOB = "batch-log-*.jsonl"

# Written by merge_batch_logs() and skipped when listing batch logs, so a
# rejected line is never re-read as input on the next merge.
REJECTED_NAME = "batch-log-rejected.jsonl"

_TRAILING_NUMBER_RE = re.compile(r"(\d+)")


def _batch_sort_key(path: Path) -> tuple:
    """Sort batch files numerically: batch-log-2 before batch-log-10."""
    numbers = [int(n) for n in _TRAILING_NUMBER_RE.findall(path.stem)]
    return (numbers, path.name)


def _batch_log_paths(import_dir: Path) -> list[Path]:
    return sorted(
        (p for p in import_dir.glob(BATCH_LOG_GLOB) if p.name != REJECTED_NAME),
        key=_batch_sort_key,
    )


def list_ingest_batch_files(root: Path) -> list[Path]:
    """Every batch-import / batch-log file under .import/, deduplicated and sorted.

    The two globs overlap (claimed batches match both), so the result is passed
    through a set before sorting — otherwise callers report more files than
    exist on disk.
    """
    import_dir = root / ".import"
    if not import_dir.is_dir():
        return []
    found = set(import_dir.glob(BATCH_IMPORT_GLOB)) | set(_batch_log_paths(import_dir))
    return sorted(found, key=_batch_sort_key)


def _read_batch_log(path: Path) -> tuple[list[dict], list[tuple[str, int, str]]]:
    """Split one batch log into (valid entries, rejected (file, lineno, raw))."""
    valid: list[dict] = []
    rejected: list[tuple[str, int, str]] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            rejected.append((path.name, lineno, raw))
            continue
        # A bare array, number or string parses cleanly but is not a log entry;
        # letting one through would break every reader of wiki/log.jsonl.
        if not isinstance(entry, dict):
            rejected.append((path.name, lineno, raw))
            continue
        valid.append(entry)
    return valid, rejected


def merge_batch_logs(root: Path, quiet: bool = False, dry_run: bool = False) -> dict:
    """Fold every .import/batch-log-*.jsonl into wiki/log.jsonl, validating each line.

    Every line is parsed before anything is written. Valid entries are re-encoded
    (which normalizes newline termination, so a batch log missing its final
    newline can no longer fuse two entries into one corrupt line) and appended in
    batch order. Lines that are not a JSON object are quarantined in
    `.import/batch-log-rejected.jsonl` with their origin, never silently dropped
    and never appended to the main log.

    The new log is written to a temp file and moved into place, and the batch
    files are deleted only once that has succeeded. If the write fails the batch
    logs stay on disk — they are the only copy of those ingest records.

    Returns a dict with 'files', 'merged', 'rejected', 'deleted' and
    'rejected_path'. With dry_run=True nothing is written or deleted.
    """
    import_dir = root / ".import"
    log_path = root / "wiki" / "log.jsonl"

    logs = _batch_log_paths(import_dir) if import_dir.is_dir() else []
    imports = sorted(import_dir.glob(BATCH_IMPORT_GLOB),
                     key=_batch_sort_key) if import_dir.is_dir() else []

    merged: list[dict] = []
    rejected: list[tuple[str, int, str]] = []
    for path in logs:
        valid, bad = _read_batch_log(path)
        merged.extend(valid)
        rejected.extend(bad)

    result = {
        "files": [p.name for p in logs],
        "merged": len(merged),
        "rejected": len(rejected),
        "deleted": 0,
        "rejected_path": str((import_dir / REJECTED_NAME).relative_to(root)),
    }

    if dry_run or not logs:
        if not quiet and not logs:
            print("No batch logs to merge.")
        return result

    existing = ""
    if log_path.exists():
        existing = log_path.read_text(encoding="utf-8")
        # A log that does not end in a newline would otherwise absorb the first
        # merged entry into its final line.
        if existing and not existing.endswith("\n"):
            existing += "\n"

    # Full rewrite through a temp file in the same directory: a crash mid-write
    # can never leave wiki/log.jsonl truncated or half-appended.
    tmp_path = log_path.with_name(log_path.name + ".merge.tmp")
    with tmp_path.open("w", encoding="utf-8") as dst:
        dst.write(existing)
        for entry in merged:
            dst.write(json.dumps(entry, ensure_ascii=False) + "\n")
    if log_path.exists():
        shutil.copy2(log_path, log_path.with_suffix(log_path.suffix + ".bak"))
    os.replace(tmp_path, log_path)

    # Past the point of no return for the log; only now discard the inputs.
    if rejected:
        with (import_dir / REJECTED_NAME).open("a", encoding="utf-8") as dst:
            for name, lineno, raw in rejected:
                dst.write(json.dumps(
                    {"source": name, "line": lineno, "raw": raw},
                    ensure_ascii=False) + "\n")

    for path in logs + imports:
        try:
            path.unlink()
            result["deleted"] += 1
        except FileNotFoundError:
            pass

    if not quiet:
        print(f"Merged {len(merged)} entr{'y' if len(merged) == 1 else 'ies'} "
              f"from {len(logs)} batch log(s) into wiki/log.jsonl.")
        if rejected:
            print(f"  WARNING: {len(rejected)} malformed line(s) quarantined in "
                  f"{result['rejected_path']} — review before discarding.",
                  file=sys.stderr)
    return result


def clear_ingest_batches(root: Path, dry_run: bool = False) -> dict:
    """Delete the batch-import / batch-log files under .import/.

    Counts what was actually removed rather than what was matched, and reports
    how many ingest records would be destroyed: any entry still sitting in a
    batch log has not reached wiki/log.jsonl, so clearing loses it.

    Returns a dict with 'files' (vault-relative names), 'unmerged_log_entries',
    'deleted' and 'failed'.
    """
    files = list_ingest_batch_files(root)

    unmerged = 0
    for path in files:
        if path.suffix == ".jsonl":
            valid, _ = _read_batch_log(path)
            unmerged += len(valid)

    result = {
        "files": [str(p.relative_to(root)) for p in files],
        "unmerged_log_entries": unmerged,
        "deleted": 0,
        "failed": [],
    }
    if dry_run:
        return result

    for path in files:
        try:
            path.unlink()
            result["deleted"] += 1
        except OSError as e:
            result["failed"].append(f"{path.relative_to(root)}: {e}")
    return result
