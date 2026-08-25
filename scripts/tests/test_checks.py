"""Tests for the check modules: vault, orphans, stubs, footnotes, legacy."""

import argparse
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.checks.footnotes import check_footnotes  # noqa: E402
from lib.checks.frontmatter import check_frontmatter  # noqa: E402
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


class CheckFrontmatterTests(VaultFixtureMixin, unittest.TestCase):
    def issues_for(self, rel):
        result = check_frontmatter(self.root, quiet=True)
        return [i for i in result["frontmatter_issues"] if i["file"] == rel]

    def test_valid_page_passes(self):
        self.write("wiki/concepts/good.md",
                   "---\ntype: concept\ndescription: A well-formed page\n---\nbody\n")
        result = check_frontmatter(self.root, quiet=True)
        self.assertEqual(result["frontmatter_issues"], [])
        self.assertEqual(result["summary"]["wiki_pages_checked"], 1)
        self.assertEqual(result["summary"]["frontmatter_errors"], 0)
        self.assertEqual(result["summary"]["frontmatter_warnings"], 0)

    def test_missing_frontmatter_is_error(self):
        self.write("wiki/concepts/bare.md", "just a body, no frontmatter\n")
        issues = self.issues_for("wiki/concepts/bare.md")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "error")
        self.assertIn("frontmatter", issues[0]["reason"])

    def test_bad_type_is_error(self):
        self.write("wiki/concepts/bad.md",
                   "---\ntype: gizmo\ndescription: d\n---\nbody\n")
        issues = self.issues_for("wiki/concepts/bad.md")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "error")
        self.assertIn("gizmo", issues[0]["reason"])

    def test_missing_type_is_error(self):
        self.write("wiki/concepts/untyped.md",
                   "---\ndescription: d\n---\nbody\n")
        issues = self.issues_for("wiki/concepts/untyped.md")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "error")
        self.assertIn("type", issues[0]["reason"])

    def test_old_style_status_value_is_error(self):
        self.write("wiki/systems/sys.md",
                   "---\ntype: system\ndescription: d\nstatus: active\n---\nbody\n")
        issues = self.issues_for("wiki/systems/sys.md")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "error")
        self.assertIn("active", issues[0]["reason"])

    def test_okf_status_value_accepted(self):
        self.write("wiki/systems/sys.md",
                   "---\ntype: system\ndescription: d\nstatus: stable\n---\nbody\n")
        self.assertEqual(self.issues_for("wiki/systems/sys.md"), [])

    def test_kb_prov_remnant_is_error(self):
        self.write("wiki/concepts/prov.md",
                   "---\ntype: concept\ndescription: d\n---\nbody kb-prov-v1 remnant\n")
        issues = self.issues_for("wiki/concepts/prov.md")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "error")
        self.assertIn("kb-prov-v1", issues[0]["reason"])

    def test_missing_description_is_warning(self):
        self.write("wiki/concepts/nodesc.md",
                   "---\ntype: concept\n---\nbody\n")
        issues = self.issues_for("wiki/concepts/nodesc.md")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "warning")
        result = check_frontmatter(self.root, quiet=True)
        self.assertEqual(result["summary"]["frontmatter_errors"], 0)
        self.assertEqual(result["summary"]["frontmatter_warnings"], 1)

    def test_index_md_exempt(self):
        self.write("wiki/concepts/index.md", "no frontmatter at all\n")
        result = check_frontmatter(self.root, quiet=True)
        self.assertEqual(result["frontmatter_issues"], [])
        self.assertEqual(result["summary"]["wiki_pages_checked"], 0)


class CheckFootnotesTests(VaultFixtureMixin, unittest.TestCase):
    def issues_for(self, rel):
        result = check_footnotes(self.root, quiet=True)
        return [i for i in result["footnote_issues"] if i["file"] == rel]

    def test_matching_ref_and_definition_passes(self):
        self.write("wiki/concepts/good.md",
                   "---\ntype: concept\n---\nA claim. [^s1]\n\n[^s1]: [[raw/notes/x.md]]\n")
        result = check_footnotes(self.root, quiet=True)
        self.assertEqual(result["footnote_issues"], [])
        self.assertEqual(result["summary"]["wiki_pages_checked"], 1)
        self.assertEqual(result["summary"]["footnote_errors"], 0)
        self.assertEqual(result["summary"]["footnote_warnings"], 0)

    def test_undefined_ref_is_error(self):
        self.write("wiki/concepts/dangling.md",
                   "---\ntype: concept\n---\nA claim. [^s2]\n\n[^s1]: [[raw/notes/x.md]]\n")
        issues = self.issues_for("wiki/concepts/dangling.md")
        errors = [i for i in issues if i["severity"] == "error"]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["line"], 4)
        self.assertIn("[^s2]", errors[0]["reason"])

    def test_unreferenced_definition_is_warning(self):
        self.write("wiki/concepts/unused.md",
                   "---\ntype: concept\n---\nA claim. [^s1]\n\n"
                   "[^s1]: [[raw/notes/x.md]]\n[^s2]: [[raw/notes/y.md]]\n")
        issues = self.issues_for("wiki/concepts/unused.md")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "warning")
        self.assertEqual(issues[0]["line"], 7)
        self.assertIn("[^s2]", issues[0]["reason"])

    def test_duplicate_definition_is_error(self):
        self.write("wiki/concepts/dupe.md",
                   "---\ntype: concept\n---\nA claim. [^s1]\n\n"
                   "[^s1]: [[raw/notes/x.md]]\n[^s1]: [[raw/notes/y.md]]\n")
        issues = self.issues_for("wiki/concepts/dupe.md")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "error")
        self.assertIn("defined 2 times", issues[0]["reason"])

    def test_ref_in_fenced_block_ignored(self):
        self.write("wiki/concepts/fenced.md",
                   "---\ntype: concept\n---\nExample:\n\n```\nA claim. [^s9]\n```\n")
        self.assertEqual(self.issues_for("wiki/concepts/fenced.md"), [])

    def test_ref_in_inline_code_ignored(self):
        self.write("wiki/concepts/inline.md",
                   "---\ntype: concept\n---\nCite a source with `[^s9]` after the claim.\n")
        self.assertEqual(self.issues_for("wiki/concepts/inline.md"), [])

    def test_regex_character_class_not_a_footnote(self):
        self.write("wiki/concepts/regex.md",
                   "---\ntype: concept\n---\nThe filter is ^[^/]+\\.md$ for top-level notes.\n")
        self.assertEqual(self.issues_for("wiki/concepts/regex.md"), [])

    def test_word_label_footnote_supported(self):
        self.write("wiki/concepts/word.md",
                   "---\ntype: concept\n---\nA claim. [^export-schema]\n\n"
                   "[^export-schema]: See the export schema.\n")
        self.assertEqual(self.issues_for("wiki/concepts/word.md"), [])

    def test_frontmatter_ref_ignored(self):
        self.write("wiki/concepts/fm.md",
                   "---\ntype: concept\ndescription: \"uses [^s9] notation\"\n---\nbody\n")
        self.assertEqual(self.issues_for("wiki/concepts/fm.md"), [])

    def test_index_md_exempt(self):
        self.write("wiki/concepts/index.md", "A claim. [^s9]\n")
        result = check_footnotes(self.root, quiet=True)
        self.assertEqual(result["footnote_issues"], [])
        self.assertEqual(result["summary"]["wiki_pages_checked"], 0)


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
