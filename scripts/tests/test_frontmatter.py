"""Tests for scripts/lib/frontmatter.py: has_key / add_key / remove_key and wrappers."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.frontmatter import (  # noqa: E402
    add_key,
    has_key,
    has_orphan_false_in_frontmatter,
    has_stub_in_frontmatter,
    remove_key,
)


class HasKeyTests(unittest.TestCase):
    def test_present(self):
        self.assertTrue(has_key("---\nstub: true\n---\nbody\n", "stub", "true"))

    def test_absent(self):
        self.assertFalse(has_key("---\ntitle: x\n---\n", "stub", "true"))

    def test_no_frontmatter_false(self):
        self.assertFalse(has_key("just body\n", "stub", "true"))

    def test_stops_at_fence(self):
        # 'stub: true' appears in the body, not frontmatter — must not match.
        self.assertFalse(has_key("---\ntitle: x\n---\nstub: true\n", "stub", "true"))

    def test_wrappers(self):
        self.assertTrue(has_orphan_false_in_frontmatter("---\norphan: false\n---\n"))
        self.assertTrue(has_stub_in_frontmatter("---\nstub: true\n---\n"))


class AddKeyTests(VaultFixtureMixin, unittest.TestCase):
    def test_add_to_existing_frontmatter(self):
        f = self.write("p.md", "---\ntitle: x\n---\nbody\n")
        self.assertTrue(add_key(f, "stub", "true"))
        self.assertTrue(has_key(self.read("p.md"), "stub", "true"))

    def test_add_when_no_frontmatter_creates_block(self):
        f = self.write("p.md", "body only\n")
        self.assertTrue(add_key(f, "orphan", "false"))
        content = self.read("p.md")
        self.assertTrue(content.startswith("---\norphan: false\n---\n"))
        self.assertIn("body only", content)

    def test_idempotent(self):
        f = self.write("p.md", "---\nstub: true\n---\n")
        self.assertFalse(add_key(f, "stub", "true"))

    def test_unclosed_frontmatter_returns_false(self):
        f = self.write("p.md", "---\ntitle: x\nno close\n")
        self.assertFalse(add_key(f, "stub", "true"))


class RemoveKeyTests(VaultFixtureMixin, unittest.TestCase):
    def test_remove_present_key(self):
        f = self.write("p.md", "---\ntitle: x\nstub: true\n---\nbody\n")
        self.assertTrue(remove_key(f, "stub", "true"))
        self.assertFalse(has_key(self.read("p.md"), "stub", "true"))
        self.assertIn("title: x", self.read("p.md"))

    def test_remove_absent_key_no_change(self):
        f = self.write("p.md", "---\ntitle: x\n---\n")
        self.assertFalse(remove_key(f, "stub", "true"))

    def test_no_frontmatter_returns_false(self):
        f = self.write("p.md", "body\n")
        self.assertFalse(remove_key(f, "stub", "true"))

    def test_roundtrip_add_then_remove(self):
        f = self.write("p.md", "---\ntitle: x\n---\nbody\n")
        add_key(f, "orphan", "false")
        self.assertTrue(has_key(self.read("p.md"), "orphan", "false"))
        remove_key(f, "orphan", "false")
        self.assertFalse(has_key(self.read("p.md"), "orphan", "false"))


if __name__ == "__main__":
    unittest.main()
