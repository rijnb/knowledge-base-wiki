"""Tests for lib.work_brief and the work-brief.py CLI.

Every fixture is invented (Alpha, Beta, @Pat, [[Someone]]) — the real `work/`,
`raw/` and `wiki/` trees are never read here, and nothing about them is
asserted.
"""

import json
import subprocess
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _vault_fixture import VaultFixtureMixin  # noqa: E402
from lib.work_backlog import load_topics  # noqa: E402
from lib.work_brief import (  # noqa: E402
    BRIEF_LINES,
    LINE_DECISION,
    LINE_FYI,
    LINE_NEED,
    LINE_RISK,
    LINE_SINCE,
    PersonError,
    build_brief,
    default_since,
    delegated_to,
    name_tokens,
    owed_asks,
    person_topics,
    render_json,
    render_markdown,
    resolve_person,
)
from lib.work_weekly import cadence_rows, parse_stakeholders  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "work-brief.py"
TODAY = date(2026, 3, 10)          # a Tuesday
COMMAND = "cmd"


def topic_page(name, status="active", horizon="now", progress="Something moved.",
               goal="[[Some Goal (2026)]]", stakeholders='["[[Someone]]"]',
               related='["[[Beta]]"]', next_review="2026-04-01", deadline=None,
               me=(), delegated=(), log=("- 2026-03-02 — topic opened",)):
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
    body += ["## Delegated", ""] + list(delegated) + [""]
    body += ["## Log", ""] + list(log) + [""]
    return "\n".join(front + body)


def raw_note(day="2026-03-05", body="Nothing in particular.", **front):
    lines = ["---", f"date: {day}"]
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
| [[Pat Nolan]] | a second opinion | weekly, 30 min | 1:1 | 2026-03-04 | *book it* | [[Alpha]] |
| [[Another Person]] | alignment | 2-weekly | 1:1 | — | — | [[Beta]] |
| [[Third Person]] / a steerco | critical review | as needed | steerco | — | — | [[Alpha]] |
| Some Group | agenda | alternating Tue / Thu | meeting | — | — | [[Beta]] |
"""


class VaultTest(VaultFixtureMixin, unittest.TestCase):
    """A vault with two topics and a stakeholder table, reused by most tests."""

    def setUp(self):
        super().setUp()
        self.write("work/Stakeholders.md", STAKEHOLDER_TABLE)
        self.write("work/topics/Alpha.md", topic_page(
            "Alpha", progress="Alpha moved a step.", related="[]",
            me=["- [ ] write the definitions",
                "- [ ] ask Pat what the split should be"],
            delegated=["- [ ] @Pat — review the draft",
                       "- [x] @Pat — an old done thing",
                       "- [ ] @Someone Else — not for Pat"],
            log=["- 2026-03-02 — topic opened", "- 2026-03-06 — draft written"]))
        self.write("work/topics/Beta.md", topic_page(
            "Beta", progress="Beta is waiting.", stakeholders='["[[Pat Nolan]]"]',
            related="[]", me=["- [ ] first beta action"]))
        self.reload()

    def reload(self):
        self.topics = load_topics(self.root)
        self.stakeholders = parse_stakeholders(self.root)

    def person(self, query="Pat"):
        return resolve_person(self.stakeholders, query)

    def brief(self, query="Pat", today=TODAY, since=None):
        return build_brief(self.root, self.topics, self.stakeholders,
                           self.person(query), today, since)


# --------------------------------------------------------------------------- #


class ResolvePersonTest(VaultTest):
    def test_exact_substring_and_first_name(self):
        for query in ("[[Pat Nolan]]", "Pat Nolan", "pat nolan", "Pat", "Nolan"):
            with self.subTest(query=query):
                self.assertEqual(self.person(query).person, "[[Pat Nolan]]")

    def test_the_suffix_after_a_slash_is_not_part_of_the_name(self):
        self.assertEqual(self.person("Third Person").person,
                         "[[Third Person]] / a steerco")
        # The whole cell still resolves, and so does the suffix on its own.
        self.assertEqual(self.person("[[Third Person]] / a steerco").names,
                         ["Third Person"])

    def test_a_plain_text_row_resolves_on_its_own_text(self):
        self.assertEqual(self.person("Some Group").person, "Some Group")

    def test_ambiguous_lists_the_matches(self):
        with self.assertRaises(PersonError) as caught:
            self.person("Person")
        message = str(caught.exception)
        self.assertIn("matches 2 stakeholders", message)
        self.assertIn("Another Person", message)
        self.assertIn("Third Person", message)

    def test_an_exact_key_beats_a_longer_substring(self):
        self.write("work/Stakeholders.md",
                   STAKEHOLDER_TABLE + "| [[Pat]] | odds and ends | weekly "
                                       "| Slack | — | — | [[Beta]] |\n")
        self.reload()
        self.assertEqual(self.person("Pat").person, "[[Pat]]")

    def test_not_found_lists_every_candidate(self):
        for query in ("Nobody", ""):
            with self.subTest(query=query):
                with self.assertRaises(PersonError) as caught:
                    self.person(query)
                self.assertIn("Pat Nolan", str(caught.exception))


class TopicUnionTest(VaultTest):
    def test_the_column_and_the_frontmatter_are_unioned(self):
        found, missing = person_topics(self.person(), self.topics)
        # `Topics` names Alpha; Beta's own `stakeholders:` names Pat Nolan.
        self.assertEqual([t.name for t in found], ["Alpha", "Beta"])
        self.assertEqual(missing, [])

    def test_a_named_topic_without_a_page_is_reported_not_dropped(self):
        self.write("work/Stakeholders.md",
                   STAKEHOLDER_TABLE.replace("| [[Alpha]] |",
                                             "| [[Alpha]], [[Gamma]] |"))
        self.reload()
        found, missing = person_topics(self.person(), self.topics)
        self.assertEqual([t.name for t in found], ["Alpha", "Beta"])
        self.assertEqual(missing, ["Gamma"])

    def test_done_topics_are_not_their_topics(self):
        self.write("work/topics/Beta.md", topic_page(
            "Beta", status="done", stakeholders='["[[Pat Nolan]]"]', related="[]"))
        self.reload()
        found, _ = person_topics(self.person(), self.topics)
        self.assertEqual([t.name for t in found], ["Alpha"])


class DelegatedMatchTest(VaultTest):
    def test_first_name_and_full_name_both_match(self):
        alpha = next(t for t in self.topics if t.name == "Alpha")
        # `@Pat` reaches [[Pat Nolan]] through the first name.
        self.assertEqual([t.text for t in delegated_to(alpha, self.person())],
                         ["review the draft"])
        self.write("work/topics/Alpha.md", topic_page(
            "Alpha", related="[]", delegated=["- [ ] @Group — an item"]))
        self.reload()
        alpha = next(t for t in self.topics if t.name == "Alpha")
        self.assertEqual(delegated_to(alpha, self.person("Some Group")), [])
        self.write("work/topics/Alpha.md", topic_page(
            "Alpha", related="[]", delegated=["- [ ] @Nolan — full name only"]))
        self.reload()
        alpha = next(t for t in self.topics if t.name == "Alpha")
        self.assertEqual(delegated_to(alpha, self.person()), [])

    def test_open_asks_and_what_i_owe_them(self):
        brief = self.brief()
        self.assertEqual([(a.text, a.topic) for a in brief.delegated],
                         [("review the draft", "Alpha")])
        # My own action naming them, matched on the first name.
        self.assertEqual([(a.text, a.topic) for a in brief.owed],
                         [("ask Pat what the split should be", "Alpha")])

    def test_what_i_owe_them_matches_whole_words_only(self):
        # The defect: a substring match made "patch the pipeline" an action
        # naming Pat.
        self.write("work/topics/Alpha.md", topic_page(
            "Alpha", related="[]",
            me=["- [ ] patch the pipeline and repatriate the job",
                "- [ ] Pat's review of the draft"]))
        self.reload()
        self.assertEqual([a.text for a in owed_asks(self.topics, self.person())],
                         ["Pat's review of the draft"])

    def test_a_token_too_short_to_match_is_dropped(self):
        self.write("work/Stakeholders.md",
                   STAKEHOLDER_TABLE + "| [[Jo Xu]] | odds and ends | weekly "
                                       "| Slack | — | — | [[Beta]] |\n")
        self.reload()
        # "Xu" is two characters — matching it against free text finds it
        # everywhere — so only the full name survives.
        self.assertEqual(name_tokens(self.person("Jo Xu")), {"jo xu"})

    def test_a_decomposed_name_matches_the_composed_table_entry(self):
        composed = "V\u00edctor Moreno"
        decomposed = "Vi\u0301ctor Moreno"
        self.assertNotEqual(composed, decomposed)
        self.write("work/Stakeholders.md",
                   STAKEHOLDER_TABLE + f"| [[{decomposed}]] | review | weekly "
                                       "| Slack | — | — | [[Alpha]] |\n")
        self.write("work/topics/Alpha.md", topic_page(
            "Alpha", related="[]", me=[f"- [ ] ask {composed} about the split"],
            delegated=["- [ ] @V\u00edctor \u2014 review the draft"]))
        self.reload()
        person = self.person(composed)
        self.assertEqual([a.text for a in owed_asks(self.topics, person)],
                         ["ask V\u00edctor Moreno about the split"])
        alpha = next(t for t in self.topics if t.name == "Alpha")
        self.assertEqual([t.text for t in delegated_to(alpha, person)],
                         ["review the draft"])


class AmbiguousFirstNameTest(VaultTest):
    """Two Pats on the roster: `@Pat` names neither of them."""

    def setUp(self):
        super().setUp()
        self.write("work/Stakeholders.md",
                   STAKEHOLDER_TABLE + "| [[Pat Okafor]] | a decision | weekly "
                                       "| Slack | — | — | [[Alpha]] |\n")
        self.write("work/topics/Alpha.md", topic_page(
            "Alpha", related="[]",
            me=["- [ ] ask Pat what the split should be",
                "- [ ] ask Pat Nolan for the definitions"],
            delegated=["- [ ] @Pat — review the draft",
                       "- [ ] @Pat Nolan — sign off the split"]))
        self.reload()

    def test_a_bare_first_name_matches_neither_pat(self):
        alpha = next(t for t in self.topics if t.name == "Alpha")
        nolan = self.person("Pat Nolan")
        # `@Pat Nolan` still matches: `lib.work_backlog` splits the owner off
        # at the first space, so the second word arrives at the head of the
        # task text and is rejoined to it here.
        self.assertEqual(
            [t.text for t in delegated_to(alpha, nolan, self.stakeholders)],
            ["Nolan — sign off the split"])
        self.assertEqual(
            [a.text for a in owed_asks(self.topics, nolan, self.stakeholders)],
            ["ask Pat Nolan for the definitions"])
        # And nothing at all is handed to the Pat who was never named in full.
        okafor = self.person("Pat Okafor")
        self.assertEqual(delegated_to(alpha, okafor, self.stakeholders), [])
        self.assertEqual(owed_asks(self.topics, okafor, self.stakeholders), [])
        # Without the roster the first name still matches, as before.
        self.assertEqual(len(delegated_to(alpha, nolan)), 2)

    def test_the_packet_says_the_first_name_was_ambiguous(self):
        brief = self.brief("Pat Nolan", since=date(2026, 3, 4))
        self.assertEqual(brief.ambiguous, ["Pat Okafor"])
        self.assertIn("- first name ambiguous with [[Pat Okafor]]; "
                      "matched on full name only",
                      render_markdown(brief, COMMAND))
        data = json.loads(render_json(brief))
        self.assertEqual(data["person"]["first_name_ambiguous_with"],
                         ["Pat Okafor"])

    def test_one_pat_is_still_matched_on_the_first_name(self):
        self.write("work/Stakeholders.md", STAKEHOLDER_TABLE)
        self.reload()
        brief = self.brief("Pat", since=date(2026, 3, 4))
        self.assertEqual(brief.ambiguous, [])
        self.assertEqual([a.text for a in brief.delegated],
                         ["review the draft", "Nolan — sign off the split"])
        self.assertNotIn("first name ambiguous", render_markdown(brief, COMMAND))


class SinceTest(VaultTest):
    def _contact(self, query="Pat", raws=()):
        return cadence_rows([self.person(query)], list(raws), TODAY)[0]

    def test_last_contact_then_cadence_then_the_fallback(self):
        # The table's own `Last` date.
        self.assertEqual(default_since(self._contact(), TODAY), date(2026, 3, 4))
        # No last contact, a 14-day cadence.
        self.assertEqual(default_since(self._contact("Another Person"), TODAY),
                         date(2026, 2, 24))
        # No last contact and no parsable cadence.
        self.assertEqual(default_since(self._contact("Some Group"), TODAY),
                         date(2026, 2, 24))

    def test_raw_evidence_moves_the_window(self):
        self.write("raw/diary/2026-03-08 Pat Nolan catch-up.md",
                   raw_note("2026-03-08", "Talked about [[Alpha]]."))
        brief = self.brief()
        self.assertEqual(brief.since, date(2026, 3, 8))
        self.assertEqual(brief.contact.evidence,
                         "raw/diary/2026-03-08 Pat Nolan catch-up.md")

    def test_an_explicit_since_overrides_everything(self):
        brief = self.brief(since=date(2026, 1, 1))
        self.assertEqual(brief.since, date(2026, 1, 1))


class WindowTest(VaultTest):
    def setUp(self):
        super().setUp()
        self.write("raw/emails/2026-03-05 A thread.md",
                   raw_note("2026-03-05", "body", **{"from": "Pat Nolan <p@x>",
                                                     "subject": "A thread"}))
        self.write("raw/notes/2026-03-06 On Alpha.md",
                   raw_note("2026-03-06", "Notes about [[Alpha]].",
                            description="Alpha notes"))
        self.write("raw/notes/2026-03-01 Too early.md",
                   raw_note("2026-03-01", "Also about [[Alpha]]."))
        self.write("raw/clips/2026-03-07 An article.md",
                   raw_note("2026-03-07", "An article naming Pat Nolan."))

    def test_mentions_topics_and_the_window(self):
        brief = self.brief(since=date(2026, 3, 4))
        # A mail they sent is contact, and the packet says which rule said so.
        self.assertEqual([(h.rel, h.reason) for h in brief.contact_raw],
                         [("raw/emails/2026-03-05 A thread.md", "from")])
        self.assertEqual(brief.mentions, [])
        self.assertIn("- raw/emails/2026-03-05 A thread.md — 2026-03-05 — "
                      "A thread (from)", render_markdown(brief, COMMAND))
        # The Alpha note does not name them, so it lands in the topic bucket
        # with its topic label; the pre-window note lands nowhere; `raw/clips/`
        # is not a folder a brief reads.
        self.assertEqual([(h.rel, h.topics) for h in brief.topic_raw],
                         [("raw/notes/2026-03-06 On Alpha.md", ["Alpha"])])
        text = render_markdown(brief, COMMAND)
        self.assertIn("- raw/notes/2026-03-06 On Alpha.md — 2026-03-06 — "
                      "Alpha notes (topic: Alpha)", text)

    def test_a_mail_to_fourteen_people_is_a_mention_not_contact(self):
        # The packet's split is the cadence's split: being one of fourteen
        # names on a circulation is not having spoken to anybody.
        crowd = ", ".join([f"Person {n} <p{n}@x>" for n in range(13)]
                          + ["Pat Nolan <p@x>"])
        self.write("raw/emails/2026-03-06 An announcement.md",
                   raw_note("2026-03-06", "body", to=crowd,
                            subject="An announcement"))
        brief = self.brief(since=date(2026, 3, 4))
        self.assertIn("raw/emails/2026-03-06 An announcement.md",
                      [h.rel for h in brief.mentions])
        self.assertNotIn("raw/emails/2026-03-06 An announcement.md",
                         [h.rel for h in brief.contact_raw])
        text = render_markdown(brief, COMMAND)
        self.assertIn("### Contact", text)
        self.assertIn("### Mentions them (not contact)", text)
        data = json.loads(render_json(brief))
        self.assertEqual(
            [h["path"] for h in data["since_last_contact"]["mentions_them"]],
            ["raw/emails/2026-03-06 An announcement.md"])
        self.assertEqual(
            [(h["path"], h["reason"])
             for h in data["since_last_contact"]["contact"]],
            [("raw/emails/2026-03-05 A thread.md", "from")])

    def test_a_file_naming_them_is_not_reported_twice(self):
        self.write("raw/notes/2026-03-06 On Alpha.md",
                   raw_note("2026-03-06", "Pat Nolan on [[Alpha]]."))
        brief = self.brief(since=date(2026, 3, 4))
        self.assertIn("raw/notes/2026-03-06 On Alpha.md",
                      [h.rel for h in brief.mentions])
        self.assertEqual(brief.topic_raw, [])

    def test_log_lines_come_from_the_window_only(self):
        brief = self.brief(since=date(2026, 3, 4))
        alpha = next(t for t in brief.topics if t.name == "Alpha")
        self.assertEqual([e.text for e in alpha.log], ["draft written"])

    def test_one_haystack_decides_both_buckets(self):
        # The defect: mentions read 40 lines while the mapping read the whole
        # file, so a note naming them deep down landed in *both* sections.
        self.write("raw/notes/2026-03-06 On Alpha.md", raw_note(
            "2026-03-06", "\n".join(["Notes about [[Alpha]]."] + ["filler"] * 60
                                    + ["Pat Nolan said so."])))
        brief = self.brief(since=date(2026, 3, 4))
        self.assertIn("raw/notes/2026-03-06 On Alpha.md",
                      [h.rel for h in brief.mentions])
        self.assertEqual([h.rel for h in brief.topic_raw], [])

    def test_a_goal_or_stakeholder_hit_is_counted_not_listed(self):
        # Beta's `stakeholders:` names Pat Nolan, so a note that only names
        # Pat's colleague reaches Beta weakly — one number, not a file line.
        self.write("work/topics/Beta.md", topic_page(
            "Beta", progress="Beta is waiting.",
            stakeholders='["[[Pat Nolan]]", "[[Another Person]]"]',
            related="[]", me=["- [ ] first beta action"]))
        self.reload()
        self.write("raw/notes/2026-03-06 Weakly.md",
                   raw_note("2026-03-06", "Another Person had a view."))
        brief = self.brief(since=date(2026, 3, 4))
        self.assertEqual(brief.weak_topic_raw, {"Beta": 1})
        self.assertNotIn("raw/notes/2026-03-06 Weakly.md",
                         [h.rel for h in brief.topic_raw])
        text = render_markdown(brief, COMMAND)
        self.assertIn("- +1 weak via goal/stakeholder on [[Beta]]", text)
        data = json.loads(render_json(brief))
        self.assertEqual(data["since_last_contact"]["on_their_topics_weak"],
                         [{"topic": "Beta", "files": 1}])

    def test_every_raw_folder_but_clips_is_read(self):
        # The folder list was hard-coded, so whole folders were invisible.
        self.write("raw/scans/2026-03-06 A scan.md",
                   raw_note("2026-03-06", "Pat Nolan signed it."))
        self.write("raw/work-in-progress/2026-03-06 A draft.md",
                   raw_note("2026-03-06", "Pat Nolan reviewed it."))
        brief = self.brief(since=date(2026, 3, 4))
        rels = [h.rel for h in brief.mentions]
        self.assertIn("raw/scans/2026-03-06 A scan.md", rels)
        self.assertIn("raw/work-in-progress/2026-03-06 A draft.md", rels)
        self.assertNotIn("raw/clips/2026-03-07 An article.md", rels)


class OtherStakeholdersTest(VaultTest):
    def test_rows_sharing_a_topic_and_how_many(self):
        brief = self.brief()
        self.assertEqual(brief.others, [
            ("[[Another Person]]", ["Beta"]),          # Beta, via the column
            ("Some Group", ["Beta"]),
            ("[[Third Person]] / a steerco", ["Alpha"]),
        ])
        self.assertIn("- [[Third Person]] / a steerco — shares [[Alpha]]",
                      render_markdown(brief, COMMAND))


class SkeletonTest(VaultTest):
    def setUp(self):
        super().setUp()
        self.write("work/topics/Alpha.md", topic_page(
            "Alpha", related="[]", next_review="2026-03-01",
            deadline="2026-03-20", me=["- [ ] write the definitions"],
            delegated=["- [ ] @Pat — review the draft"],
            log=["- 2026-03-06 — draft written"]))
        self.write("work/topics/Beta.md", topic_page(
            "Beta", stakeholders='["[[Pat Nolan]]"]', related="[]",
            deadline="2027-01-01", log=[]))
        self.write("raw/notes/2026-03-06 On Alpha.md",
                   raw_note("2026-03-06", "Notes about [[Alpha]].",
                            description="Alpha notes"))
        self.reload()
        self.brief_ = self.brief(since=date(2026, 3, 4))

    def test_every_candidate_lands_in_its_own_slot(self):
        candidates = self.brief_.candidates
        self.assertEqual(sorted(candidates), sorted(BRIEF_LINES))
        self.assertEqual(candidates[LINE_SINCE],
                         ["2026-03-06 — draft written ([[Alpha]])"])
        self.assertEqual(candidates[LINE_NEED], ["review the draft ([[Alpha]])"])
        self.assertEqual(candidates[LINE_DECISION],
                         ["[[Alpha]] — deadline 2026-03-20 (in 10 days)"])
        self.assertEqual(candidates[LINE_FYI],
                         ["raw/notes/2026-03-06 On Alpha.md — 2026-03-06 — "
                          "Alpha notes (topic: Alpha)"])
        # Alpha's review is overdue; Beta has no unchecked action of mine.
        self.assertEqual(candidates[LINE_RISK],
                         ["[[Alpha]] — review overdue since 2026-03-01 (9 days)",
                          "[[Beta]] — no unchecked action of mine"])

    def test_the_five_lines_are_rendered_empty_in_order(self):
        text = render_markdown(self.brief_, COMMAND)
        labels = [line for line in text.splitlines() if line.startswith("- **")]
        self.assertEqual(labels, [f"- **{label}:**" for label in BRIEF_LINES])
        self.assertIn("    - candidate: review the draft ([[Alpha]])", text)


class PacketTest(VaultTest):
    def setUp(self):
        super().setUp()
        self.write("raw/diary/2026-03-08 Pat Nolan catch-up.md",
                   raw_note("2026-03-08", "Talked about [[Alpha]]."))
        self.write("raw/notes/2026-03-09 On Alpha.md",
                   raw_note("2026-03-09", "More about [[Alpha]].",
                            description="Alpha notes"))
        self.brief_ = self.brief()

    def test_sections_in_order(self):
        text = render_markdown(self.brief_, COMMAND)
        headings = [line for line in text.splitlines() if line.startswith("## ")]
        self.assertEqual(headings, [
            "## Person",
            "## Their topics",
            "## Since last contact",
            "## Open asks",
            "## Other stakeholders on the same topics",
            "## Suggested brief skeleton",
        ])

    def test_person_and_topic_bodies(self):
        text = render_markdown(self.brief_, COMMAND)
        self.assertIn("# 1:1 brief packet — Pat Nolan", text)
        self.assertIn("- person: [[Pat Nolan]]", text)
        self.assertIn("- needs from me: a second opinion", text)
        self.assertIn("- cadence: weekly, 30 min (7d) — due in 5 days", text)
        # The evidence names the file and the rule that made it count.
        self.assertIn("- last contact: 2026-03-08 "
                      "(raw/diary/2026-03-08 Pat Nolan catch-up.md, diary)", text)
        self.assertIn("- next: *book it*", text)
        self.assertIn("### [[Alpha]]", text)
        self.assertIn("- progress: Alpha moved a step.", text)
        self.assertIn("- my next action: write the definitions", text)
        self.assertIn("    - [ ] review the draft", text)
        self.assertIn("- log since 2026-03-08:", text)
        self.assertIn("    - (nothing logged)", text)
        self.assertIn("- [ ] review the draft — [[Alpha]]", text)

    def test_json_mirrors_the_sections(self):
        data = json.loads(render_json(self.brief_))
        self.assertEqual(data["today"], "2026-03-10")
        self.assertEqual(data["since"], "2026-03-08")
        self.assertEqual(data["person"]["name"], "Pat Nolan")
        self.assertEqual(data["person"]["cadence_days"], 7)
        self.assertEqual(data["person"]["last"], "2026-03-08")
        self.assertEqual([t["topic"] for t in data["topics"]], ["Alpha", "Beta"])
        self.assertEqual(data["topics"][0]["delegated"], ["review the draft"])
        self.assertEqual(data["topics_without_a_page"], [])
        self.assertEqual(
            [h["path"] for h in data["since_last_contact"]["on_their_topics"]],
            ["raw/notes/2026-03-09 On Alpha.md"])
        self.assertEqual([a["text"] for a in data["open_asks"]["delegated"]],
                         ["review the draft"])
        self.assertEqual([s["line"] for s in data["skeleton"]], list(BRIEF_LINES))
        self.assertEqual([o["person"] for o in data["other_stakeholders"]],
                         ["[[Another Person]]", "Some Group",
                          "[[Third Person]] / a steerco"])

    # ---------------------------------------------------------------- CLI

    def _run(self, *args, expect=0):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--vault", str(self.root), *args],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, expect, result.stderr)
        return result.stdout if expect == 0 else result.stderr

    def test_cli_prints_to_stdout(self):
        out = self._run("Pat", "--today", "2026-03-10")
        self.assertIn("# 1:1 brief packet — Pat Nolan", out)
        self.assertIn("## Suggested brief skeleton", out)

    def test_cli_writes_the_out_file_and_json(self):
        self._run("Pat", "--today", "2026-03-10", "--out", str(self.root / "out.md"))
        self.assertIn("## Person", self.read("out.md"))
        data = json.loads(self._run("Pat", "--today", "2026-03-10",
                                    "--format", "json"))
        self.assertEqual(data["person"]["name"], "Pat Nolan")

    def test_cli_rejects_bad_dates_and_an_empty_window(self):
        self._run("Pat", "--today", "yesterday", expect=2)
        self._run("Pat", "--since", "yesterday", expect=2)
        self._run("Pat", "--today", "2026-03-10", "--since", "2026-03-10", expect=2)

    def test_cli_reports_an_unresolvable_person(self):
        self.assertIn("no stakeholder matches 'Nobody'",
                      self._run("Nobody", "--today", "2026-03-10", expect=2))
        self.assertIn("matches 2 stakeholders",
                      self._run("Person", "--today", "2026-03-10", expect=2))


if __name__ == "__main__":
    unittest.main()
