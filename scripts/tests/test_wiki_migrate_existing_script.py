import json
import os
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

    def test_legacy_layout_step_uses_root_not_cwd(self):
        # A converted/ tree under the target vault must be migrated against the
        # vault even when the script is invoked from an unrelated directory.
        (self.root / "raw/clips/converted").mkdir(parents=True)
        (self.root / "raw/clips/converted/Doc.md").write_text(
            "# Doc\n\nA standalone converted note with enough words to migrate.\n",
            encoding="utf-8",
        )
        workdir = Path(tempfile.mkdtemp(prefix="wiki-migrate-cwd-"))
        self.addCleanup(lambda: shutil.rmtree(workdir, ignore_errors=True))

        proc = subprocess.run(
            ["bash", str(SCRIPT), "--root", str(self.root), "--skip-qmd", "--limit", "1", "--apply"],
            text=True,
            capture_output=True,
            timeout=120,
            cwd=str(workdir),
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)
        # The converted/ tree was consumed inside the vault, not the cwd.
        self.assertFalse((self.root / "raw/clips/converted").exists())
        self.assertFalse((workdir / "wiki").exists())
        self.assertFalse((workdir / "raw").exists())

    def test_strict_propagates_step_failure_to_exit_code(self):
        if os.geteuid() == 0:
            self.skipTest("cannot make a file unreadable as root")
        unreadable = self.root / "raw/locked.md"
        unreadable.write_text("# Locked\n", encoding="utf-8")
        os.chmod(unreadable, 0o000)
        self.addCleanup(lambda: os.chmod(unreadable, 0o644))

        lenient = self.run_script("--apply")
        self.assertEqual(lenient.returncode, 0, lenient.stderr)

        strict = self.run_script("--apply", "--strict")
        self.assertNotEqual(strict.returncode, 0)

    def test_root_without_value_fails_cleanly(self):
        proc = subprocess.run(
            ["bash", str(SCRIPT), "--root"],
            text=True,
            capture_output=True,
            timeout=30,
        )

        self.assertEqual(proc.returncode, 2)
        self.assertIn("--root requires", proc.stderr)

    def test_limit_without_value_fails_cleanly(self):
        proc = subprocess.run(
            ["bash", str(SCRIPT), "--limit"],
            text=True,
            capture_output=True,
            timeout=30,
        )

        self.assertEqual(proc.returncode, 2)
        self.assertIn("--limit requires", proc.stderr)


if __name__ == "__main__":
    unittest.main()
