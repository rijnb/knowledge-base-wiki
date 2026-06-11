"""Tests for scripts/lib/links.py: extract_links, is_external, strip_frontmatter."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.links import extract_links, is_external, strip_frontmatter  # noqa: E402


def collect(content, include_images=True, skip_frontmatter=False):
    return list(extract_links(content, include_images, skip_frontmatter))


class IsExternalTests(unittest.TestCase):
    def test_http_https_ftp_mailto_are_external(self):
        for url in ("http://x", "https://x", "ftp://x", "mailto:a@b"):
            self.assertTrue(is_external(url))

    def test_relative_and_wikilink_targets_are_not_external(self):
        for t in ("foo/bar.md", "people/me", "image.png", ""):
            self.assertFalse(is_external(t))


class StripFrontmatterTests(unittest.TestCase):
    def test_no_frontmatter_returns_unchanged_and_zero(self):
        content = "# Title\nbody\n"
        out, end = strip_frontmatter(content)
        self.assertEqual(out, content)
        self.assertEqual(end, 0)

    def test_closed_frontmatter_blanked_and_line_preserved(self):
        content = "---\ntitle: x\n---\nbody on line 4\n"
        out, end = strip_frontmatter(content)
        self.assertEqual(end, 3)
        # Body line number is preserved: "body on line 4" still on line 4.
        self.assertEqual(out.splitlines()[3], "body on line 4")
        # Frontmatter contents are gone.
        self.assertNotIn("title: x", out)

    def test_unclosed_frontmatter_not_stripped(self):
        content = "---\ntitle: x\nstill in fm\n"
        out, end = strip_frontmatter(content)
        self.assertEqual(out, content)
        self.assertEqual(end, 0)

    def test_dots_terminator_recognized(self):
        content = "---\na: 1\n...\nbody\n"
        out, end = strip_frontmatter(content)
        self.assertEqual(end, 3)


class ExtractLinksTests(unittest.TestCase):
    def test_wikilink_extracted_with_type_and_line(self):
        links = collect("see [[foo/bar]] here\n")
        self.assertEqual(len(links), 1)
        lineno, ltype, raw, target = links[0]
        self.assertEqual(lineno, 1)
        self.assertEqual(ltype, "wikilink")
        self.assertEqual(target, "foo/bar")

    def test_wikilink_alias_target_only(self):
        links = collect("[[foo|Display Text]]\n")
        self.assertEqual(links[0][3], "foo")

    def test_image_embed_detected(self):
        links = collect("![[pic.png]]\n")
        self.assertEqual(links[0][1], "image")
        self.assertEqual(links[0][3], "pic.png")

    def test_image_embed_skipped_when_images_off(self):
        self.assertEqual(collect("![[pic.png]]\n", include_images=False), [])

    def test_markdown_link_extracted(self):
        links = collect("[text](path/to/file.md)\n")
        self.assertEqual(links[0][1], "markdown")
        self.assertEqual(links[0][3], "path/to/file.md")

    def test_markdown_image_detected(self):
        links = collect("![alt](img.png)\n")
        self.assertEqual(links[0][1], "image")
        self.assertEqual(links[0][3], "img.png")

    def test_markdown_image_skipped_when_images_off(self):
        self.assertEqual(collect("![alt](img.png)\n", include_images=False), [])

    def test_line_numbers_track_correctly(self):
        content = "line1\n[[a]]\nline3\n[[b]]\n"
        links = collect(content)
        self.assertEqual([(l[0], l[3]) for l in links], [(2, "a"), (4, "b")])

    def test_already_marked_broken_link_skipped(self):
        # [[x|(broken link) x]] should not be re-yielded as a wikilink.
        links = collect("[[x|(broken link) x]]\n")
        self.assertEqual(links, [])

    def test_already_marked_broken_link_backslash_pipe_skipped(self):
        links = collect("[[x\\|(broken link) x]]\n")
        self.assertEqual(links, [])

    def test_skip_frontmatter_excludes_fm_links(self):
        content = "---\nauthor: [[Some Person]]\n---\n[[real-link]]\n"
        links = collect(content, skip_frontmatter=True)
        targets = [l[3] for l in links]
        self.assertIn("real-link", targets)
        self.assertNotIn("Some Person", targets)

    def test_without_skip_frontmatter_fm_links_included(self):
        content = "---\nauthor: [[Some Person]]\n---\n[[real-link]]\n"
        targets = [l[3] for l in collect(content, skip_frontmatter=False)]
        self.assertIn("Some Person", targets)

    def test_embed_wikilink_not_double_counted_as_plain(self):
        # ![[x]] should yield exactly one image link, not also a wikilink.
        links = collect("![[x.png]]\n")
        self.assertEqual(len(links), 1)
        self.assertEqual(links[0][1], "image")


if __name__ == "__main__":
    unittest.main()
