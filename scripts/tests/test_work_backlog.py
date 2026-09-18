"""Tests for lib.work_backlog and the three work-backlog.py modes.

Every fixture topic is invented (Alpha, Beta, …) — the real `work/` pages are
never read here, and nothing about them is asserted.
"""

import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.work_backlog import (  # noqa: E402
    PORTFOLIO_CAP,
    PeriodError,
    all_section_spans,
    archive_done,
    compile_backlog,
    compile_recap,
    delegated_lines,
    deadline_lines,
    load_snapshots,
    load_topics,
    next_action_lines,
    overdue_lines,
    parse_frontmatter,
    parse_period,
    parse_topic,
    parse_week_stem,
    portfolio_lines,
    section_spans,
    smell_lines,
    snapshot_at,
    split_delegated,
    split_lines,
    unlinkable,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "work-backlog.py"
TODAY = date(2026, 3, 10)
LS = "\u2028"     # a line separator str.splitlines() would break on


def topic_page(name, status="active", horizon="now", progress="Something moved.",
               next_review="2026-04-01", deadline=None, me=(), delegated=(),
               log=("- 2026-03-02 — topic opened",), extra_sections="",
               stakeholders='["[[Someone]]", "Some Group"]'):
    """One synthetic topic page. Keep the shape, invent the content."""
    front = [
        "---",
        "type: topic",
        f"status: {status}",
        f"horizon: {horizon}",
        "lever: throughput",
        'goal: "[[Some Goal (2026)]]"',
        f"stakeholders: {stakeholders}",
        f'progress: "{progress}"' if progress else 'progress: ""',
        f"next_review: {next_review}",
    ]
    if deadline:
        front.append(f"deadline: {deadline}")
    front += ['related: ["[[Beta]]"]', "date: 2026-03-01", "---"]
    body = [
        f"# {name}",
        "",
        "## Why it matters",
        "",
        "Because the fixture says so.",
        "",
        "## My role",
        "",
        "Owner.",
        "",
    ]
    if extra_sections:
        body += [extra_sections, ""]
    body += ["## Next actions (me)", ""] + list(me) + [""]
    body += ["## Delegated", ""] + list(delegated) + [""]
    body += ["## Log", ""] + list(log) + [""]
    return "\n".join(front + body)


class FrontmatterTest(unittest.TestCase):
    def test_scalars_lists_and_quotes(self):
        data = parse_frontmatter(topic_page("Alpha"))
        self.assertEqual(data["type"], "topic")
        self.assertEqual(data["goal"], "[[Some Goal (2026)]]")
        self.assertEqual(data["stakeholders"], ["[[Someone]]", "Some Group"])
        self.assertEqual(data["related"], ["[[Beta]]"])

    def test_block_list_and_empty_list(self):
        content = ('---\ntype: topic\nstakeholders:\n  - "[[Someone]]"\n'
                   '  - Some Group\nrelated: []\n---\nbody\n')
        data = parse_frontmatter(content)
        self.assertEqual(data["stakeholders"], ["[[Someone]]", "Some Group"])
        self.assertEqual(data["related"], [])

    def test_no_frontmatter(self):
        self.assertEqual(parse_frontmatter("# Alpha\n"), {})

    def test_block_list_written_flush_against_the_margin(self):
        content = ('---\ntype: topic\nstakeholders:\n- "[[Someone]]"\n- Some Group\n'
                   'status: active\n---\nbody\n')
        data = parse_frontmatter(content)
        self.assertEqual(data["stakeholders"], ["[[Someone]]", "Some Group"])
        self.assertEqual(data["status"], "active")

    def test_a_list_item_containing_a_colon_stays_an_item(self):
        data = parse_frontmatter("---\ntype: topic\nrelated:\n- A: B\n---\nbody\n")
        self.assertEqual(data["related"], ["A: B"])
        self.assertNotIn("- A", data)

    def test_inline_comments_are_dropped(self):
        data = parse_frontmatter(
            '---\ntype: topic  # personal topic\nstatus: done # x\n'
            'progress: "a # b"\nhorizon: #later\nstakeholders:\n'
            '  - Some Group  # the whole group\n---\nbody\n')
        self.assertEqual(data["type"], "topic")
        self.assertEqual(data["status"], "done")
        self.assertEqual(data["progress"], "a # b")     # quoted: kept
        self.assertEqual(data["horizon"], "#later")     # no space before it: kept
        self.assertEqual(data["stakeholders"], ["Some Group"])

    def test_a_nested_mapping_stays_nested(self):
        # The defect: the children of a key with no scalar of its own were
        # promoted to the top level, so a page carrying a `meta:` block with
        # `status: done` under it read as a finished topic.
        data = parse_frontmatter(
            '---\ntype: topic\nmeta:\n  status: done\n  owner: Pat\n'
            'status: active\nrelated:\n  - "[[Beta]]"\n---\nbody\n')
        self.assertEqual(data["status"], "active")
        self.assertEqual(data["meta"], [])
        self.assertNotIn("owner", data)
        self.assertEqual(data["related"], ["[[Beta]]"])

    def test_a_list_inside_a_nested_mapping_is_not_the_parents_list(self):
        data = parse_frontmatter(
            "---\ntype: topic\nmeta:\n  tags:\n    - one\nstatus: active\n"
            "---\nbody\n")
        self.assertEqual(data["meta"], [])
        self.assertEqual(data["status"], "active")
        self.assertNotIn("tags", data)

    def test_bom_and_a_closing_delimiter_at_end_of_file(self):
        self.assertEqual(parse_frontmatter("﻿---\ntype: topic\n---\nbody\n"),
                         {"type": "topic"})
        self.assertEqual(parse_frontmatter("---\ntype: topic\nstatus: active\n---"),
                         {"type": "topic", "status": "active"})
        self.assertEqual(parse_frontmatter("---\r\ntype: topic\r\n---\r\nbody\r\n"),
                         {"type": "topic"})


class WeekStemTest(unittest.TestCase):
    """The one validator for a `work/weekly/` filename, shared with
    `lib.work_weekly.newest_weekly`."""

    def test_a_real_iso_week_prefix_and_nothing_else(self):
        self.assertEqual(parse_week_stem("2026-W11"), (2026, 11))
        self.assertEqual(parse_week_stem("2026-w11 review"), (2026, 11))
        self.assertEqual(parse_week_stem("2026-W1"), (2026, 1))
        for stem in ("2026-W99", "2026-W00", "2026-w111", "2026-11",
                     "not-a-week", ""):
            with self.subTest(stem=stem):
                self.assertIsNone(parse_week_stem(stem))


class SectionAndTaskTest(VaultFixtureMixin, unittest.TestCase):
    def test_deeper_headings_and_fences_stay_inside_a_section(self):
        lines = ("## One\n### Sub\ntext\n```\n## Not a heading\n```\n## Two\ntail\n"
                 ).splitlines()
        spans = section_spans(lines)
        self.assertEqual(sorted(spans), ["One", "Two"])
        self.assertEqual(lines[spans["One"][0]:spans["One"][1]],
                         ["### Sub", "text", "```", "## Not a heading", "```"])

    def test_delegated_name_parsing_both_dash_styles(self):
        self.assertEqual(split_delegated("@Pat — write the brief"),
                         ("Pat", "write the brief"))
        self.assertEqual(split_delegated("@Robin - run the pilot"),
                         ("Robin", "run the pilot"))
        self.assertEqual(split_delegated("@Robin – en dash"), ("Robin", "en dash"))
        person, text = split_delegated("nobody owns this")
        self.assertIsNone(person)
        self.assertEqual(text, "nobody owns this")

    def test_lines_are_split_on_the_files_own_newline_only(self):
        lines, newline, trailing = split_lines("a\r\nb\r\n")
        self.assertEqual((lines, newline, trailing), (["a", "b"], "\r\n", True))
        lines, newline, trailing = split_lines("one two\nthree")
        self.assertEqual((lines, newline, trailing),
                         (["one two", "three"], "\n", False))

    def test_checkboxes_in_code_blocks_are_not_tasks(self):
        page = topic_page("Alpha", me=[
            "- [ ] real action",
            "",
            "```markdown",
            "- [ ] documentation, not a task",
            "```",
            "",
            "Sample:",
            "",
            "        - [ ] indented code sample",
        ])
        topic = parse_topic(self.write("Alpha.md", page))
        self.assertEqual([t.text for t in topic.my_tasks], ["real action"])

    def test_a_duplicate_heading_is_read_and_flagged(self):
        page = ("---\ntype: topic\n---\n# Alpha\n\n## Next actions (me)\n\n- [ ] first\n\n"
                "## Notes\n\nstuff\n\n## Next actions (me)\n\n- [ ] second\n")
        lines = page.splitlines()
        self.assertEqual(len(all_section_spans(lines)["Next actions (me)"]), 2)
        # The first span is what the back-compatible view reports.
        self.assertEqual(section_spans(lines)["Next actions (me)"],
                         all_section_spans(lines)["Next actions (me)"][0])
        topic = parse_topic(self.write("Dup.md", page))
        self.assertEqual([t.text for t in topic.my_tasks], ["first", "second"])
        self.assertIn("duplicate heading `## Next actions (me)`", topic.smells)

    def test_an_unclosed_fence_does_not_hide_the_sections_below_it(self):
        page = ("---\ntype: topic\n---\n# Alpha\n\n```mermaid\ngraph TD; A-->B;\n\n"
                "## Next actions (me)\n\n- [ ] still visible\n\n"
                "## Log\n\n- 2026-03-01 — opened\n")
        self.assertIn("Next actions (me)", section_spans(page.splitlines()))
        topic = parse_topic(self.write("Unclosed.md", page))
        self.assertEqual([t.text for t in topic.my_tasks], ["still visible"])
        self.assertEqual([e.day for e in topic.log], [date(2026, 3, 1)])
        self.assertIn("unclosed code fence", topic.smells)
        self.assertIn("unclosed code fence", "\n".join(smell_lines([topic])))

    def test_log_and_snapshot_lines_take_any_of_the_three_dashes(self):
        for dash in ("—", "–", "-"):
            with self.subTest(dash=dash):
                page = topic_page("Alpha", log=[f"- 2026-03-02 {dash} a note"])
                topic = parse_topic(self.write("Alpha.md", page))
                self.assertEqual([(e.day, e.text) for e in topic.log],
                                 [(date(2026, 3, 2), "a note")])
                self.write("work/weekly/2026-W10.md",
                           f"# Weekly\n\n## Snapshot\n\n- [[Alpha]] {dash} going well\n")
                self.assertEqual(load_snapshots(self.root)[date(2026, 3, 2)],
                                 {"Alpha": "going well"})

    def test_unlinkable_filenames_are_flagged(self):
        self.assertEqual(unlinkable("Plain Name"), "")
        for name in ("Roadmap #1", "Alpha|Beta", "Trailing "):
            with self.subTest(name=name):
                self.assertTrue(unlinkable(name))
                topic = parse_topic(self.write(f"{name}.md", topic_page(name)))
                self.assertIn(f"- `{name}` — unlinkable filename: contains",
                              "\n".join(smell_lines([topic])))

    def test_tasks_outside_the_known_sections_are_ignored(self):
        page = topic_page(
            "Alpha",
            me=["- [ ] mine"],
            extra_sections="## Candidates\n\n- [ ] not a next action\n",
        )
        topic = parse_topic(self.write("Alpha.md", page))
        self.assertEqual([t.text for t in topic.my_tasks], ["mine"])


class VaultTest(VaultFixtureMixin, unittest.TestCase):
    """A four-topic vault used by the projection and CLI tests."""

    def setUp(self):
        super().setUp()
        self.write("work/topics/Alpha.md", topic_page(
            "Alpha", horizon="now", next_review="2026-03-01",
            me=["- [ ] first alpha action", "- [x] already done", "- [ ] second"],
            delegated=["- [ ] @Pat — draft the brief", "- [x] @Pat — old thing"],
            log=["- 2026-03-02 — topic opened", "- 2026-02-10 — earlier note"],
        ))
        self.write("work/topics/Beta.md", topic_page(
            "Beta", horizon="later", deadline="2026-03-20",
            me=["- [ ] beta action"],
            delegated=["- [ ] @Robin - run the pilot"],
        ))
        self.write("work/topics/Gamma.md", topic_page(
            "Gamma", horizon="next", progress="", next_review="not-a-date",
            me=[], delegated=[],
        ))
        self.write("work/topics/Delta.md", topic_page(
            "Delta", status="parked", horizon="later",
            progress="Parked until later.", me=["- [ ] parked action"],
        ))
        # Not a topic page: must be skipped, not guessed at.
        self.write("work/topics/index.md", "---\ntype: index\n---\n# Topics\n")
        self.topics = load_topics(self.root)

    def test_load_skips_non_topic_pages(self):
        self.assertEqual([t.name for t in self.topics],
                         ["Alpha", "Beta", "Delta", "Gamma"])

    def test_portfolio_order_and_next_action(self):
        lines = portfolio_lines(self.topics)
        self.assertEqual(len(lines), 3)  # Delta is parked
        self.assertTrue(lines[0].startswith("- **[[Alpha]]**"))    # now
        self.assertTrue(lines[1].startswith("- **[[Gamma]]**"))    # next
        self.assertTrue(lines[2].startswith("- **[[Beta]]**"))     # later
        self.assertIn("*next:* first alpha action", lines[0])
        self.assertIn("*next:* (no next action)", lines[1])

    def test_portfolio_cap_warning(self):
        for n in range(PORTFOLIO_CAP):
            self.write(f"work/topics/Extra {n}.md", topic_page(f"Extra {n}"))
        lines = portfolio_lines(load_topics(self.root))
        self.assertIn(f"Portfolio has {PORTFOLIO_CAP + 3} topics; merge or park.",
                      lines[-1])

    def test_no_cap_warning_under_the_cap(self):
        self.assertFalse(any("merge or park" in line
                             for line in portfolio_lines(self.topics)))

    def test_next_actions_grouped_by_horizon(self):
        lines = next_action_lines(self.topics)
        self.assertEqual([line for line in lines if line.startswith("### ")],
                         ["### now", "### next", "### later"])
        now_block = lines[lines.index("### now"):lines.index("### next")]
        self.assertIn("- [ ] first alpha action — [[Alpha]]", now_block)
        self.assertIn("- [ ] second — [[Alpha]]", now_block)
        # Checked items never appear, parked topics still contribute actions.
        self.assertFalse(any("already done" in line for line in lines))
        self.assertTrue(any("parked action — [[Delta]]" in line for line in lines))

    def test_delegated_grouped_by_person(self):
        lines = delegated_lines(self.topics)
        self.assertEqual([line for line in lines if line.startswith("### ")],
                         ["### @Pat", "### @Robin"])
        self.assertIn("- [ ] draft the brief — [[Alpha]]", lines)
        self.assertIn("- [ ] run the pilot — [[Beta]]", lines)
        self.assertFalse(any("old thing" in line for line in lines))

    def test_overdue_review_oldest_first(self):
        lines = overdue_lines(self.topics, TODAY)
        self.assertEqual(len(lines), 1)
        self.assertIn("[[Alpha]] — due 2026-03-01 (9 days)", lines[0])

    def test_deadline_window(self):
        self.assertEqual(len(deadline_lines(self.topics, TODAY)), 1)
        # Outside the six-week window in either direction: nothing.
        self.assertEqual(deadline_lines(self.topics, date(2026, 1, 1)), [])
        self.assertEqual(deadline_lines(self.topics, date(2026, 4, 1)), [])

    def test_deadline_window_is_inclusive_at_both_ends(self):
        self.write("work/topics/Edge.md", topic_page("Edge", deadline="2026-03-10"))
        self.write("work/topics/Far.md", topic_page("Far", deadline="2026-04-21"))
        self.write("work/topics/Past.md", topic_page("Past", deadline="2026-03-09"))
        self.write("work/topics/Late.md", topic_page("Late", deadline="2026-04-22"))
        lines = "\n".join(deadline_lines(load_topics(self.root), TODAY))
        self.assertIn("[[Edge]] — deadline 2026-03-10 (in 0 days)", lines)
        self.assertIn("[[Far]] — deadline 2026-04-21 (in 42 days)", lines)
        self.assertNotIn("[[Past]]", lines)
        self.assertNotIn("[[Late]]", lines)

    def test_a_review_due_today_is_not_yet_overdue(self):
        self.write("work/topics/Today.md", topic_page("Today", next_review="2026-03-10"))
        lines = "\n".join(overdue_lines(load_topics(self.root), TODAY))
        self.assertNotIn("[[Today]]", lines)
        self.assertIn("[[Alpha]]", lines)      # due 2026-03-01

    def test_portfolio_sorts_by_name_inside_a_horizon(self):
        self.write("work/topics/Aardvark.md", topic_page("Aardvark", horizon="now"))
        lines = portfolio_lines(load_topics(self.root))
        self.assertTrue(lines[0].startswith("- **[[Aardvark]]**"))
        self.assertTrue(lines[1].startswith("- **[[Alpha]]**"))

    def test_smells(self):
        lines = "\n".join(smell_lines(self.topics))
        self.assertIn("[[Gamma]] — active with no unchecked action of mine", lines)
        self.assertIn("[[Gamma]] — no `progress`", lines)
        self.assertIn("[[Gamma]] — `next_review` malformed: `not-a-date`", lines)
        self.assertNotIn("[[Alpha]]", lines)

    def test_compiled_document_structure(self):
        text = compile_backlog(self.topics, TODAY, "cmd")
        self.assertTrue(text.startswith("> [!info] Generated file\n> Compiled by `cmd` on 2026-03-10"))
        self.assertNotIn("<!--", text)
        headings = [line for line in text.splitlines() if line.startswith("## ")]
        self.assertEqual(headings, [
            "## Portfolio", "## Next actions (me)", "## Delegated",
            "## Overdue review", "## Deadlines within 6 weeks",
            "## Smells", "## Watching and parked",
        ])
        self.assertIn("- [[Delta]] (parked) — Parked until later.", text)

    def test_empty_sections_say_none(self):
        text = compile_backlog([t for t in self.topics if t.name == "Gamma"],
                               TODAY, "cmd")
        self.assertIn("## Delegated\n\n- (none)\n", text)

    # ---------------------------------------------------------------- CLI

    def _run(self, *args):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--vault", str(self.root), *args],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_cli_compile_writes_backlog(self):
        self._run("--today", "2026-03-10")
        text = self.read("work/Backlog.md")
        self.assertIn("## Portfolio", text)
        self.assertIn("Compiled by `scripts/work-backlog.py` on 2026-03-10", text)

    def test_cli_dry_run_writes_nothing(self):
        out = self._run("--today", "2026-03-10", "--dry-run")
        self.assertIn("## Portfolio", out)
        self.assertFalse((self.root / "work" / "Backlog.md").exists())

    def test_cli_rejects_bad_today(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--vault", str(self.root), "--today", "yesterday"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 2)

    def test_cli_archive_done_is_idempotent(self):
        first = self._run("--archive-done", "2026-03-10")
        self.assertIn("2 moved to ## Log", first)
        text = self.read("work/topics/Alpha.md")
        self.assertIn("- 2026-03-10 — done: already done", text)
        self.assertIn("- 2026-03-10 — done: @Pat — old thing", text)
        self.assertNotIn("- [x]", text)
        self.assertIn("- [ ] first alpha action", text)

        second = self._run("--archive-done", "2026-03-11")
        self.assertIn("no checked boxes to archive", second)
        self.assertEqual(text, self.read("work/topics/Alpha.md"))

    def _page_bytes(self):
        folder = self.root / "work" / "topics"
        return {p.name: p.read_bytes() for p in sorted(folder.glob("*.md"))}

    def test_cli_archive_dry_run_leaves_every_page_byte_identical(self):
        before = self._page_bytes()
        out = self._run("--archive-done", "2026-03-10", "--dry-run")
        self.assertIn("2 items would move", out)
        self.assertEqual(before, self._page_bytes())

    def test_cli_archive_skips_a_page_that_is_not_utf8(self):
        # A latin-1 é: readable enough to compile from, never safe to rewrite.
        raw = ("---\ntype: topic\nstatus: active\nprogress: \"p\"\n"
               "next_review: 2026-04-01\n---\n# Caf\xe9\n\n## Next actions (me)\n\n"
               "- [x] visit the caf\xe9\n\n## Log\n\n- 2026-03-01 - opened\n"
               ).encode("latin-1")
        self.write_bytes("work/topics/Cafe.md", raw)
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--vault", str(self.root),
             "--archive-done", "2026-03-10"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("not valid UTF-8", result.stderr)
        self.assertIn("1 page(s) skipped", result.stdout)
        self.assertEqual((self.root / "work/topics/Cafe.md").read_bytes(), raw)
        # The other pages are still archived.
        self.assertIn("- 2026-03-10 — done: already done",
                      self.read("work/topics/Alpha.md"))

    def test_cli_recap_writes_file(self):
        self._run("--recap", "2026-03")
        text = self.read("work/recaps/2026-03.md")
        self.assertIn("### [[Alpha]]", text)
        self.assertIn("- 2026-03-02 — topic opened", text)
        self.assertNotIn("2026-02-10", text)   # outside the period


class ArchiveDoneTest(unittest.TestCase):
    def test_preserves_surrounding_text_and_appends_to_log(self):
        page = topic_page(
            "Alpha",
            me=["- [ ] keep me", "- [x] done one"],
            delegated=["- [x] @Pat — done two"],
            extra_sections="## Candidates\n\n| a | b |\n|---|---|\n| 1 | 2 |\n",
        )
        new, moved = archive_done(page, "2026-03-10")
        self.assertEqual(moved, ["done one", "@Pat — done two"])
        self.assertIn("| a | b |", new)
        self.assertIn("Because the fixture says so.", new)
        self.assertIn("- [ ] keep me", new)
        self.assertTrue(new.endswith("- 2026-03-10 — done: @Pat — done two\n"))
        self.assertEqual(archive_done(new, "2026-03-11"), (new, []))

    def test_creates_a_log_section_when_missing(self):
        page = ("---\ntype: topic\n---\n# Alpha\n\n## Next actions (me)\n\n"
                "- [x] done one\n")
        new, moved = archive_done(page, "2026-03-10")
        self.assertEqual(moved, ["done one"])
        self.assertIn("## Log\n\n- 2026-03-10 — done: done one", new)

    def test_nothing_checked_returns_the_input_unchanged(self):
        page = topic_page("Alpha", me=["- [ ] open"])
        self.assertEqual(archive_done(page, "2026-03-10"), (page, []))

    def test_a_checked_box_moves_with_its_children(self):
        page = ("---\ntype: topic\n---\n# Alpha\n\n## Next actions (me)\n\n"
                "- [x] Ship the thing\n    - sub-detail\n    - second sub-detail\n"
                "  because reasons (lazy continuation)\n- [ ] Keep going\n\n"
                "## Log\n\n- 2026-03-01 — opened\n")
        new, moved = archive_done(page, "2026-03-10")
        self.assertEqual(moved, ["Ship the thing"])
        self.assertEqual(new, (
            "---\ntype: topic\n---\n# Alpha\n\n## Next actions (me)\n\n"
            "- [ ] Keep going\n\n"
            "## Log\n\n- 2026-03-01 — opened\n"
            "- 2026-03-10 — done: Ship the thing\n"
            "    - sub-detail\n    - second sub-detail\n"
            "  because reasons (lazy continuation)\n"))
        self.assertEqual(archive_done(new, "2026-03-11"), (new, []))

    def test_only_top_level_checkboxes_are_archived(self):
        page = ("---\ntype: topic\n---\n# Alpha\n\n## Next actions (me)\n\n"
                "- [ ] Keep going\n    - [x] a finished subtask\n\n"
                "## Log\n\n- 2026-03-01 — opened\n")
        self.assertEqual(archive_done(page, "2026-03-10"), (page, []))

    def test_checked_boxes_inside_code_never_move(self):
        page = ("---\ntype: topic\n---\n# Alpha\n\n## Next actions (me)\n\n"
                "- [ ] real action\n\n```markdown\n- [x] documentation\n```\n\n"
                "Sample:\n\n        - [x] indented code sample\n\n"
                "> - [x] quoted from a mail\n\n| task | state |\n|---|---|\n"
                "| - [x] table cell | n/a |\n\n## Log\n\n- 2026-03-01 — opened\n")
        self.assertEqual(archive_done(page, "2026-03-10"), (page, []))

    def test_both_spans_of_a_duplicated_section_are_archived(self):
        page = ("---\ntype: topic\n---\n# Alpha\n\n## Next actions (me)\n\n"
                "- [x] first\n\n## Notes\n\nstuff\n\n## Next actions (me)\n\n"
                "- [x] second\n- [ ] open\n\n## Log\n\n- 2026-03-01 — opened\n")
        new, moved = archive_done(page, "2026-03-10")
        self.assertEqual(moved, ["first", "second"])
        self.assertNotIn("- [x]", new)
        self.assertIn("stuff", new)

    def test_an_unclosed_fence_does_not_hide_the_checked_boxes(self):
        page = ("---\ntype: topic\n---\n# Alpha\n\n```mermaid\ngraph TD; A-->B;\n\n"
                "## Next actions (me)\n\n- [x] archive me\n- [ ] open\n\n"
                "## Log\n\n- 2026-03-01 — opened\n")
        new, moved = archive_done(page, "2026-03-10")
        self.assertEqual(moved, ["archive me"])
        self.assertIn("graph TD; A-->B;", new)

    def test_crlf_and_exotic_separators_survive_the_surgery(self):
        page = ("---\r\ntype: topic\r\n---\r\n# Alpha\r\n\r\n## Next actions (me)\r\n"
                f"\r\n- [x] done one\r\n- [ ] para one{LS}para two\r\n\r\n"
                "## Log\r\n\r\n- 2026-03-01 — opened\r\n")
        new, moved = archive_done(page, "2026-03-10")
        self.assertEqual(moved, ["done one"])
        # Every LF is still half of a CRLF, and U+2028 is still just a character.
        self.assertEqual(new.count("\n"), new.count("\r\n"))
        self.assertEqual(new.count(LS), 1)
        self.assertIn(f"- [ ] para one{LS}para two\r\n", new)
        self.assertIn("- 2026-03-10 — done: done one\r\n", new)
        # Byte-identical apart from the line that moved.
        self.assertEqual([line for line in page.split("\r\n") if "done one" not in line],
                         [line for line in new.split("\r\n") if "done one" not in line])

    def test_log_entries_land_before_a_following_section(self):
        page = ("---\ntype: topic\n---\n# Alpha\n\n## Next actions (me)\n\n"
                "- [x] done one\n\n## Log\n\n- 2026-03-01 — opened\n\n"
                "## Afterwards\n\ntail text\n")
        new, _ = archive_done(page, "2026-03-10")
        lines = new.splitlines()
        self.assertLess(lines.index("- 2026-03-10 — done: done one"),
                        lines.index("## Afterwards"))
        self.assertTrue(new.endswith("tail text\n"))


class PeriodTest(unittest.TestCase):
    def test_month(self):
        self.assertEqual(parse_period("2026-02", TODAY),
                         ("2026-02", date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(parse_period("2026-12", TODAY)[2], date(2026, 12, 31))

    def test_week_and_week_range(self):
        label, start, end = parse_period("2026-W10", TODAY)
        self.assertEqual((label, start, end),
                         ("2026-W10", date(2026, 3, 2), date(2026, 3, 8)))
        label, start, end = parse_period("2026-W10..W12", TODAY)
        self.assertEqual((label, start, end),
                         ("2026-W10..W12", date(2026, 3, 2), date(2026, 3, 22)))
        self.assertEqual(parse_period("2026-W10..12", TODAY)[0], "2026-W10..W12")

    def test_relative_forms_resolve_to_absolute_labels(self):
        self.assertEqual(parse_period("last-month", TODAY),
                         ("2026-02", date(2026, 2, 1), date(2026, 2, 28)))
        label, start, end = parse_period("last-week", TODAY)
        self.assertEqual((label, start, end),
                         ("2026-W10", date(2026, 3, 2), date(2026, 3, 8)))

    def test_last_month_crosses_the_year(self):
        self.assertEqual(parse_period("last-month", date(2026, 1, 15))[0], "2025-12")

    def test_rejects_nonsense(self):
        for bad in ("2026-13", "2026-W99", "2026-W12..W10", "yesterday", ""):
            with self.subTest(bad=bad), self.assertRaises(PeriodError):
                parse_period(bad, TODAY)


class RecapTest(VaultFixtureMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.write("work/topics/Alpha.md", topic_page(
            "Alpha", progress="Still going.",
            log=["- 2026-03-02 — said something", "- 2026-01-04 — long ago"]))
        self.write("work/topics/Beta.md", topic_page(
            "Beta", log=["- 2026-01-04 — nothing since"]))
        self.write("work/topics/Gamma.md", topic_page(
            "Gamma", status="done", progress="Closed.",
            log=["- 2026-03-05 — done: handed over"]))
        self.topics = load_topics(self.root)

    def test_only_topics_with_in_period_activity(self):
        text = compile_recap(self.topics, "2026-03", date(2026, 3, 1),
                             date(2026, 3, 31), "cmd")
        self.assertIn("### [[Alpha]]", text)
        self.assertNotIn("### [[Beta]]", text)
        self.assertIn("- progress (current): Still going.", text)
        self.assertIn("    - 2026-03-02 — said something", text)
        self.assertNotIn("long ago", text)

    def test_done_topics_go_last_under_closed(self):
        text = compile_recap(self.topics, "2026-03", date(2026, 3, 1),
                             date(2026, 3, 31), "cmd")
        self.assertLess(text.index("### [[Alpha]]"), text.index("## Closed in period"))
        self.assertGreater(text.index("### [[Gamma]]"), text.index("## Closed in period"))

    def test_snapshot_line_appears_only_when_a_snapshot_exists(self):
        without = compile_recap(self.topics, "2026-03", date(2026, 3, 1),
                                date(2026, 3, 31), "cmd", {})
        self.assertNotIn("progress at start of period", without)

        self.write("work/weekly/2026-W08.md",
                   "# Weekly\n\n## Snapshot\n\n- [[Alpha]] — was starting out\n")
        self.write("work/weekly/2026-W20.md",
                   "# Weekly\n\n## Snapshot\n\n- [[Alpha]] — much later\n")
        snapshots = load_snapshots(self.root)
        self.assertEqual(sorted(snapshots), [date(2026, 2, 16), date(2026, 5, 11)])
        # The newest snapshot at or before the period start wins.
        picked = snapshot_at(snapshots, date(2026, 3, 1))
        self.assertEqual(picked, {"Alpha": "was starting out"})
        with_snapshot = compile_recap(self.topics, "2026-03", date(2026, 3, 1),
                                      date(2026, 3, 31), "cmd", picked)
        self.assertIn("- progress at start of period: was starting out", with_snapshot)

    def test_closed_in_period_needs_no_keyword(self):
        self.write("work/topics/Quiet.md", topic_page(
            "Quiet", status="done", progress="Closed.",
            log=["- 2026-02-20 — still working", "- 2026-03-04 — handed over"]))
        text = compile_recap(load_topics(self.root), "2026-03", date(2026, 3, 1),
                             date(2026, 3, 31), "cmd")
        closed = text[text.index("## Closed in period"):]
        self.assertIn("### [[Quiet]]", closed)
        self.assertIn("    - 2026-03-04 — handed over", closed)

    def test_a_topic_closed_before_the_period_is_not_reported_in_it(self):
        self.write("work/topics/Old.md", topic_page(
            "Old", status="done", progress="Closed.",
            log=["- 2026-01-09 — done: wrapped up"]))
        text = compile_recap(load_topics(self.root), "2026-03", date(2026, 3, 1),
                             date(2026, 3, 31), "cmd")
        self.assertNotIn("[[Old]]", text)

    def test_a_done_topic_that_kept_logging_after_the_period_shows_progress(self):
        self.write("work/topics/Trailing On.md", topic_page(
            "Trailing On", status="done", progress="Closed later.",
            log=["- 2026-03-04 — a step", "- 2026-05-06 — done: much later"]))
        text = compile_recap(load_topics(self.root), "2026-03", date(2026, 3, 1),
                             date(2026, 3, 31), "cmd")
        progress, closed = text.split("## Closed in period")
        self.assertIn("### [[Trailing On]]", progress)
        self.assertNotIn("[[Trailing On]]", closed)

    def test_no_weekly_dir_means_no_snapshots(self):
        self.assertEqual(load_snapshots(self.root), {})
        self.assertEqual(snapshot_at({}, date(2026, 3, 1)), {})


if __name__ == "__main__":
    unittest.main()
