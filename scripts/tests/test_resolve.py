"""Tests for scripts/lib/resolve.py: resolve_wikilink, resolve_mdlink,
normalize_name, find_normalized_match, find_whitespace_before_ext_match."""

import sys
import unicodedata
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.paths import VaultIndex  # noqa: E402
from lib.resolve import (  # noqa: E402
    find_normalized_match,
    find_whitespace_before_ext_match,
    normalize_name,
    resolve_mdlink,
    resolve_wikilink,
)


class NormalizeNameTests(unittest.TestCase):
    def test_colon_underscore_space_equivalence(self):
        self.assertEqual(normalize_name("foo: bar"), normalize_name("foo bar"))
        self.assertEqual(normalize_name("foo_bar"), normalize_name("foo bar"))

    def test_quotes_and_punctuation_collapse(self):
        self.assertEqual(normalize_name("foo's bar?"), normalize_name("foo s bar"))

    def test_non_ascii_collapses(self):
        self.assertEqual(normalize_name("café"), normalize_name("caf"))

    def test_case_insensitive(self):
        self.assertEqual(normalize_name("FooBar"), normalize_name("foobar"))

    def test_hyphen_space_equivalence(self):
        # Slugified link and spaced filename normalize to the same key.
        self.assertEqual(normalize_name("Foo-Bar-Baz"), normalize_name("Foo Bar Baz"))

    def test_genuinely_hyphenated_title_matches_itself(self):
        # A real hyphenated title still normalizes consistently with itself,
        # so correct links to it keep resolving.
        self.assertEqual(
            normalize_name("Cost-Aware Model Routing"),
            normalize_name("Cost-Aware Model Routing"),
        )


class UnicodeNormalizationTests(VaultFixtureMixin, unittest.TestCase):
    """Filenames synced across machines may differ only in Unicode form
    (NFC on APFS vs NFD on HFS+). Link resolution must not depend on it."""

    NFC = unicodedata.normalize("NFC", "Adam Kepi\u0144ski")   # 'ń' precomposed
    NFD = unicodedata.normalize("NFD", "Adam Kepi\u0144ski")   # 'n' + combining acute

    def _index(self):
        v = VaultIndex(self.root)
        return v.stem_index, v.path_suffix_set

    def test_nfc_link_resolves_nfd_filename(self):
        self.write(f"wiki/people/{self.NFD}.md", "x")
        stems, suffixes = self._index()
        self.assertTrue(resolve_wikilink(self.NFC, self.root, stems, suffixes))

    def test_nfd_link_resolves_nfc_filename(self):
        self.write(f"wiki/people/{self.NFC}.md", "x")
        stems, suffixes = self._index()
        self.assertTrue(resolve_wikilink(self.NFD, self.root, stems, suffixes))

    def test_path_suffix_lookup_normalizes(self):
        self.write(f"raw/notes/_resources/{self.NFD}.pdf", "x")
        stems, suffixes = self._index()
        self.assertTrue(
            resolve_wikilink(f"_resources/{self.NFC}.pdf", self.root, stems, suffixes)
        )

    def test_find_normalized_match_across_forms(self):
        self.write(f"wiki/people/{self.NFD}.md", "x")
        v = VaultIndex(self.root)
        fix = find_normalized_match(self.NFC, self.root, v.norm_index)
        self.assertIsNotNone(fix)


class ResolveWikilinkTests(VaultFixtureMixin, unittest.TestCase):
    def _index(self):
        v = VaultIndex(self.root)
        return v.stem_index, v.path_suffix_set

    def test_exact_path_with_extension(self):
        self.write("wiki/concepts/foo.md", "x")
        stems, suffixes = self._index()
        self.assertTrue(resolve_wikilink("wiki/concepts/foo.md", self.root, stems, suffixes))

    def test_path_plus_md_suffix(self):
        self.write("wiki/concepts/foo.md", "x")
        stems, suffixes = self._index()
        self.assertTrue(resolve_wikilink("wiki/concepts/foo", self.root, stems, suffixes))

    def test_under_top_dir(self):
        self.write("wiki/concepts/foo.md", "x")
        stems, suffixes = self._index()
        # [[concepts/foo]] resolves via wiki/ prefix search.
        self.assertTrue(resolve_wikilink("concepts/foo", self.root, stems, suffixes))

    def test_bare_stem_match(self):
        self.write("wiki/people/rijn-buve.md", "x")
        stems, suffixes = self._index()
        self.assertTrue(resolve_wikilink("rijn-buve", self.root, stems, suffixes))

    def test_suffix_path_match(self):
        self.write("raw/notes/_resources/foo/bar.pdf", "x")
        stems, suffixes = self._index()
        self.assertTrue(resolve_wikilink("_resources/foo/bar.pdf", self.root, stems, suffixes))

    def test_unresolvable_returns_false(self):
        self.write("wiki/concepts/foo.md", "x")
        stems, suffixes = self._index()
        self.assertFalse(resolve_wikilink("does-not-exist", self.root, stems, suffixes))

    def test_bare_image_in_root_resources(self):
        # Obsidian resolves [[shot.jpeg]] to a file anywhere in the vault,
        # including _resources/ at the vault root (outside raw/ and wiki/).
        self.write("_resources/shot.jpeg", "x")
        stems, suffixes = self._index()
        self.assertTrue(resolve_wikilink("shot.jpeg", self.root, stems, suffixes))

    def test_bare_unknown_extension_in_root_resources(self):
        # Extensions outside KNOWN_EXTENSIONS (e.g. .py, .csv) must still
        # resolve when the file exists somewhere in the vault.
        self.write("_resources/critical_osv_monthly.py", "x")
        self.write("_resources/linux_kernel_critical_monthly.csv", "x")
        stems, suffixes = self._index()
        self.assertTrue(resolve_wikilink("critical_osv_monthly.py", self.root, stems, suffixes))
        self.assertTrue(resolve_wikilink("linux_kernel_critical_monthly.csv", self.root, stems, suffixes))

    def test_hidden_directories_not_indexed(self):
        # Obsidian does not index dot-directories; neither should we.
        self.write(".obsidian/plugins/asset.jpeg", "x")
        stems, suffixes = self._index()
        self.assertFalse(resolve_wikilink("asset.jpeg", self.root, stems, suffixes))


class ResolveMdlinkTests(VaultFixtureMixin, unittest.TestCase):
    def test_relative_link(self):
        src = self.write("wiki/concepts/page.md", "x")
        self.write("wiki/concepts/sibling.md", "x")
        self.assertTrue(resolve_mdlink("sibling.md", src, self.root, {}))

    def test_root_relative_link(self):
        src = self.write("wiki/concepts/page.md", "x")
        self.write("wiki/other/target.md", "x")
        self.assertTrue(resolve_mdlink("wiki/other/target.md", src, self.root, {}))

    def test_target_plus_md(self):
        src = self.write("wiki/concepts/page.md", "x")
        self.write("wiki/concepts/foo.png.md", "x")
        self.assertTrue(resolve_mdlink("foo.png", src, self.root, {}))

    def test_external_always_true(self):
        src = self.write("wiki/concepts/page.md", "x")
        self.assertTrue(resolve_mdlink("https://example.com", src, self.root, {}))

    def test_missing_returns_false(self):
        src = self.write("wiki/concepts/page.md", "x")
        self.assertFalse(resolve_mdlink("nope.md", src, self.root, {}))


class FindNormalizedMatchTests(VaultFixtureMixin, unittest.TestCase):
    def test_unique_match_returns_stem(self):
        self.write("wiki/concepts/foo_ bar.md", "x")
        v = VaultIndex(self.root)
        fix = find_normalized_match("foo: bar", self.root, v.norm_index)
        self.assertEqual(fix, "foo_ bar")

    def test_ambiguous_match_returns_none(self):
        self.write("wiki/concepts/foo bar.md", "x")
        self.write("wiki/people/foo_bar.md", "x")
        v = VaultIndex(self.root)
        self.assertIsNone(find_normalized_match("foo: bar", self.root, v.norm_index))

    def test_no_match_returns_none(self):
        self.write("wiki/concepts/foo.md", "x")
        v = VaultIndex(self.root)
        self.assertIsNone(find_normalized_match("totally different", self.root, v.norm_index))

    def test_slug_link_resolves_to_spaced_filename(self):
        # A slugified wikilink target maps back to the real spaced note name.
        self.write("wiki/concepts/Note Links Like This.md", "x")
        v = VaultIndex(self.root)
        fix = find_normalized_match("Note-Links-Like-This", self.root, v.norm_index)
        self.assertEqual(fix, "Note Links Like This")


class FindWhitespaceBeforeExtTests(VaultFixtureMixin, unittest.TestCase):
    def test_bare_md_returns_stem(self):
        self.write("wiki/concepts/foo.md", "x")
        v = VaultIndex(self.root)
        fix = find_whitespace_before_ext_match("foo .md", self.root, v.path_suffix_set)
        self.assertEqual(fix, "foo")

    def test_directory_qualified_preserves_dir(self):
        self.write("wiki/concepts/bar.pdf", "x")
        v = VaultIndex(self.root)
        fix = find_whitespace_before_ext_match(
            "wiki/concepts/bar .pdf", self.root, v.path_suffix_set
        )
        self.assertEqual(fix, str(Path("wiki/concepts/bar.pdf")))

    def test_no_trailing_whitespace_returns_none(self):
        self.write("wiki/concepts/foo.md", "x")
        v = VaultIndex(self.root)
        self.assertIsNone(
            find_whitespace_before_ext_match("foo.md", self.root, v.path_suffix_set)
        )


if __name__ == "__main__":
    unittest.main()
