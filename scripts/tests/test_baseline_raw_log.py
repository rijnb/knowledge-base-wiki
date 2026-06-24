import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent.parent / "system" / "wiki-baseline-raw-log.py"


class BaselineRawLogTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="wiki-baseline-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        (self.root / "raw").mkdir()
        (self.root / "wiki").mkdir()

    def write(self, rel, content):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def run_script(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), "--format", "json", *args],
            text=True,
            capture_output=True,
            timeout=120,
        )

    def test_dry_run_does_not_write_log(self):
        self.write("raw/note.md", "# Note\n")
        proc = self.run_script()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["summary"]["entries_to_add"], 1)
        self.assertFalse((self.root / "wiki/log.jsonl").exists())

    def test_apply_baselines_existing_raw_and_is_idempotent(self):
        self.write("raw/note.md", "# Note\n")
        proc = self.run_script("--apply")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        log_lines = (self.root / "wiki/log.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(log_lines), 1)
        entry = json.loads(log_lines[0])
        self.assertEqual(entry["file"], "raw/note.md")
        self.assertTrue(entry["migration_baseline"])
        self.assertTrue(entry["hash"].startswith("sha256:"))

        proc = self.run_script("--apply")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        log_lines = (self.root / "wiki/log.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(log_lines), 1)

    def test_baseline_entries_use_insertion_order_not_sorted_keys(self):
        self.write("raw/note.md", "# Note\n")
        proc = self.run_script("--apply")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        line = (self.root / "wiki/log.jsonl").read_text(encoding="utf-8").splitlines()[0]
        # Canonical log writer emits insertion order (date, session, file, ...),
        # not alphabetical; "session" must appear before "file".
        self.assertLess(line.index('"session"'), line.index('"file"'))

    def test_existing_log_is_backed_up_before_apply(self):
        original = '{"date": "2026-01-01 00:00:00", "session": 1, "file": "raw/old.md"}\n'
        self.write("wiki/log.jsonl", original)
        self.write("raw/note.md", "# Note\n")

        proc = self.run_script("--apply")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        backup = self.root / ".wiki-scratch/log.jsonl.bak"
        self.assertTrue(backup.is_file())
        self.assertEqual(backup.read_text(encoding="utf-8"), original)

    def test_ingest_false_note_and_linked_file_are_not_logged(self):
        self.write(
            "raw/private.md",
            "---\ningest: false\n---\n\n![[secret.pdf]]\n",
        )
        self.write("raw/secret.pdf", "not really a pdf")
        self.write("raw/public.md", "# Public\n")

        proc = self.run_script("--apply")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        log_lines = (self.root / "wiki/log.jsonl").read_text(encoding="utf-8").splitlines()
        files = {json.loads(line)["file"] for line in log_lines}
        self.assertEqual(files, {"raw/public.md"})


if __name__ == "__main__":
    unittest.main()
