"""Tests for the loose-file check and fixer (scripts/lib/checks/loose.py, scripts/lib/fixers.py)."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.checks.loose import check_loose_files  # noqa: E402
from lib.fixers import _numbered_fallback, _write_companion, fix_loose_files  # noqa: E402


class LooseFixtureMixin:
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="loose-test-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))

    def touch(self, rel: str, content: bytes = b"x") -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return p


class CheckLooseFilesTests(LooseFixtureMixin, unittest.TestCase):
    def test_detects_loose_files_in_all_content_trees(self):
        self.touch("raw/notes/photo.jpg")
        self.touch("wiki/concepts/spec.pdf")
        self.touch("INBOX/dump.txt")
        result = check_loose_files(self.root, quiet=True)
        self.assertEqual(
            result["loose_files"],
            ["INBOX/dump.txt", "raw/notes/photo.jpg", "wiki/concepts/spec.pdf"],
        )
        self.assertEqual(result["summary"]["loose_found"], 3)

    def test_ignores_markdown_and_resources_dirs(self):
        self.touch("raw/notes/note.md")
        self.touch("raw/notes/_resources/photo.jpg")
        self.touch("raw/scans/2020_Daily.resources/scan.png")
        result = check_loose_files(self.root, quiet=True)
        self.assertEqual(result["loose_files"], [])

    def test_ignores_infrastructure_files(self):
        self.touch("wiki/log.jsonl")
        self.touch("wiki/log.jsonl.bak")
        self.touch("raw/emails/.gitkeep")
        self.touch("INBOX/.DS_Store")
        result = check_loose_files(self.root, quiet=True)
        self.assertEqual(result["loose_files"], [])

    def test_ignores_files_outside_content_trees(self):
        self.touch("config/intro.png")
        self.touch("scripts/tool.sh")
        self.touch("docs/diagram.svg")
        result = check_loose_files(self.root, quiet=True)
        self.assertEqual(result["loose_files"], [])

    def test_files_scanned_counts_all_regular_files(self):
        # files_scanned = every regular file walked in the content trees,
        # including .md and excluded infrastructure files.
        self.touch("raw/notes/note.md")
        self.touch("raw/notes/photo.jpg")
        self.touch("wiki/log.jsonl")
        result = check_loose_files(self.root, quiet=True)
        self.assertEqual(result["summary"]["files_scanned"], 3)
        self.assertEqual(result["summary"]["loose_found"], 1)

    def test_includes_pipeline_extensions(self):
        # All file types are included by design — even pending .eml/.vtt inputs.
        self.touch("raw/emails/mail.eml")
        self.touch("raw/transcripts/meeting.vtt")
        result = check_loose_files(self.root, quiet=True)
        self.assertEqual(len(result["loose_files"]), 2)


class NumberedFallbackTests(LooseFixtureMixin, unittest.TestCase):
    def test_returns_first_free_numbered_name(self):
        self.touch("raw/notes/_resources/photo.jpg")
        self.touch("raw/notes/_resources/photo 2.jpg")
        target = self.root / "raw/notes/_resources/photo.jpg"
        self.assertEqual(_numbered_fallback(target).name, "photo 3.jpg")

    def test_exhaustion_raises(self):
        for n in range(2, 100):
            self.touch(f"raw/notes/_resources/photo {n}.jpg")
        target = self.root / "raw/notes/_resources/photo.jpg"
        with self.assertRaises(RuntimeError):
            _numbered_fallback(target)


class WriteCompanionTests(LooseFixtureMixin, unittest.TestCase):
    def test_txt_companion_inlines_text(self):
        moved = self.touch("INBOX/_resources/dump.txt", b"line one\nline two\n")
        companion = _write_companion(moved)
        self.assertEqual(companion, self.root / "INBOX/dump.md")
        content = companion.read_text(encoding="utf-8")
        self.assertIn('source: "_resources/dump.txt"', content)
        self.assertIn("converted: ", content)
        self.assertIn("![[dump.txt]]", content)
        self.assertIn("> [!ocr-extractor]- Extracted text", content)
        self.assertIn("> line one", content)
        self.assertIn("> line two", content)

    def test_image_companion_has_empty_callout(self):
        moved = self.touch("raw/notes/_resources/photo.jpg")
        content = _write_companion(moved).read_text(encoding="utf-8")
        self.assertIn("![[photo.jpg]]", content)
        self.assertIn("> [!ocr-extractor]- Extracted text", content)
        self.assertTrue(content.rstrip().endswith(">"))

    def test_rejects_file_outside_resources_dir(self):
        stray = self.touch("INBOX/dump.txt")
        with self.assertRaises(ValueError):
            _write_companion(stray)


def fake_mover(root: Path, src_rel: str, dest_rel: str):
    """Test stand-in for the Obsidian CLI mover: a plain filesystem move."""
    (root / dest_rel).parent.mkdir(parents=True, exist_ok=True)
    (root / src_rel).rename(root / dest_rel)
    return True, ""


def failing_mover(root: Path, src_rel: str, dest_rel: str):
    return False, "obsidian CLI not found"


def lying_mover(root: Path, src_rel: str, dest_rel: str):
    """Claims success but does not move anything (e.g. Obsidian not running)."""
    return True, ""


class FixLooseFilesTests(LooseFixtureMixin, unittest.TestCase):
    def test_moves_and_writes_companion(self):
        self.touch("INBOX/photo.jpg")
        result = fix_loose_files(["INBOX/photo.jpg"], self.root, quiet=True, mover=fake_mover)
        self.assertEqual(result["moved"], 1)
        self.assertEqual(result["converted"], 1)
        self.assertEqual(result["skipped"], 0)
        self.assertTrue((self.root / "INBOX/_resources/photo.jpg").is_file())
        self.assertTrue((self.root / "INBOX/photo.md").is_file())

    def test_clash_gets_numbered_name(self):
        self.touch("INBOX/photo.jpg")
        self.touch("INBOX/_resources/photo.jpg")
        result = fix_loose_files(["INBOX/photo.jpg"], self.root, quiet=True, mover=fake_mover)
        self.assertEqual(result["moved"], 1)
        self.assertTrue((self.root / "INBOX/_resources/photo 2.jpg").is_file())
        self.assertTrue((self.root / "INBOX/photo 2.md").is_file())

    def test_existing_companion_not_overwritten(self):
        self.touch("INBOX/photo.jpg")
        (self.root / "INBOX/photo.md").write_text("existing companion\n", encoding="utf-8")
        result = fix_loose_files(["INBOX/photo.jpg"], self.root, quiet=True, mover=fake_mover)
        self.assertEqual(result["moved"], 1)
        self.assertEqual(result["converted"], 0)
        self.assertEqual(
            (self.root / "INBOX/photo.md").read_text(encoding="utf-8"),
            "existing companion\n",
        )

    def test_mover_failure_skips_file(self):
        self.touch("INBOX/photo.jpg")
        result = fix_loose_files(["INBOX/photo.jpg"], self.root, quiet=True, mover=failing_mover)
        self.assertEqual(result["moved"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertTrue((self.root / "INBOX/photo.jpg").is_file())  # untouched
        self.assertEqual(result["details"][0]["reason"], "obsidian CLI not found")

    def test_unconfirmed_move_counts_as_skipped(self):
        self.touch("INBOX/photo.jpg")
        result = fix_loose_files(["INBOX/photo.jpg"], self.root, quiet=True, mover=lying_mover,
                                 verify_timeout=0.1)
        self.assertEqual(result["moved"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertIn("not confirmed on disk", result["details"][0]["reason"])

    def test_converter_extensions_invoke_converter(self):
        calls = []

        def recording_runner(cmd, **kwargs):
            calls.append(cmd)
            class P:
                returncode = 0
                stderr = ""
            return P()

        self.touch("raw/emails/mail.eml")
        result = fix_loose_files(
            ["raw/emails/mail.eml"], self.root, quiet=True,
            mover=fake_mover, runner=recording_runner,
        )
        self.assertEqual(result["moved"], 1)
        self.assertEqual(result["converted"], 1)
        self.assertEqual(len(calls), 1)
        self.assertIn("convert-eml-to-md.py", calls[0][1])
        self.assertIn("--no-rename", calls[0])
        self.assertTrue(calls[0][-1].endswith("raw/emails/_resources/mail.eml"))

    def test_companion_write_failure_recorded_not_raised(self):
        from unittest import mock
        self.touch("INBOX/photo.jpg")
        self.touch("INBOX/other.png")
        with mock.patch("lib.fixers._write_companion", side_effect=OSError("disk full")):
            result = fix_loose_files(
                ["INBOX/photo.jpg", "INBOX/other.png"], self.root,
                quiet=True, mover=fake_mover,
            )
        self.assertEqual(result["moved"], 2)  # both moves still happen
        self.assertEqual(result["converted"], 0)
        self.assertEqual(result["details"][0]["conversion_error"], "disk full")
        self.assertEqual(result["details"][1]["conversion_error"], "disk full")

    def test_obsidian_unavailable_warns_and_skips_all(self):
        from unittest import mock
        self.touch("INBOX/photo.jpg")
        self.touch("INBOX/dump.txt")
        with mock.patch("lib.fixers._find_obsidian_cli", return_value="/fake/obsidian"), \
             mock.patch("lib.fixers._ensure_obsidian_running", return_value=False):
            result = fix_loose_files(
                ["INBOX/photo.jpg", "INBOX/dump.txt"], self.root, quiet=True,
            )
        self.assertEqual(result["moved"], 0)
        self.assertEqual(result["skipped"], 2)
        self.assertIn("could not be started", result["warning"])
        self.assertEqual(result["details"][0]["reason"], "Obsidian unavailable")
        self.assertTrue((self.root / "INBOX/photo.jpg").is_file())  # untouched

    def test_missing_cli_warns_and_skips_all(self):
        from unittest import mock
        self.touch("INBOX/photo.jpg")
        with mock.patch("lib.fixers._find_obsidian_cli", return_value=None):
            result = fix_loose_files(["INBOX/photo.jpg"], self.root, quiet=True)
        self.assertEqual(result["skipped"], 1)
        self.assertIn("could not be started", result["warning"])

    def test_obsidian_available_proceeds_normally(self):
        from unittest import mock
        self.touch("INBOX/photo.jpg")
        with mock.patch("lib.fixers._find_obsidian_cli", return_value="/fake/obsidian"), \
             mock.patch("lib.fixers._ensure_obsidian_running", return_value=True), \
             mock.patch("lib.fixers._obsidian_mover", side_effect=fake_mover):
            result = fix_loose_files(["INBOX/photo.jpg"], self.root, quiet=True)
        self.assertEqual(result["moved"], 1)
        self.assertIsNone(result["warning"])


class DoctorIntegrationTests(LooseFixtureMixin, unittest.TestCase):
    """Run the real CLI in detection mode (no --fix-simple-errors → no moves, no Obsidian)."""

    def run_doctor(self, *extra):
        script = Path(__file__).resolve().parent.parent / "wiki-doctor.py"
        return subprocess.run(
            [sys.executable, str(script), "--batch-mode", "--quiet",
             "--format", "json", *extra, str(self.root)],
            capture_output=True, text=True, timeout=120,
        )

    def test_batch_mode_reports_loose_files(self):
        self.touch("INBOX/photo.jpg")
        proc = self.run_doctor()
        self.assertEqual(proc.returncode, 1, proc.stderr)  # issues found
        result = json.loads(proc.stdout)
        self.assertEqual(result["loose_files"], ["INBOX/photo.jpg"])
        self.assertEqual(result["loose_summary"]["loose_found"], 1)
        self.assertEqual(result["summary"]["loose_pending"], 1)

    def test_batch_mode_clean_vault_exits_zero(self):
        self.touch("raw/notes/_resources/photo.jpg")
        (self.root / "wiki").mkdir(exist_ok=True)
        proc = self.run_doctor()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        result = json.loads(proc.stdout)
        self.assertEqual(result["loose_files"], [])


if __name__ == "__main__":
    unittest.main()
