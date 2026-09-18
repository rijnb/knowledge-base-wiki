"""Tests for lib.wiki_tags and the wiki-tags.py phases 0-2."""

import json
import subprocess
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.wiki_tags import (  # noqa: E402
    ObsidianUnavailable,
    append_jsonl,
    blind_reason,
    build_excerpt,
    build_inventory,
    declared_tags,
    escape_document,
    escape_inline_tags,
    frontmatter_backup_record,
    full_backup_record,
    iter_notes,
    iter_vault_md,
    normalize_key,
    parent_aggregates,
    parse_obsidian_tags,
    parse_tags,
    restore_frontmatter,
    restore_full,
    series_key,
    split_document,
    unlisted_inline_tags,
    valid_tag,
    wiki_type_index,
    write_tags,
    _spread,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "wiki-tags.py"


class ParseTagsTest(unittest.TestCase):
    """All three frontmatter shapes present in this vault must parse."""

    def test_block_list(self):
        fm = 'type: system\ntags:\n  - sw/agile\n  - "map/hd-map"\n  - year/2022\n'
        self.assertEqual(parse_tags(fm), ["sw/agile", "map/hd-map", "year/2022"])

    def test_inline_list(self):
        fm = "tags: [megacorp, gent, engineering]\n"
        self.assertEqual(parse_tags(fm), ["megacorp", "gent", "engineering"])

    def test_bare_scalar(self):
        fm = "tags: sw/agile sw/test\n"
        self.assertEqual(parse_tags(fm), ["sw/agile", "sw/test"])

    def test_empty_list_and_missing_key(self):
        self.assertEqual(parse_tags("tags: []\n"), [])
        self.assertEqual(parse_tags("type: concept\n"), [])
        self.assertEqual(parse_tags(""), [])

    def test_strips_hash_and_dedupes(self):
        self.assertEqual(parse_tags("tags: [#ai, ai, ' ai ']\n"), ["ai"])

    def test_block_list_wins_over_a_later_scalar_key(self):
        fm = "tags:\n  - map/hd-map\nother: tags: nonsense\n"
        self.assertEqual(parse_tags(fm), ["map/hd-map"])

    def test_split_document(self):
        content = "---\ntype: concept\n---\nbody text\n"
        fm, body = split_document(content)
        self.assertEqual(fm, "type: concept")
        self.assertEqual(body, "body text\n")
        self.assertEqual(split_document("no frontmatter\n"), ("", "no frontmatter\n"))


class ValidTagTest(unittest.TestCase):
    def test_two_and_three_segments_are_valid(self):
        self.assertTrue(valid_tag("sw/agile"))
        self.assertTrue(valid_tag("sw/agile/scrum"))
        self.assertTrue(valid_tag("map/hd-map"))

    def test_one_and_four_segments_are_not(self):
        self.assertFalse(valid_tag("megacorp"))
        self.assertFalse(valid_tag("a/b/c/d"))

    def test_year_is_exempt(self):
        self.assertTrue(valid_tag("year/2022"))

    def test_rejects_uppercase_and_underscores_and_spaces(self):
        self.assertFalse(valid_tag("SW/Agile"))
        self.assertFalse(valid_tag("sw/agile_scrum"))
        self.assertFalse(valid_tag("sw/agile scrum"))


class ParentAggregateTest(unittest.TestCase):
    def test_undeclared_parent_with_children_is_an_aggregate(self):
        counts = {"year": 2971, "year/2022": 528, "year/2021": 411}
        declared = Counter({"year/2022": 528, "year/2021": 411})
        self.assertEqual(parent_aggregates(counts, declared), {"year"})

    def test_declared_parent_is_a_real_tag(self):
        counts = {"sw": 40, "sw/agile": 10}
        declared = Counter({"sw": 40, "sw/agile": 10})
        self.assertEqual(parent_aggregates(counts, declared), set())

    def test_childless_tag_is_never_an_aggregate(self):
        counts = {"B0403A": 35}
        self.assertEqual(parent_aggregates(counts, Counter()), set())

    def test_parse_obsidian_tags(self):
        out = "#year\t2971\n#megacorp\t2278\n\nmalformed\n#bad\tx\n"
        self.assertEqual(parse_obsidian_tags(out), {"year": 2971, "megacorp": 2278})


class BlindReasonTest(unittest.TestCase):
    """Why Obsidian ignores a tag a note declares decides what the remap does."""

    SEEN = {"dataspec": 281, "adas": 204, "sw/agile": 10}

    def test_indexed_tag_has_no_reason(self):
        self.assertEqual(blind_reason("dataspec", self.SEEN), "")

    def test_key_leaked_into_the_tag_list(self):
        self.assertEqual(blind_reason("stub: true", self.SEEN), "malformed-frontmatter")

    def test_case_variant_is_not_a_lost_tag(self):
        self.assertEqual(blind_reason("DataSpec", self.SEEN), "case-variant")
        self.assertEqual(blind_reason("coreSDK", {"coresdk": 1}), "case-variant")

    def test_numeric_only_is_not_a_tag_to_obsidian(self):
        self.assertEqual(blind_reason("2026", self.SEEN), "numeric-only")

    def test_illegal_characters(self):
        for tag in ("1:1", "t&d", "c++", "r&d"):
            self.assertEqual(blind_reason(tag, self.SEEN), "illegal-char", tag)

    def test_legal_but_unindexed(self):
        self.assertEqual(blind_reason("brand-new-tag", self.SEEN), "unindexed")


class EscapeInlineTagsTest(unittest.TestCase):
    def test_escapes_a_target(self):
        body, n = escape_inline_tags("see #define and more\n", ["define"])
        self.assertEqual(body, "see \\#define and more\n")
        self.assertEqual(n, 1)

    def test_leaves_non_targets_alone(self):
        body, n = escape_inline_tags("keep #ai here\n", ["define"])
        self.assertEqual(body, "keep #ai here\n")
        self.assertEqual(n, 0)

    def test_does_not_double_escape(self):
        body, n = escape_inline_tags("already \\#define\n", ["define"])
        self.assertEqual(n, 0)
        self.assertEqual(body, "already \\#define\n")

    def test_skips_fenced_code_and_code_spans(self):
        text = "```\n#define X\n```\nprose `#define` and #define\n"
        body, n = escape_inline_tags(text, ["define"])
        self.assertEqual(n, 1)
        self.assertIn("```\n#define X\n```", body)
        self.assertIn("`#define`", body)
        self.assertIn("and \\#define", body)

    def test_escapes_at_start_of_a_quoted_ocr_line(self):
        # A space instead of an escape would turn this into an H1.
        body, n = escape_inline_tags("> #define NULL 0\n", ["define"])
        self.assertEqual(body, "> \\#define NULL 0\n")
        self.assertEqual(n, 1)

    def test_longer_target_wins(self):
        body, n = escape_inline_tags("#sig-claude\n", ["sig", "sig-claude"])
        self.assertEqual(body, "\\#sig-claude\n")
        self.assertEqual(n, 1)

    def test_shorter_target_does_not_match_inside_a_longer_tag(self):
        body, n = escape_inline_tags("#sig-claude\n", ["sig"])
        self.assertEqual(n, 0)

    def test_ignores_headings_and_html_entities(self):
        body, n = escape_inline_tags("## define\n&#define;\n", ["define"])
        self.assertEqual(n, 0)

    def test_document_leaves_frontmatter_untouched(self):
        content = "---\ntags: [define]\n---\nbody #define\n"
        new, n = escape_document(content, ["define"])
        self.assertEqual(n, 1)
        self.assertIn("tags: [define]", new)
        self.assertIn("body \\#define", new)


class ExcerptTest(unittest.TestCase):
    def test_prose_is_capped(self):
        body = " ".join(f"w{i}" for i in range(50)) + "\n"
        text, words, title_only = build_excerpt(body, cap=10)
        self.assertEqual(words, 10)
        self.assertEqual(text.split()[0], "w0")
        # A note that filled its budget is never "too thin to tag", even when
        # the budget is below the 20-word floor.
        self.assertFalse(title_only)

    def test_embeds_are_never_resolved(self):
        body = "![[Some Report.pdf]]\n\nreal prose here\n"
        text, _, _ = build_excerpt(body)
        self.assertNotIn("pdf", text.lower())
        self.assertIn("real prose here", text)

    def test_code_fences_tables_and_rules_are_dropped(self):
        body = (
            "prose one\n"
            "```\ntags: [secret, leaked]\n```\n"
            "| a | b |\n|---|---|\n"
            "---\n"
            "prose two\n"
        )
        text, _, _ = build_excerpt(body)
        self.assertEqual(text, "prose one prose two")

    def test_ocr_callout_title_is_dropped_but_content_kept(self):
        body = "> [!quote] Extracted text\n> scanned words here\n"
        text, _, _ = build_excerpt(body)
        self.assertNotIn("Extracted", text)
        self.assertIn("scanned words here", text)

    def test_thin_note_is_title_only(self):
        _, words, title_only = build_excerpt("two words\n")
        self.assertEqual(words, 2)
        self.assertTrue(title_only)

    def test_callouts_are_sampled_spread_not_from_the_front(self):
        # 20 callouts; only the last carries the distinguishing word. A
        # head-of-document sample would miss it entirely.
        pages = "".join(
            f"> [!quote] Extracted text\n> page {i} {'zebra' if i == 19 else 'filler'}\n"
            for i in range(20)
        )
        text, _, _ = build_excerpt(pages, cap=400)
        self.assertIn("zebra", text)

    def test_spread_samples_evenly(self):
        self.assertEqual(_spread(list("abcdefghij"), 3), ["a", "e", "j"])
        self.assertEqual(_spread(["a", "b"], 5), ["a", "b"])
        self.assertEqual(_spread([], 3), [])

    def test_series_key_strips_dates(self):
        self.assertEqual(series_key("2015-06-25 Taipei Source Code"), "taipei source code")
        self.assertEqual(series_key("2014 LDAP Sample Records"), "ldap sample records")


class VaultScanTest(VaultFixtureMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.write("raw/notes/A Note.md", "---\ntags: [megacorp, ai]\n---\nbody\n")
        self.write("raw/notes/B Note.md", "---\ntags:\n  - ai\n---\nbody #define\n")
        self.write("wiki/systems/Alpha.md", '---\ntype: system\ntags: []\n---\nbody\n')
        self.write("wiki/systems/index.md", "# Systems\n")
        self.write("wiki/concepts/DataSpec-Live.md", "---\ntype: concept\n---\nbody\n")
        self.write("wiki/systems/DataSpec-Live.md", "---\ntype: system\n---\nbody\n")
        self.write("raw/notes/_resources/skip.md", "---\ntags: [ignored]\n---\n")
        self.write("config/tags.md", "- `sw/agile`\n- `map/hd-map`\n")

    def test_iter_notes_skips_underscore_dirs_and_config(self):
        found = {p.name for p in iter_notes(self.root)}
        self.assertIn("A Note.md", found)
        self.assertNotIn("skip.md", found)
        self.assertNotIn("tags.md", found)

    def test_iter_vault_md_reaches_payloads_and_root_but_not_config(self):
        # Obsidian indexes _resources payloads and root-level files, so the
        # escape phase must reach them even though they are not notes.
        self.write("README.md", "See #team-platform on Slack.\n")
        found = {str(p.relative_to(self.root)) for p in iter_vault_md(self.root)}
        self.assertIn("README.md", found)
        self.assertIn("raw/notes/_resources/skip.md", found)
        self.assertIn("raw/notes/A Note.md", found)
        self.assertNotIn("config/tags.md", found)

    def test_declared_tags_counts_usage(self):
        self.assertEqual(declared_tags(self.root), Counter({"ai": 2, "megacorp": 1}))

    def test_wiki_type_index_records_ambiguity(self):
        index = wiki_type_index(self.root)
        self.assertEqual(index[normalize_key("Alpha")], {"systems"})
        self.assertEqual(index[normalize_key("DataSpec-Live")], {"concepts", "systems"})
        self.assertNotIn("index", index)

    def test_inventory_strips_aggregates_and_joins_wiki_types(self):
        fake = "#ai\t2\n#megacorp\t1\n#year\t5\n#year/2022\t5\n#alpha\t3\n"
        rows, stats = build_inventory(self.root, runner=lambda root: fake)
        by_tag = {r.tag: r for r in rows}
        self.assertNotIn("year", by_tag)                    # phantom aggregate
        self.assertEqual(stats["parent_aggregates"], 1)
        self.assertEqual(by_tag["alpha"].wiki_types, ["systems"])
        self.assertTrue(by_tag["alpha"].inline_only)       # seen but never declared
        self.assertFalse(by_tag["ai"].inline_only)
        self.assertEqual(by_tag["ai"].declared_count, 2)

    def test_inventory_keeps_declared_tags_obsidian_missed(self):
        rows, _ = build_inventory(self.root, runner=lambda root: "#ai\t2\n")
        self.assertIn("megacorp", {r.tag for r in rows})

    def test_inventory_refuses_to_fall_back_when_obsidian_is_silent(self):
        # A frontmatter-only inventory looks plausible but has every inline tag
        # missing, so it must be an error rather than a quiet degradation.
        with self.assertRaises(ObsidianUnavailable):
            build_inventory(self.root, runner=lambda root: None)
        with self.assertRaises(ObsidianUnavailable):
            unlisted_inline_tags(self.root, runner=lambda root: "")

    def test_unlisted_inline_tags_protects_declared_ancestors(self):
        fake = "#ai\t2\n#sw\t4\n#sw/agile\t4\n#define\t1\n"
        self.write("raw/notes/C Note.md", "---\ntags:\n  - sw/agile\n---\nbody\n")
        unlisted = unlisted_inline_tags(self.root, runner=lambda root: fake)
        self.assertEqual(set(unlisted), {"define"})         # `sw` is implied by sw/agile


class BackupTest(VaultFixtureMixin, unittest.TestCase):
    def test_restore_is_byte_for_byte(self):
        original = "---\ntags: []\n---\nbody #define\n"
        path = self.write("raw/notes/A.md", original)
        record = full_backup_record(path, self.root, original)
        path.write_text("clobbered", encoding="utf-8")
        self.assertEqual(restore_full(record, self.root), "restored")
        self.assertEqual(self.read("raw/notes/A.md"), original)

    def test_restore_reports_unchanged_when_already_original(self):
        original = "body\n"
        path = self.write("raw/notes/A.md", original)
        record = full_backup_record(path, self.root, original)
        self.assertEqual(restore_full(record, self.root), "unchanged")

    def test_restore_reports_missing_file(self):
        record = {"path": "raw/notes/gone.md", "sha256": "x", "text": "y"}
        self.assertEqual(restore_full(record, self.root), "missing")

    def test_revert_prefers_the_earliest_snapshot_of_a_path(self):
        # Two escape runs over the same file append two records; reverting must
        # land on the text from before the first run, not the second.
        original, after_first = "body #a #b\n", "body \\#a #b\n"
        path = self.write("raw/notes/A.md", original)
        backup = self.root / ".tags" / "inline-escape-backup.jsonl"
        backup.parent.mkdir(exist_ok=True)
        append_jsonl(backup, full_backup_record(path, self.root, original))
        append_jsonl(backup, full_backup_record(path, self.root, after_first))
        path.write_text("body \\#a \\#b\n", encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root),
             "--phase", "escape-revert", "--apply"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.read("raw/notes/A.md"), original)


class CliTest(VaultFixtureMixin, unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root), *args],
            capture_output=True, text=True,
        )

    def setUp(self):
        super().setUp()
        self.write("raw/notes/A Note.md",
                   "---\ntags: [megacorp]\n---\nsome prose words here\n")
        self.write("raw/notes/B Note.md",
                   "---\ntags: []\n---\n> [!quote] Extracted text\n> scanned page one\n")

    def test_excerpts_writes_jsonl(self):
        result = self._run("--phase", "excerpts")
        self.assertEqual(result.returncode, 0, result.stderr)
        records = [json.loads(l) for l in
                   (self.root / ".tags" / "excerpts.jsonl").read_text().splitlines()]
        self.assertEqual({r["title"] for r in records}, {"A Note", "B Note"})
        by_title = {r["title"]: r for r in records}
        self.assertEqual(by_title["A Note"]["tags"], ["megacorp"])
        self.assertIn("scanned page one", by_title["B Note"]["excerpt"])
        self.assertNotIn("Extracted", by_title["B Note"]["excerpt"])

    def test_excerpts_honours_limit(self):
        self._run("--phase", "excerpts", "--limit", "1")
        lines = (self.root / ".tags" / "excerpts.jsonl").read_text().splitlines()
        self.assertEqual(len(lines), 1)

    def test_escape_errors_loudly_when_obsidian_cannot_answer(self):
        # This fixture vault is not open in Obsidian, so the CLI has nothing to
        # say about it. The phase must say so and exit non-zero rather than
        # escape nothing and report success.
        before = self.read("raw/notes/A Note.md")
        result = self._run("--phase", "escape")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Is Obsidian running", result.stderr)
        self.assertEqual(self.read("raw/notes/A Note.md"), before)

    def test_unknown_phase_is_rejected(self):
        self.assertNotEqual(self._run("--phase", "nonsense").returncode, 0)

    def test_missing_note_dirs_exits_two(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(self.root / "raw"), "--phase", "excerpts"],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()


class WriteTagsTest(unittest.TestCase):
    """Frontmatter surgery: replace tags, preserve everything else byte-for-byte."""

    def test_inline_list_stays_inline(self):
        content = '---\ntype: system\ntags: [megacorp, ai]\ndescription: "A: b"\n---\nbody\n'
        out = write_tags(content, ["ai/general", "system/alpha"])
        self.assertIn("tags: [ai/general, system/alpha]", out)
        self.assertIn('description: "A: b"', out)
        self.assertIn("type: system", out)
        self.assertTrue(out.endswith("body\n"))

    def test_block_list_stays_block_and_items_are_replaced(self):
        content = "---\ntags:\n  - old-one\n  - old-two\ndate: 2025-05-27\n---\nbody\n"
        out = write_tags(content, ["hr/one-on-one"])
        self.assertIn("tags:\n  - hr/one-on-one\n", out)
        self.assertNotIn("old-one", out)
        self.assertNotIn("old-two", out)
        self.assertIn("date: 2025-05-27", out)

    def test_bare_scalar_becomes_an_inline_list(self):
        out = write_tags("---\ntags: a b\n---\nbody\n", ["map/hd-map"])
        self.assertIn("tags: [map/hd-map]", out)

    def test_emptying_writes_an_empty_list_rather_than_dropping_the_key(self):
        out = write_tags("---\ntype: system\ntags: [megacorp]\n---\nbody\n", [])
        self.assertIn("tags: []", out)
        self.assertIn("type: system", out)

    def test_missing_key_is_inserted(self):
        out = write_tags("---\ntype: system\n---\nbody\n", ["ai/general"])
        self.assertIn("tags: [ai/general]", out)
        self.assertIn("type: system", out)

    def test_no_frontmatter_gets_one(self):
        out = write_tags("just a body\n", ["ai/general"])
        self.assertTrue(out.startswith("---\ntags: [ai/general]\n---\n"))
        self.assertTrue(out.endswith("just a body\n"))

    def test_body_and_other_keys_survive_a_round_trip(self):
        content = ("---\ntype: decision\ntags: [a]\nsources:\n  - id: s1\n"
                   '    resource: "raw/notes/x.md"\n---\nclaim [^s1] ^anchor\n')
        out = write_tags(content, ["process/architecture"])
        self.assertIn("sources:\n  - id: s1\n", out)
        self.assertIn('    resource: "raw/notes/x.md"', out)
        self.assertIn("claim [^s1] ^anchor", out)

    def test_parse_after_write_round_trips(self):
        for start in ('---\ntags: [a, b]\n---\nx\n',
                      '---\ntags:\n  - a\n  - b\n---\nx\n',
                      '---\ntags: a b\n---\nx\n'):
            out = write_tags(start, ["map/hd-map", "process/testing"])
            fm, _ = split_document(out)
            self.assertEqual(parse_tags(fm), ["map/hd-map", "process/testing"], start)


class FrontmatterBackupTest(VaultFixtureMixin, unittest.TestCase):
    def test_restore_puts_back_the_original_frontmatter(self):
        original = "---\ntype: system\ntags: [megacorp]\n---\nbody\n"
        path = self.write("wiki/systems/A.md", original)
        record = frontmatter_backup_record(path, self.root, original)
        path.write_text(write_tags(original, ["system/a"]), encoding="utf-8")
        self.assertEqual(restore_frontmatter(record, self.root), "restored")
        self.assertEqual(self.read("wiki/systems/A.md"), original)

    def test_refuses_when_the_body_changed_since_the_backup(self):
        original = "---\ntags: [megacorp]\n---\nbody\n"
        path = self.write("wiki/systems/A.md", original)
        record = frontmatter_backup_record(path, self.root, original)
        path.write_text("---\ntags: [system/a]\n---\nDIFFERENT body\n", encoding="utf-8")
        self.assertEqual(restore_frontmatter(record, self.root), "mismatch")
        self.assertIn("DIFFERENT", self.read("wiki/systems/A.md"))

    def test_unchanged_and_missing(self):
        original = "---\ntags: [a]\n---\nbody\n"
        path = self.write("wiki/systems/A.md", original)
        record = frontmatter_backup_record(path, self.root, original)
        self.assertEqual(restore_frontmatter(record, self.root), "unchanged")
        path.unlink()
        self.assertEqual(restore_frontmatter(record, self.root), "missing")


class NonNoteFileTest(VaultFixtureMixin, unittest.TestCase):
    """Structural files sit among the notes but must never be tagged."""

    def setUp(self):
        super().setUp()
        self.write("wiki/systems/Real.md", "---\ntags: [a]\n---\nbody\n")
        for name in ("index.md", "CLAUDE.md", "README.md",
                     "RELEASE-NOTES.md", "AGENTS.md", "BACKLOG.md"):
            self.write(f"wiki/systems/{name}", "# heading\n")

    def test_iter_notes_skips_them(self):
        found = {p.name for p in iter_notes(self.root)}
        self.assertEqual(found, {"Real.md"})

    def test_escaping_still_reaches_them(self):
        # A stray hashtag in README.md does pollute Obsidian's tag pane, so the
        # escape phase's wider walk must still see these files.
        names = {p.name for p in iter_vault_md(self.root)}
        self.assertIn("README.md", names)
        self.assertIn("index.md", names)


class NoFrontmatterBackupTest(VaultFixtureMixin, unittest.TestCase):
    """A note that had no frontmatter must still be revertible."""

    def test_restore_removes_a_frontmatter_block_that_was_added(self):
        original = "# A heading\n\nbody\n"
        path = self.write("raw/notes/A.md", original)
        record = frontmatter_backup_record(path, self.root, original)
        self.assertFalse(record["had_frontmatter"])
        path.write_text(write_tags(original, ["ai/general"]), encoding="utf-8")
        self.assertIn("tags: [ai/general]", self.read("raw/notes/A.md"))
        self.assertEqual(restore_frontmatter(record, self.root), "restored")
        self.assertEqual(self.read("raw/notes/A.md"), original)

    def test_old_records_without_the_flag_are_inferred(self):
        original = "# A heading\n\nbody\n"
        path = self.write("raw/notes/A.md", original)
        record = frontmatter_backup_record(path, self.root, original)
        del record["had_frontmatter"]          # a record written before the fix
        path.write_text(write_tags(original, ["ai/general"]), encoding="utf-8")
        self.assertEqual(restore_frontmatter(record, self.root), "restored")
        self.assertEqual(self.read("raw/notes/A.md"), original)
