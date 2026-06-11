"""Tests for scripts/lib/fixers.py: fix_curly_quotes, fix_raw_references, prune_log."""

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.fixers import (  # noqa: E402
    _write_companion,
    fix_curly_quotes,
    fix_raw_references,
    prune_log,
)


class FixCurlyQuotesTests(VaultFixtureMixin, unittest.TestCase):
    def test_renames_file_with_curly_stem(self):
        self.write("wiki/concepts/foo’s note.md", "body\n")
        renamed, link_files, links = fix_curly_quotes(self.root, quiet=True)
        self.assertEqual(renamed, 1)
        self.assertTrue((self.root / "wiki/concepts/foo's note.md").exists())
        self.assertFalse((self.root / "wiki/concepts/foo’s note.md").exists())

    def test_fixes_curly_in_link_target(self):
        self.write("wiki/concepts/page.md", "see [[foo’s note]] here\n")
        renamed, link_files, links = fix_curly_quotes(self.root, quiet=True)
        self.assertEqual(links, 1)
        self.assertIn("[[foo's note]]", self.read("wiki/concepts/page.md"))

    def test_rename_oserror_skips_and_continues(self):
        # Regression for Bug 8: a locked file must not abort the whole pass.
        self.write("wiki/concepts/a’x.md", "x")
        self.write("wiki/concepts/b’y.md", "x")
        real_rename = Path.rename
        calls = {"n": 0}

        def flaky_rename(self_path, target):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("locked by OneDrive")
            return real_rename(self_path, target)

        with mock.patch.object(Path, "rename", flaky_rename):
            renamed, _, _ = fix_curly_quotes(self.root, quiet=True)
        # First rename failed, second still succeeded.
        self.assertEqual(renamed, 1)

    def test_invalid_utf8_file_skipped(self):
        # Regression for Bug 1: invalid UTF-8 content must be skipped, not mangled.
        raw = b"see [[foo\xe2\x80\x99s note]]\n\xff\xfe\n"
        f = self.write_bytes("wiki/concepts/page.md", raw)
        fix_curly_quotes(self.root, quiet=True)
        self.assertEqual(f.read_bytes(), raw)


class FixRawReferencesTests(VaultFixtureMixin, unittest.TestCase):
    def test_backticked_raw_wrapped(self):
        self.write("wiki/concepts/page.md", "ref `raw/notes/x.md` here\n")
        files, changes = fix_raw_references(self.root, quiet=True)
        self.assertEqual(changes, 1)
        self.assertIn("[[raw/notes/x.md]]", self.read("wiki/concepts/page.md"))

    def test_bullet_bare_raw_wrapped(self):
        self.write("wiki/concepts/page.md", "- raw/notes/x.md trailing note\n")
        files, changes = fix_raw_references(self.root, quiet=True)
        self.assertEqual(changes, 1)
        body = self.read("wiki/concepts/page.md")
        self.assertIn("[[raw/notes/x.md]]", body)
        self.assertIn("trailing note", body)

    def test_source_bare_raw_wrapped(self):
        self.write("wiki/concepts/page.md", "Source: raw/notes/x.md\n")
        files, changes = fix_raw_references(self.root, quiet=True)
        self.assertEqual(changes, 1)
        self.assertIn("[[raw/notes/x.md]]", self.read("wiki/concepts/page.md"))

    def test_not_modified_inside_code_fence(self):
        content = "```\nraw/notes/x.md\n`raw/notes/y.md`\n```\n"
        self.write("wiki/concepts/page.md", content)
        files, changes = fix_raw_references(self.root, quiet=True)
        self.assertEqual(changes, 0)
        self.assertEqual(self.read("wiki/concepts/page.md"), content)

    def test_mixed_tilde_inside_backtick_fence_not_toggled(self):
        # Regression for Bug 6: a ~~~ line inside a ``` block must NOT close it,
        # so the backticked raw ref inside stays untouched.
        content = (
            "```\n"
            "~~~\n"
            "`raw/notes/x.md`\n"
            "```\n"
            "`raw/notes/y.md`\n"  # this one is OUTSIDE the fence -> should be wrapped
        )
        self.write("wiki/concepts/page.md", content)
        files, changes = fix_raw_references(self.root, quiet=True)
        out = self.read("wiki/concepts/page.md")
        # Inside the fence: untouched.
        self.assertIn("`raw/notes/x.md`", out)
        self.assertNotIn("[[raw/notes/x.md]]", out)
        # Outside the fence: wrapped.
        self.assertIn("[[raw/notes/y.md]]", out)
        self.assertEqual(changes, 1)

    def test_dry_run_counts_without_writing(self):
        content = "ref `raw/notes/x.md`\n"
        self.write("wiki/concepts/page.md", content)
        files, changes = fix_raw_references(self.root, quiet=True, dry_run=True)
        self.assertEqual(changes, 1)
        self.assertEqual(self.read("wiki/concepts/page.md"), content)  # unchanged

    def test_only_wiki_files_modified(self):
        self.write("raw/notes/page.md", "ref `raw/notes/x.md`\n")
        files, changes = fix_raw_references(self.root, quiet=True)
        self.assertEqual(changes, 0)


class WriteCompanionTimestampTests(VaultFixtureMixin, unittest.TestCase):
    def test_converted_timestamp_is_utc(self):
        # Regression for Bug 7: companions must stamp UTC, matching the converters.
        moved = self.write("wiki/concepts/_resources/note.txt", "hello")
        before = datetime.now(timezone.utc)
        companion = _write_companion(moved)
        after = datetime.now(timezone.utc)
        content = companion.read_text(encoding="utf-8")
        line = next(l for l in content.splitlines() if l.startswith("converted:"))
        stamp = line.split("converted:", 1)[1].strip()
        parsed = datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        # The stamp must fall within the UTC window around the call (allow the
        # whole-second truncation to round down).
        self.assertGreaterEqual(parsed, before.replace(microsecond=0))
        self.assertLessEqual(parsed, after)


class PruneLogTests(VaultFixtureMixin, unittest.TestCase):
    def _write_log(self, lines):
        log = self.root / "wiki" / "log.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return log

    def test_missing_file_path_returns_zeros(self):
        self.assertEqual(prune_log(self.root, quiet=True), (0, 0, 0, 0))

    def test_drops_missing_file_entries(self):
        self.write("wiki/concepts/exists.md", "x")
        self._write_log([
            json.dumps({"file": "wiki/concepts/exists.md", "date": "2026-01-01"}),
            json.dumps({"file": "wiki/concepts/gone.md", "date": "2026-01-02"}),
        ])
        kept, dropped, malformed, dupes = prune_log(self.root, quiet=True)
        self.assertEqual(kept, 1)
        self.assertEqual(dropped, 1)

    def test_collapses_duplicates_keeping_latest_merged_pages(self):
        self.write("wiki/concepts/exists.md", "x")
        self._write_log([
            json.dumps({"file": "wiki/concepts/exists.md", "date": "2026-01-01",
                        "pages_created": ["a"]}),
            json.dumps({"file": "wiki/concepts/exists.md", "date": "2026-02-01",
                        "pages_created": ["b"]}),
        ])
        kept, dropped, malformed, dupes = prune_log(self.root, quiet=True)
        self.assertEqual(kept, 1)
        self.assertEqual(dupes, 1)
        result_lines = (self.root / "wiki/log.jsonl").read_text().splitlines()
        entry = json.loads(result_lines[0])
        self.assertEqual(entry["date"], "2026-02-01")  # latest kept
        self.assertEqual(entry["pages_created"], ["a", "b"])  # merged

    def test_malformed_lines_counted(self):
        self.write("wiki/concepts/exists.md", "x")
        self._write_log([
            json.dumps({"file": "wiki/concepts/exists.md", "date": "2026-01-01"}),
            "{not valid json",
        ])
        kept, dropped, malformed, dupes = prune_log(self.root, quiet=True)
        self.assertEqual(malformed, 1)
        self.assertEqual(kept, 1)

    def test_backup_created_and_result_valid(self):
        self.write("wiki/concepts/exists.md", "x")
        self._write_log([
            json.dumps({"file": "wiki/concepts/exists.md", "date": "2026-01-01"}),
            json.dumps({"file": "wiki/concepts/gone.md", "date": "2026-01-02"}),
        ])
        prune_log(self.root, quiet=True)
        bak = self.root / "wiki/log.jsonl.bak"
        self.assertTrue(bak.exists())
        # Result file is complete and every line is valid JSON (atomicity: Bug 5).
        result = (self.root / "wiki/log.jsonl").read_text().splitlines()
        for line in result:
            json.loads(line)  # raises if truncated/corrupt
        # No leftover temp file.
        self.assertFalse((self.root / "wiki/log.jsonl.tmp").exists())

    def test_dry_run_does_not_write_or_backup(self):
        self.write("wiki/concepts/exists.md", "x")
        log = self._write_log([
            json.dumps({"file": "wiki/concepts/gone.md", "date": "2026-01-02"}),
        ])
        original = log.read_text()
        prune_log(self.root, quiet=True, dry_run=True)
        self.assertEqual(log.read_text(), original)
        self.assertFalse((self.root / "wiki/log.jsonl.bak").exists())


if __name__ == "__main__":
    unittest.main()
