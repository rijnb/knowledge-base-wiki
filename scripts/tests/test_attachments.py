"""Tests for the misplaced-attachment check (scripts/lib/checks/attachments.py)."""

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.checks.attachments import check_misplaced_attachments  # noqa: E402
from lib.fixers import fix_misplaced_attachments  # noqa: E402
from lib.report import format_text  # noqa: E402


class AttachmentFixtureMixin:
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="attach-test-"))
        self.addCleanup(lambda: shutil.rmtree(self.root, ignore_errors=True))

    def touch(self, rel: str, content: bytes = b"x") -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        return p

    def note(self, rel: str, body: str) -> Path:
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
        return p


class CheckMisplacedAttachmentsTests(AttachmentFixtureMixin, unittest.TestCase):
    def test_attachment_in_own_resources_is_ok(self):
        self.touch("raw/notes/_resources/photo.jpg")
        self.note("raw/notes/note.md", "![[_resources/photo.jpg]]\n")
        result = check_misplaced_attachments(self.root, quiet=True)
        self.assertEqual(result["misplaced_attachments"], [])
        self.assertEqual(result["summary"]["misplaced_found"], 0)

    def test_attachment_in_other_dirs_resources_is_flagged(self):
        self.touch("raw/other/_resources/spec.pdf")
        self.note("raw/notes/note.md", "![[spec.pdf]]\n")
        result = check_misplaced_attachments(self.root, quiet=True)
        self.assertEqual(len(result["misplaced_attachments"]), 1)
        entry = result["misplaced_attachments"][0]
        self.assertEqual(entry["file"], "raw/notes/note.md")
        self.assertEqual(entry["target"], "spec.pdf")
        self.assertEqual(entry["resolved"], "raw/other/_resources/spec.pdf")
        self.assertEqual(entry["expected_dir"], "raw/notes/_resources")

    def test_inbox_notes_are_enforced(self):
        self.touch("raw/emails/_resources/mail.pdf")
        self.note("INBOX/todo.md", "![[mail.pdf]]\n")
        result = check_misplaced_attachments(self.root, quiet=True)
        self.assertEqual(len(result["misplaced_attachments"]), 1)
        self.assertEqual(result["misplaced_attachments"][0]["file"], "INBOX/todo.md")

    def test_wiki_notes_may_reference_raw_attachments(self):
        self.touch("raw/notes/_resources/photo.jpg")
        self.note("wiki/systems/Foo.md", "![[photo.jpg]]\n")
        result = check_misplaced_attachments(self.root, quiet=True)
        self.assertEqual(result["misplaced_attachments"], [])

    def test_links_to_markdown_notes_are_ignored(self):
        self.note("raw/notes/other.md", "content\n")
        self.note("raw/notes/note.md", "[[other]] and [[raw/notes/other.md]]\n")
        result = check_misplaced_attachments(self.root, quiet=True)
        self.assertEqual(result["misplaced_attachments"], [])

    def test_unresolvable_targets_are_skipped(self):
        # Broken links are the broken-link check's job, not this one's.
        self.note("raw/notes/note.md", "![[missing.png]]\n")
        result = check_misplaced_attachments(self.root, quiet=True)
        self.assertEqual(result["misplaced_attachments"], [])

    def test_legacy_dot_resources_sibling_is_accepted(self):
        self.touch("raw/scans/2020_Daily.resources/scan.png")
        self.note("raw/scans/scan note.md", "![[2020_Daily.resources/scan.png]]\n")
        result = check_misplaced_attachments(self.root, quiet=True)
        self.assertEqual(result["misplaced_attachments"], [])

    def test_attachment_loose_next_to_note_is_flagged(self):
        self.touch("raw/notes/photo.jpg")
        self.note("raw/notes/note.md", "![[photo.jpg]]\n")
        result = check_misplaced_attachments(self.root, quiet=True)
        self.assertEqual(len(result["misplaced_attachments"]), 1)
        self.assertEqual(
            result["misplaced_attachments"][0]["resolved"], "raw/notes/photo.jpg"
        )

    def test_markdown_style_relative_link_is_checked(self):
        self.touch("raw/other/diagram.png")
        self.note("raw/notes/note.md", "![diagram](../other/diagram.png)\n")
        result = check_misplaced_attachments(self.root, quiet=True)
        self.assertEqual(len(result["misplaced_attachments"]), 1)
        self.assertEqual(
            result["misplaced_attachments"][0]["resolved"], "raw/other/diagram.png"
        )

    def test_external_links_are_ignored(self):
        self.note("raw/notes/note.md", "[site](https://example.com/x.pdf)\n")
        result = check_misplaced_attachments(self.root, quiet=True)
        self.assertEqual(result["misplaced_attachments"], [])

    def test_ambiguous_bare_name_is_skipped(self):
        # Two files with the same name — cannot know which one is meant.
        self.touch("raw/a/_resources/photo.jpg")
        self.touch("raw/b/_resources/photo.jpg")
        self.note("raw/notes/note.md", "![[photo.jpg]]\n")
        result = check_misplaced_attachments(self.root, quiet=True)
        self.assertEqual(result["misplaced_attachments"], [])

    def test_subdirectory_below_resources_is_ok(self):
        self.touch("raw/notes/_resources/imgs/photo.jpg")
        self.note("raw/notes/note.md", "![[_resources/imgs/photo.jpg]]\n")
        result = check_misplaced_attachments(self.root, quiet=True)
        self.assertEqual(result["misplaced_attachments"], [])

    def test_note_inside_resources_bundle_with_sibling_attachment_is_ok(self):
        # Companion notes inside a resources dir sit next to their originals —
        # they are co-located by definition, no nested _resources required.
        self.touch("raw/notes/_resources/spec.resources/adas.pdf")
        self.note("raw/notes/_resources/spec.resources/adas.md", "![[adas.pdf]]\n")
        result = check_misplaced_attachments(self.root, quiet=True)
        self.assertEqual(result["misplaced_attachments"], [])

    def test_note_inside_resources_linking_same_resources_tree_is_ok(self):
        self.touch("raw/notes/_resources/img/photo.jpg")
        self.note("raw/notes/_resources/photo note.md", "![[img/photo.jpg]]\n")
        result = check_misplaced_attachments(self.root, quiet=True)
        self.assertEqual(result["misplaced_attachments"], [])

    def test_note_inside_resources_linking_other_resources_tree_is_flagged(self):
        self.touch("raw/other/_resources/spec.pdf")
        self.note("raw/notes/_resources/bundle.resources/note.md", "![[spec.pdf]]\n")
        result = check_misplaced_attachments(self.root, quiet=True)
        self.assertEqual(len(result["misplaced_attachments"]), 1)

    def test_bare_name_link_to_vault_root_resources_is_flagged(self):
        # The legacy vault-root _resources/ is outside raw/wiki/INBOX but must
        # still be searchable, or bare-name links to it go unchecked.
        self.touch("_resources/photo.png")
        self.note("raw/notes/note.md", "![[photo.png]]\n")
        result = check_misplaced_attachments(self.root, quiet=True)
        self.assertEqual(len(result["misplaced_attachments"]), 1)
        self.assertEqual(
            result["misplaced_attachments"][0]["resolved"], "_resources/photo.png"
        )

    def test_symlinked_attachment_is_skipped(self):
        # Symlinks are excluded, matching check_loose_files — a symlink target
        # outside the vault must never surface as an absolute "resolved" path.
        outside = Path(tempfile.mkdtemp(prefix="attach-outside-"))
        self.addCleanup(lambda: shutil.rmtree(outside, ignore_errors=True))
        real = outside / "link.pdf"
        real.write_bytes(b"x")
        link_dir = self.root / "raw/other/_resources"
        link_dir.mkdir(parents=True)
        (link_dir / "link.pdf").symlink_to(real)
        self.note("raw/notes/note.md", "![[link.pdf]]\n")
        result = check_misplaced_attachments(self.root, quiet=True)
        self.assertEqual(result["misplaced_attachments"], [])

    def test_curly_quote_in_target_resolves_to_straight_quote_filename(self):
        # resolve_wikilink normalizes curly quotes; this check must agree.
        self.touch("raw/other/_resources/spec's.pdf")
        self.note("raw/notes/note.md", "![[spec’s.pdf]]\n")
        result = check_misplaced_attachments(self.root, quiet=True)
        self.assertEqual(len(result["misplaced_attachments"]), 1)
        self.assertEqual(
            result["misplaced_attachments"][0]["resolved"],
            "raw/other/_resources/spec's.pdf",
        )

    def test_summary_counts(self):
        self.touch("raw/notes/photo.jpg")
        self.touch("raw/notes/_resources/ok.pdf")
        self.note("raw/notes/note.md", "![[photo.jpg]]\n![[_resources/ok.pdf]]\n")
        result = check_misplaced_attachments(self.root, quiet=True)
        s = result["summary"]
        self.assertEqual(s["notes_scanned"], 1)
        self.assertEqual(s["attachments_checked"], 2)
        self.assertEqual(s["misplaced_found"], 1)


class MultiNoteReferenceTests(AttachmentFixtureMixin, unittest.TestCase):
    def test_colocated_with_one_referencing_note_is_fine(self):
        # Attachment lives in the _resources of ONE of its referencing notes —
        # fine for all of them, no warning.
        self.touch("raw/a/_resources/spec.pdf")
        self.note("raw/a/owner.md", "![[_resources/spec.pdf]]\n")
        self.note("raw/b/other.md", "![[spec.pdf]]\n")
        result = check_misplaced_attachments(self.root, quiet=True)
        self.assertEqual(result["misplaced_attachments"], [])

    def test_colocated_with_wiki_referencing_note_is_fine(self):
        self.touch("wiki/systems/_resources/diagram.png")
        self.note("wiki/systems/Foo.md", "![[_resources/diagram.png]]\n")
        self.note("raw/notes/note.md", "![[diagram.png]]\n")
        result = check_misplaced_attachments(self.root, quiet=True)
        self.assertEqual(result["misplaced_attachments"], [])

    def test_not_colocated_with_any_referencing_note_is_flagged(self):
        # Lives in SOME _resources, but no note in that directory links it.
        self.touch("raw/a/_resources/spec.pdf")
        self.note("raw/b/other.md", "![[spec.pdf]]\n")
        result = check_misplaced_attachments(self.root, quiet=True)
        self.assertEqual(len(result["misplaced_attachments"]), 1)
        self.assertEqual(result["misplaced_attachments"][0]["file"], "raw/b/other.md")


def _fake_mover(root):
    def mover(_root, src_rel, dest_rel):
        src, dest = root / src_rel, root / dest_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dest)
        return True, ""
    return mover


class FixMisplacedAttachmentsTests(AttachmentFixtureMixin, unittest.TestCase):
    def _findings(self):
        return check_misplaced_attachments(self.root, quiet=True)["misplaced_attachments"]

    def test_moves_attachment_into_notes_resources(self):
        self.touch("_resources/spec.pdf")
        self.note("raw/notes/note.md", "![[_resources/spec.pdf]]\n")
        fix = fix_misplaced_attachments(
            self._findings(), self.root, quiet=True, mover=_fake_mover(self.root))
        self.assertEqual(fix["moved"], 1)
        self.assertEqual(fix["skipped"], 0)
        self.assertTrue((self.root / "raw/notes/_resources/spec.pdf").is_file())
        self.assertFalse((self.root / "_resources/spec.pdf").exists())
        self.assertEqual(self._findings(), [])

    def test_same_attachment_linked_many_times_moves_once(self):
        self.touch("_resources/spec.pdf")
        self.note("raw/notes/note.md",
                  "![[_resources/spec.pdf]]\n![[_resources/spec.pdf]]\n"
                  "![[_resources/spec.pdf]]\n")
        findings = self._findings()
        self.assertEqual(len(findings), 3)
        fix = fix_misplaced_attachments(
            findings, self.root, quiet=True, mover=_fake_mover(self.root))
        self.assertEqual(fix["moved"], 1)
        self.assertTrue((self.root / "raw/notes/_resources/spec.pdf").is_file())

    def test_failed_move_is_skipped_with_reason(self):
        self.touch("_resources/spec.pdf")
        self.note("raw/notes/note.md", "![[_resources/spec.pdf]]\n")

        def failing_mover(_root, _src, _dest):
            return False, "vault not open"

        fix = fix_misplaced_attachments(
            self._findings(), self.root, quiet=True, mover=failing_mover)
        self.assertEqual(fix["moved"], 0)
        self.assertEqual(fix["skipped"], 1)
        self.assertEqual(fix["details"][0]["reason"], "vault not open")
        self.assertTrue((self.root / "_resources/spec.pdf").is_file())

    def test_name_clash_in_destination_uses_numbered_fallback(self):
        self.touch("INBOX/_resources/spec.pdf")
        self.touch("raw/notes/_resources/spec.pdf")  # unrelated same-name file
        self.note("raw/notes/note.md", "![[INBOX/_resources/spec.pdf]]\n")
        findings = self._findings()
        self.assertEqual(len(findings), 1)
        fix = fix_misplaced_attachments(
            findings, self.root, quiet=True, mover=_fake_mover(self.root))
        self.assertEqual(fix["moved"], 1)
        self.assertTrue((self.root / "raw/notes/_resources/spec 2.pdf").is_file())


class CheckVaultWiringTests(AttachmentFixtureMixin, unittest.TestCase):
    def _args(self, **overrides):
        import argparse
        base = dict(quiet=True, include_images=True, skip_frontmatter=False,
                    external=False, timeout=5, fix_simple_errors=False,
                    remove_broken_links=False)
        base.update(overrides)
        return argparse.Namespace(**base)

    def _misplaced_fixture(self):
        self.touch("INBOX/_resources/spec.pdf")
        self.note("raw/notes/note.md", "![[INBOX/_resources/spec.pdf]]\n")

    def test_pending_count_reported_without_fix(self):
        from lib.checks.vault import check_vault
        self._misplaced_fixture()
        result = check_vault(self.root, self._args())
        self.assertEqual(result["attachments_pending"], 1)
        self.assertEqual(result["summary"]["attachments_pending"], 1)

    def test_fix_simple_errors_invokes_attachment_fixer(self):
        from unittest import mock
        from lib.checks.vault import check_vault
        self._misplaced_fixture()
        fake = {"moved": 1, "skipped": 0, "details": [], "warning": None}
        with mock.patch("lib.checks.vault.fix_misplaced_attachments",
                        return_value=fake) as fx:
            result = check_vault(self.root, self._args(fix_simple_errors=True))
        fx.assert_called_once()
        self.assertEqual(result["summary"]["attachments_moved"], 1)


class ReportRenderingTests(unittest.TestCase):
    def _base_result(self) -> dict:
        return {
            "summary": {"files_checked": 1, "links_checked": 1,
                        "broken": 0, "skipped_external": 0},
            "errors": [],
            "broken_links": [],
        }

    def test_misplaced_attachments_section_rendered(self):
        result = self._base_result()
        result["misplaced_attachments"] = [{
            "file": "raw/notes/note.md", "line": 3, "target": "spec.pdf",
            "resolved": "raw/other/_resources/spec.pdf",
            "expected_dir": "raw/notes/_resources",
        }]
        result["attachment_summary"] = {
            "notes_scanned": 1, "attachments_checked": 1, "misplaced_found": 1,
        }
        text = format_text(result)
        self.assertIn("MISPLACED ATTACHMENTS", text)
        self.assertIn("raw/notes/note.md", text)
        self.assertIn("raw/other/_resources/spec.pdf", text)
        self.assertIn("misplaced attachments: 1 found", text)

    def test_no_misplaced_attachments_message(self):
        result = self._base_result()
        result["misplaced_attachments"] = []
        result["attachment_summary"] = {
            "notes_scanned": 1, "attachments_checked": 1, "misplaced_found": 0,
        }
        text = format_text(result)
        self.assertIn("No misplaced attachments found.", text)


if __name__ == "__main__":
    unittest.main()


class CheckOrphanAttachmentsTests(AttachmentFixtureMixin, unittest.TestCase):
    def _run(self):
        from lib.checks.attachments import check_orphan_attachments
        return check_orphan_attachments(self.root, quiet=True)

    def test_unreferenced_root_resources_file_is_flagged(self):
        self.touch("_resources/Untitled-123.jpeg")
        result = self._run()
        self.assertEqual(result["orphan_attachments"], ["_resources/Untitled-123.jpeg"])
        self.assertEqual(result["summary"]["orphan_attachments_found"], 1)

    def test_wikilink_embed_reference_exempts(self):
        self.touch("_resources/shot.png")
        self.note("wiki/concepts/page.md", "![[shot.png]]\n")
        result = self._run()
        self.assertEqual(result["orphan_attachments"], [])

    def test_mdlink_with_path_reference_exempts(self):
        self.touch("_resources/diagram.png")
        self.note("raw/notes/note.md", "![d](_resources/diagram.png)\n")
        result = self._run()
        self.assertEqual(result["orphan_attachments"], [])

    def test_companion_note_exempts(self):
        self.touch("_resources/report.pdf")
        self.note("_resources/report.pdf.md", "companion\n")
        result = self._run()
        self.assertEqual(result["orphan_attachments"], [])

    def test_infrastructure_files_ignored(self):
        self.touch("_resources/.DS_Store")
        result = self._run()
        self.assertEqual(result["orphan_attachments"], [])

    def test_missing_root_resources_dir_is_clean(self):
        self.note("wiki/concepts/page.md", "text\n")
        result = self._run()
        self.assertEqual(result["orphan_attachments"], [])
        self.assertEqual(result["summary"]["orphan_attachments_found"], 0)

    def test_nfc_nfd_reference_forms_match(self):
        import unicodedata
        nfd = unicodedata.normalize("NFD", "Kepiński.png")
        nfc = unicodedata.normalize("NFC", "Kepiński.png")
        self.touch(f"_resources/{nfd}")
        self.note("wiki/concepts/page.md", f"![[{nfc}]]\n")
        result = self._run()
        self.assertEqual(result["orphan_attachments"], [])
