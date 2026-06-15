"""Tests for scripts/lib/fixers.py: fix_curly_quotes, fix_raw_references, prune_log, stamp_log_hashes."""

import hashlib
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
    relink_renamed_log_entries,
    stamp_log_hashes,
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


class StampLogHashesTests(VaultFixtureMixin, unittest.TestCase):
    def _entry(self, **kw):
        e = {"date": "2026-06-01 12:00:00", "session": 1,
             "summary": "x", "pages_created": [], "pages_updated": []}
        e.update(kw)
        return e

    def _write_log(self, entries):
        self.write(
            "wiki/log.jsonl",
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
        )

    def _entries(self):
        return [json.loads(l) for l in self.read("wiki/log.jsonl").splitlines() if l.strip()]

    def test_stamps_missing_hash_and_mtime(self):
        f = self.write("raw/notes/Note.md", "hello world\n")
        self._write_log([self._entry(file="raw/notes/Note.md")])
        stamped, total = stamp_log_hashes(self.root, quiet=True)
        self.assertEqual((stamped, total), (1, 1))
        entry = self._entries()[0]
        expected = "sha256:" + hashlib.sha256(f.read_bytes()).hexdigest()
        self.assertEqual(entry["hash"], expected)
        self.assertEqual(entry["mtime"], int(f.stat().st_mtime))

    def test_idempotent_second_run_stamps_nothing(self):
        self.write("raw/notes/Note.md", "hello\n")
        self._write_log([self._entry(file="raw/notes/Note.md")])
        stamp_log_hashes(self.root, quiet=True)
        before = self.read("wiki/log.jsonl")
        stamped, total = stamp_log_hashes(self.root, quiet=True)
        self.assertEqual(stamped, 0)
        self.assertEqual(self.read("wiki/log.jsonl"), before)

    def test_skips_entry_whose_file_is_missing(self):
        self._write_log([self._entry(file="raw/notes/Gone.md")])
        stamped, total = stamp_log_hashes(self.root, quiet=True)
        self.assertEqual((stamped, total), (0, 1))
        self.assertNotIn("hash", self._entries()[0])

    def test_does_not_overwrite_existing_hash(self):
        self.write("raw/notes/Note.md", "hello\n")
        self._write_log([self._entry(file="raw/notes/Note.md",
                                     hash="sha256:deadbeef", mtime=123)])
        stamped, total = stamp_log_hashes(self.root, quiet=True)
        self.assertEqual(stamped, 0)
        entry = self._entries()[0]
        self.assertEqual(entry["hash"], "sha256:deadbeef")
        self.assertEqual(entry["mtime"], 123)

    def test_dry_run_does_not_write(self):
        self.write("raw/notes/Note.md", "hello\n")
        self._write_log([self._entry(file="raw/notes/Note.md")])
        before = self.read("wiki/log.jsonl")
        stamped, total = stamp_log_hashes(self.root, quiet=True, dry_run=True)
        self.assertEqual(stamped, 1)
        self.assertEqual(self.read("wiki/log.jsonl"), before)

    def test_returns_zero_when_log_absent(self):
        self.assertEqual(stamp_log_hashes(self.root, quiet=True), (0, 0))

    def test_backfills_every_unstamped_entry(self):
        # Migration path: a pre-hash log with many entries is fully backfilled
        # in a single pass (this is what every user's first post-upgrade finalize
        # does). Entries whose file is gone are left unstamped.
        for name in ("A", "B", "C"):
            self.write(f"raw/notes/{name}.md", f"content {name}\n")
        self._write_log([
            self._entry(file="raw/notes/A.md"),
            self._entry(file="raw/notes/B.md"),
            self._entry(file="raw/notes/C.md"),
            self._entry(file="raw/notes/Gone.md"),  # file does not exist
        ])
        stamped, total = stamp_log_hashes(self.root, quiet=True)
        self.assertEqual((stamped, total), (3, 4))
        entries = self._entries()
        for e in entries:
            if e["file"] == "raw/notes/Gone.md":
                self.assertNotIn("hash", e)
            else:
                self.assertTrue(e["hash"].startswith("sha256:"))
                self.assertIsInstance(e["mtime"], int)


class RelinkRenamedLogEntriesTests(VaultFixtureMixin, unittest.TestCase):
    def _stamped_entry(self, file_rel, content_path):
        p = self.root / content_path
        return {"date": "2026-06-01 12:00:00", "session": 1, "file": file_rel,
                "hash": "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest(),
                "mtime": int(p.stat().st_mtime),
                "summary": "x", "pages_created": [], "pages_updated": []}

    def _write_log(self, entries):
        self.write("wiki/log.jsonl",
                   "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries))

    def _entries(self):
        return [json.loads(l) for l in self.read("wiki/log.jsonl").splitlines() if l.strip()]

    def test_relinks_orphan_to_renamed_file(self):
        # Post-rename state: New.md holds the bytes; the entry still names Old.md.
        new = self.write("raw/notes/New.md", "stable content\n")
        entry = self._stamped_entry("raw/notes/Old.md", "raw/notes/New.md")
        self._write_log([entry])
        relinked, ambiguous = relink_renamed_log_entries(self.root, quiet=True)
        self.assertEqual((relinked, ambiguous), (1, 0))
        e = self._entries()[0]
        self.assertEqual(e["file"], "raw/notes/New.md")
        self.assertEqual(e["mtime"], int(new.stat().st_mtime))

    def test_does_not_relink_when_old_path_still_exists(self):
        # A copy: both files present, same content -> Old.md not an orphan.
        self.write("raw/notes/Old.md", "dup\n")
        self.write("raw/notes/Copy.md", "dup\n")
        self._write_log([self._stamped_entry("raw/notes/Old.md", "raw/notes/Old.md")])
        self.assertEqual(relink_renamed_log_entries(self.root, quiet=True), (0, 0))
        self.assertEqual(self._entries()[0]["file"], "raw/notes/Old.md")

    def test_ambiguous_match_is_skipped(self):
        self.write("raw/notes/A.md", "twins\n")
        self.write("raw/notes/B.md", "twins\n")
        self._write_log([self._stamped_entry("raw/notes/Old.md", "raw/notes/A.md")])
        relinked, ambiguous = relink_renamed_log_entries(self.root, quiet=True)
        self.assertEqual((relinked, ambiguous), (0, 1))
        self.assertEqual(self._entries()[0]["file"], "raw/notes/Old.md")

    def test_orphan_with_no_content_match_left_alone(self):
        self.write("raw/notes/Other.md", "different\n")
        self._write_log([{"date": "2026-06-01 12:00:00", "session": 1,
                          "file": "raw/notes/Gone.md", "hash": "sha256:" + "0" * 64,
                          "mtime": 1, "summary": "x",
                          "pages_created": [], "pages_updated": []}])
        self.assertEqual(relink_renamed_log_entries(self.root, quiet=True), (0, 0))
        self.assertEqual(self._entries()[0]["file"], "raw/notes/Gone.md")

    def test_dry_run_does_not_write(self):
        self.write("raw/notes/New.md", "x\n")
        self._write_log([self._stamped_entry("raw/notes/Old.md", "raw/notes/New.md")])
        before = self.read("wiki/log.jsonl")
        relinked, _ = relink_renamed_log_entries(self.root, quiet=True, dry_run=True)
        self.assertEqual(relinked, 1)
        self.assertEqual(self.read("wiki/log.jsonl"), before)

    def test_returns_zero_when_log_absent(self):
        self.assertEqual(relink_renamed_log_entries(self.root, quiet=True), (0, 0))

    def test_two_orphans_relink_to_distinct_files(self):
        new1 = self.write("raw/notes/New1.md", "content one\n")
        new2 = self.write("raw/notes/New2.md", "content two\n")
        self._write_log([
            self._stamped_entry("raw/notes/Old1.md", "raw/notes/New1.md"),
            self._stamped_entry("raw/notes/Old2.md", "raw/notes/New2.md"),
        ])
        relinked, ambiguous = relink_renamed_log_entries(self.root, quiet=True)
        self.assertEqual((relinked, ambiguous), (2, 0))
        files = sorted(e["file"] for e in self._entries())
        self.assertEqual(files, ["raw/notes/New1.md", "raw/notes/New2.md"])

    def test_entry_without_hash_is_left_untouched(self):
        self.write("raw/notes/New.md", "stable content\n")
        self._write_log([{"date": "2026-06-01 12:00:00", "session": 1,
                          "file": "raw/notes/Old.md", "mtime": 1, "summary": "x",
                          "pages_created": [], "pages_updated": []}])
        self.assertEqual(relink_renamed_log_entries(self.root, quiet=True), (0, 0))
        self.assertEqual(self._entries()[0]["file"], "raw/notes/Old.md")


if __name__ == "__main__":
    unittest.main()
