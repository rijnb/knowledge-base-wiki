"""Tests for scripts/lib/checks/duplicates.py: check_accent_duplicates."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.checks.duplicates import check_accent_duplicates  # noqa: E402


class AccentDuplicateTests(VaultFixtureMixin, unittest.TestCase):
    def test_detects_ascii_and_accented_pair(self):
        self.write("wiki/people/Adam Kepinski.md", "a")
        self.write("wiki/people/Adam Kepiński.md", "b")
        result = check_accent_duplicates(self.root, quiet=True)
        self.assertEqual(result["summary"]["accent_duplicates_found"], 1)
        [dup] = result["accent_duplicates"]
        self.assertEqual(dup["keep"], "wiki/people/Adam Kepinski.md")
        self.assertEqual(dup["duplicates"], ["wiki/people/Adam Kepiński.md"])

    def test_accented_pair_without_ascii_canonical(self):
        # Two accented variants, no ASCII file: still a duplicate group,
        # but no canonical to keep.
        self.write("wiki/people/Frédéric Depuydt.md", "a")
        self.write("wiki/people/Fréderic Depuydt.md", "b")
        result = check_accent_duplicates(self.root, quiet=True)
        self.assertEqual(result["summary"]["accent_duplicates_found"], 1)
        [dup] = result["accent_duplicates"]
        self.assertIsNone(dup["keep"])
        self.assertEqual(len(dup["duplicates"]), 2)

    def test_no_false_positive_on_distinct_names(self):
        self.write("wiki/people/Rene Beer.md", "a")
        self.write("wiki/people/Rene Bier.md", "b")
        result = check_accent_duplicates(self.root, quiet=True)
        self.assertEqual(result["summary"]["accent_duplicates_found"], 0)

    def test_different_directories_not_paired(self):
        self.write("wiki/people/Rene Beer.md", "a")
        self.write("wiki/concepts/René Beer.md", "b")
        result = check_accent_duplicates(self.root, quiet=True)
        self.assertEqual(result["summary"]["accent_duplicates_found"], 0)

    def test_single_accented_file_not_a_duplicate(self):
        self.write("wiki/competition/Škoda.md", "a")
        result = check_accent_duplicates(self.root, quiet=True)
        self.assertEqual(result["summary"]["accent_duplicates_found"], 0)


if __name__ == "__main__":
    unittest.main()
