"""Gather the deterministic data packet the Monday weekly review reads from.

The review itself is a judgement call, so it stays with the skill. Everything
that can be *counted* is compiled here: the progress snapshot, the compiled
backlog, stakeholders past their cadence, raw material that appeared since the
last review, wiki pages that changed, deadlines inside the horizon, and the
interactions between topics. Nothing here is derived by an LLM, so the packet
can be regenerated at any time and thrown away.

Five invariants:

* **Being named is not evidence.** A cc on a mail to the department and a name
  in the body of somebody else's notes are not a conversation, and a one-word
  goal spelled out in prose is not a topic. Every count here separates what
  positively happened — `contact_evidence`, a title or `related` hit — from
  what merely co-occurred, and reports the second as a number rather than
  hiding it or letting it masquerade as the first.
* **The topic pages are read-only.** This module never writes; the CLI writes
  at most the one file it was asked for. All topic parsing is
  `lib.work_backlog` — the packet is another projection of the same pages, not
  a second parser.
* **Today and the window are arguments.** Every date comparison goes through
  the caller's `today`/`since`, which is what makes the whole packet testable.
  The window is half-open at the start — `since < day <= today` — so a file
  already reported by last week's review is not reported twice.
* **A date comes from the filename when the filename has one.** Raw folders
  hold thousands of files; parsing the leading `YYYY-MM-DD` off the name costs
  nothing, and only a file whose name carries no date is opened to look at its
  frontmatter. That, and one `Haystack` per file rather than one per key, is
  what keeps a full scan to a second or two.
* **`## Snapshot` is a contract.** `lib.work_backlog.load_snapshots` reads the
  weekly files back for start-of-period progress, so the snapshot section is
  emitted in exactly the shape that parser expects.
"""

import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from .work_backlog import (
    DEADLINE_WINDOW_DAYS,
    EMPTY_LINE,
    SECTION_SNAPSHOT,
    WEEKLY_DIR,
    Topic,
    compile_backlog,
    deadline_lines,
    generated_banner,
    parse_date,
    parse_frontmatter,
    parse_week_stem,
)

# Where the packet reads from, relative to the vault root.
STAKEHOLDERS_PATH = "work/Stakeholders.md"
WIKI_LOG_PATH = "wiki/log.jsonl"
# Every folder under `raw/` is scanned. Naming the ones that count was a
# standing source of blind spots — `raw/scans/`, `raw/confluence/` and
# `raw/work-in-progress/` were six hundred files nobody's review ever saw — so
# the rule is inverted: everything, minus the folders that hold no notes.
RAW_ROOT = "raw"
RAW_DENY = ("_resources", "resources")
# Contact evidence only counts from the folders that record an interaction —
# a clipped article mentioning a name is not a conversation with them.
CONTACT_DIRS = ("raw/emails", "raw/slack", "raw/diary", "raw/transcripts", "raw/notes")
# A diary entry is my own record of a conversation: its title is the evidence.
DIARY_DIRS = ("raw/diary",)
# Folders whose files carry an attendee list or speaker turns.
MEETING_DIRS = ("raw/transcripts", "raw/notes")
# Wiki page types worth surfacing in the scan step. `people`, `concepts` and
# `conversations` change constantly without changing what to work on.
WIKI_TYPES = ("problems", "decisions", "projects", "systems", "competition")
# Statuses that are still mappable but are not what this week is about.
WATCHING_STATUSES = ("watching", "parked")

DEFAULT_WINDOW_DAYS = 7
CONTACT_LOOKBACK_DAYS = 90
# A link has to tie together at least this many unmapped files to be worth
# naming as a candidate topic.
CLUSTER_MIN = 2
# The path, the frontmatter and this many body lines are the "header" of a
# file — where a diary title and a converted mail's `**From:**` line live.
MENTION_HEAD_LINES = 40
# Frontmatter fields that list who was in the room.
ATTENDEE_KEYS = ("attendees", "participants", "speakers")
# A `to:` longer than this is a broadcast, not a conversation.
RECIPIENT_CAP = 3
# Tokens that give away a distribution list rather than a person.
DISTRIBUTION_HINTS = frozenset(
    {"employees", "contractors", "staff", "worldwide", "all", "dl", "list",
     "team", "group", "everyone", "users", "members", "department", "dept"})
# Shorter than this, a name is an abbreviation that matches anything — "TT"
# inside "https", "Jo" inside "Johnson".
MIN_NAME_CHARS = 3
# A one-word key only counts as a wikilink. Spelled out in prose, a single
# programme name lands on hundreds of unrelated files.
MIN_PHRASE_CHARS = 4
# Two topics on a small roster share one stakeholder as a matter of course.
MIN_SHARED_STAKEHOLDERS = 2
# Enough of a file to hold its frontmatter and the part anyone reads.
READ_LIMIT = 60_000
# Contact evidence lives in the header, but the body has to stay searchable in
# the folders where a conversation is recorded in full.
DEEP_READ_LIMIT = 256 * 1024
DEEP_READ_DIRS = ("raw/diary", "raw/transcripts", "raw/emails")
DESCRIPTION_LIMIT = 160

SECTION_BACKLOG = "Backlog"
SECTION_CADENCE = "Stakeholder cadence"
SECTION_TOPIC_NEWS = "New on my topics since"
SECTION_UNMAPPED = "Unmapped new material"
SECTION_WIKI = "New or changed wiki pages"
SECTION_DEADLINES = "Deadlines and horizon flags"
SECTION_INTERACTION = "Interaction check"

NO_DESCRIPTION = "(no description)"
NO_CADENCE = "no fixed cadence"
NEVER_CONTACTED = "never contacted"

# Why a raw file counts as contact with a person, strongest first.
EVIDENCE_DIARY = "diary"
EVIDENCE_FROM = "from"
EVIDENCE_RECIPIENT = "to"
EVIDENCE_ATTENDEE = "attendees"
EVIDENCE_SPEAKER = "speaker"

_FILENAME_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
# `[[Target|alias]]`, `[[Target#heading]]` — the target is what identifies a
# page. A leading `!` makes it an embed, which is a file reference, not a topic
# reference, so those are skipped.
_LINK_RE = re.compile(r"(!?)\[\[([^\]|#]+)")
# A row starts with a pipe; the closing one is optional because hand-written
# tables lose it. Cells are split on unescaped pipes only, so a `\|` inside a
# cell stays part of that cell.
_TABLE_ROW_RE = re.compile(r"^\s*\|(.*?)\|?\s*$")
_TABLE_CELL_SPLIT_RE = re.compile(r"(?<!\\)\|")
_TABLE_RULE_RE = re.compile(r"^[\s|:-]+$")
_HEADING_TEXT_RE = re.compile(r"^#{1,6} +(.*?)\s*$")
# `**From:** Someone <s@x>` — a mail converted out of a `.eml` keeps its
# headers in the body, so the sender is not always in the frontmatter.
_HEADER_LINE_RE = re.compile(
    r"^\s*(?:>\s*)*\*\*(from|to|cc):?\*\*:?\s*(.*)$", re.IGNORECASE)
# `**Someone**` on a line of its own, with or without a timestamp — one turn
# of a transcript or a 1:1 note.
_SPEAKER_LINE_RE = re.compile(
    r"^\s*(?:>\s*)*\*\*([^*]{2,60}?)\*\*\s*:?\s*(?:\d{1,2}:\d{2}(?::\d{2})?)?\s*$")
# Lines that carry a citation rather than the page's own prose.
_FOOTNOTE_RE = re.compile(r"^\s*\[\^")
_RAW_ITEM_RE = re.compile(r"^\s*[-*]\s*!?\[\[raw/")
SOURCES_HEADING = "sources"

# Longest first: "bi-monthly" contains "monthly" and "2-weekly" contains
# "weekly", so the order of these patterns is the disambiguation.
CADENCE_PATTERNS = (
    (re.compile(r"bi[-\s]?monthly"), 60),
    (re.compile(r"quarterly"), 90),
    (re.compile(r"(?:2|two)[-\s]?weekly|bi[-\s]?weekly|fortnightly"), 14),
    (re.compile(r"monthly"), 30),
    (re.compile(r"weekly"), 7),
)


# --------------------------------------------------------------------------- #
# Small shared helpers


def nfc(text: str) -> str:
    """Compose accents. One machine writes `Víctor` as `Vi` + a combining
    acute and the other as one codepoint; either spelling has to match the
    table's, so every needle and every haystack passes through here.

    The `is_normalized` check is not decoration: almost every string in the
    vault is already NFC, and skipping the copy is the difference between
    normalising a 20 KB file once and normalising it once per key.
    """
    text = text or ""
    if unicodedata.is_normalized("NFC", text):
        return text
    return unicodedata.normalize("NFC", text)


@lru_cache(maxsize=4096)
def phrase_pattern(phrase: str) -> re.Pattern | None:
    """A whole-word, case-insensitive matcher for `phrase`, or None.

    Word boundaries are the whole point: without them "Pat" matches "patch"
    and "TT" matches "https". Lookarounds rather than `\\b` so a phrase that
    starts or ends on punctuation still anchors correctly.
    """
    needle = nfc(phrase).strip()
    if len(needle) < MIN_NAME_CHARS:
        return None
    return re.compile(rf"(?<!\w){re.escape(needle)}(?!\w)", re.IGNORECASE)


@dataclass
class Haystack:
    """A body of text prepared once for many whole-word searches.

    Normalising and lowercasing a 20 KB note is cheap; doing it again for
    every one of the eighty keys a portfolio of topics produces is not, and
    that was most of the scan's running time.
    """

    text: str
    lowered: str

    @classmethod
    def of(cls, text: str) -> "Haystack":
        text = nfc(text)
        return cls(text, text.lower())

    def has(self, phrase: str) -> bool:
        """Does `phrase` occur here as a whole word?"""
        needle = nfc(phrase).strip()
        if len(needle) < MIN_NAME_CHARS:
            return False
        # A substring test rejects nearly every key and costs a fraction of
        # the anchored match, which only runs once the text is known to be in
        # there somewhere.
        if needle.lower() not in self.lowered:
            return False
        pattern = phrase_pattern(needle)
        return bool(pattern and pattern.search(self.text))


def phrase_in(haystack: str, phrase: str) -> bool:
    """Does `phrase` occur in `haystack` as a whole word?

    For one-off searches. Anything searching the same text repeatedly should
    build a `Haystack` instead.
    """
    return Haystack.of(haystack).has(phrase)


def strip_link(value: str) -> str:
    """`[[Target|alias]]` → `Target`; anything else comes back trimmed."""
    value = (value or "").strip()
    match = _LINK_RE.match(value)
    return match.group(2).strip() if match else value


def link_targets(text: str) -> list[str]:
    """Every non-embed wikilink target in `text`, in order, deduplicated.

    Targets containing a `/` are file references (`![[raw/…]]`-style paths that
    lost their `!`), not page names, and are dropped.
    """
    out: list[str] = []
    for bang, target in _LINK_RE.findall(text or ""):
        name = nfc(target).strip()
        if bang or not name or "/" in name or name in out:
            continue
        out.append(name)
    return out


def _scalar(front: dict[str, str | list[str]], key: str) -> str:
    value = front.get(key)
    if isinstance(value, list):
        return ", ".join(value)
    return str(value or "")


def _read(path: Path, limit: int = READ_LIMIT) -> str:
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return handle.read(limit)


def page_body(text: str) -> str:
    """The page's own prose — footnotes, raw-file lists and `## Sources` cut.

    A page that cites `raw/notes/2026-03-05 Alpha review.md` in a footnote is
    not a page about Alpha, so those lines are removed before any phrase match
    rather than being matched and then doubted.
    """
    out: list[str] = []
    in_sources = False
    for line in text.splitlines():
        heading = _HEADING_TEXT_RE.match(line)
        if heading is not None:
            in_sources = heading.group(1).strip().lower().startswith(SOURCES_HEADING)
        if in_sources or _FOOTNOTE_RE.match(line) or _RAW_ITEM_RE.match(line):
            continue
        out.append(line)
    return "\n".join(out)


def _first_heading(text: str) -> str:
    for line in text.splitlines():
        match = _HEADING_TEXT_RE.match(line)
        if match and match.group(1):
            return match.group(1)
    return ""


def describe(front: dict[str, str | list[str]], text: str) -> str:
    """One line for a file: its own description, else subject/title, else H1.

    Frontmatter is read as text rather than as YAML, so a quoted description
    arrives with its `\\"` escapes intact; they are cosmetic and go.
    """
    for key in ("description", "subject", "title"):
        value = _scalar(front, key).strip().replace('\\"', '"')
        if value:
            return _clip(value)
    heading = _first_heading(text)
    return _clip(heading) if heading else NO_DESCRIPTION


def _clip(value: str) -> str:
    value = " ".join(value.split())
    if len(value) <= DESCRIPTION_LIMIT:
        return value
    return value[: DESCRIPTION_LIMIT - 1].rstrip() + "…"


def _section(title: str, body: list[str]) -> list[str]:
    return [f"## {title}", ""] + (body or [EMPTY_LINE]) + [""]


def week_label(day: date) -> str:
    year, week, _ = day.isocalendar()
    return f"{year}-W{week:02d}"


# --------------------------------------------------------------------------- #
# Raw material


@dataclass
class RawFile:
    """One raw note inside the scan window, with the text that was read."""

    rel: str
    day: date
    front: dict[str, str | list[str]] = field(default_factory=dict)
    text: str = ""
    _haystack: Haystack | None = field(default=None, compare=False, repr=False)

    @property
    def description(self) -> str:
        return describe(self.front, self.text)

    @property
    def folder(self) -> str:
        return self.rel.rsplit("/", 1)[0]

    @property
    def haystack(self) -> Haystack:
        """Path, frontmatter and body as one searchable whole.

        Everything that searches a raw file searches this, so a name found by
        the cadence step and a topic found by the mapping step can never have
        been looking at different amounts of the same file.
        """
        if self._haystack is None:
            front = "\n".join(f"{key}: {_scalar(self.front, key)}"
                              for key in self.front)
            self._haystack = Haystack.of(f"{self.rel}\n{front}\n{self.text}")
        return self._haystack

    @property
    def identity(self) -> str:
        """What the file says it is *about*: its name, its frontmatter, its H1.

        Not its body. A diary entry's title is my own record of who I spoke
        to, so it is contact evidence; a name that came up on line 30 of a
        day's notes is not, and searching forty lines of body for it counted
        every passing mention as a conversation.
        """
        front = "\n".join(_scalar(self.front, key) for key in self.front)
        return nfc(f"{self.rel}\n{front}\n{_first_heading(self.text)}")


def raw_dirs(root: Path, deny: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Every `raw/*` folder that holds at least one note.

    Listing the folders that count was a standing blind spot, so the list is
    discovered instead: attachment folders and empty ones drop out, everything
    else is scanned. `deny` is for a caller that means to exclude a folder —
    a brief has no use for clipped articles.
    """
    base = root / RAW_ROOT
    if not base.is_dir():
        return ()
    out: list[str] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if child.name in RAW_DENY or child.name in deny:
            continue
        if not any(child.rglob("*.md")):
            continue
        out.append(f"{RAW_ROOT}/{child.name}")
    return tuple(out)


def scan_raw(root: Path, earliest: date, today: date,
             dirs: tuple[str, ...] | None = None) -> list[RawFile]:
    """Every raw note dated in `[earliest, today]`, cheapest test first.

    A filename that starts with a date is trusted and the file is opened only
    when that date is inside the window; a filename without one costs one read
    to reach its frontmatter `date:`. Files under `_resources/` and the folder
    `index.md` pages are not notes and are skipped. `dirs` defaults to every
    folder `raw_dirs` finds.
    """
    out: list[RawFile] = []
    disagreed = 0
    for rel_dir in (raw_dirs(root) if dirs is None else dirs):
        folder = root / rel_dir
        if not folder.is_dir():
            continue
        limit = DEEP_READ_LIMIT if rel_dir in DEEP_READ_DIRS else READ_LIMIT
        for path in sorted(folder.rglob("*.md")):
            if "_resources" in path.parts or path.name == "index.md":
                continue
            named = _FILENAME_DATE_RE.match(path.name)
            day = parse_date(named.group(1)) if named else None
            text, front = "", {}
            if day is None:
                text = _read(path, limit)
                front = parse_frontmatter(text)
                day = parse_date(_scalar(front, "date"))
                if day is None:
                    continue
            if not (earliest <= day <= today):
                continue
            if not text:
                text = _read(path, limit)
                front = parse_frontmatter(text)
                stamped = parse_date(_scalar(front, "date"))
                if stamped is not None and stamped != day:
                    disagreed += 1
            out.append(RawFile(rel=path.relative_to(root).as_posix(), day=day,
                               front=front, text=text))
    if disagreed:
        print(f"warning: {disagreed} raw files in the window whose filename date "
              "and frontmatter `date:` disagree — the filename wins", file=sys.stderr)
    out.sort(key=lambda r: (r.day, r.rel))
    return out


def mentions(raw: RawFile, name: str) -> bool:
    """Is the person named anywhere in this file?

    A weak signal on its own — an article can name someone without either of
    us knowing about it — so this answers "worth showing" and never "we spoke".
    `contact_evidence` is the question the cadence asks.
    """
    return raw.haystack.has(name)


def _header_values(raw: RawFile, key: str) -> str:
    """One mail header, from the frontmatter and from the body.

    A mail converted out of a `.eml` keeps `**From:**` in the body instead of
    the frontmatter, and dropping those would lose the sender of every mail
    that came in through an attachment.
    """
    values = [_scalar(raw.front, key)]
    for line in raw.text.splitlines()[:MENTION_HEAD_LINES]:
        match = _HEADER_LINE_RE.match(line)
        if match and match.group(1).lower() == key:
            values.append(match.group(2))
    return "\n".join(v for v in values if v)


def recipients(raw: RawFile) -> list[str]:
    """The distinct entries of `to:` and `cc:`, however they were written."""
    out: list[str] = []
    for key in ("to", "cc"):
        for chunk in _header_values(raw, key).replace("\n", ",").split(","):
            chunk = chunk.strip()
            if chunk and chunk not in out:
                out.append(chunk)
    return out


def _display_name(entry: str) -> str:
    """The human part of `Someone <s@x>`, or "" when there is not one."""
    angle = entry.find("<")
    if angle >= 0:
        return entry[:angle].strip(" \"'")
    return "" if "@" in entry else entry.strip(" \"'")


def looks_like_distribution(entry: str) -> bool:
    """Is this recipient a list rather than a person?

    Token equality rather than substring: `all-employees@` is a list, while
    "Allison Marshall" contains "all" twice and is not.
    """
    tokens = set(re.findall(r"[a-z0-9]+", entry.lower()))
    if tokens.intersection(DISTRIBUTION_HINTS):
        return True
    return not re.search(r"[^\W\d_]", _display_name(entry))


def speaker_names(raw: RawFile) -> list[str]:
    """Every `**Someone**` that starts a turn, in order, deduplicated."""
    out: list[str] = []
    for line in raw.text.splitlines():
        match = _SPEAKER_LINE_RE.match(line)
        if match:
            name = match.group(1).strip()
            if name and name not in out:
                out.append(name)
    return out


def contact_evidence(raw: RawFile, name: str) -> str:
    """Why this file is evidence that I spoke with this person, or "".

    The distinction the cadence lives or dies on. Being *named* in a file is
    not contact — a cc on a mail to the whole department, a name in the body
    of somebody else's meeting notes — and counting it that way quietly
    reported every stakeholder as freshly spoken to. So evidence has to be one
    of four positive shapes, in this order:

    * a diary entry whose filename, frontmatter or first heading names them —
      my own record of it. Not its body: see `RawFile.identity`;
    * a `from:` naming them, addressed to at least one real person — they
      wrote to me. A mail from them to nothing but distribution lists is an
      announcement, and announcing something to the department is not a
      conversation with me. A file with no recipients at all (a diary
      export, a note converted without headers) keeps the sender;
    * a `to:`/`cc:` naming them on a list of at most `RECIPIENT_CAP` real
      people — a small thread is a conversation, a broadcast is not;
    * an attendee list or a speaker turn naming them in a transcript or a
      meeting note — we were in the room.

    Anything else, including a mention in the body, is not contact.
    """
    pattern = phrase_pattern(name)
    if pattern is None or raw.folder not in CONTACT_DIRS:
        return ""
    if raw.folder in DIARY_DIRS and pattern.search(raw.identity):
        return EVIDENCE_DIARY
    addressed = recipients(raw)
    if (pattern.search(nfc(_header_values(raw, "from")))
            and (not addressed
                 or any(not looks_like_distribution(e) for e in addressed))):
        return EVIDENCE_FROM
    if (any(pattern.search(nfc(entry)) for entry in addressed)
            and len(addressed) <= RECIPIENT_CAP
            and not any(looks_like_distribution(entry) for entry in addressed)):
        return EVIDENCE_RECIPIENT
    if raw.folder in MEETING_DIRS:
        listed = " · ".join(_scalar(raw.front, key) for key in ATTENDEE_KEYS)
        if pattern.search(nfc(listed)):
            return EVIDENCE_ATTENDEE
        if any(pattern.search(nfc(speaker)) for speaker in speaker_names(raw)):
            return EVIDENCE_SPEAKER
    return ""


# --------------------------------------------------------------------------- #
# Stakeholders


@dataclass
class Stakeholder:
    """One row of the `work/Stakeholders.md` table."""

    person: str                   # the cell as written, wikilinks included
    names: list[str]              # full names to match raw material against
    needs: str = ""
    cadence_raw: str = ""
    channel: str = ""
    last_raw: str = ""
    last: date | None = None
    next_raw: str = ""
    topics: list[str] = field(default_factory=list)

    @property
    def cadence_days(self) -> int | None:
        return parse_cadence(self.cadence_raw)


@dataclass
class CadenceRow:
    """A stakeholder measured against their cadence."""

    person: str
    cadence_raw: str
    cadence_days: int | None
    last: date | None = None
    evidence: str = ""            # where `last` came from
    evidence_reason: str = ""     # which `contact_evidence` rule matched
    overdue_days: int | None = None
    due_in_days: int | None = None
    skipped: str = ""             # reason, when there is no cadence to check
    # Files that name the person without being evidence of contact. Kept so
    # the review can see what was *not* counted rather than wonder.
    weak_mentions: list[str] = field(default_factory=list)

    @property
    def status(self) -> str:
        if self.skipped:
            return self.skipped
        if self.last is None:
            return NEVER_CONTACTED
        if self.overdue_days is not None:
            return f"overdue by {self.overdue_days} days"
        return f"due in {self.due_in_days} days"

    @property
    def sort_key(self) -> tuple[int, int, str]:
        """Never contacted, then most overdue, then soonest due, then skipped.

        A row with no parsable cadence cannot be late, so it is the one thing
        on this list that needs no decision this week — it goes last.
        """
        if self.skipped:
            return (3, 0, self.person)
        if self.last is None:
            return (0, 0, self.person)
        if self.overdue_days is not None:
            return (1, -self.overdue_days, self.person)
        return (2, self.due_in_days or 0, self.person)


def parse_cadence(text: str) -> int | None:
    """Free-text cadence → days, or None when the text fixes no interval."""
    lowered = (text or "").lower()
    for pattern, days in CADENCE_PATTERNS:
        if pattern.search(lowered):
            return days
    return None


def _table_cells(line: str) -> list[str] | None:
    """The cells of a Markdown table row, or None when this is not one.

    Splitting on unescaped pipes only is what lets a cell contain a literal
    `|`, written `\\|` as Markdown requires; the escape is cosmetic and goes.
    """
    match = _TABLE_ROW_RE.match(line)
    if not match or not line.lstrip().startswith("|"):
        return None
    return [cell.strip().replace("\\|", "|")
            for cell in _TABLE_CELL_SPLIT_RE.split(match.group(1))]


# The columns the packet reads, each with the header prefixes that name it.
# Prefix matching by design: "Cadence (target)" and "Last contact" are the
# same columns as "Cadence" and "Last", and renaming one must not silently
# empty it.
STAKEHOLDER_COLUMNS = (
    ("person", ("person",)),
    ("needs", ("needs",)),
    ("cadence", ("cadence",)),
    ("channel", ("channel",)),
    ("last", ("last",)),
    ("next", ("next",)),
    ("topics", ("topic",)),
)
REQUIRED_COLUMNS = ("person", "cadence")


def _header_index(cells: list[str]) -> dict[str, int]:
    """Column name → position, or {} when this row is not the header."""
    index: dict[str, int] = {}
    lowered = [cell.lower() for cell in cells]
    for key, prefixes in STAKEHOLDER_COLUMNS:
        for position, cell in enumerate(lowered):
            if cell.startswith(prefixes):
                index.setdefault(key, position)
                break
    if any(key not in index for key in REQUIRED_COLUMNS):
        return {}
    return index


def parse_stakeholders(root: Path) -> list[Stakeholder]:
    """The stakeholder table, by column *name* rather than by position.

    Reading the header row means an extra or reordered column does not shift
    every value by one. The header survives a stray non-table line inside the
    table, and it survives a blank line too: a blank line ends the table, but
    if more `|`-rows follow before the next heading they are still that
    table's rows, and dropping them lost a third of the roster without a
    word. Only a heading retires the header for good; a fresh header row
    replaces it. A file with no such table yields no rows and one warning
    rather than raising.
    """
    path = root / STAKEHOLDERS_PATH
    if not path.is_file():
        return []
    index: dict[str, int] = {}
    kept: dict[str, int] = {}      # the header a blank line set aside
    seen_header = False
    rows: list[Stakeholder] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        cells = _table_cells(line)
        if cells is None:
            if _HEADING_TEXT_RE.match(line):
                index, kept = {}, {}
            elif not line.strip():
                index, kept = {}, index or kept
            # Anything else is a wrapped cell or a stray line, and the header
            # still holds.
            continue
        if not index:
            found = _header_index(cells)
            if found:
                index, kept = found, {}
                seen_header = True
                continue
            if not kept:
                continue
            # More rows of the same table after a blank line.
            index, kept = kept, {}
        if _TABLE_RULE_RE.match("".join(cells)):
            continue

        def cell(key: str) -> str:
            position = index.get(key)
            return cells[position] if position is not None and position < len(cells) else ""

        person = cell("person")
        if not person:
            continue
        names = link_targets(person) or [nfc(person)]
        last_raw = cell("last")
        rows.append(Stakeholder(
            person=person,
            names=names,
            needs=cell("needs"),
            cadence_raw=cell("cadence"),
            channel=cell("channel"),
            last_raw=last_raw,
            last=parse_date(last_raw),
            next_raw=cell("next"),
            topics=link_targets(cell("topics")),
        ))
    if not seen_header:
        print(f"warning: no `Person` / `Cadence` header found in "
              f"{STAKEHOLDERS_PATH} — the cadence section will be empty",
              file=sys.stderr)
    return rows


def cadence_rows(stakeholders: list[Stakeholder], raws: list[RawFile],
                 today: date) -> list[CadenceRow]:
    """Each stakeholder's last contact and whether the cadence has slipped.

    Last contact is the later of the table's own `Last` date and the newest
    raw note inside `CONTACT_LOOKBACK_DAYS` that is `contact_evidence` for
    them — the table is a habit that gets forgotten, the raw folders are not.
    Files that merely name them are collected as `weak_mentions` instead, so
    the difference between "we spoke" and "your name came up" is visible.
    """
    window = today - timedelta(days=CONTACT_LOOKBACK_DAYS)
    recent = [r for r in raws if r.day >= window]
    out: list[CadenceRow] = []
    for person in stakeholders:
        newest: RawFile | None = None
        reason = ""
        weak: list[str] = []
        for raw in recent:
            found = ""
            for name in person.names:
                found = contact_evidence(raw, name)
                if found:
                    break
            if found:
                if newest is None or raw.day > newest.day:
                    newest, reason = raw, found
            elif any(mentions(raw, name) for name in person.names):
                weak.append(raw.rel)
        last, evidence = person.last, (STAKEHOLDERS_PATH if person.last else "")
        evidence_reason = ""
        if newest is not None and (last is None or newest.day > last):
            last, evidence, evidence_reason = newest.day, newest.rel, reason

        row = CadenceRow(person=person.person, cadence_raw=person.cadence_raw,
                         cadence_days=person.cadence_days, last=last,
                         evidence=evidence, evidence_reason=evidence_reason,
                         weak_mentions=list(reversed(weak)))
        if row.cadence_days is None:
            row.skipped = NO_CADENCE
        elif last is not None:
            elapsed = (today - last).days
            if elapsed > row.cadence_days:
                row.overdue_days = elapsed - row.cadence_days
            else:
                row.due_in_days = row.cadence_days - elapsed
        out.append(row)
    out.sort(key=lambda r: r.sort_key)
    return out


def cadence_lines(rows: list[CadenceRow]) -> list[str]:
    lines = []
    for row in rows:
        cadence = row.cadence_raw or "(none)"
        if row.cadence_days is not None:
            cadence += f" ({row.cadence_days}d)"
        line = f"- {row.person} — {cadence} — {row.status}"
        if row.last is not None:
            evidence = row.evidence
            if row.evidence_reason:
                evidence += f", {row.evidence_reason}"
            line += f" — last {row.last.isoformat()} ({evidence})"
        lines.append(line)
        if row.weak_mentions:
            lines.append(f"    - named in {len(row.weak_mentions)} files, not "
                         f"counted as contact (newest: {row.weak_mentions[0]})")
    return lines


# --------------------------------------------------------------------------- #
# Mapping raw material onto topics


@dataclass
class NewsItem:
    """A raw note in the window, with the topics it turned out to touch."""

    rel: str
    day: date
    description: str
    topics: list[str] = field(default_factory=list)
    matched_on: dict[str, str] = field(default_factory=dict)
    weak_topics: list[str] = field(default_factory=list)
    weak_matched_on: dict[str, str] = field(default_factory=dict)
    links: list[str] = field(default_factory=list)


@dataclass
class TopicKeys:
    """What ties a note to a topic, split by how much the tie is worth.

    A note that names the topic, or one of the pages the topic says it is
    `related:` to, is about the topic. A note that only shares the topic's
    quarterly `goal` or one of its stakeholders is about the same corner of
    the company — true of hundreds of files a quarter, and useless as a list.
    """

    strong: list[str] = field(default_factory=list)   # title, `related:`
    weak: list[str] = field(default_factory=list)      # `goal:`, stakeholders


def topic_keys(topic: Topic, stakeholders: list[Stakeholder]) -> TopicKeys:
    """The strong and weak keys for one topic."""
    keys = TopicKeys(strong=[nfc(topic.name)])
    for value in topic.related:
        name = nfc(strip_link(value))
        if name and name not in keys.strong:
            keys.strong.append(name)
    candidates = [strip_link(topic.goal)]
    candidates += [strip_link(v) for v in topic.stakeholders]
    for person in stakeholders:
        if topic.name in person.topics:
            candidates += list(person.names)
    for value in candidates:
        name = nfc(value)
        if name and name not in keys.strong and name not in keys.weak:
            keys.weak.append(name)
    return keys


def key_hit(key: str, links: set[str], haystack: Haystack) -> bool:
    """Does `key` identify this note — as a wikilink, or as a whole phrase?

    A wikilink always counts: writing `[[Atlas]]` is deliberate. Spelling the
    same word out in prose does not, unless the key is several words long:
    a one-word programme name appears in hundreds of files that have nothing
    to do with the topic, which is how one goal came to claim 312 of them.
    """
    if key in links:
        return True
    if len(key) < MIN_PHRASE_CHARS or len(key.split()) < 2:
        return False
    return haystack.has(key)


def map_raw_to_topics(
        raws: list[RawFile], topics: list[Topic], stakeholders: list[Stakeholder],
        since: date, today: date,
) -> tuple[list[NewsItem], list[NewsItem], list[NewsItem]]:
    """The window's notes, split into strongly mapped, weakly mapped, unmapped.

    An item can be strong for one topic and weak for another, in which case it
    is reported under the strong one and counted under the weak one.
    """
    live = [t for t in topics if not t.is_done]
    keys = {t.name: topic_keys(t, stakeholders) for t in live}
    mapped: list[NewsItem] = []
    weak: list[NewsItem] = []
    unmapped: list[NewsItem] = []
    for raw in raws:
        if not (since < raw.day <= today):
            continue
        haystack = raw.haystack
        links = set(link_targets(raw.text))
        item = NewsItem(rel=raw.rel, day=raw.day, description=raw.description)
        for topic in live:
            topic_key = keys[topic.name]
            hit = next((k for k in topic_key.strong if key_hit(k, links, haystack)), "")
            if hit:
                item.topics.append(topic.name)
                item.matched_on[topic.name] = hit
                continue
            hit = next((k for k in topic_key.weak if key_hit(k, links, haystack)), "")
            if hit:
                item.weak_topics.append(topic.name)
                item.weak_matched_on[topic.name] = hit
        if item.topics:
            mapped.append(item)
        elif item.weak_topics:
            weak.append(item)
        else:
            item.links = link_targets(raw.text)
            unmapped.append(item)
    return mapped, weak, unmapped


def weak_topic_counts(items: list[NewsItem]) -> dict[str, int]:
    """How many notes reached each topic only through a goal or a stakeholder."""
    counts: dict[str, int] = {}
    for item in items:
        for name in item.weak_topics:
            counts[name] = counts.get(name, 0) + 1
    return counts


def topic_news_lines(mapped: list[NewsItem], weak: list[NewsItem] = (),
                     secondary: dict[str, str] | None = None) -> list[str]:
    """Grouped by topic, with the match reason whenever it is not the title.

    A note reached a topic through its own name or a `related` page; that is
    worth a line each. Everything that only shares a goal or a stakeholder is
    one number, because a list of it is a list of the whole quarter. Topics
    that are only being watched or are parked come after the active ones.
    """
    secondary = secondary or {}
    by_topic: dict[str, list[NewsItem]] = {}
    for item in mapped:
        for name in item.topics:
            by_topic.setdefault(name, []).append(item)
    counts = weak_topic_counts(list(mapped) + list(weak))
    names = sorted(set(by_topic) | set(counts),
                   key=lambda name: (name in secondary, name))
    lines: list[str] = []
    for name in names:
        status = secondary.get(name, "")
        lines.append(f"### [[{name}]]" + (f" ({status})" if status else ""))
        lines.append("")
        for item in by_topic.get(name, []):
            line = f"- {item.rel} — {item.description}"
            key = item.matched_on.get(name, "")
            if key and key != name:
                line += f" (via {key})"
            lines.append(line)
        if counts.get(name):
            lines.append(f"- +{counts[name]} weak via goal/stakeholder")
        lines.append("")
    return lines[:-1] if lines else []


def cluster_links(unmapped: list[NewsItem]) -> list[tuple[str, int]]:
    """Link targets shared by `CLUSTER_MIN`+ unmapped notes — candidate topics.

    Crude on purpose: a name that several unrelated notes reached for in one
    week is worth a look, and the judgement about it belongs to the review.
    """
    counts: dict[str, int] = {}
    for item in unmapped:
        for target in item.links:
            counts[target] = counts.get(target, 0) + 1
    shared = [(name, n) for name, n in counts.items() if n >= CLUSTER_MIN]
    shared.sort(key=lambda pair: (-pair[1], pair[0]))
    return shared


def unmapped_lines(unmapped: list[NewsItem],
                   clusters: list[tuple[str, int]]) -> list[str]:
    lines = [f"- {i.rel} — {i.description}" for i in unmapped]
    if clusters:
        lines.append("")
        lines.append("### Candidate new topics (links shared by 2+ unmapped files)")
        lines.append("")
        lines += [f"- [[{name}]] — in {n} unmapped files" for name, n in clusters]
    return lines


# --------------------------------------------------------------------------- #
# Wiki changes


# How a wiki page reaches a topic, strongest evidence first. Naming the topic
# or one of its `related` pages is about the topic; sharing only a goal or a
# stakeholder is about the same corner of the company, which a hub page like a
# quarterly goal does with dozens of pages a week.
TOUCH_TITLE = "title"
TOUCH_RELATED = "related"
TOUCH_GOAL = "goal"
TOUCH_STAKEHOLDER = "stakeholder"
STRONG_TOUCHES = (TOUCH_TITLE, TOUCH_RELATED)


@dataclass
class WikiChange:
    page: str
    rel: str
    type: str
    action: str
    description: str = ""
    topics: list[str] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)

    @property
    def strong(self) -> list[str]:
        return [t for t in self.topics if self.reasons.get(t) in STRONG_TOUCHES]


def load_wiki_changes(root: Path, since: date, today: date, topics: list[Topic],
                      types: tuple[str, ...] = WIKI_TYPES) -> list[WikiChange]:
    """Pages the ingest log created or updated in the window, with their reach.

    `wiki/log.jsonl` is one JSON object per ingested file, carrying its own
    `date` plus the `pages_created` / `pages_updated` it produced. A page in
    both lists counts as created — that is the more interesting of the two.
    Ordered by how many topics it *strongly* touches, because a new problem
    that lands on three active topics outranks a new project that lands on
    none — and outranks a page that only happens to link the same quarterly
    goal, which on a busy week is most of them.
    """
    path = root / WIKI_LOG_PATH
    if not path.is_file():
        return []
    live = [t for t in topics if not t.is_done]

    found: dict[str, WikiChange] = {}
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            stamp = str(record.get("date", ""))
            day = parse_date(stamp.split("T")[0].split(" ")[0])
            if day is None or not (since < day <= today):
                continue
            for action, key in (("updated", "pages_updated"),
                                ("created", "pages_created")):
                for page_rel in record.get(key) or []:
                    change = _wiki_change(root, str(page_rel), action, types)
                    if change is None:
                        continue
                    if change.rel in found and action == "updated":
                        continue
                    found[change.rel] = change

    for rel, change in list(found.items()):
        page_path = root / rel
        if not page_path.is_file():
            # The log records what was written, not what survived. A page that
            # has since been merged away or renamed is not a change to report.
            del found[rel]
            continue
        text = _read(page_path)
        change.description = describe(parse_frontmatter(text), text)
        page_links = set(link_targets(text))
        body = page_body(text)
        for topic in live:
            reason = _touch_reason(topic, page_links, body)
            if reason:
                change.topics.append(topic.name)
                change.reasons[topic.name] = reason
    out = list(found.values())
    out.sort(key=lambda c: (-len(c.strong), -len(c.topics), c.page))
    return out


def _touch_reason(topic: Topic, page_links: set[str], body: str) -> str:
    """Why this page touches this topic, strongest reason first, or "".

    The title counts as an exact link target or as a whole-word phrase in the
    page's own prose. Neither a substring nor a footnote: a topic whose name
    is the leading part of a cited path used to make every page that cited it
    look like a page about the topic.
    """
    if topic.name in page_links or phrase_in(body, topic.name):
        return TOUCH_TITLE
    if page_links.intersection({strip_link(v) for v in topic.related if strip_link(v)}):
        return TOUCH_RELATED
    goal = strip_link(topic.goal)
    if goal and goal in page_links:
        return TOUCH_GOAL
    if page_links.intersection(
            {strip_link(v) for v in topic.stakeholders if strip_link(v)}):
        return TOUCH_STAKEHOLDER
    return ""


def _wiki_change(root: Path, page_rel: str, action: str,
                 types: tuple[str, ...]) -> WikiChange | None:
    parts = Path(page_rel).parts
    if len(parts) < 3 or parts[0] != "wiki" or parts[1] not in types:
        return None
    return WikiChange(page=Path(page_rel).stem, rel=Path(page_rel).as_posix(),
                      type=parts[1], action=action)


def wiki_lines(changes: list[WikiChange]) -> list[str]:
    lines = []
    for change in changes:
        line = f"- [[{change.page}]] ({change.type}, {change.action}) — {change.description}"
        if change.topics:
            line += " — touches " + ", ".join(
                f"[[{t}]] ({change.reasons.get(t, '?')})" for t in change.topics)
        lines.append(line)
    return lines


# --------------------------------------------------------------------------- #
# Deadlines, horizon and interactions


def horizon_flag_lines(topics: list[Topic], today: date) -> list[str]:
    """`horizon: next` with a deadline inside the window is really `now`."""
    end = today + timedelta(days=DEADLINE_WINDOW_DAYS)
    flagged = [t for t in topics
               if not t.is_done and t.horizon == "next" and t.deadline
               and today <= t.deadline <= end]
    flagged.sort(key=lambda t: (t.deadline, t.name))
    return [
        f"- {t.link} — horizon `next`, deadline {t.deadline.isoformat()} "
        f"(in {(t.deadline - today).days} days) — consider moving to now"
        for t in flagged
    ]


def shared_interaction_lines(topics: list[Topic]) -> list[str]:
    """Active pairs sharing a goal or two stakeholders that link to neither other.

    An unrecorded dependency is the expensive kind: two topics move on the
    same person's attention and neither page says so. One shared stakeholder
    is not that — on a roster of nine people it is every pair — so a pair is
    only flagged on a shared goal or `MIN_SHARED_STAKEHOLDERS` of them.
    """
    active = sorted([t for t in topics if t.status == "active"], key=lambda t: t.name)
    lines: list[str] = []
    for i, first in enumerate(active):
        for second in active[i + 1:]:
            first_related = {strip_link(v) for v in first.related}
            second_related = {strip_link(v) for v in second.related}
            if second.name in first_related or first.name in second_related:
                continue
            goal = strip_link(first.goal)
            shares_goal = bool(goal) and goal == strip_link(second.goal)
            shared = sorted({strip_link(v) for v in first.stakeholders if strip_link(v)}
                            .intersection({strip_link(v) for v in second.stakeholders}))
            if not shares_goal and len(shared) < MIN_SHARED_STAKEHOLDERS:
                continue
            reasons = [f"goal [[{goal}]]"] if shares_goal else []
            reasons += [f"stakeholder {s}" for s in shared]
            lines.append(f"- {first.link} + {second.link} — share "
                         + ", ".join(reasons)
                         + "; neither lists the other in `related`")
    return lines


def action_link_lines(topics: list[Topic]) -> list[str]:
    """A first next action that names another topic — a dependency in disguise."""
    names = {t.name for t in topics}
    lines: list[str] = []
    for topic in sorted([t for t in topics if not t.is_done], key=lambda t: t.name):
        open_tasks = topic.open_tasks()
        if not open_tasks:
            continue
        text = open_tasks[0].text
        for target in link_targets(text):
            if target in names and target != topic.name:
                lines.append(f"- {topic.link} — first action names [[{target}]]: {text}")
    return lines


# --------------------------------------------------------------------------- #
# The packet


@dataclass
class Packet:
    """Everything the weekly review needs, in one deterministic bundle."""

    today: date
    since: date
    label: str
    snapshot: list[tuple[str, str]] = field(default_factory=list)
    backlog: list[str] = field(default_factory=list)
    cadence: list[CadenceRow] = field(default_factory=list)
    mapped: list[NewsItem] = field(default_factory=list)
    weak: list[NewsItem] = field(default_factory=list)
    unmapped: list[NewsItem] = field(default_factory=list)
    clusters: list[tuple[str, int]] = field(default_factory=list)
    # Topic name → status, for the ones that are watched or parked rather
    # than active. They map like any other topic but render after them.
    secondary: dict[str, str] = field(default_factory=dict)
    wiki: list[WikiChange] = field(default_factory=list)
    deadlines: list[str] = field(default_factory=list)
    horizon_flags: list[str] = field(default_factory=list)
    shared: list[str] = field(default_factory=list)
    action_links: list[str] = field(default_factory=list)


def backlog_body(topics: list[Topic], today: date, command: str) -> list[str]:
    """The compiled backlog, demoted one heading level to nest under `## Backlog`.

    The compiler owns the backlog's shape; repeating it here would be a second
    source of truth. So its document is reused verbatim minus the generated-file
    banner and its `# Backlog` title, with every heading pushed down one level
    so nothing in it looks like a section of the weekly packet.
    """
    lines: list[str] = []
    for line in compile_backlog(topics, today, command).splitlines():
        if line.startswith("> [!info] Generated") or line.startswith("> Compiled by ") \
                or line.startswith("# "):
            continue
        lines.append("#" + line if line.startswith("#") else line)
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def build_packet(root: Path, topics: list[Topic], today: date, since: date,
                 command: str) -> Packet:
    """Read the vault once and assemble every section."""
    earliest = min(since, today - timedelta(days=CONTACT_LOOKBACK_DAYS))
    raws = scan_raw(root, earliest, today)
    stakeholders = parse_stakeholders(root)
    mapped, weak, unmapped = map_raw_to_topics(raws, topics, stakeholders,
                                               since, today)
    live = [t for t in topics if not t.is_done]
    return Packet(
        today=today,
        since=since,
        label=week_label(today),
        snapshot=[(t.name, t.progress or "(no progress)")
                  for t in sorted(live, key=lambda t: (t.horizon_rank, t.name))],
        backlog=backlog_body(topics, today, command),
        cadence=cadence_rows(stakeholders, raws, today),
        mapped=mapped,
        weak=weak,
        unmapped=unmapped,
        clusters=cluster_links(unmapped),
        secondary={t.name: t.status for t in live
                   if t.status in WATCHING_STATUSES},
        wiki=load_wiki_changes(root, since, today, topics),
        deadlines=deadline_lines(topics, today),
        horizon_flags=horizon_flag_lines(topics, today),
        shared=shared_interaction_lines(topics),
        action_links=action_link_lines(topics),
    )


def render_markdown(packet: Packet, command: str) -> str:
    """The packet as one Markdown document.

    `## Snapshot` comes first and in `load_snapshots` shape: the weekly file
    built from this packet is read back by `--recap` later, and that only works
    if the lines are `- [[Topic]] — <progress>`.
    """
    out = [
        *generated_banner(command, packet.today, "data for the weekly review, not the review itself"),
        "",
        f"# Weekly review packet {packet.label}",
        "",
        f"{packet.since.isoformat()} .. {packet.today.isoformat()}",
        "",
    ]
    out += _section(SECTION_SNAPSHOT,
                    [f"- [[{name}]] — {progress}" for name, progress in packet.snapshot])
    out += _section(SECTION_BACKLOG, packet.backlog)
    out += _section(SECTION_CADENCE, cadence_lines(packet.cadence))
    out += _section(f"{SECTION_TOPIC_NEWS} {packet.since.isoformat()}",
                    topic_news_lines(packet.mapped, packet.weak, packet.secondary))
    out += _section(SECTION_UNMAPPED, unmapped_lines(packet.unmapped, packet.clusters))
    out += _section(SECTION_WIKI, wiki_lines(packet.wiki))
    out += _section(SECTION_DEADLINES, packet.deadlines + packet.horizon_flags)
    interaction = list(packet.shared)
    if packet.action_links:
        interaction += packet.action_links
    out += _section(SECTION_INTERACTION, interaction)
    return "\n".join(out).rstrip("\n") + "\n"


def render_json(packet: Packet) -> str:
    """The same sections as data, for anything that would otherwise re-parse."""
    data = {
        "today": packet.today.isoformat(),
        "since": packet.since.isoformat(),
        "week": packet.label,
        "snapshot": [{"topic": name, "progress": progress}
                     for name, progress in packet.snapshot],
        "backlog": packet.backlog,
        "stakeholder_cadence": [
            {
                "person": row.person,
                "cadence": row.cadence_raw,
                "cadence_days": row.cadence_days,
                "last": row.last.isoformat() if row.last else None,
                "evidence": row.evidence or None,
                "evidence_reason": row.evidence_reason or None,
                "status": row.status,
                "overdue_days": row.overdue_days,
                "due_in_days": row.due_in_days,
                "weak_mentions": row.weak_mentions,
            }
            for row in packet.cadence
        ],
        "new_on_topics": [
            {"path": item.rel, "date": item.day.isoformat(),
             "description": item.description, "topics": item.topics,
             "matched_on": item.matched_on,
             "weak_topics": item.weak_topics,
             "weak_matched_on": item.weak_matched_on}
            for item in packet.mapped
        ],
        "weak_on_topics": [
            {"topic": name, "files": n}
            for name, n in sorted(
                weak_topic_counts(packet.mapped + packet.weak).items())
        ],
        "secondary_topics": packet.secondary,
        "unmapped": [
            {"path": item.rel, "date": item.day.isoformat(),
             "description": item.description, "links": item.links}
            for item in packet.unmapped
        ],
        "clusters": [{"link": name, "files": n} for name, n in packet.clusters],
        "wiki_changes": [
            {"page": c.page, "path": c.rel, "type": c.type, "action": c.action,
             "description": c.description, "topics": c.topics,
             "reasons": c.reasons, "strong_topics": c.strong}
            for c in packet.wiki
        ],
        "deadlines": packet.deadlines,
        "horizon_flags": packet.horizon_flags,
        "interaction_check": {
            "shared_without_related": packet.shared,
            "action_links": packet.action_links,
        },
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------- #
# Window


def newest_weekly(root: Path) -> date | None:
    """When the newest `work/weekly/YYYY-Www*.md` was written, if any.

    A name is a weekly file only when `parse_week_stem` — the same validator
    `load_snapshots` uses — recognises a real ISO week in it, so a typo like
    `2026-W99.md` cannot sort above every genuine review and hand
    `default_since` a window that starts in a week that does not exist.

    The ISO week in the name only picks *which* file is the newest; the date
    the window should start at is the day that review actually covered up to,
    which is its frontmatter `date`, and its mtime when it has none. The
    Monday of its week is neither — a review written on Thursday reported
    Thursday's material, and starting the next window on Monday reports three
    days of it twice.
    """
    folder = root / WEEKLY_DIR
    if not folder.is_dir():
        return None
    best: tuple[tuple[int, int, str], Path] | None = None
    for path in sorted(folder.glob("*.md")):
        parsed = parse_week_stem(path.stem)
        if parsed is None:
            continue
        key = (parsed[0], parsed[1], path.name)
        if best is None or key > best[0]:
            best = (key, path)
    if best is None:
        return None
    path = best[1]
    day = parse_date(_scalar(parse_frontmatter(_read(path)), "date"))
    return day if day is not None else date.fromtimestamp(path.stat().st_mtime)


def default_since(root: Path, today: date) -> date:
    """A week back, or the last review if that was more recent.

    Two reviews in one week must not report the same material twice, and a
    review after a three-week gap must not lose the middle two weeks. A review
    written today would leave an empty window, so it does not count.
    """
    fallback = today - timedelta(days=DEFAULT_WINDOW_DAYS)
    newest = newest_weekly(root)
    if newest is not None and fallback < newest < today:
        return newest
    return fallback
