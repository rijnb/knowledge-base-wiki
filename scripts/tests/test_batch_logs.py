"""Tests for scripts/lib/batch_logs.py: merge_batch_logs, clear_ingest_batches."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.batch_logs import (  # noqa: E402
    clear_ingest_batches,
    list_ingest_batch_files,
    merge_batch_logs,
)


class BatchFixtureMixin:
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="batchlogs-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        (self.root / "wiki").mkdir(parents=True, exist_ok=True)
        (self.root / ".import").mkdir(parents=True, exist_ok=True)

    def write(self, rel, content):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return p

    def read(self, rel):
        return (self.root / rel).read_text(encoding="utf-8")

    def log_entries(self):
        text = self.read("wiki/log.jsonl")
        return [json.loads(l) for l in text.splitlines() if l.strip()]

    def entry(self, name):
        return {"date": "2026-01-01 10:00:00", "file": f"raw/notes/{name}.md",
                "session": 1, "summary": name,
                "pages_created": [], "pages_updated": []}


class MergeBatchLogsTests(BatchFixtureMixin, unittest.TestCase):
    def test_no_batch_logs_leaves_log_untouched(self):
        self.write("wiki/log.jsonl", json.dumps(self.entry("a")) + "\n")
        before = self.read("wiki/log.jsonl")
        result = merge_batch_logs(self.root, quiet=True)
        self.assertEqual(result["merged"], 0)
        self.assertEqual(self.read("wiki/log.jsonl"), before)

    def test_merges_valid_entries_from_all_batch_logs(self):
        self.write("wiki/log.jsonl", json.dumps(self.entry("a")) + "\n")
        self.write(".import/batch-log-1.jsonl", json.dumps(self.entry("b")) + "\n")
        self.write(".import/batch-log-2.jsonl", json.dumps(self.entry("c")) + "\n")
        result = merge_batch_logs(self.root, quiet=True)
        self.assertEqual(result["merged"], 2)
        self.assertEqual(result["rejected"], 0)
        self.assertEqual([e["summary"] for e in self.log_entries()], ["a", "b", "c"])

    def test_creates_log_when_absent(self):
        self.write(".import/batch-log-1.jsonl", json.dumps(self.entry("b")) + "\n")
        merge_batch_logs(self.root, quiet=True)
        self.assertEqual([e["summary"] for e in self.log_entries()], ["b"])

    def test_batch_log_without_trailing_newline_does_not_fuse_entries(self):
        # `cat a b >> log` glues a's last line to b's first when a has no final
        # newline, producing one corrupt line and losing two entries.
        self.write(".import/batch-log-1.jsonl", json.dumps(self.entry("b")))  # no \n
        self.write(".import/batch-log-2.jsonl", json.dumps(self.entry("c")) + "\n")
        result = merge_batch_logs(self.root, quiet=True)
        self.assertEqual(result["merged"], 2)
        self.assertEqual([e["summary"] for e in self.log_entries()], ["b", "c"])

    def test_existing_log_without_trailing_newline_is_repaired(self):
        self.write("wiki/log.jsonl", json.dumps(self.entry("a")))  # no \n
        self.write(".import/batch-log-1.jsonl", json.dumps(self.entry("b")) + "\n")
        merge_batch_logs(self.root, quiet=True)
        self.assertEqual([e["summary"] for e in self.log_entries()], ["a", "b"])

    def test_malformed_line_is_quarantined_not_appended(self):
        self.write("wiki/log.jsonl", json.dumps(self.entry("a")) + "\n")
        self.write(".import/batch-log-1.jsonl",
                   json.dumps(self.entry("b")) + "\n{ truncated by a crashed agent\n")
        result = merge_batch_logs(self.root, quiet=True)
        self.assertEqual(result["merged"], 1)
        self.assertEqual(result["rejected"], 1)
        self.assertEqual([e["summary"] for e in self.log_entries()], ["a", "b"])
        quarantine = self.read(".import/batch-log-rejected.jsonl")
        self.assertIn("truncated by a crashed agent", quarantine)
        self.assertIn("batch-log-1.jsonl", quarantine)

    def test_non_object_json_line_is_rejected(self):
        # A bare array or string is valid JSON but not a log entry.
        self.write(".import/batch-log-1.jsonl", '["not", "an", "entry"]\n')
        result = merge_batch_logs(self.root, quiet=True)
        self.assertEqual(result["merged"], 0)
        self.assertEqual(result["rejected"], 1)

    def test_batch_logs_deleted_only_after_successful_merge(self):
        self.write(".import/batch-log-1.jsonl", json.dumps(self.entry("b")) + "\n")
        self.write(".import/batch-import-1.claimed.txt", "raw/notes/b.md\n")
        merge_batch_logs(self.root, quiet=True)
        self.assertFalse((self.root / ".import/batch-log-1.jsonl").exists())
        self.assertFalse((self.root / ".import/batch-import-1.claimed.txt").exists())

    def test_failed_append_keeps_batch_logs_on_disk(self):
        # If the log cannot be written, the batch logs are the only copy of the
        # ingest records — they must survive.
        self.write(".import/batch-log-1.jsonl", json.dumps(self.entry("b")) + "\n")
        (self.root / "wiki").rmdir()  # wiki/ missing -> append must fail
        with self.assertRaises(OSError):
            merge_batch_logs(self.root, quiet=True)
        self.assertTrue((self.root / ".import/batch-log-1.jsonl").exists())

    def test_dry_run_changes_nothing(self):
        self.write("wiki/log.jsonl", json.dumps(self.entry("a")) + "\n")
        before = self.read("wiki/log.jsonl")
        self.write(".import/batch-log-1.jsonl", json.dumps(self.entry("b")) + "\n")
        result = merge_batch_logs(self.root, quiet=True, dry_run=True)
        self.assertEqual(result["merged"], 1)
        self.assertEqual(self.read("wiki/log.jsonl"), before)
        self.assertTrue((self.root / ".import/batch-log-1.jsonl").exists())

    def test_merge_is_ordered_by_batch_number_not_lexically(self):
        for n in (1, 2, 10):
            self.write(f".import/batch-log-{n}.jsonl",
                       json.dumps(self.entry(f"b{n}")) + "\n")
        merge_batch_logs(self.root, quiet=True)
        self.assertEqual([e["summary"] for e in self.log_entries()],
                         ["b1", "b2", "b10"])


class ClearIngestBatchesTests(BatchFixtureMixin, unittest.TestCase):
    def test_listing_does_not_double_count_claimed_files(self):
        # 'batch-import-*.txt' already matches 'batch-import-*.claimed.txt'.
        self.write(".import/batch-import-1.txt", "x\n")
        self.write(".import/batch-import-2.claimed.txt", "x\n")
        self.write(".import/batch-log-1.jsonl", "{}\n")
        files = list_ingest_batch_files(self.root)
        self.assertEqual(len(files), 3)
        self.assertEqual(len(set(files)), 3)

    def test_ignores_unrelated_files_in_import_dir(self):
        self.write(".import/.gitkeep", "")
        self.write(".import/notes.txt", "keep me")
        self.write(".import/batch-import-1.txt", "x\n")
        names = [p.name for p in list_ingest_batch_files(self.root)]
        self.assertEqual(names, ["batch-import-1.txt"])

    def test_reports_unmerged_log_entries_before_deleting(self):
        # Clearing batch-log files throws away ingest records that were never
        # merged into wiki/log.jsonl. The caller must be able to say so.
        self.write(".import/batch-log-1.jsonl",
                   json.dumps(self.entry("b")) + "\n" + json.dumps(self.entry("c")) + "\n")
        result = clear_ingest_batches(self.root, dry_run=True)
        self.assertEqual(result["unmerged_log_entries"], 2)

    def test_dry_run_lists_without_deleting(self):
        self.write(".import/batch-import-1.txt", "x\n")
        result = clear_ingest_batches(self.root, dry_run=True)
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(len(result["files"]), 1)
        self.assertTrue((self.root / ".import/batch-import-1.txt").exists())

    def test_deletes_and_reports_actual_count(self):
        self.write(".import/batch-import-1.txt", "x\n")
        self.write(".import/batch-import-2.claimed.txt", "x\n")
        self.write(".import/batch-log-1.jsonl", "{}\n")
        result = clear_ingest_batches(self.root)
        self.assertEqual(result["deleted"], 3)
        self.assertEqual(result["failed"], [])
        self.assertEqual(list_ingest_batch_files(self.root), [])

    def test_empty_import_dir_is_not_an_error(self):
        result = clear_ingest_batches(self.root)
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(result["files"], [])

    def test_missing_import_dir_is_not_an_error(self):
        shutil.rmtree(self.root / ".import")
        result = clear_ingest_batches(self.root)
        self.assertEqual(result["deleted"], 0)


if __name__ == "__main__":
    unittest.main()
