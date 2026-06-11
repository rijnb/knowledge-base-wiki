"""Tests for scripts/lib/rewrite.py: fix_wikilinks_in_file,
mark_broken_wikilinks_in_file, delete_wikilink_in_file."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.rewrite import (  # noqa: E402
    delete_wikilink_in_file,
    fix_wikilinks_in_file,
    mark_broken_wikilinks_in_file,
)


class FixWikilinksTests(VaultFixtureMixin, unittest.TestCase):
    def test_applies_fix_and_returns_count(self):
        f = self.write("note.md", "see [[old]] and [[old]]\n")
        n = fix_wikilinks_in_file(f, [("old", "new")])
        self.assertEqual(n, 2)
        self.assertEqual(self.read("note.md"), "see [[new]] and [[new]]\n")

    def test_preserves_alias(self):
        f = self.write("note.md", "[[old|Display]]\n")
        fix_wikilinks_in_file(f, [("old", "new")])
        self.assertEqual(self.read("note.md"), "[[new|Display]]\n")

    def test_preserves_anchor(self):
        f = self.write("note.md", "[[old#heading]]\n")
        fix_wikilinks_in_file(f, [("old", "new")])
        self.assertEqual(self.read("note.md"), "[[new#heading]]\n")

    def test_return_targets_reports_substituted_set(self):
        f = self.write("note.md", "[[old]] but [[absent]] is not present\n")
        n, fixed = fix_wikilinks_in_file(
            f, [("old", "new"), ("not-in-file", "x")], return_targets=True
        )
        self.assertEqual(n, 1)
        self.assertEqual(fixed, {"old"})

    def test_return_targets_zero_sub_empty_set(self):
        # Regression for Bug 2: a suggested fix that matches nothing must report
        # an empty fixed-targets set (so the caller does not falsely mark fixed).
        f = self.write("note.md", "no links here\n")
        n, fixed = fix_wikilinks_in_file(f, [("old", "new")], return_targets=True)
        self.assertEqual(n, 0)
        self.assertEqual(fixed, set())

    def test_does_not_touch_embeds_for_plain_fix(self):
        f = self.write("note.md", "![[old]]\n")
        n = fix_wikilinks_in_file(f, [("old", "new")])
        self.assertEqual(n, 0)
        self.assertEqual(self.read("note.md"), "![[old]]\n")

    def test_unicode_decode_error_leaves_file_untouched(self):
        # Regression for Bug 1: invalid UTF-8 must be skipped, not rewritten
        # with replacement chars.
        raw = b"see [[old]]\n\xff\xfe invalid bytes\n"
        f = self.write_bytes("note.md", raw)
        n = fix_wikilinks_in_file(f, [("old", "new")])
        self.assertEqual(n, 0)
        self.assertEqual(f.read_bytes(), raw)  # bytes untouched

    def test_unicode_decode_error_with_return_targets(self):
        raw = b"[[old]]\n\xff\xfe\n"
        f = self.write_bytes("note.md", raw)
        n, fixed = fix_wikilinks_in_file(f, [("old", "new")], return_targets=True)
        self.assertEqual(n, 0)
        self.assertEqual(fixed, set())
        self.assertEqual(f.read_bytes(), raw)


class MarkBrokenWikilinksTests(VaultFixtureMixin, unittest.TestCase):
    def test_plain_link_marked(self):
        f = self.write("note.md", "[[broken]]\n")
        n = mark_broken_wikilinks_in_file(f, ["broken"])
        self.assertEqual(n, 1)
        self.assertEqual(self.read("note.md"), "[[broken|(broken link) broken]]\n")

    def test_aliased_link_keeps_alias_text(self):
        f = self.write("note.md", "[[broken|Visible]]\n")
        mark_broken_wikilinks_in_file(f, ["broken"])
        self.assertEqual(self.read("note.md"), "[[broken|(broken link) Visible]]\n")

    def test_anchor_preserved(self):
        f = self.write("note.md", "[[broken#sec]]\n")
        mark_broken_wikilinks_in_file(f, ["broken"])
        self.assertEqual(self.read("note.md"), "[[broken#sec|(broken link) broken]]\n")

    def test_unicode_decode_error_skips(self):
        raw = b"[[broken]]\n\xff\n"
        f = self.write_bytes("note.md", raw)
        self.assertEqual(mark_broken_wikilinks_in_file(f, ["broken"]), 0)
        self.assertEqual(f.read_bytes(), raw)


class DeleteWikilinkTests(VaultFixtureMixin, unittest.TestCase):
    def test_inline_whitespace_collapsed(self):
        f = self.write("note.md", "before [[gone]] after\n")
        changed, removed = delete_wikilink_in_file(f, "gone")
        self.assertTrue(changed)
        self.assertEqual(removed, [])
        self.assertEqual(self.read("note.md"), "before after\n")

    def test_bare_line_dropped_and_lineno_returned(self):
        f = self.write("note.md", "keep\n[[gone]]\nkeep2\n")
        changed, removed = delete_wikilink_in_file(f, "gone")
        self.assertTrue(changed)
        self.assertEqual(removed, [2])
        self.assertEqual(self.read("note.md"), "keep\nkeep2\n")

    def test_bare_list_marker_line_dropped(self):
        f = self.write("note.md", "- [[gone]]\n")
        changed, removed = delete_wikilink_in_file(f, "gone")
        self.assertTrue(changed)
        self.assertEqual(removed, [1])
        self.assertEqual(self.read("note.md"), "")

    def test_no_match_no_change(self):
        f = self.write("note.md", "nothing here\n")
        changed, removed = delete_wikilink_in_file(f, "gone")
        self.assertFalse(changed)
        self.assertEqual(removed, [])

    def test_unicode_decode_error_skips(self):
        raw = b"[[gone]]\n\xff\n"
        f = self.write_bytes("note.md", raw)
        changed, removed = delete_wikilink_in_file(f, "gone")
        self.assertFalse(changed)
        self.assertEqual(removed, [])
        self.assertEqual(f.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
