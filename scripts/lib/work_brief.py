"""Gather the deterministic packet one pre-1:1 stakeholder brief is written from.

The brief itself is five sentences of judgement, so it stays with the skill.
Everything that can be *looked up* is compiled here: the person's row in
`work/Stakeholders.md`, the topics they are tied to, what is delegated to them
and what I owe them, the raw material that appeared since we last spoke, and a
labelled skeleton whose candidate bullets are picked mechanically.

Four invariants, the same ones the weekly packet holds:

* **Nothing is parsed twice.** Topic pages come from `lib.work_backlog`, the
  stakeholder table, raw scan, name matching, cadence and topic mapping from
  `lib.work_weekly`. This module only projects what those two already read, so
  a brief and a weekly review can never disagree about a date or a name.
* **Today and the window are arguments.** The window is half-open at the start
  — `since < day <= today` — so material from the day of the last conversation
  is not reported back as news. `since` defaults to the resolved last-contact
  date, then to one cadence, then to `DEFAULT_WINDOW_DAYS`.
* **The vault is read-only here.** The CLI writes at most the one file it was
  asked for; the brief is written by the skill, into `work/briefs/`.
* **The skeleton candidates are material, not sentences.** Each one is a log
  line, a delegated item, a deadline or a file path lifted verbatim from a
  section above it. No ranking, no summarising, no invention.
"""

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .work_backlog import (
    DEADLINE_WINDOW_DAYS,
    EMPTY_LINE,
    LogEntry,
    Task,
    Topic,
    generated_banner,
)
from .work_weekly import (
    CONTACT_LOOKBACK_DAYS,
    MIN_NAME_CHARS,
    STAKEHOLDERS_PATH,
    CadenceRow,
    Stakeholder,
    cadence_rows,
    contact_evidence,
    map_raw_to_topics,
    mentions,
    nfc,
    phrase_in,
    raw_dirs,
    scan_raw,
    strip_link,
    weak_topic_counts,
)

# A brief reads every raw folder except the ones that are somebody else's
# work: a clipped article is not news about this person.
BRIEF_DENY_DIRS = ("clips",)
# Where the skill writes the brief itself. Nothing here writes it.
BRIEFS_DIR = "work/briefs"

# Window when the person has neither a last contact nor a parsable cadence.
DEFAULT_WINDOW_DAYS = 14
# Most candidates a skeleton line gets. Four would already be a paragraph.
CANDIDATE_CAP = 3

SECTION_PERSON = "Person"
SECTION_TOPICS = "Their topics"
SECTION_WINDOW = "Since last contact"
SECTION_ASKS = "Open asks"
SECTION_OTHERS = "Other stakeholders on the same topics"
SECTION_SKELETON = "Suggested brief skeleton"

# The five lines of the brief, in the order they are said out loud.
LINE_SINCE = "Since last time"
LINE_NEED = "What I need from you"
LINE_RISK = "Risk I see"
LINE_DECISION = "Decision needed"
LINE_FYI = "FYI"
BRIEF_LINES = (LINE_SINCE, LINE_NEED, LINE_RISK, LINE_DECISION, LINE_FYI)

NO_TOPIC_PAGE = "no topic page"
NO_PROGRESS = "(no progress)"
NEVER = "never contacted"


class PersonError(ValueError):
    """`PERSON` matched no stakeholder row, or more than one."""


# --------------------------------------------------------------------------- #
# Small shared helpers


def _section(title: str, body: list[str]) -> list[str]:
    return [f"## {title}", ""] + (body or [EMPTY_LINE]) + [""]


def first_name(name: str) -> str:
    parts = (name or "").split()
    return parts[0] if parts else ""


def primary_name(person: Stakeholder) -> str:
    """What to call this row: its first link target, else its plain text."""
    return person.names[0] if person.names else person.person


def match_keys(person: Stakeholder) -> list[str]:
    """Every string `PERSON` may be given as for this row.

    The cell as written, its link targets, and the cell with any ` / …` suffix
    dropped — `[[Someone]] / a steerco` is addressed as "Someone" as often as
    by the whole cell.
    """
    head = person.person.split(" / ")[0].strip()
    out: list[str] = []
    for key in [person.person, *person.names, strip_link(head), head]:
        key = (key or "").strip()
        if key and key not in out:
            out.append(key)
    return out


def ambiguous_first_name(person: Stakeholder,
                         stakeholders: list[Stakeholder]) -> list[str]:
    """Other rows that answer to the same first name as this one.

    `resolve_person` refuses an ambiguous query outright rather than guessing,
    so matching `@Pat` or the bare word "Pat" against a roster holding two
    Pats would be the one place in the packet that does guess. Names in
    roster order, so the packet line reads the same twice.
    """
    mine = {nfc(first_name(n)).lower() for n in person.names if first_name(n)}
    out: list[str] = []
    for other in stakeholders:
        if other is person or other.person == person.person:
            continue
        theirs = {nfc(first_name(n)).lower() for n in other.names if first_name(n)}
        if mine.intersection(theirs):
            name = primary_name(other)
            if name not in out:
                out.append(name)
    return out


def name_tokens(person: Stakeholder,
                stakeholders: list[Stakeholder] | None = None) -> set[str]:
    """Full names and first names, normalised and lowercased.

    `lib.work_backlog` parses a delegated owner as one whitespace-free token,
    so `@Pat` has to reach "Pat Smith" through the first name. Anything under
    `MIN_NAME_CHARS` is dropped: a two-letter token is an abbreviation, and
    matching one against free text finds it everywhere.

    Given the roster, a first name shared with another row is dropped as
    well — with two Pats on the table, `@Pat` names neither of them, and only
    the full name (or `@Pat Nolan`, which `_owner_keys` rejoins) matches. A
    row whose whole name is one word keeps it: that word *is* the full name.
    """
    others = stakeholders or []
    ambiguous = bool(ambiguous_first_name(person, others)) if others else False
    tokens: set[str] = set()
    for name in person.names:
        for token in (name,) if ambiguous else (name, first_name(name)):
            token = nfc(token).strip().lower()
            if len(token) >= MIN_NAME_CHARS:
                tokens.add(token)
    return tokens


def resolve_person(stakeholders: list[Stakeholder], query: str) -> Stakeholder:
    """The one row `query` names, case-insensitively.

    An exact key wins outright, so a row called "Pat" is still reachable when a
    row "Pat Smith" exists. Otherwise any substring is accepted — a first name
    is the usual way to ask — and an ambiguous or unmatched query raises with
    the full candidate list rather than guessing.
    """
    candidates = ", ".join(primary_name(p) for p in stakeholders) or "(none)"
    needle = (query or "").strip().lower()
    if not needle:
        raise PersonError(f"no person given — candidates: {candidates}")

    exact = [p for p in stakeholders if any(k.lower() == needle for k in match_keys(p))]
    partial = [p for p in stakeholders
               if any(needle in k.lower() for k in match_keys(p))]
    for found in (exact, partial):
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            names = ", ".join(primary_name(p) for p in found)
            raise PersonError(f"{query!r} matches {len(found)} stakeholders: {names}")
    raise PersonError(f"no stakeholder matches {query!r} — candidates: {candidates}")


# --------------------------------------------------------------------------- #
# Topics, asks and raw material


@dataclass
class TopicBrief:
    """One of the person's topics, reduced to what a 1:1 needs."""

    name: str
    progress: str = ""
    next_action: str = ""
    delegated: list[Task] = field(default_factory=list)
    log: list[LogEntry] = field(default_factory=list)
    deadline: date | None = None
    next_review: date | None = None

    @property
    def link(self) -> str:
        return f"[[{self.name}]]"


@dataclass
class Ask:
    """One open item, with the topic page it lives on."""

    text: str
    topic: str

    @property
    def line(self) -> str:
        return f"- [ ] {self.text} — [[{self.topic}]]"


@dataclass
class RawHit:
    """A raw note in the window. `topics` is empty for a direct mention."""

    rel: str
    day: date
    description: str
    topics: list[str] = field(default_factory=list)
    # Which `contact_evidence` rule made this file contact, for the files
    # where one did. Empty for a mention and for a topic hit.
    reason: str = ""

    @property
    def line(self) -> str:
        line = f"- {self.rel} — {self.day.isoformat()} — {self.description}"
        if self.reason:
            line += f" ({self.reason})"
        if self.topics:
            line += f" (topic: {', '.join(self.topics)})"
        return line


def owns_topic(topic: Topic, person: Stakeholder) -> bool:
    """Does this topic's own `stakeholders:` field name the person?"""
    listed = {strip_link(v).lower() for v in topic.stakeholders if strip_link(v)}
    return bool(listed.intersection({n.lower() for n in person.names if n}))


def person_topics(person: Stakeholder,
                  topics: list[Topic]) -> tuple[list[Topic], list[str]]:
    """The union of the row's `Topics` column and the topics claiming them.

    The column is a habit that gets forgotten and a topic page's own
    `stakeholders:` is the other half of the same fact, so neither alone is the
    answer. Column order is kept — that is the person's own priority — and the
    pages that only claim the person follow, by name. A name with no live page
    comes back separately rather than silently vanishing.
    """
    live = [t for t in topics if not t.is_done]
    by_name = {t.name: t for t in live}
    ordered = list(dict.fromkeys(person.topics))
    ordered += sorted(t.name for t in live
                      if owns_topic(t, person) and t.name not in ordered)
    found = [by_name[name] for name in ordered if name in by_name]
    missing = [name for name in ordered if name not in by_name]
    return found, missing


def _owner_keys(task: Task) -> list[str]:
    """Who a delegated item is addressed to, as written and rejoined.

    `lib.work_backlog` takes the owner as the first whitespace-free token
    after the `@`, so `@Pat Nolan — review the draft` arrives as owner "Pat"
    with "Nolan — review the draft" as its text. Rejoining the two is what
    lets a first name shared by two rows still be matched on the full name
    the page actually wrote.
    """
    person = nfc(task.person or "").strip()
    if not person:
        return []
    keys = [person]
    words = nfc(task.text or "").split()
    if words:
        keys.append(f"{person} {words[0].strip(',;.')}")
    return keys


def delegated_to(topic: Topic, person: Stakeholder,
                 stakeholders: list[Stakeholder] | None = None) -> list[Task]:
    """Unchecked `@Name` items on this topic that belong to the person."""
    tokens = name_tokens(person, stakeholders)
    return [t for t in topic.delegated
            if not t.done and any(k.lower() in tokens for k in _owner_keys(t))]


def topic_brief(topic: Topic, person: Stakeholder, since: date, today: date,
                stakeholders: list[Stakeholder] | None = None) -> TopicBrief:
    open_tasks = topic.open_tasks()
    return TopicBrief(
        name=topic.name,
        progress=topic.progress or NO_PROGRESS,
        next_action=open_tasks[0].text if open_tasks else "",
        delegated=delegated_to(topic, person, stakeholders),
        log=sorted((e for e in topic.log if since < e.day <= today),
                   key=lambda e: e.day),
        deadline=topic.deadline,
        next_review=topic.next_review,
    )


def open_asks(topics: list[Topic], person: Stakeholder,
              stakeholders: list[Stakeholder] | None = None) -> list[Ask]:
    """Everything delegated to the person, across every live topic."""
    out: list[Ask] = []
    for topic in [t for t in topics if not t.is_done]:
        out += [Ask(text=task.text, topic=topic.name)
                for task in delegated_to(topic, person, stakeholders)]
    return out


def owed_asks(topics: list[Topic], person: Stakeholder,
              stakeholders: list[Stakeholder] | None = None) -> list[Ask]:
    """My own unchecked actions that name the person — what I owe them.

    A first name is usually enough here. On a topic page it is my own
    handwriting, not a shared inbox, so "ask Pat about the split" is about
    Pat — but it has to be the word "Pat", not the "pat" inside "patch the
    pipeline", and with a second Pat on the roster it has to be the full name.
    """
    tokens = name_tokens(person, stakeholders)
    out: list[Ask] = []
    for topic in [t for t in topics if not t.is_done]:
        for task in topic.open_tasks():
            if any(phrase_in(task.text, token) for token in tokens):
                out.append(Ask(text=task.text, topic=topic.name))
    return out


def other_stakeholders(stakeholders: list[Stakeholder], person: Stakeholder,
                       topics: list[Topic],
                       names: set[str]) -> list[tuple[str, list[str]]]:
    """Rows sharing at least one topic with the person, and which topics.

    Same union rule as for the person themselves, so someone tied to a topic
    only by its page still shows up.
    """
    rows: list[tuple[Stakeholder, list[str]]] = []
    for other in stakeholders:
        if other is person or other.person == person.person:
            continue
        found, _ = person_topics(other, topics)
        shared = sorted(names.intersection({t.name for t in found}))
        if shared:
            rows.append((other, shared))
    # Most overlap first, then by the name a person is called — not by the cell,
    # whose leading `[[` would sort every linked row after every plain one.
    rows.sort(key=lambda pair: (-len(pair[1]), primary_name(pair[0])))
    return [(other.person, shared) for other, shared in rows]


# --------------------------------------------------------------------------- #
# The packet


@dataclass
class Brief:
    """Everything a pre-1:1 brief needs, in one deterministic bundle."""

    today: date
    since: date
    person: Stakeholder
    contact: CadenceRow
    topics: list[TopicBrief] = field(default_factory=list)
    missing_topics: list[str] = field(default_factory=list)
    # Files the person took part in, by the same `contact_evidence` rule the
    # weekly review's cadence uses, and files that merely name them. The
    # second list is never evidence that anything was said.
    contact_raw: list[RawHit] = field(default_factory=list)
    mentions: list[RawHit] = field(default_factory=list)
    topic_raw: list[RawHit] = field(default_factory=list)
    # Topic name → how many notes reached it only through a shared goal or a
    # shared stakeholder. A count rather than a list, for the same reason the
    # weekly packet counts them: the list is most of the quarter.
    weak_topic_raw: dict[str, int] = field(default_factory=dict)
    delegated: list[Ask] = field(default_factory=list)
    owed: list[Ask] = field(default_factory=list)
    others: list[tuple[str, list[str]]] = field(default_factory=list)
    candidates: dict[str, list[str]] = field(default_factory=dict)
    # Other rows sharing this person's first name. Non-empty means the
    # delegated and owed lists were matched on the full name only.
    ambiguous: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return primary_name(self.person)


def default_since(contact: CadenceRow, today: date) -> date:
    """The last contact, else one cadence back, else `DEFAULT_WINDOW_DAYS`.

    The point of the window is "what happened that they have not heard", so it
    starts where the last conversation ended whenever that is known.
    """
    if contact.last is not None:
        return contact.last
    return today - timedelta(days=contact.cadence_days or DEFAULT_WINDOW_DAYS)


def build_brief(root: Path, topics: list[Topic], stakeholders: list[Stakeholder],
                person: Stakeholder, today: date,
                since: date | None = None) -> Brief:
    """Read the vault once and assemble every section.

    The raw scan has to reach back `CONTACT_LOOKBACK_DAYS` to resolve the last
    contact at all, and that resolution is what fixes `since` — so the scan is
    widened a second time only when the caller asked for an older window than
    the lookback.
    """
    dirs = raw_dirs(root, BRIEF_DENY_DIRS)
    lookback = today - timedelta(days=CONTACT_LOOKBACK_DAYS)
    earliest = min(since, lookback) if since else lookback
    raws = scan_raw(root, earliest, today, dirs)
    contact = cadence_rows([person], raws, today)[0]
    if since is None:
        since = default_since(contact, today)
        if since < earliest:
            raws = scan_raw(root, since, today, dirs)

    found, missing = person_topics(person, topics)
    names = {t.name for t in found}
    briefs = [topic_brief(t, person, since, today, stakeholders) for t in found]

    # One pass over the window, splitting on the same rule the cadence uses:
    # a file the person took part in, versus a file that merely names them.
    contact_hits: list[RawHit] = []
    mention_hits: list[RawHit] = []
    named_rels: set[str] = set()
    for raw in [r for r in raws if since < r.day <= today]:
        reason = next((found_reason for found_reason
                       in (contact_evidence(raw, n) for n in person.names)
                       if found_reason), "")
        if not reason and not any(mentions(raw, n) for n in person.names):
            continue
        named_rels.add(raw.rel)
        hit = RawHit(rel=raw.rel, day=raw.day, description=raw.description,
                     reason=reason)
        (contact_hits if reason else mention_hits).append(hit)
    mapped, weak, _ = map_raw_to_topics(raws, topics, stakeholders, since, today)
    topic_raw = [
        RawHit(rel=item.rel, day=item.day, description=item.description,
               topics=[t for t in item.topics if t in names])
        for item in mapped
        if item.rel not in named_rels and names.intersection(item.topics)
    ]
    weak_counts = {
        name: n
        for name, n in weak_topic_counts(
            [i for i in mapped + weak if i.rel not in named_rels]).items()
        if name in names
    }

    brief = Brief(
        today=today,
        since=since,
        person=person,
        contact=contact,
        topics=briefs,
        missing_topics=missing,
        contact_raw=contact_hits,
        mentions=mention_hits,
        topic_raw=topic_raw,
        weak_topic_raw=weak_counts,
        delegated=open_asks(topics, person, stakeholders),
        owed=owed_asks(topics, person, stakeholders),
        others=other_stakeholders(stakeholders, person, topics, names),
        ambiguous=ambiguous_first_name(person, stakeholders),
    )
    brief.candidates = candidate_lines(brief, today)
    return brief


def candidate_lines(brief: Brief, today: date) -> dict[str, list[str]]:
    """Material for each of the five lines, lifted from the sections above.

    Mechanical on purpose: a log line is a "since last time" candidate because
    it is dated inside the window, not because anything judged it interesting.
    Which candidates survive into a sentence — and which line they belong on —
    is the skill's call.
    """
    since_last = sorted(
        ((entry.day, f"{entry.day.isoformat()} — {entry.text} ([[{topic.name}]])")
         for topic in brief.topics for entry in topic.log),
        key=lambda pair: pair[0], reverse=True)

    horizon = today + timedelta(days=DEADLINE_WINDOW_DAYS)
    decisions = [
        f"[[{topic.name}]] — deadline {topic.deadline.isoformat()} "
        f"(in {(topic.deadline - today).days} days)"
        for topic in sorted((t for t in brief.topics
                             if t.deadline and today <= t.deadline <= horizon),
                            key=lambda t: (t.deadline, t.name))
    ]

    risks: list[str] = []
    for topic in brief.topics:
        if topic.next_review is not None and topic.next_review < today:
            risks.append(f"[[{topic.name}]] — review overdue since "
                         f"{topic.next_review.isoformat()} "
                         f"({(today - topic.next_review).days} days)")
        if not topic.next_action:
            risks.append(f"[[{topic.name}]] — no unchecked action of mine")

    return {
        LINE_SINCE: [text for _, text in since_last][:CANDIDATE_CAP],
        LINE_NEED: [f"{ask.text} ([[{ask.topic}]])"
                    for ask in brief.delegated][:CANDIDATE_CAP],
        LINE_RISK: risks[:CANDIDATE_CAP],
        LINE_DECISION: decisions[:CANDIDATE_CAP],
        LINE_FYI: [hit.line[2:] for hit in brief.topic_raw][:CANDIDATE_CAP],
    }


# --------------------------------------------------------------------------- #
# Rendering


def person_lines(brief: Brief) -> list[str]:
    person, contact = brief.person, brief.contact
    cadence = person.cadence_raw or "(none)"
    if contact.cadence_days is not None:
        cadence += f" ({contact.cadence_days}d)"
    last = NEVER
    if contact.last is not None:
        evidence = contact.evidence or STAKEHOLDERS_PATH
        if contact.evidence_reason:
            evidence += f", {contact.evidence_reason}"
        last = f"{contact.last.isoformat()} ({evidence})"
    lines = [
        f"- person: {person.person}",
        f"- needs from me: {person.needs or '(not recorded)'}",
        f"- cadence: {cadence} — {contact.status}",
        f"- channel: {person.channel or '(not recorded)'}",
        f"- last contact: {last}",
        f"- next: {person.next_raw or '(not planned)'}",
    ]
    if brief.ambiguous:
        others = ", ".join(f"[[{name}]]" for name in brief.ambiguous)
        lines.append(f"- first name ambiguous with {others}; "
                     "matched on full name only")
    return lines


def topic_lines(brief: Brief) -> list[str]:
    lines: list[str] = []
    for topic in brief.topics:
        lines += [f"### {topic.link}", ""]
        lines.append(f"- progress: {topic.progress}")
        lines.append(f"- my next action: {topic.next_action or EMPTY_LINE[2:]}")
        if topic.delegated:
            lines.append(f"- delegated to {brief.name}:")
            lines += [f"    - [ ] {task.text}" for task in topic.delegated]
        else:
            lines.append(f"- delegated to {brief.name}: (none)")
        lines.append(f"- log since {brief.since.isoformat()}:")
        lines += [f"    - {entry.day.isoformat()} — {entry.text}"
                  for entry in topic.log] or ["    - (nothing logged)"]
        lines.append("")
    for name in brief.missing_topics:
        lines += [f"- [[{name}]] — {NO_TOPIC_PAGE}", ""]
    return lines[:-1] if lines else []


def window_lines(brief: Brief) -> list[str]:
    lines = ["### Contact", ""]
    lines += [hit.line for hit in brief.contact_raw] or [EMPTY_LINE]
    lines += ["", "### Mentions them (not contact)", ""]
    lines += [hit.line for hit in brief.mentions] or [EMPTY_LINE]
    lines += ["", "### On their topics, without naming them", ""]
    strong = [hit.line for hit in brief.topic_raw]
    weak = [f"- +{n} weak via goal/stakeholder on [[{name}]]"
            for name, n in sorted(brief.weak_topic_raw.items())]
    lines += strong + weak or [EMPTY_LINE]
    return lines


def ask_lines(brief: Brief) -> list[str]:
    lines = [f"### Delegated to {brief.name}", ""]
    lines += [ask.line for ask in brief.delegated] or [EMPTY_LINE]
    lines += ["", f"### What I owe {brief.name} (my actions naming them)", ""]
    lines += [ask.line for ask in brief.owed] or [EMPTY_LINE]
    return lines


def other_lines(brief: Brief) -> list[str]:
    return [f"- {person} — shares " + ", ".join(f"[[{name}]]" for name in shared)
            for person, shared in brief.others]


def skeleton_lines(brief: Brief) -> list[str]:
    lines = ["Write one sentence per line. The candidates are material lifted "
             "from the sections above — not sentences, and not a ranking.", ""]
    for label in BRIEF_LINES:
        lines.append(f"- **{label}:**")
        lines += [f"    - candidate: {text}"
                  for text in brief.candidates.get(label, [])]
    return lines


def render_markdown(brief: Brief, command: str) -> str:
    """The packet as one Markdown document, in the order the brief is written."""
    out = [
        *generated_banner(command, brief.today, "data for a 1:1 brief, not the brief itself"),
        "",
        f"# 1:1 brief packet — {brief.name}",
        "",
        f"{brief.since.isoformat()} .. {brief.today.isoformat()}",
        "",
    ]
    out += _section(SECTION_PERSON, person_lines(brief))
    out += _section(SECTION_TOPICS, topic_lines(brief))
    out += _section(SECTION_WINDOW, window_lines(brief))
    out += _section(SECTION_ASKS, ask_lines(brief))
    out += _section(SECTION_OTHERS, other_lines(brief))
    out += _section(SECTION_SKELETON, skeleton_lines(brief))
    return "\n".join(out).rstrip("\n") + "\n"


def render_json(brief: Brief) -> str:
    """The same sections as data, for anything that would otherwise re-parse."""
    data = {
        "today": brief.today.isoformat(),
        "since": brief.since.isoformat(),
        "person": {
            "name": brief.name,
            "cell": brief.person.person,
            "needs": brief.person.needs,
            "cadence": brief.person.cadence_raw,
            "cadence_days": brief.contact.cadence_days,
            "channel": brief.person.channel,
            "last": brief.contact.last.isoformat() if brief.contact.last else None,
            "evidence": brief.contact.evidence or None,
            "evidence_reason": brief.contact.evidence_reason or None,
            "status": brief.contact.status,
            "weak_mentions": brief.contact.weak_mentions,
            "next": brief.person.next_raw,
            "first_name_ambiguous_with": brief.ambiguous,
        },
        "topics": [
            {
                "topic": topic.name,
                "progress": topic.progress,
                "next_action": topic.next_action or None,
                "delegated": [task.text for task in topic.delegated],
                "log": [{"date": e.day.isoformat(), "text": e.text}
                        for e in topic.log],
                "deadline": topic.deadline.isoformat() if topic.deadline else None,
                "next_review": (topic.next_review.isoformat()
                                if topic.next_review else None),
            }
            for topic in brief.topics
        ],
        "topics_without_a_page": brief.missing_topics,
        "since_last_contact": {
            "contact": [
                {"path": h.rel, "date": h.day.isoformat(),
                 "description": h.description, "reason": h.reason}
                for h in brief.contact_raw
            ],
            "mentions_them": [
                {"path": h.rel, "date": h.day.isoformat(),
                 "description": h.description}
                for h in brief.mentions
            ],
            "on_their_topics": [
                {"path": h.rel, "date": h.day.isoformat(),
                 "description": h.description, "topics": h.topics}
                for h in brief.topic_raw
            ],
            "on_their_topics_weak": [
                {"topic": name, "files": n}
                for name, n in sorted(brief.weak_topic_raw.items())
            ],
        },
        "open_asks": {
            "delegated": [{"text": a.text, "topic": a.topic}
                          for a in brief.delegated],
            "owed": [{"text": a.text, "topic": a.topic} for a in brief.owed],
        },
        "other_stakeholders": [{"person": person, "shared_topics": shared}
                               for person, shared in brief.others],
        "skeleton": [{"line": label, "candidates": brief.candidates.get(label, [])}
                     for label in BRIEF_LINES],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"
