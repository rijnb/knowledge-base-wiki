"""Tests for lib.work_weekly and the work-weekly.py CLI.

Every fixture is invented (Alpha, Beta, @Pat, [[Someone]]) — the real `work/`,
`raw/` and `wiki/` trees are never read here, and nothing about them is
asserted.
"""

import io
import json
import os
import subprocess
import sys
import time
import unittest
from contextlib import redirect_stderr
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.work_backlog import load_snapshots, load_topics, section_spans  # noqa: E402
from lib.work_weekly import (  # noqa: E402
    CLUSTER_MIN,
    EVIDENCE_ATTENDEE,
    EVIDENCE_DIARY,
    EVIDENCE_FROM,
    EVIDENCE_RECIPIENT,
    EVIDENCE_SPEAKER,
    NEVER_CONTACTED,
    NO_CADENCE,
    Haystack,
    RawFile,
    action_link_lines,
    build_packet,
    cadence_lines,
    cadence_rows,
    cluster_links,
    contact_evidence,
    default_since,
    horizon_flag_lines,
    key_hit,
    link_targets,
    load_wiki_changes,
    looks_like_distribution,
    map_raw_to_topics,
    mentions,
    newest_weekly,
    page_body,
    parse_cadence,
    parse_stakeholders,
    phrase_in,
    raw_dirs,
    render_json,
    render_markdown,
    scan_raw,
    shared_interaction_lines,
    speaker_names,
    strip_link,
    topic_keys,
    topic_news_lines,
    week_label,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "work-weekly.py"
TODAY = date(2026, 3, 10)          # a Tuesday, ISO week 11
SINCE = date(2026, 3, 3)
COMMAND = "cmd"


def topic_page(name, status="active", horizon="now", progress="Something moved.",
               goal="[[Some Goal (2026)]]", stakeholders='["[[Someone]]"]',
               related='["[[Beta]]"]', next_review="2026-04-01", deadline=None,
               me=(), log=("- 2026-03-02 — topic opened",)):
    """One synthetic topic page. Keep the shape, invent the content."""
    front = [
        "---",
        "type: topic",
        f"status: {status}",
        f"horizon: {horizon}",
        "lever: throughput",
        f'goal: "{goal}"',
        f"stakeholders: {stakeholders}",
        f'progress: "{progress}"',
        f"next_review: {next_review}",
    ]
    if deadline:
        front.append(f"deadline: {deadline}")
    front += [f"related: {related}", "date: 2026-03-01", "---"]
    body = [f"# {name}", "", "## Why it matters", "", "Because the fixture says so.", ""]
    body += ["## Next actions (me)", ""] + list(me) + [""]
    body += ["## Delegated", ""]
    body += ["## Log", ""] + list(log) + [""]
    return "\n".join(front + body)


def raw_note(day=None, body="Nothing in particular.", **front):
    """One synthetic raw note. `day` is only needed when the filename has none."""
    lines = ["---"]
    if day:
        lines.append(f"date: {day}")
    lines += [f'{key}: "{value}"' for key, value in front.items()]
    lines += ["---", "", body, ""]
    return "\n".join(lines)


STAKEHOLDER_TABLE = """---
date: 2026-03-10
description: "Who needs what from me."
---
# Stakeholders

Update `Last` after each contact.

| Person | Needs from me | Cadence | Channel | Last | Next | Topics |
|---|---|---|---|---|---|---|
| [[Someone]] | a second opinion | weekly, 30 min | 1:1 | — | *book it* | [[Alpha]] |
| [[Another Person]] | alignment | 2-weekly | 1:1 | 2026-03-08 | — | [[Beta]] |
| [[Third Person]] | checkpoints | bi-monthly | Slack | 2026-01-01 | — | [[Alpha]] |
| Some Group | agenda | alternating Tue / Thu | meeting | — | — | [[Beta]] |

## Members

[[Someone]] · [[Another Person]]
"""


# --------------------------------------------------------------------------- #


class HelpersTest(unittest.TestCase):
    def test_strip_link_and_link_targets(self):
        self.assertEqual(strip_link("[[Alpha]]"), "Alpha")
        self.assertEqual(strip_link("[[Alpha|the first one]]"), "Alpha")
        self.assertEqual(strip_link("Some Group"), "Some Group")
        self.assertEqual(
            link_targets("see [[Alpha]] and [[Beta#Why]] and [[Alpha]] again"),
            ["Alpha", "Beta"])
        # Embeds and path-shaped targets are file references, not page names.
        self.assertEqual(link_targets("![[raw/emails/_resources/x.eml]] [[Gamma]]"),
                         ["Gamma"])

    def test_week_label(self):
        self.assertEqual(week_label(TODAY), "2026-W11")
        self.assertEqual(week_label(date(2026, 1, 1)), "2026-W01")

    def test_phrase_matching_is_whole_word_and_normalised(self):
        # The abbreviation that used to match every URL in the vault.
        self.assertFalse(phrase_in("see https://example.test", "TT"))
        self.assertFalse(phrase_in("patch the pipeline", "Pat"))
        self.assertTrue(phrase_in("ask Pat about it", "Pat"))
        self.assertTrue(phrase_in("Pat, and then Sam", "Pat"))
        # A decomposed needle matches a composed haystack and the reverse.
        composed = "V\u00edctor Moreno"
        decomposed = "Vi\u0301ctor Moreno"
        self.assertNotEqual(composed, decomposed)
        self.assertTrue(phrase_in(decomposed, composed))
        self.assertTrue(phrase_in(composed, decomposed))

    def test_page_body_drops_citations(self):
        body = page_body("\n".join([
            "# A Page", "", "It is about Alpha.", "",
            "- [[raw/notes/2026-03-05 Beta review.md]]",
            "[^1]: raw/notes/2026-03-05 Gamma review.md",
            "## Sources", "", "- Delta and more Delta", "",
        ]))
        self.assertIn("It is about Alpha.", body)
        for cited in ("Beta", "Gamma", "Delta"):
            self.assertNotIn(cited, body)


class CadenceParsingTest(unittest.TestCase):
    def test_table(self):
        cases = {
            "weekly, 30 min": 7,
            "Weekly": 7,
            "2-weekly": 14,
            "2 weekly": 14,
            "biweekly": 14,
            "bi-weekly": 14,
            "fortnightly": 14,
            "two-weekly": 14,
            "monthly": 30,
            "bi-monthly": 60,
            "bimonthly": 60,
            "quarterly": 90,
        }
        for text, days in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_cadence(text), days)

    def test_free_text_has_no_cadence(self):
        for text in ("as needed", "steerco cadence", "alternating Tue / Thu", "", None):
            with self.subTest(text=text):
                self.assertIsNone(parse_cadence(text))


class StakeholderTableTest(VaultFixtureMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.write("work/Stakeholders.md", STAKEHOLDER_TABLE)
        self.rows = parse_stakeholders(self.root)

    def test_rows_and_columns(self):
        self.assertEqual([r.person for r in self.rows],
                         ["[[Someone]]", "[[Another Person]]", "[[Third Person]]",
                          "Some Group"])
        first = self.rows[0]
        self.assertEqual(first.names, ["Someone"])
        self.assertEqual(first.needs, "a second opinion")
        self.assertEqual(first.cadence_days, 7)
        self.assertIsNone(first.last)
        self.assertEqual(first.topics, ["Alpha"])
        # A plain-text person cell matches on its own text.
        self.assertEqual(self.rows[3].names, ["Some Group"])
        self.assertEqual(self.rows[1].last, date(2026, 3, 8))

    def test_no_table_means_no_rows_and_one_warning(self):
        self.write("work/Stakeholders.md", "# Stakeholders\n\nnothing here\n")
        noise = io.StringIO()
        with redirect_stderr(noise):
            self.assertEqual(parse_stakeholders(self.root), [])
        self.assertIn("work/Stakeholders.md", noise.getvalue())
        self.assertIn("Cadence", noise.getvalue())
        # A vault with no table at all is a legitimate state, not a warning.
        (self.root / "work" / "Stakeholders.md").unlink()
        noise = io.StringIO()
        with redirect_stderr(noise):
            self.assertEqual(parse_stakeholders(self.root), [])
        self.assertEqual(noise.getvalue(), "")

    def test_a_header_survives_a_stray_line_inside_the_table(self):
        # A wrapped cell or a stray comment used to reset the header, which
        # silently dropped every row after it.
        self.write("work/Stakeholders.md", STAKEHOLDER_TABLE.replace(
            "| [[Third Person]] |",
            "a stray line, not a table row\n| [[Third Person]] |"))
        rows = parse_stakeholders(self.root)
        self.assertIn("[[Third Person]]", [r.person for r in rows])
        self.assertEqual(rows[-1].person, "Some Group")

    def test_a_row_may_lose_its_closing_pipe(self):
        self.write("work/Stakeholders.md", STAKEHOLDER_TABLE.replace(
            "| — | *book it* | [[Alpha]] |", "| — | *book it* | [[Alpha]]"))
        first = parse_stakeholders(self.root)[0]
        self.assertEqual(first.person, "[[Someone]]")
        self.assertEqual(first.topics, ["Alpha"])

    def test_an_escaped_pipe_stays_inside_its_cell(self):
        self.write("work/Stakeholders.md", STAKEHOLDER_TABLE.replace(
            "a second opinion", r"a second opinion \| and a sanity check"))
        first = parse_stakeholders(self.root)[0]
        self.assertEqual(first.needs, "a second opinion | and a sanity check")
        self.assertEqual(first.cadence_days, 7)

    def test_rows_after_a_blank_line_inside_the_table_are_still_parsed(self):
        # The defect: a blank line retired the header, and because a header
        # had already been seen no warning could fire either — every row
        # below the blank line vanished without a word.
        self.write("work/Stakeholders.md", STAKEHOLDER_TABLE.replace(
            "| [[Third Person]] |", "\n| [[Third Person]] |"))
        noise = io.StringIO()
        with redirect_stderr(noise):
            rows = parse_stakeholders(self.root)
        self.assertEqual([r.person for r in rows],
                         ["[[Someone]]", "[[Another Person]]",
                          "[[Third Person]]", "Some Group"])
        self.assertEqual(rows[2].cadence_days, 60)
        self.assertEqual(rows[2].topics, ["Alpha"])
        self.assertEqual(noise.getvalue(), "")

    def test_a_second_table_still_gets_its_own_header(self):
        self.write("work/Stakeholders.md", STAKEHOLDER_TABLE
                   + "\n| Cadence | Person |\n|---|---|\n"
                     "| monthly | [[Fourth Person]] |\n")
        rows = {r.person: r for r in parse_stakeholders(self.root)}
        self.assertEqual(rows["[[Fourth Person]]"].cadence_days, 30)
        self.assertEqual(rows["[[Someone]]"].cadence_days, 7)

    def test_headers_match_case_insensitively_by_prefix(self):
        self.write("work/Stakeholders.md", STAKEHOLDER_TABLE.replace(
            "| Person | Needs from me | Cadence | Channel | Last | Next | Topics |",
            "| PERSON | Needs | Cadence (target) | Channel | Last contact "
            "| Next slot | Topics touched |"))
        first = parse_stakeholders(self.root)[0]
        self.assertEqual(first.needs, "a second opinion")
        self.assertEqual(first.cadence_days, 7)
        self.assertEqual(first.next_raw, "*book it*")
        self.assertEqual(first.topics, ["Alpha"])


class LastContactTest(VaultFixtureMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.write("work/Stakeholders.md", STAKEHOLDER_TABLE)
        self.stakeholders = parse_stakeholders(self.root)

    def _rows(self, raws):
        return {r.person: r for r in cadence_rows(self.stakeholders, raws, TODAY)}

    def test_never_contacted_and_no_cadence(self):
        rows = self._rows([])
        self.assertEqual(rows["[[Someone]]"].status, NEVER_CONTACTED)
        self.assertEqual(rows["Some Group"].status, NO_CADENCE)
        self.assertIsNone(rows["Some Group"].cadence_days)

    def test_overdue_and_due_in(self):
        rows = self._rows([])
        # 2026-03-08 against a 14-day cadence on 2026-03-10.
        self.assertEqual(rows["[[Another Person]]"].status, "due in 12 days")
        self.assertEqual(rows["[[Another Person]]"].evidence, "work/Stakeholders.md")
        # 2026-01-01 against a 60-day cadence: 68 days elapsed.
        self.assertEqual(rows["[[Third Person]]"].status, "overdue by 8 days")

    def test_raw_evidence_wins_when_newer_than_the_table(self):
        self.write("raw/diary/2026-03-09 Someone catch-up.md",
                   raw_note("2026-03-09", "Talked about [[Alpha]]."))
        self.write("raw/emails/2026-03-10 A thread.md",
                   raw_note("2026-03-10", "body", **{"from": "Third Person <t@x>"}))
        raws = scan_raw(self.root, date(2025, 12, 1), TODAY)
        rows = self._rows(raws)
        # Filename evidence, no table date at all.
        self.assertEqual(rows["[[Someone]]"].last, date(2026, 3, 9))
        self.assertEqual(rows["[[Someone]]"].evidence,
                         "raw/diary/2026-03-09 Someone catch-up.md")
        self.assertEqual(rows["[[Someone]]"].status, "due in 6 days")
        # Frontmatter `from:` beats the older table date.
        self.assertEqual(rows["[[Third Person]]"].last, date(2026, 3, 10))
        self.assertEqual(rows["[[Third Person]]"].status, "due in 60 days")

    def test_clips_and_notes_are_not_contact_evidence(self):
        self.write("raw/clips/2026-03-09 An article by Someone.md", raw_note("2026-03-09"))
        raws = scan_raw(self.root, date(2025, 12, 1), TODAY)
        self.assertEqual(self._rows(raws)["[[Someone]]"].status, NEVER_CONTACTED)

    def test_evidence_older_than_the_lookback_is_ignored(self):
        self.write("raw/diary/2025-06-01 Someone catch-up.md", raw_note("2025-06-01"))
        raws = scan_raw(self.root, date(2025, 1, 1), TODAY)
        self.assertEqual(self._rows(raws)["[[Someone]]"].status, NEVER_CONTACTED)

    def test_never_contacted_first_and_no_cadence_last(self):
        # A row with no parsable cadence cannot be late, so it is the one row
        # that needs no decision this week.
        order = [r.person for r in cadence_rows(self.stakeholders, [], TODAY)]
        self.assertEqual(order, ["[[Someone]]",          # never contacted
                                 "[[Third Person]]",     # overdue by 8
                                 "[[Another Person]]",   # due in 12
                                 "Some Group"])          # no fixed cadence

    def test_a_bare_mention_is_reported_but_not_counted_as_contact(self):
        # The defect: any appearance of a name reset the clock. Now a body
        # mention is listed as a weak mention and the person stays uncontacted.
        self.write("raw/notes/2026-03-09 Someone else's notes.md",
                   raw_note("2026-03-09", "Someone was mentioned in passing."))
        raws = scan_raw(self.root, date(2025, 12, 1), TODAY)
        row = self._rows(raws)["[[Someone]]"]
        self.assertEqual(row.status, NEVER_CONTACTED)
        self.assertEqual(row.weak_mentions,
                         ["raw/notes/2026-03-09 Someone else's notes.md"])
        self.assertIn("    - named in 1 files, not counted as contact "
                      "(newest: raw/notes/2026-03-09 Someone else's notes.md)",
                      cadence_lines([row]))

    def test_mentions_reads_the_whole_file_and_matches_whole_words(self):
        raw = RawFile(rel="raw/diary/2026-03-09 catch-up.md", day=date(2026, 3, 9),
                      front={"from": "Another Person <a@x>"}, text="# notes\n\nbody\n")
        self.assertTrue(mentions(raw, "another person"))
        self.assertFalse(mentions(raw, "Someone"))
        # Deep in the body is still a mention — the same haystack the topic
        # mapping uses, so the two can never disagree about one file.
        deep = RawFile(rel="raw/diary/x.md", day=date(2026, 3, 9), front={},
                       text="\n".join(["filler"] * 60 + ["Someone said so"]))
        self.assertTrue(mentions(deep, "Someone"))
        self.assertEqual(contact_evidence(deep, "Someone"), "")
        # But only as a whole word.
        self.assertFalse(mentions(
            RawFile(rel="raw/notes/x.md", day=TODAY, text="Someoneelse wrote"),
            "Someone"))


class ContactEvidenceTest(unittest.TestCase):
    """The four shapes that count as having spoken with someone."""

    @staticmethod
    def _raw(rel, text="", **front):
        return RawFile(rel=rel, day=date(2026, 3, 9), front=front, text=text)

    def test_a_diary_title_naming_them_is_contact(self):
        raw = self._raw("raw/diary/2026-03-09 Pat Nolan catch-up.md",
                        "Talked about the split.")
        self.assertEqual(contact_evidence(raw, "Pat Nolan"), EVIDENCE_DIARY)
        # Deep in a diary body is not the title, so it is not evidence.
        deep = self._raw("raw/diary/2026-03-09 a day.md",
                         "\n".join(["filler"] * 60 + ["Pat Nolan came up"]))
        self.assertEqual(contact_evidence(deep, "Pat Nolan"), "")

    def test_a_sender_is_contact_from_the_frontmatter_or_the_body(self):
        front = self._raw("raw/emails/2026-03-09 A thread.md", "body",
                          **{"from": "Pat Nolan <p@x>"})
        self.assertEqual(contact_evidence(front, "Pat Nolan"), EVIDENCE_FROM)
        # A mail converted out of a `.eml` keeps its headers in the body.
        body = self._raw("raw/emails/A thread.md",
                         "# Re: a thread\n\n**From:** Pat Nolan <p@x>  \n")
        self.assertEqual(contact_evidence(body, "Pat Nolan"), EVIDENCE_FROM)

    def test_a_diary_names_them_in_its_title_not_in_its_body(self):
        # The defect: the docstring promised title and header, the code
        # searched forty lines, so a name that came up in passing halfway
        # down a day's notes reset that person's cadence.
        deep = self._raw("raw/diary/2026-03-09 a day.md",
                         "\n".join(["# Tuesday", ""] + ["filler"] * 28
                                   + ["We should ask Pat Nolan about it"]))
        self.assertEqual(contact_evidence(deep, "Pat Nolan"), "")
        self.assertTrue(mentions(deep, "Pat Nolan"))
        # The first heading is a title, and so is a frontmatter value.
        heading = self._raw("raw/diary/2026-03-09 a day.md",
                            "# Catch-up with Pat Nolan\n\nfiller\n")
        self.assertEqual(contact_evidence(heading, "Pat Nolan"), EVIDENCE_DIARY)
        titled = self._raw("raw/diary/2026-03-09 a day.md", "filler\n",
                           title="Catch-up with Pat Nolan")
        self.assertEqual(contact_evidence(titled, "Pat Nolan"), EVIDENCE_DIARY)

    def test_a_sender_who_wrote_only_to_lists_is_not_contact(self):
        # The defect: a `from:` counted outright, with no broadcast guard, so
        # an announcement they sent to the department reset their cadence.
        blast = self._raw("raw/emails/2026-03-09 An announcement.md", "body",
                          **{"from": "Pat Nolan <p@x>",
                             "to": "all-employees@x, maps-team@x"})
        self.assertEqual(contact_evidence(blast, "Pat Nolan"), "")
        self.assertTrue(mentions(blast, "Pat Nolan"))
        # One real person on the list and it is a thread again.
        thread = self._raw("raw/emails/2026-03-09 A thread.md", "body",
                           **{"from": "Pat Nolan <p@x>",
                              "to": "all-employees@x, Sam Okafor <s@x>"})
        self.assertEqual(contact_evidence(thread, "Pat Nolan"), EVIDENCE_FROM)
        # A file with no recipients at all — a diary export, a note converted
        # without headers — still credits the sender.
        bare = self._raw("raw/emails/2026-03-09 A note.md", "body",
                         **{"from": "Pat Nolan <p@x>"})
        self.assertEqual(contact_evidence(bare, "Pat Nolan"), EVIDENCE_FROM)

    def test_a_small_recipient_list_is_contact(self):
        raw = self._raw("raw/emails/2026-03-09 A thread.md", "body",
                        **{"to": "Pat Nolan <p@x>, Sam Okafor <s@x>"})
        self.assertEqual(contact_evidence(raw, "Pat Nolan"), EVIDENCE_RECIPIENT)
        cc = self._raw("raw/emails/2026-03-09 A thread.md", "body",
                       **{"to": "Sam Okafor <s@x>", "cc": "Pat Nolan <p@x>"})
        self.assertEqual(contact_evidence(cc, "Pat Nolan"), EVIDENCE_RECIPIENT)

    def test_a_broadcast_is_not_contact(self):
        crowd = self._raw("raw/emails/2026-03-09 An announcement.md", "body",
                          **{"to": "Pat Nolan <p@x>, Sam Okafor <s@x>, "
                                   "Ada Byrne <a@x>, Jo Halvorsen <j@x>"})
        self.assertEqual(contact_evidence(crowd, "Pat Nolan"), "")
        self.assertTrue(mentions(crowd, "Pat Nolan"))
        listed = self._raw("raw/emails/2026-03-09 An announcement.md", "body",
                           **{"to": "Pat Nolan <p@x>, all-employees@x"})
        self.assertEqual(contact_evidence(listed, "Pat Nolan"), "")
        faceless = self._raw("raw/emails/2026-03-09 An announcement.md", "body",
                             **{"to": "Pat Nolan <p@x>, noreply@x"})
        self.assertEqual(contact_evidence(faceless, "Pat Nolan"), "")

    def test_distribution_lists_are_told_apart_from_people(self):
        for entry in ("all-employees@x", "maps-team@x", "DL-Platform <dl@x>",
                      "everyone@x", "noreply@x", "group@x",
                      "ACME Contractors Worldwide <ACME_Contractors_Worldwide@x>",
                      "Engineering Staff <staff@x>"):
            with self.subTest(entry=entry):
                self.assertTrue(looks_like_distribution(entry))
        # A name that merely contains one of the words is a person.
        for entry in ("Allison Marshall <a@x>", "Pat Nolan <p@x>", "Sam Okafor"):
            with self.subTest(entry=entry):
                self.assertFalse(looks_like_distribution(entry))

    def test_an_attendee_list_or_a_speaker_turn_is_contact(self):
        listed = self._raw("raw/transcripts/2026-03-09 A meeting.md", "body",
                           speakers=["Pat Nolan", "Sam Okafor"])
        self.assertEqual(contact_evidence(listed, "Pat Nolan"), EVIDENCE_ATTENDEE)
        spoken = self._raw("raw/transcripts/2026-03-09 A meeting.md",
                           "> **Pat Nolan** 00:12\n> Thoughts?\n")
        self.assertEqual(contact_evidence(spoken, "Pat Nolan"), EVIDENCE_SPEAKER)
        self.assertEqual(speaker_names(spoken), ["Pat Nolan"])
        notes = self._raw("raw/notes/2026-03-09 A meeting.md",
                          "**Pat Nolan**\nsaid a thing\n")
        self.assertEqual(contact_evidence(notes, "Pat Nolan"), EVIDENCE_SPEAKER)
        # A body mention in the same folder is not a speaker turn.
        aside = self._raw("raw/notes/2026-03-09 A meeting.md",
                          "We should ask Pat Nolan about it.\n")
        self.assertEqual(contact_evidence(aside, "Pat Nolan"), "")

    def test_folders_that_record_nobody_are_never_contact(self):
        for folder in ("raw/clips", "raw/confluence", "raw/scans"):
            raw = self._raw(f"{folder}/2026-03-09 Pat Nolan on things.md", "body",
                            **{"from": "Pat Nolan <p@x>"})
            with self.subTest(folder=folder):
                self.assertEqual(contact_evidence(raw, "Pat Nolan"), "")

    def test_a_name_too_short_to_match_is_never_contact(self):
        raw = self._raw("raw/emails/2026-03-09 A thread.md",
                        "see https://example.test", **{"from": "TT <t@x>"})
        self.assertEqual(contact_evidence(raw, "TT"), "")
        self.assertFalse(mentions(raw, "TT"))


class WindowTest(VaultFixtureMixin, unittest.TestCase):
    def test_filename_date_wins_over_frontmatter(self):
        # Filename says in-window, frontmatter says otherwise: the name wins,
        # so the file is not opened to be re-dated.
        self.write("raw/notes/2026-03-05 Named.md", raw_note("2020-01-01"))
        self.write("raw/notes/Unnamed.md", raw_note("2026-03-05"))
        self.write("raw/notes/Old.md", raw_note("2020-01-01"))
        self.write("raw/notes/Undated.md", "# no frontmatter at all\n")
        with redirect_stderr(io.StringIO()):     # the disagreement is the point
            found = {r.rel: r.day for r in scan_raw(self.root, SINCE, TODAY)}
        self.assertEqual(found, {
            "raw/notes/2026-03-05 Named.md": date(2026, 3, 5),
            "raw/notes/Unnamed.md": date(2026, 3, 5),
        })

    def test_resources_and_index_pages_are_not_notes(self):
        self.write("raw/emails/index.md", raw_note("2026-03-05"))
        self.write("raw/emails/_resources/2026-03-05 attachment.md", raw_note("2026-03-05"))
        self.assertEqual(scan_raw(self.root, SINCE, TODAY), [])

    def test_every_raw_folder_is_scanned(self):
        # The defect: the folder list was hard-coded, so whole folders of
        # material were invisible to every review ever run.
        for folder in ("emails", "notes", "scans", "confluence",
                       "work-in-progress", "something new"):
            self.write(f"raw/{folder}/2026-03-05 A file.md", raw_note())
        self.write("raw/_resources/2026-03-05 An attachment.md", raw_note())
        (self.root / "raw" / "empty").mkdir(parents=True)
        found = raw_dirs(self.root)
        self.assertIn("raw/scans", found)
        self.assertIn("raw/confluence", found)
        self.assertIn("raw/work-in-progress", found)
        self.assertIn("raw/something new", found)
        self.assertNotIn("raw/_resources", found)
        self.assertNotIn("raw/empty", found)
        self.assertEqual(len(scan_raw(self.root, SINCE, TODAY)), 6)

    def test_a_deny_list_narrows_the_folders(self):
        for folder in ("emails", "clips"):
            self.write(f"raw/{folder}/2026-03-05 A file.md", raw_note())
        self.assertEqual(raw_dirs(self.root, ("clips",)), ("raw/emails",))

    def test_a_disagreeing_date_warns_once_with_a_count(self):
        self.write("raw/notes/2026-03-05 One.md", raw_note("2026-03-04"))
        self.write("raw/notes/2026-03-06 Two.md", raw_note("2026-03-04"))
        self.write("raw/notes/2026-03-07 Three.md", raw_note("2026-03-07"))
        noise = io.StringIO()
        with redirect_stderr(noise):
            found = scan_raw(self.root, SINCE, TODAY)
        self.assertEqual(len(found), 3)
        self.assertEqual(noise.getvalue().count("\n"), 1)
        self.assertIn("2 raw files", noise.getvalue())
        # The filename still wins, as documented.
        self.assertEqual(found[0].day, date(2026, 3, 5))

    def test_default_since_is_a_week_back_or_the_last_review(self):
        self.assertEqual(default_since(self.root, TODAY), date(2026, 3, 3))
        self.write("work/weekly/2026-W10.md", "---\ndate: 2026-03-02\n---\n# Weekly\n")
        self.assertEqual(default_since(self.root, TODAY), date(2026, 3, 3))
        # The review's own date, not the Monday of its week: a review written
        # on the Thursday already reported Thursday's material.
        self.write("work/weekly/2026-W11.md", "---\ndate: 2026-03-05\n---\n# Weekly\n")
        self.assertEqual(default_since(self.root, TODAY), date(2026, 3, 5))
        self.write("work/weekly/not-a-week.md", "---\ndate: 2026-03-09\n---\n# w\n")
        self.assertEqual(default_since(self.root, TODAY), date(2026, 3, 5))

    def test_a_weekly_written_today_leaves_the_window_alone(self):
        self.write("work/weekly/2026-W11.md", "---\ndate: 2026-03-10\n---\n# Weekly\n")
        self.assertEqual(default_since(self.root, TODAY), date(2026, 3, 3))

    def test_the_weekly_name_is_matched_case_insensitively(self):
        self.write("work/weekly/2026-w11 review.md",
                   "---\ndate: 2026-03-06\n---\n# Weekly\n")
        self.assertEqual(newest_weekly(self.root), date(2026, 3, 6))
        self.assertEqual(default_since(self.root, TODAY), date(2026, 3, 6))

    def test_an_impossible_iso_week_in_a_filename_is_not_a_review(self):
        # The defect: `newest_weekly` took any `YYYY-Www` prefix while
        # `load_snapshots` validated the week, so `2026-W99.md` sorted above
        # every real review and handed `default_since` its date. One shared
        # validator now, so the two readers cannot disagree.
        self.write("work/weekly/2026-W10.md",
                   "---\ndate: 2026-03-04\n---\n# Weekly\n")
        self.write("work/weekly/2026-W99.md",
                   "---\ndate: 2026-01-05\n---\n# Weekly\n\n## Snapshot\n\n"
                   "- [[Alpha]] — nonsense\n")
        self.assertEqual(newest_weekly(self.root), date(2026, 3, 4))
        self.assertEqual(default_since(self.root, TODAY), date(2026, 3, 4))
        self.assertEqual(load_snapshots(self.root), {})

    def test_a_weekly_without_a_date_falls_back_to_its_mtime(self):
        path = self.write("work/weekly/2026-W11.md", "# Weekly\n")
        stamp = date(2026, 3, 6)
        when = time.mktime(stamp.timetuple())
        os.utime(path, (when, when))
        self.assertEqual(newest_weekly(self.root), stamp)


class TopicMappingTest(VaultFixtureMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.write("work/topics/Alpha.md", topic_page(
            "Alpha", stakeholders='["[[Someone]]"]',
            related='["[[Gamma Programme]]"]'))
        self.write("work/topics/Beta.md", topic_page(
            "Beta", goal='[[Another Goal]]', stakeholders="[]", related="[]"))
        self.write("work/Stakeholders.md", STAKEHOLDER_TABLE)
        self.topics = load_topics(self.root)
        self.stakeholders = parse_stakeholders(self.root)

    def _map(self):
        raws = scan_raw(self.root, SINCE, TODAY)
        return map_raw_to_topics(raws, self.topics, self.stakeholders, SINCE, TODAY)

    def test_topic_keys_are_split_by_how_much_the_tie_is_worth(self):
        alpha = next(t for t in self.topics if t.name == "Alpha")
        keys = topic_keys(alpha, self.stakeholders)
        # The title and `related:` say the note is about the topic.
        self.assertEqual(keys.strong, ["Alpha", "Gamma Programme"])
        # A goal or a stakeholder says it is about the same corner of the
        # company — true of most of the quarter.
        self.assertIn("Some Goal (2026)", keys.weak)
        self.assertIn("Someone", keys.weak)
        # The table ties [[Third Person]] to Alpha too.
        self.assertIn("Third Person", keys.weak)

    def test_a_key_counts_as_a_wikilink_always_and_as_a_phrase_rarely(self):
        # The defect: one bare one-word goal claimed hundreds of files.
        def hit(key, links, text):
            return key_hit(key, links, Haystack.of(text))

        self.assertTrue(hit("Atlas", {"Atlas"}, "nothing else here"))
        self.assertFalse(hit("Atlas", set(), "the Atlas rollout continues"))
        self.assertTrue(hit("Gamma Programme", set(), "the Gamma Programme"))
        self.assertFalse(hit("Gamma Programme", set(), "the gamma programmes"))
        self.assertFalse(hit("Ada", set(), "Ada said so"))

    def test_mapping_by_title_and_related_is_strong(self):
        self.write("raw/diary/2026-03-05 By title.md", raw_note(body="Worked on [[Alpha]]."))
        self.write("raw/notes/2026-03-06 By related.md",
                   raw_note(body="Gamma Programme came up."))
        self.write("raw/clips/2026-03-08 Unrelated.md",
                   raw_note(body="An article about nothing we track."))
        mapped, weak, unmapped = self._map()
        by_path = {i.rel: i.topics for i in mapped}
        self.assertEqual(by_path["raw/diary/2026-03-05 By title.md"], ["Alpha"])
        self.assertEqual(by_path["raw/notes/2026-03-06 By related.md"], ["Alpha"])
        self.assertEqual(weak, [])
        self.assertEqual([i.rel for i in unmapped],
                         ["raw/clips/2026-03-08 Unrelated.md"])
        # The match reason survives into the rendered line when it is not the
        # topic's own title.
        reasons = {i.rel: i.matched_on for i in mapped}
        self.assertEqual(reasons["raw/notes/2026-03-06 By related.md"],
                         {"Alpha": "Gamma Programme"})
        self.assertIn("- raw/notes/2026-03-06 By related.md — (no description) "
                      "(via Gamma Programme)", topic_news_lines(mapped))

    def test_a_stakeholder_or_goal_hit_is_weak_and_only_counted(self):
        # One multi-recipient mail used to join every topic any recipient sat
        # on, with a file line each. Now it is one number per topic.
        self.write("raw/emails/2026-03-07 By person.md",
                   raw_note(body="body", **{"from": "Another Person <a@x>"}))
        self.write("raw/emails/2026-03-08 By person too.md",
                   raw_note(body="Another Person wrote in."))
        mapped, weak, unmapped = self._map()
        self.assertEqual(mapped, [])
        self.assertEqual(unmapped, [])
        self.assertEqual([i.rel for i in weak],
                         ["raw/emails/2026-03-07 By person.md",
                          "raw/emails/2026-03-08 By person too.md"])
        self.assertEqual(weak[0].weak_topics, ["Beta"])
        lines = topic_news_lines(mapped, weak)
        self.assertEqual(lines, ["### [[Beta]]", "",
                                 "- +2 weak via goal/stakeholder"])

    def test_watched_and_parked_topics_render_after_the_active_ones(self):
        self.write("work/topics/Later Thing.md", topic_page(
            "Later Thing", status="watching", related="[]", stakeholders="[]"))
        self.topics = load_topics(self.root)
        self.write("raw/diary/2026-03-05 Both.md",
                   raw_note(body="[[Later Thing]] and [[Alpha]]."))
        mapped, weak, _ = self._map()
        self.assertEqual(sorted(mapped[0].topics), ["Alpha", "Later Thing"])
        headings = [line for line in
                    topic_news_lines(mapped, weak, {"Later Thing": "watching"})
                    if line.startswith("###")]
        self.assertEqual(headings, ["### [[Alpha]]",
                                    "### [[Later Thing]] (watching)"])

    def test_the_window_is_half_open_at_the_start(self):
        self.write("raw/diary/2026-03-03 On the edge.md", raw_note(body="[[Alpha]]"))
        self.write("raw/diary/2026-03-10 Today.md", raw_note(body="[[Alpha]]"))
        mapped, _, _ = self._map()
        self.assertEqual([i.rel for i in mapped], ["raw/diary/2026-03-10 Today.md"])

    def test_unmapped_clustering_needs_two_files(self):
        self.write("raw/clips/2026-03-05 One.md", raw_note(body="[[Shared Thing]] and [[Only Here]]"))
        self.write("raw/clips/2026-03-06 Two.md", raw_note(body="[[Shared Thing]] again"))
        _, _, unmapped = self._map()
        self.assertEqual(len(unmapped), 2)
        self.assertEqual(cluster_links(unmapped), [("Shared Thing", CLUSTER_MIN)])


class WikiLogTest(VaultFixtureMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.write("work/topics/Alpha.md", topic_page(
            "Alpha", stakeholders='["[[Someone]]"]', related='["[[Gamma]]"]'))
        self.write("work/topics/Beta.md", topic_page(
            "Beta", goal="[[Another Goal]]", stakeholders="[]", related="[]"))
        self.topics = load_topics(self.root)
        self.write("wiki/problems/A Problem.md",
                   '---\ntype: problem\ndescription: "Something is wrong."\n'
                   'date: 2026-03-05\n---\n# A Problem\n\nIt touches [[Gamma]].\n')
        self.write("wiki/decisions/A Decision.md",
                   '---\ntype: decision\ndescription: "We chose one way."\n'
                   'date: 2026-03-06\n---\n# A Decision\n\nAbout Alpha and Beta.\n')
        self.write("wiki/concepts/A Concept.md",
                   '---\ntype: concept\ndescription: "Vocabulary."\n---\n# A Concept\n')
        self.write("wiki/log.jsonl", "\n".join([
            json.dumps({"date": "2026-03-05 12:10:00", "file": "raw/clips/one.md",
                        "pages_created": ["wiki/problems/A Problem.md"],
                        "pages_updated": []}),
            json.dumps({"date": "2026-03-06 09:00:00", "file": "raw/clips/two.md",
                        "pages_created": [],
                        "pages_updated": ["wiki/decisions/A Decision.md",
                                          "wiki/concepts/A Concept.md"]}),
            json.dumps({"date": "2026-02-01 09:00:00", "file": "raw/clips/old.md",
                        "pages_created": ["wiki/systems/A System.md"],
                        "pages_updated": []}),
            "not json at all",
        ]) + "\n")

    def test_window_type_filtering_and_touched_topics(self):
        changes = load_wiki_changes(self.root, SINCE, TODAY, self.topics)
        # `wiki/concepts/` is out of scope and the February record is out of
        # the window, so only two pages remain.
        self.assertEqual([c.page for c in changes], ["A Decision", "A Problem"])
        decision, problem = changes
        # Both topic titles appear in the decision's body.
        self.assertEqual(decision.topics, ["Alpha", "Beta"])
        self.assertEqual(decision.reasons, {"Alpha": "title", "Beta": "title"})
        self.assertEqual(decision.action, "updated")
        self.assertEqual(decision.description, "We chose one way.")
        # The problem shares only [[Gamma]], which is Alpha's `related`.
        self.assertEqual(problem.topics, ["Alpha"])
        self.assertEqual(problem.reasons, {"Alpha": "related"})
        self.assertEqual(problem.action, "created")
        self.assertEqual(problem.type, "problems")

    def test_a_shared_goal_is_a_weaker_touch_than_a_named_topic(self):
        # A hub page that only links the goal three topics share must not
        # outrank a page that names one topic outright.
        self.write("wiki/systems/A Hub.md",
                   '---\ntype: system\ndescription: "A busy page."\n---\n'
                   '# A Hub\n\nLinks [[Some Goal (2026)]] and little else.\n')
        self.write("wiki/log.jsonl", json.dumps({
            "date": "2026-03-05 12:10:00", "file": "raw/clips/one.md",
            "pages_created": ["wiki/systems/A Hub.md",
                              "wiki/problems/A Problem.md"],
            "pages_updated": []}) + "\n")
        changes = load_wiki_changes(self.root, SINCE, TODAY, self.topics)
        hub = next(c for c in changes if c.page == "A Hub")
        self.assertEqual(hub.reasons, {"Alpha": "goal"})
        self.assertEqual(hub.strong, [])
        # One strong touch beats one weak one.
        self.assertEqual([c.page for c in changes], ["A Problem", "A Hub"])

    def test_created_wins_over_updated_for_the_same_page(self):
        self.write("wiki/log.jsonl", json.dumps({
            "date": "2026-03-05 12:10:00", "file": "raw/clips/one.md",
            "pages_created": ["wiki/problems/A Problem.md"],
            "pages_updated": ["wiki/problems/A Problem.md"]}) + "\n")
        changes = load_wiki_changes(self.root, SINCE, TODAY, self.topics)
        self.assertEqual([(c.page, c.action) for c in changes],
                         [("A Problem", "created")])

    def test_a_cited_path_or_a_longer_word_is_not_a_title_touch(self):
        # The defect: the title test was a substring test over the whole page,
        # so a footnote citing `…/Alpha review.md` — or the word "Alphabet" —
        # made the page look like a page about Alpha.
        self.write("wiki/problems/A Problem.md", "\n".join([
            '---', 'type: problem', 'description: "Something is wrong."',
            'date: 2026-03-05', '---', '# A Problem', '',
            'Alphabet soup, and nothing else.[^1]', '',
            '- [[raw/notes/2026-03-04 Beta review.md]]',
            '[^1]: raw/notes/2026-03-05 Alpha review.md', '',
            '## Sources', '', '- Alpha and Beta again', '',
        ]))
        self.write("wiki/log.jsonl", json.dumps({
            "date": "2026-03-05 12:10:00", "file": "raw/clips/one.md",
            "pages_created": ["wiki/problems/A Problem.md"],
            "pages_updated": []}) + "\n")
        changes = load_wiki_changes(self.root, SINCE, TODAY, self.topics)
        self.assertEqual([c.page for c in changes], ["A Problem"])
        self.assertEqual(changes[0].topics, [])

    def test_a_page_that_no_longer_exists_is_skipped(self):
        (self.root / "wiki" / "problems" / "A Problem.md").unlink()
        changes = load_wiki_changes(self.root, SINCE, TODAY, self.topics)
        self.assertEqual([c.page for c in changes], ["A Decision"])

    def test_no_log_means_no_changes(self):
        (self.root / "wiki" / "log.jsonl").unlink()
        self.assertEqual(load_wiki_changes(self.root, SINCE, TODAY, self.topics), [])


class DeadlineAndInteractionTest(VaultFixtureMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        # Alpha and Beta share [[Someone]] and the same goal, and neither lists
        # the other; Alpha's first action names Beta.
        self.write("work/topics/Alpha.md", topic_page(
            "Alpha", related="[]", me=["- [ ] agree the split with [[Beta]]",
                                       "- [ ] a second thing"]))
        self.write("work/topics/Beta.md", topic_page(
            "Beta", horizon="next", deadline="2026-04-01", related="[]"))
        self.write("work/topics/Gamma.md", topic_page(
            "Gamma", horizon="next", deadline="2026-12-01",
            goal="[[Another Goal]]", stakeholders='["Some Group"]',
            related='["[[Alpha]]", "[[Beta]]"]'))
        self.topics = load_topics(self.root)

    def test_horizon_flag_only_inside_the_window(self):
        lines = horizon_flag_lines(self.topics, TODAY)
        self.assertEqual(len(lines), 1)
        self.assertIn("[[Beta]]", lines[0])
        self.assertIn("consider moving to now", lines[0])

    def test_shared_stakeholder_or_goal_without_related(self):
        lines = shared_interaction_lines(self.topics)
        self.assertEqual(len(lines), 1)
        self.assertIn("[[Alpha]] + [[Beta]]", lines[0])
        self.assertIn("goal [[Some Goal (2026)]]", lines[0])
        self.assertIn("stakeholder Someone", lines[0])
        # Gamma lists both, so its pairs are already recorded.
        self.assertNotIn("Gamma", lines[0])

    def test_one_shared_stakeholder_is_not_a_hidden_dependency(self):
        # On a small roster one shared stakeholder is every pair, so it used
        # to flag the whole portfolio against itself.
        self.write("work/topics/Alpha.md", topic_page(
            "Alpha", goal="[[One Goal]]", related="[]",
            stakeholders='["[[Someone]]", "[[Another Person]]"]'))
        self.write("work/topics/Beta.md", topic_page(
            "Beta", goal="[[Another Goal]]", related="[]",
            stakeholders='["[[Someone]]"]'))
        self.write("work/topics/Gamma.md", topic_page(
            "Gamma", goal="[[A Third Goal]]", related="[]",
            stakeholders='["[[Someone]]", "[[Another Person]]"]'))
        topics = load_topics(self.root)
        lines = shared_interaction_lines(topics)
        # Alpha + Gamma share two; neither shares two with Beta.
        self.assertEqual(len(lines), 1)
        self.assertIn("[[Alpha]] + [[Gamma]]", lines[0])
        self.assertIn("stakeholder Another Person", lines[0])
        self.assertNotIn("goal", lines[0])

    def test_first_action_naming_another_topic(self):
        lines = action_link_lines(self.topics)
        self.assertEqual(len(lines), 1)
        self.assertIn("[[Alpha]] — first action names [[Beta]]", lines[0])


class PacketTest(VaultFixtureMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.write("work/topics/Alpha.md", topic_page(
            "Alpha", progress="Alpha moved a step.", related="[]",
            me=["- [ ] first alpha action"]))
        self.write("work/topics/Beta.md", topic_page(
            "Beta", horizon="later", progress="Beta is waiting.", related="[]"))
        self.write("work/topics/Zeta.md", topic_page(
            "Zeta", status="done", progress="Closed.", related="[]"))
        self.write("work/Stakeholders.md", STAKEHOLDER_TABLE)
        self.write("raw/diary/2026-03-05 A day.md", raw_note(body="Worked on [[Alpha]]."))
        self.write("raw/clips/2026-03-06 An article.md",
                   raw_note(body="Nothing we track, but see [[Shared Thing]]."))
        self.write("raw/clips/2026-03-07 Another article.md",
                   raw_note(body="Also [[Shared Thing]]."))
        # Reaches Beta only through the stakeholder the table ties to it.
        self.write("raw/emails/2026-03-09 A thread.md",
                   raw_note(body="body", **{"from": "Another Person <a@x>"}))
        self.write("wiki/problems/A Problem.md",
                   '---\ntype: problem\ndescription: "Something is wrong."\n---\n'
                   '# A Problem\n\nIt touches Alpha.\n')
        self.write("wiki/log.jsonl", json.dumps({
            "date": "2026-03-05 12:10:00", "file": "raw/clips/one.md",
            "pages_created": ["wiki/problems/A Problem.md"], "pages_updated": []}) + "\n")
        self.topics = load_topics(self.root)
        self.packet = build_packet(self.root, self.topics, TODAY, SINCE, COMMAND)

    def test_sections_in_order(self):
        text = render_markdown(self.packet, COMMAND)
        headings = [line for line in text.splitlines() if line.startswith("## ")]
        self.assertEqual(headings, [
            "## Snapshot",
            "## Backlog",
            "## Stakeholder cadence",
            "## New on my topics since 2026-03-03",
            "## Unmapped new material",
            "## New or changed wiki pages",
            "## Deadlines and horizon flags",
            "## Interaction check",
        ])

    def test_snapshot_round_trips_through_load_snapshots(self):
        # The weekly file the skill writes must be readable by `--recap`.
        self.write("work/weekly/2026-W11.md", render_markdown(self.packet, COMMAND))
        snapshots = load_snapshots(self.root)
        self.assertEqual(sorted(snapshots), [date(2026, 3, 9)])
        self.assertEqual(snapshots[date(2026, 3, 9)],
                         {"Alpha": "Alpha moved a step.", "Beta": "Beta is waiting."})

    def test_backlog_is_embedded_one_level_down(self):
        text = render_markdown(self.packet, COMMAND)
        lines = text.splitlines()
        span = section_spans(lines)["Backlog"]
        body = "\n".join(lines[span[0]:span[1]])
        self.assertIn("### Portfolio", body)
        self.assertIn("#### now", body)
        self.assertIn("- **[[Alpha]]** — Alpha moved a step.", body)
        # Nothing inside the embedded backlog reads as a packet section.
        self.assertFalse(any(line.startswith("## ") for line in body.splitlines()))

    def test_body_sections(self):
        text = render_markdown(self.packet, COMMAND)
        self.assertIn("- [[Someone]] — weekly, 30 min (7d) — never contacted", text)
        self.assertIn("- Some Group — alternating Tue / Thu — no fixed cadence", text)
        self.assertIn("- raw/diary/2026-03-05 A day.md", text)
        self.assertIn("- [[Shared Thing]] — in 2 unmapped files", text)
        self.assertIn("- [[A Problem]] (problems, created) — Something is wrong. "
                      "— touches [[Alpha]] (title)", text)
        # A stakeholder-only hit is one number, not a file list.
        self.assertIn("- +1 weak via goal/stakeholder", text)
        self.assertNotIn("- raw/emails/2026-03-09 A thread.md", text)
        # Done topics stay out of the snapshot.
        self.assertNotIn("[[Zeta]]", text)

    def test_json_mirrors_the_sections(self):
        data = json.loads(render_json(self.packet))
        self.assertEqual(data["week"], "2026-W11")
        self.assertEqual(data["since"], "2026-03-03")
        self.assertEqual([s["topic"] for s in data["snapshot"]], ["Alpha", "Beta"])
        self.assertEqual(data["clusters"], [{"link": "Shared Thing", "files": 2}])
        self.assertEqual(data["wiki_changes"][0]["page"], "A Problem")
        self.assertEqual([i["path"] for i in data["new_on_topics"]],
                         ["raw/diary/2026-03-05 A day.md"])
        self.assertEqual(data["weak_on_topics"], [{"topic": "Beta", "files": 1}])
        self.assertIn("stakeholder_cadence", data)
        self.assertIn("interaction_check", data)
        # The cadence row carries what it did *not* count, and why.
        someone = next(r for r in data["stakeholder_cadence"]
                       if r["person"] == "[[Someone]]")
        self.assertEqual(someone["status"], NEVER_CONTACTED)
        another = next(r for r in data["stakeholder_cadence"]
                       if r["person"] == "[[Another Person]]")
        self.assertEqual(another["evidence"], "raw/emails/2026-03-09 A thread.md")
        self.assertEqual(another["evidence_reason"], "from")

    # ---------------------------------------------------------------- CLI

    def _run(self, *args, expect=0):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--vault", str(self.root), *args],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, expect, result.stderr)
        return result.stdout

    def test_cli_prints_to_stdout(self):
        out = self._run("--today", "2026-03-10", "--since", "2026-03-03")
        self.assertIn("# Weekly review packet 2026-W11", out)
        self.assertIn("## Snapshot", out)

    def test_cli_writes_the_out_file(self):
        self._run("--today", "2026-03-10", "--out", str(self.root / "out.md"))
        self.assertIn("## Snapshot", self.read("out.md"))

    def test_cli_json_format(self):
        data = json.loads(self._run("--today", "2026-03-10", "--format", "json"))
        self.assertEqual(data["today"], "2026-03-10")

    def test_cli_rejects_bad_dates_and_an_empty_window(self):
        self._run("--today", "yesterday", expect=2)
        self._run("--since", "yesterday", expect=2)
        self._run("--today", "2026-03-10", "--since", "2026-03-10", expect=2)


if __name__ == "__main__":
    unittest.main()
