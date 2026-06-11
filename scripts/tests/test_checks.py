"""Tests for the check modules: vault, orphans, stubs, legacy."""

import argparse
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.checks.legacy import check_legacy_converted  # noqa: E402
from lib.checks.orphans import check_orphans  # noqa: E402
from lib.checks.stubs import check_stubs  # noqa: E402
from lib.checks.vault import check_vault  # noqa: E402


def make_args(**overrides):
    base = dict(
        external=False,
        timeout=5,
        include_images=True,
        format="json",
        skip_frontmatter=False,
        remove_broken_links=False,
        fix_simple_errors=False,
        fix_orphans=False,
        quiet=True,
        batch_mode=True,
        root=None,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


class CheckVaultTests(VaultFixtureMixin, unittest.TestCase):
    def test_valid_links_no_broken(self):
        self.write("wiki/concepts/a.md", "[[b]]\n")
        self.write("wiki/concepts/b.md", "[[a]]\n")
        result = check_vault(self.root, make_args())
        self.assertEqual(result["summary"]["broken"], 0)
        self.assertEqual(result["broken_links"], [])

    def test_broken_wikilink_reported(self):
        self.write("wiki/concepts/a.md", "[[does-not-exist]]\n")
        result = check_vault(self.root, make_args())
        self.assertEqual(result["summary"]["broken"], 1)
        self.assertEqual(result["broken_links"][0]["target"], "does-not-exist")

    def test_broken_mdlink_reported(self):
        self.write("wiki/concepts/a.md", "[txt](missing.md)\n")
        result = check_vault(self.root, make_args())
        self.assertEqual(result["summary"]["broken"], 1)

    def test_suggested_fix_present_for_normalizable_target(self):
        self.write("wiki/concepts/foo_ bar.md", "x")
        self.write("wiki/concepts/a.md", "[[foo: bar]]\n")
        result = check_vault(self.root, make_args())
        entry = next(b for b in result["broken_links"] if b["target"] == "foo: bar")
        self.assertEqual(entry["suggested_fix"], "foo_ bar")

    def test_fix_simple_errors_marks_only_substituted_fixed(self):
        # Regression for Bug 2: a suggested_fix that the rewriter could not apply
        # in-place must NOT be marked fixed.
        self.write("wiki/concepts/foo_ bar.md", "x")
        # The link text uses an alias/heading form the fixer's regex won't match
        # on this raw, but suggested_fix is still computed from the target.
        self.write("wiki/concepts/a.md", "[[foo: bar]]\n")
        result = check_vault(self.root, make_args(fix_simple_errors=True))
        # This one is genuinely fixable -> fixed True and rewritten on disk.
        self.assertIn("[[foo_ bar]]", self.read("wiki/concepts/a.md"))
        self.assertEqual(result["summary"]["fixed_links"], 1)

    def test_fix_simple_errors_marks_each_present_link_fixed(self):
        self.write("wiki/concepts/foo_ bar.md", "x")
        self.write("wiki/concepts/baz_ qux.md", "y")
        self.write("wiki/concepts/a.md", "[[foo: bar]] and [[baz: qux]]\n")
        result = check_vault(self.root, make_args(fix_simple_errors=True))
        fixed_targets = {b["target"] for b in result["broken_links"] if b.get("fixed")}
        self.assertIn("foo: bar", fixed_targets)
        self.assertIn("baz: qux", fixed_targets)
        self.assertEqual(result["summary"]["fixed_links"], 2)

    def test_fix_simple_errors_unfixable_entry_not_marked_fixed(self):
        # Regression for Bug 2: an entry that carries a suggested_fix but whose
        # target the rewriter cannot find/substitute in-place must NOT get
        # fixed=True. We force this by pre-rewriting the file out from under the
        # second target via a unique-stem scenario the regex won't touch.
        self.write("wiki/concepts/foo_ bar.md", "x")
        # The link is an EMBED ![[...]]; the plain-wikilink fixer (embed=False)
        # will not substitute an embed, so even though a suggested_fix exists the
        # substitution count is 0.
        self.write("wiki/concepts/a.md", "![[foo: bar]]\n")
        result = check_vault(self.root, make_args(fix_simple_errors=True))
        entries = [b for b in result["broken_links"] if b["target"] == "foo: bar"]
        # The embed remained broken and was never substituted.
        self.assertTrue(entries)
        self.assertFalse(any(e.get("fixed") for e in entries))
        self.assertEqual(result["summary"]["fixed_links"], 0)


class CheckOrphansTests(VaultFixtureMixin, unittest.TestCase):
    def test_orphan_detected(self):
        self.write("wiki/concepts/lonely.md", "no links and nobody links here\n")
        self.write("wiki/concepts/hub.md", "just text\n")
        result = check_orphans(self.root, quiet=True)
        self.assertIn("wiki/concepts/lonely.md", result["orphans"])

    def test_backlinked_page_not_orphan(self):
        self.write("wiki/concepts/target.md", "body\n")
        self.write("wiki/concepts/source.md", "[[target]]\n")
        result = check_orphans(self.root, quiet=True)
        self.assertNotIn("wiki/concepts/target.md", result["orphans"])

    def test_orphan_false_suppresses(self):
        self.write("wiki/concepts/lonely.md", "---\norphan: false\n---\nbody\n")
        result = check_orphans(self.root, quiet=True)
        self.assertNotIn("wiki/concepts/lonely.md", result["orphans"])

    def test_backlink_from_skipped_file_does_not_count(self):
        # Regression for Bug 9: a link inside wiki/log.md (a should_skip_md file)
        # must NOT save a page from orphanhood.
        self.write("wiki/concepts/target.md", "body\n")
        self.write("wiki/log.md", "[[target]]\n")
        result = check_orphans(self.root, quiet=True)
        self.assertIn("wiki/concepts/target.md", result["orphans"])


class CheckStubsTests(VaultFixtureMixin, unittest.TestCase):
    def test_thin_page_flagged(self):
        self.write("wiki/concepts/thin.md", "---\ntitle: x\n---\ntwo words\n")
        result = check_stubs(self.root, quiet=True)
        self.assertIn("wiki/concepts/thin.md", result["stubs"])

    def test_stub_true_suppressed(self):
        self.write("wiki/concepts/thin.md", "---\nstub: true\n---\ntwo words\n")
        result = check_stubs(self.root, quiet=True)
        self.assertNotIn("wiki/concepts/thin.md", result["stubs"])

    def test_frontmatterless_long_body_not_flagged(self):
        # Regression for Bug 3: a page with NO frontmatter and a long body must
        # be counted (body words), not treated as empty and flagged as a stub.
        body = "This is a substantial body with plenty of real prose words here.\n"
        self.write("wiki/concepts/nofm.md", body)
        result = check_stubs(self.root, quiet=True)
        self.assertNotIn("wiki/concepts/nofm.md", result["stubs"])

    def test_frontmatterless_thin_body_flagged(self):
        self.write("wiki/concepts/nofm-thin.md", "two words\n")
        result = check_stubs(self.root, quiet=True)
        self.assertIn("wiki/concepts/nofm-thin.md", result["stubs"])


class CheckLegacyTests(VaultFixtureMixin, unittest.TestCase):
    def test_detects_converted_dir(self):
        self.write("raw/notes/converted/x.md", "x")
        result = check_legacy_converted(self.root, quiet=True)
        self.assertEqual(result["summary"]["converted_dirs_found"], 1)
        self.assertIn("raw/notes/converted", result["legacy_converted"])
        self.assertEqual(result["summary"]["converted_md_files"], 1)

    def test_no_legacy_dirs(self):
        self.write("raw/notes/x.md", "x")
        result = check_legacy_converted(self.root, quiet=True)
        self.assertEqual(result["summary"]["converted_dirs_found"], 0)


if __name__ == "__main__":
    unittest.main()
