#!/usr/bin/env python3
"""Tests for configurable local AI backends used by scripts."""

from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[2]


class AiBackendSettingsTests(unittest.TestCase):
    def make_fixture(self, settings_body: str, *, copy_system_scripts: bool = False) -> Path:
        tmp = Path(tempfile.mkdtemp(prefix="kb-ai-backend-"))
        self.addCleanup(lambda: shutil.rmtree(tmp, ignore_errors=True))
        (tmp / "scripts").mkdir()
        (tmp / "config").mkdir()
        shutil.copy2(ROOT / "scripts/wiki-ingest.sh", tmp / "scripts/wiki-ingest.sh")
        if copy_system_scripts:
            shutil.copytree(ROOT / "scripts/system", tmp / "scripts/system")
        (tmp / "config/settings.md").write_text(settings_body, encoding="utf-8")
        return tmp

    def run_dry(self, fixture: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "scripts/wiki-ingest.sh", "--dry-run", "--max-batches", "0", *args],
            cwd=fixture,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def run_pipeline(self, fixture: Path, *args: str, path: str | None = None) -> subprocess.CompletedProcess[str]:
        env = None
        if path is not None:
            env = dict(os.environ)
            env["PATH"] = path
        return subprocess.run(
            ["bash", "scripts/wiki-ingest.sh", *args],
            cwd=fixture,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            check=False,
        )

    def test_settings_file_documents_default_claude_backend(self):
        settings = (ROOT / "config/settings.md").read_text(encoding="utf-8")

        self.assertTrue(settings.startswith("---\nai_backend: claude\n---"))
        self.assertIn("| `claude` | Anthropic", settings)
        self.assertIn("| `vibe`", settings)
        self.assertIn("| `codex`", settings)

    def test_dry_run_uses_backend_from_settings(self):
        fixture = self.make_fixture(
            textwrap.dedent(
                """\
                ---
                ai_backend: codex
                ---

                # Settings
                """
            )
        )

        result = self.run_dry(fixture)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("LLM backend: codex", result.stdout)

    def test_cli_agent_override_wins_over_settings(self):
        fixture = self.make_fixture(
            textwrap.dedent(
                """\
                ---
                ai_backend: codex
                ---

                # Settings
                """
            )
        )

        result = self.run_dry(fixture, "--agent", "vibe")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("LLM backend: vibe", result.stdout)

    def test_invalid_settings_backend_falls_back_to_claude(self):
        fixture = self.make_fixture(
            textwrap.dedent(
                """\
                ---
                ai_backend: made-up
                ---

                # Settings
                """
            )
        )

        result = self.run_dry(fixture)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("LLM backend: claude", result.stdout)
        self.assertIn("unknown ai_backend", result.stderr)

    def test_missing_backend_cli_leaves_batch_state_intact(self):
        fixture = self.make_fixture(
            textwrap.dedent(
                """\
                ---
                ai_backend: vibe
                ---

                # Settings
                """
            )
        )
        import_dir = fixture / ".import"
        import_dir.mkdir()
        batch_file = import_dir / "batch-import-1.txt"
        batch_file.write_text("raw/notes/example.md\n", encoding="utf-8")

        result = self.run_pipeline(
            fixture,
            path="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/pkg/bin",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(batch_file.exists())
        self.assertIn("requires 'vibe'", result.stderr)
        self.assertIn("Pipeline stopped before all batches were consumed", result.stdout)

    def test_max_files_per_batch_zero_is_rejected(self):
        fixture = self.make_fixture(
            textwrap.dedent(
                """\
                ---
                ai_backend: codex
                ---

                # Settings
                """
            )
        )

        result = self.run_dry(fixture, "--max-files-per-batch", "0")

        self.assertEqual(result.returncode, 1)
        self.assertIn("--max-files-per-batch must be a positive integer", result.stderr)

    def test_raw_filename_sanitizer_preserves_collisions(self):
        fixture = self.make_fixture(
            textwrap.dedent(
                """\
                ---
                ai_backend: vibe
                ---

                # Settings
                """
            ),
            copy_system_scripts=True,
        )
        raw_notes = fixture / "raw/notes"
        raw_notes.mkdir(parents=True)
        (fixture / "wiki").mkdir()
        (raw_notes / "a?.txt").write_text("unsafe\n", encoding="utf-8")
        (raw_notes / "a_.txt").write_text("existing\n", encoding="utf-8")

        result = self.run_pipeline(
            fixture,
            "--max-files-per-batch",
            "1",
            path="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/pkg/bin",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((raw_notes / "a?.txt").exists())
        self.assertEqual((raw_notes / "a_.txt").read_text(encoding="utf-8"), "existing\n")
        self.assertEqual((raw_notes / "a_ 2.txt").read_text(encoding="utf-8"), "unsafe\n")


if __name__ == "__main__":
    unittest.main()
