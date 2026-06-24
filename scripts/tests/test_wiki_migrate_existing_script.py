import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent.parent / "wiki-migrate-existing.sh"


class WikiMigrateExistingScriptTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="wiki-migrate-existing-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))
        (self.root / "raw").mkdir()
        (self.root / "wiki/concepts").mkdir(parents=True)
        (self.root / "raw/note.md").write_text("# Source\n\n2026 note.\n", encoding="utf-8")
        (self.root / "wiki/concepts/Thing.md").write_text(
            "# Thing\n\nA concept with enough words to avoid being a stub page in doctor.\n",
            encoding="utf-8",
        )

    def run_script(self, *args):
        return subprocess.run(
            ["bash", str(SCRIPT), "--root", str(self.root), "--skip-qmd", "--limit", "1", *args],
            text=True,
            capture_output=True,
            timeout=120,
        )

    def test_dry_run_does_not_baseline_log(self):
        proc = self.run_script()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("baseline existing raw files: yes", proc.stdout)
        self.assertFalse((self.root / "wiki/log.jsonl").exists())

    def test_apply_baselines_existing_raw_by_default(self):
        proc = self.run_script("--apply")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        log_lines = (self.root / "wiki/log.jsonl").read_text(encoding="utf-8").splitlines()
        files = {json.loads(line)["file"] for line in log_lines}
        self.assertIn("raw/note.md", files)
        self.assertTrue((self.root / ".wiki-scratch/migration-report.md").is_file())

    def test_allow_reingest_existing_skips_baseline(self):
        proc = self.run_script("--apply", "--allow-reingest-existing")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("future ingest may process the historical raw corpus", proc.stdout)
        self.assertFalse((self.root / "wiki/log.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
