"""Compile personal topic pages into one backlog, archive done work, recap a period.

`work/topics/*.md` is the source of truth: one page per topic, carrying its own
frontmatter (status, horizon, review date) and its own checkbox lists. Nothing
here is derived by an LLM — every line of `work/Backlog.md` is a projection of
those pages, so the compiler can be re-run at any time and the output thrown
away.

Four invariants hold throughout:

* **The topic pages are the only writable source.** Mode 1 and mode 3 never
  touch them; mode 2 (`archive_done`) rewrites them by *line surgery* — checked
  boxes are cut and appended to `## Log` and every other byte is left alone, so
  a hand-formatted table or an unquoted YAML value can never be re-serialised
  into something else.
* **Line surgery means the bytes it did not cut come back unchanged.** The
  file's own newline is what the result is joined with, no other separator
  counts as a line break (`split_lines`), and a page that cannot be decoded as
  UTF-8 is reported and skipped rather than rewritten with replacement
  characters in it. Reading a page to *project* it may be lenient; writing one
  may not.
* **A WikiLink target is the filename stem, never the H1.** A page titled
  `# Alpha / Beta` still links as `[[Alpha Beta]]` if that is what it is called
  on disk.
* **Today is an argument.** Every date comparison goes through the caller's
  `today`, which is what makes overdue reviews, deadline windows and relative
  recap periods testable.
"""

import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

# Where the compiler reads and writes, relative to the vault root.
TOPICS_DIR = "work/topics"
BACKLOG_PATH = "work/Backlog.md"
RECAPS_DIR = "work/recaps"
WEEKLY_DIR = "work/weekly"

# H2 sections the compiler understands. Any other section on a topic page is
# ignored, which is what lets a page carry its own tables and notes.
SECTION_ME = "Next actions (me)"
SECTION_DELEGATED = "Delegated"
SECTION_LOG = "Log"
SECTION_SNAPSHOT = "Snapshot"

# now → next → later. Anything else sorts last rather than raising: a typo in
# one page must not stop the whole backlog from compiling.
HORIZONS = ("now", "next", "later")

DEADLINE_WINDOW_DAYS = 42
PORTFOLIO_CAP = 10

NO_NEXT_ACTION = "(no next action)"
EMPTY_LINE = "- (none)"
UNASSIGNED = "(unassigned)"

# Frontmatter is matched locally rather than with `lib.frontmatter`: topic pages
# arrive with a BOM, with CRLF, and with the closing `---` as the last byte of
# the file, and all three have to parse. `lib.frontmatter` is shared with the
# wiki tools and is deliberately left alone.
_BOM = "﻿"
FRONTMATTER_RE = re.compile(
    r"\A---[ \t]*\r?\n(.*?)\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|\Z)", re.DOTALL
)

_HEADING_RE = re.compile(r"^#{1,2} +(.*?)\s*$")
_FENCE_RE = re.compile(r"^[ \t]*(`{3,}|~{3,})[ \t]*(.*?)\s*$")
_LIST_ITEM_RE = re.compile(r"^[ \t]*(?:[-*+] |\d+[.)] )")
_FM_ITEM_RE = re.compile(r"^\s*-\s*(.*)$")
_CHECKBOX_RE = re.compile(r"^\s*[-*] +\[([ xX])\] *(.*?)\s*$")
# Em dash, en dash or hyphen — all three occur in hand-written pages.
_DASH = r"[—–-]"
_DELEGATED_RE = re.compile(rf"^@([^\s]+)\s*(?:{_DASH}\s*)?(.*)$")
_LOG_RE = re.compile(rf"^\s*[-*] +(\d{{4}}-\d{{2}}-\d{{2}})\s*(?:{_DASH}\s*)?(.*)$")
_SNAPSHOT_RE = re.compile(rf"^\s*[-*] +\[\[([^\]]+)\]\]\s*(?:{_DASH}\s*)?(.*)$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_PERIOD_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_PERIOD_WEEK_RE = re.compile(r"^(\d{4})-W(\d{1,2})$")
_PERIOD_WEEK_RANGE_RE = re.compile(r"^(\d{4})-W(\d{1,2})\.\.W?(\d{1,2})$")
# A `work/weekly/` filename: the ISO week is a prefix, so `2026-w11 review.md`
# is that week's review. Case-insensitive, and never a third digit —
# `2026-w111` is not week 11.
_WEEK_STEM_RE = re.compile(r"^(\d{4})-w(\d{1,2})(?!\d)", re.IGNORECASE)


class PeriodError(ValueError):
    """An unparsable `--recap` period."""


# --------------------------------------------------------------------------- #
# Parsing


@dataclass
class Task:
    """One checkbox line, with the topic it came from."""

    text: str
    done: bool
    person: str | None = None  # None for a "me" action
    topic: str = ""
    horizon: str = ""


@dataclass
class LogEntry:
    day: date
    text: str


@dataclass
class Topic:
    name: str                     # filename stem — the WikiLink target
    path: Path
    status: str = ""
    horizon: str = ""
    lever: str = ""
    goal: str = ""
    progress: str = ""
    stakeholders: list[str] = field(default_factory=list)
    related: list[str] = field(default_factory=list)
    next_review: date | None = None
    next_review_raw: str = ""
    deadline: date | None = None
    deadline_raw: str = ""
    my_tasks: list[Task] = field(default_factory=list)
    delegated: list[Task] = field(default_factory=list)
    log: list[LogEntry] = field(default_factory=list)
    # Structural complaints about the page itself, found while parsing it.
    smells: list[str] = field(default_factory=list)

    @property
    def link(self) -> str:
        return f"[[{self.name}]]"

    @property
    def is_done(self) -> bool:
        return self.status == "done"

    @property
    def horizon_rank(self) -> int:
        return HORIZONS.index(self.horizon) if self.horizon in HORIZONS else len(HORIZONS)

    def open_tasks(self) -> list[Task]:
        return [t for t in self.my_tasks if not t.done]

    def next_action(self) -> str:
        open_tasks = self.open_tasks()
        return open_tasks[0].text if open_tasks else NO_NEXT_ACTION


def parse_frontmatter(content: str) -> dict[str, str | list[str]]:
    """Flat frontmatter with list support.

    `lib.frontmatter.split_frontmatter` is scalar-only; topic pages carry
    `stakeholders` and `related` as lists, in either the inline (`[a, b]`) or
    the block (`- a`) YAML shape, so both are handled here. Values are
    unquoted; nested mappings are not supported, and their children are
    *ignored* rather than promoted.

    Four tolerances, each one a page that used to come back wrong:

    * a leading BOM and a closing `---` that is the last byte of the file
      (and CRLF line endings) still parse;
    * a block sequence written flush against the margin (`key:` then `- a`
      at zero indent, which is what most editors emit) is a list, so
      `- A: B` under such a key is the item `A: B` and not a key `- A`;
    * an indented `key: value` under a key with no scalar of its own is a
      nested mapping, and stays inside it: `meta:` / `  status: done` used to
      come back as a top-level `status: done`, which made a page with a
      `meta:` block look like a finished topic;
    * an unquoted ` #…` suffix is a YAML comment and is dropped. A `#` inside
      quotes survives, so a wikilink that carries one (`"[[Roadmap #1]]"`)
      must be quoted — unquoted, its `#` starts a comment.
    """
    match = FRONTMATTER_RE.match(content.removeprefix(_BOM))
    if not match:
        return {}
    data: dict[str, str | list[str]] = {}
    pending: str | None = None            # key whose block list we are inside
    pending_indent = 0                    # how far that key is indented
    nested = False                        # inside a mapping under that key
    for raw_line in match.group(1).split("\n"):
        line = raw_line.rstrip("\r")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indent = _indent_width(line)
        item = _FM_ITEM_RE.match(line)
        if item is not None:
            # Tried before the `key: value` split so that an item which
            # happens to contain a colon stays an item.
            if pending is not None and not nested:
                value = _unquote(_strip_comment(item.group(1)))
                if value:
                    data[pending].append(value)   # type: ignore[union-attr]
            continue
        if ":" not in line:
            continue
        if pending is not None and indent > pending_indent:
            # A nested mapping. Its keys belong to the parent, so promoting
            # them to the top level invented keys the page never declared.
            nested = True
            continue
        key, raw = line.split(":", 1)
        key, raw = key.strip(), _strip_comment(raw.strip())
        pending, nested = None, False
        if raw.startswith("[") and raw.endswith("]"):
            data[key] = _inline_list(raw)
        elif raw == "":
            data[key] = []
            pending, pending_indent = key, indent
        else:
            data[key] = _unquote(raw)
    # A key that opened a block list but got no items stays the empty list it
    # was initialised to, which is the same thing `key: []` means.
    return data


def _strip_comment(value: str) -> str:
    """Drop an unquoted ` #…` comment from a frontmatter value.

    The hash has to follow whitespace, so a value that *is* a tag (`#later`)
    keeps it, and quoted text keeps it wherever it sits. An unbalanced quote
    (an apostrophe in prose) makes the rest of the line count as quoted, which
    errs towards keeping the author's bytes.
    """
    quote = ""
    for i, char in enumerate(value):
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
        elif char == "#" and i > 0 and value[i - 1] in " \t":
            return value[:i].rstrip()
    return value


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1].strip()
    return value


def _inline_list(raw: str) -> list[str]:
    """`["[[A]]", "B"]` → `['[[A]]', 'B']`. Commas never occur inside a link."""
    inner = raw[1:-1].strip()
    if not inner:
        return []
    return [v for v in (_unquote(part) for part in inner.split(",")) if v]


def split_lines(content: str) -> tuple[list[str], str, bool]:
    """`(lines, newline, ended_with_a_newline)`, splitting on that newline only.

    `str.splitlines()` also breaks on U+2028, U+0085 and a form feed, so a
    round-trip through `"\\n".join()` silently rewrites them. Splitting on the
    file's dominant newline keeps every other separator inside its line, where
    line surgery can never touch it.
    """
    crlf = content.count("\r\n")
    newline = "\r\n" if crlf > content.count("\n") - crlf else "\n"
    lines = content.split(newline)
    trailing = content.endswith(newline)
    if trailing:
        lines.pop()
    return lines, newline, trailing


def _indent_width(line: str) -> int:
    """Leading indentation in columns, a tab taking the next multiple of four."""
    width = 0
    for char in line:
        if char == " ":
            width += 1
        elif char == "\t":
            width += 4 - width % 4
        else:
            break
    return width


@dataclass
class _Layout:
    """Which lines of a page are code, and what is malformed about it."""

    code: list[bool]
    open_fence_at: int | None = None
    unclosed_fence: bool = False


def _scan(lines: list[str], ignore_fences: set[int]) -> _Layout:
    """One pass: mark fenced and indented code, remembering a dangling fence.

    A checkbox, a heading and a log line only count when they are prose. The
    hard case is indentation: four spaces under a list item are that item's
    child, while four spaces after a paragraph are a code block, so the scan
    has to know whether a list is open.
    """
    layout = _Layout(code=[False] * len(lines))
    fence: str | None = None
    in_indent_code = False
    after_blank = True
    in_list = False
    for i, line in enumerate(lines):
        if fence is not None:
            layout.code[i] = True
            close = _FENCE_RE.match(line)
            if (close and close.group(1)[0] == fence[0]
                    and len(close.group(1)) >= len(fence) and not close.group(2)):
                fence = None
            continue
        if not line.strip():
            after_blank = True
            continue
        indent = _indent_width(line)
        if indent >= 4 and not in_list and (in_indent_code or after_blank):
            in_indent_code = True
            layout.code[i] = True
            after_blank = False
            continue
        in_indent_code = False
        opener = _FENCE_RE.match(line)
        if opener is not None and i not in ignore_fences:
            fence, layout.open_fence_at = opener.group(1), i
            layout.code[i] = True
            after_blank = False
            continue
        if _HEADING_RE.match(line):
            in_list = False
        elif _LIST_ITEM_RE.match(line):
            in_list = True
        elif indent == 0 and after_blank:
            in_list = False       # a fresh block at the margin ends the list
        after_blank = False
    if fence is None:
        layout.open_fence_at = None
    else:
        layout.unclosed_fence = True
    return layout


def page_layout(lines: list[str]) -> _Layout:
    """`_scan`, with an unterminated fence ignored rather than believed.

    A page that opens a fence and never closes it would otherwise swallow
    every heading below it — the sections disappear and the page silently
    stops contributing. The dangling opener is dropped and the page re-scanned
    (a page can have more than one), and `unclosed_fence` is left set so the
    author gets told about it.
    """
    ignore: set[int] = set()
    layout = _scan(lines, ignore)
    while layout.open_fence_at is not None:
        ignore.add(layout.open_fence_at)
        layout = _scan(lines, ignore)
        layout.unclosed_fence = True
    return layout


@dataclass
class _Page:
    """A page's lines with everything the line surgery needs to know."""

    lines: list[str]
    code: list[bool]
    spans: dict[str, list[tuple[int, int]]]
    unclosed_fence: bool


def read_page(lines: list[str]) -> _Page:
    """Scan a page once: code lines, every heading span, and the fence smell.

    One scan feeds all three readers — the task lists, the log, and the
    archive surgery — so none of them can disagree about where a section ends
    or about which `- [x]` is real.
    """
    layout = page_layout(lines)
    heads: list[tuple[str, int]] = []
    for i, line in enumerate(lines):
        if layout.code[i]:
            continue
        match = _HEADING_RE.match(line)
        if match:
            heads.append((match.group(1), i))
    spans: dict[str, list[tuple[int, int]]] = {}
    for n, (title, index) in enumerate(heads):
        end = heads[n + 1][1] if n + 1 < len(heads) else len(lines)
        spans.setdefault(title, []).append((index + 1, end))
    return _Page(lines=lines, code=layout.code, spans=spans,
                 unclosed_fence=layout.unclosed_fence)


def all_section_spans(lines: list[str]) -> dict[str, list[tuple[int, int]]]:
    """H1/H2 heading text → every (first body line, one past the last) span.

    A page that repeats `## Next actions (me)` has two spans under that title
    and both of them hold real work, so every consumer here iterates the list.
    """
    return read_page(lines).spans


def section_spans(lines: list[str]) -> dict[str, tuple[int, int]]:
    """H1/H2 heading text → (first body line, one past the last body line).

    `###` and deeper stay *inside* their section; fenced and indented code is
    skipped so a `## …` inside a code block never splits a section. Only the
    first span per title — `all_section_spans` has the rest.
    """
    return {title: spans[0] for title, spans in all_section_spans(lines).items()}


def _tasks(page: _Page, spans: list[tuple[int, int]]) -> list[tuple[bool, str]]:
    out = []
    for span in spans:
        for i in range(*span):
            match = _CHECKBOX_RE.match(page.lines[i])
            if match and not page.code[i]:
                out.append((match.group(1).lower() == "x", match.group(2)))
    return out


def split_delegated(text: str) -> tuple[str | None, str]:
    """`@Pat — do the thing` → `("Pat", "do the thing")`.

    Any of the three dashes separates the name from the task, and a line
    without a leading `@` keeps its whole text and no owner.
    """
    match = _DELEGATED_RE.match(text.strip())
    if not match:
        return None, text.strip()
    person, rest = match.group(1), match.group(2).strip()
    return person, rest or text.strip()


def parse_date(value: str) -> date | None:
    value = (value or "").strip()
    if not _ISO_DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_topic(path: Path) -> Topic:
    content = path.read_text(encoding="utf-8", errors="replace")
    front = parse_frontmatter(content)
    topic = Topic(name=path.stem, path=path)
    topic.status = str(front.get("status", "") or "")
    topic.horizon = str(front.get("horizon", "") or "")
    topic.lever = str(front.get("lever", "") or "")
    topic.goal = str(front.get("goal", "") or "")
    topic.progress = str(front.get("progress", "") or "")
    topic.stakeholders = _as_list(front.get("stakeholders"))
    topic.related = _as_list(front.get("related"))
    topic.next_review_raw = str(front.get("next_review", "") or "")
    topic.next_review = parse_date(topic.next_review_raw)
    topic.deadline_raw = str(front.get("deadline", "") or "")
    topic.deadline = parse_date(topic.deadline_raw)

    lines, _, _ = split_lines(content)
    page = read_page(lines)
    for done, text in _tasks(page, page.spans.get(SECTION_ME, [])):
        topic.my_tasks.append(
            Task(text=text, done=done, topic=topic.name, horizon=topic.horizon)
        )
    for done, text in _tasks(page, page.spans.get(SECTION_DELEGATED, [])):
        person, rest = split_delegated(text)
        topic.delegated.append(
            Task(text=rest, done=done, person=person or UNASSIGNED,
                 topic=topic.name, horizon=topic.horizon)
        )
    for span in page.spans.get(SECTION_LOG, []):
        for i in range(*span):
            match = _LOG_RE.match(page.lines[i])
            day = parse_date(match.group(1)) if match else None
            if match and day and not page.code[i]:
                topic.log.append(LogEntry(day=day, text=match.group(2).strip()))
    topic.smells = page_smells(page)
    return topic


def page_smells(page: _Page) -> list[str]:
    """What is wrong with the page as a document, rather than as a plan."""
    smells: list[str] = []
    if page.unclosed_fence:
        smells.append("unclosed code fence")
    for title in (SECTION_ME, SECTION_DELEGATED, SECTION_LOG):
        if len(page.spans.get(title, [])) > 1:
            smells.append(f"duplicate heading `## {title}`")
    return smells


def unlinkable(name: str) -> str:
    """Why `[[name]]` will not resolve in Obsidian, or `""` if it will.

    The compiler links a topic by its filename stem, and three characters make
    that impossible to write as a plain WikiLink: `#` starts a heading
    reference, `|` starts an alias, and an edge space is eaten by the reader.
    Renaming the file is the only fix, so the page is named and left alone.
    """
    bad = [f"`{char}`" for char in "#|" if char in name]
    if name != name.strip():
        bad.append("a leading or trailing space")
    return " and ".join(bad)


def _as_list(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    return [value] if value else []


def load_topics(root: Path) -> list[Topic]:
    """Every `type: topic` page under `work/topics/`, sorted by name.

    Pages without `type: topic` are skipped rather than guessed at, so an
    index or a stray draft in the folder costs nothing.
    """
    folder = root / TOPICS_DIR
    if not folder.is_dir():
        return []
    topics = []
    for path in sorted(folder.glob("*.md")):
        content = path.read_text(encoding="utf-8", errors="replace")
        if parse_frontmatter(content).get("type") != "topic":
            continue
        topics.append(parse_topic(path))
    return topics


# --------------------------------------------------------------------------- #
# Mode 1 — compile the backlog


def _sorted_for_portfolio(topics: list[Topic]) -> list[Topic]:
    return sorted(topics, key=lambda t: (t.horizon_rank, t.name))


def _section(title: str, body: list[str]) -> list[str]:
    return [f"## {title}", ""] + (body or [EMPTY_LINE]) + [""]


def portfolio_lines(topics: list[Topic]) -> list[str]:
    active = _sorted_for_portfolio([t for t in topics if t.status == "active"])
    lines = [
        f"- **{t.link}** — {t.progress or '(no progress)'} — *next:* {t.next_action()}"
        for t in active
    ]
    if len(active) > PORTFOLIO_CAP:
        lines.append("")
        lines.append(f"> ⚠ Portfolio has {len(active)} topics; merge or park.")
    return lines


def next_action_lines(topics: list[Topic]) -> list[str]:
    live = [t for t in topics if not t.is_done]
    lines: list[str] = []
    for horizon in HORIZONS + ("",):
        group = [t for t in _sorted_for_portfolio(live)
                 if (t.horizon if t.horizon in HORIZONS else "") == horizon]
        items = [f"- [ ] {task.text} — {t.link}"
                 for t in group for task in t.open_tasks()]
        if not items and horizon == "":
            continue
        lines.append(f"### {horizon or 'unset horizon'}")
        lines.append("")
        lines.extend(items or [EMPTY_LINE])
        lines.append("")
    return lines[:-1] if lines else []


def delegated_lines(topics: list[Topic]) -> list[str]:
    by_person: dict[str, list[str]] = {}
    for topic in _sorted_for_portfolio([t for t in topics if not t.is_done]):
        for task in topic.delegated:
            if task.done:
                continue
            person = task.person or UNASSIGNED
            label = person if person == UNASSIGNED else f"@{person}"
            by_person.setdefault(label, []).append(f"- [ ] {task.text} — {topic.link}")
    lines: list[str] = []
    for label in sorted(by_person):
        lines.append(f"### {label}")
        lines.append("")
        lines.extend(by_person[label])
        lines.append("")
    return lines[:-1] if lines else []


def overdue_lines(topics: list[Topic], today: date) -> list[str]:
    overdue = [t for t in topics
               if not t.is_done and t.next_review and t.next_review < today]
    overdue.sort(key=lambda t: (t.next_review, t.name))
    return [
        f"- {t.link} — due {t.next_review.isoformat()} "
        f"({(today - t.next_review).days} days)"
        for t in overdue
    ]


def deadline_lines(topics: list[Topic], today: date) -> list[str]:
    horizon_end = today + timedelta(days=DEADLINE_WINDOW_DAYS)
    due = [t for t in topics
           if not t.is_done and t.deadline and today <= t.deadline <= horizon_end]
    due.sort(key=lambda t: (t.deadline, t.name))
    return [
        f"- {t.link} — deadline {t.deadline.isoformat()} "
        f"(in {(t.deadline - today).days} days)"
        for t in due
    ]


def smell_lines(topics: list[Topic]) -> list[str]:
    lines: list[str] = []
    for topic in _sorted_for_portfolio(topics):
        if topic.status == "active" and not topic.open_tasks():
            lines.append(f"- {topic.link} — active with no unchecked action of mine")
        if not topic.progress:
            lines.append(f"- {topic.link} — no `progress`")
        if topic.next_review is None:
            raw = topic.next_review_raw
            lines.append(f"- {topic.link} — `next_review` "
                         + (f"malformed: `{raw}`" if raw else "missing"))
        bad = unlinkable(topic.name)
        if bad:
            lines.append(f"- `{topic.name}` — unlinkable filename: contains {bad}")
        for smell in topic.smells:
            lines.append(f"- {topic.link} — {smell}")
    return lines


def watching_lines(topics: list[Topic]) -> list[str]:
    selected = [t for t in topics if t.status in ("watching", "parked")]
    selected.sort(key=lambda t: (t.status, t.name))
    return [f"- {t.link} ({t.status}) — {t.progress or '(no progress)'}"
            for t in selected]


def generated_banner(command: str, today: date | None = None, note: str = "") -> list[str]:
    """The lines that open every compiled document: an Obsidian callout, open
    by default, so the reader sees it — an HTML comment is invisible in
    reading view and the file gets edited by hand."""
    when = f" on {today.isoformat()}" if today else ""
    tail = f"; {note}" if note else ""
    return [
        "> [!info] Generated file",
        f"> Compiled by `{command}`{when}{tail}.",
    ]


def compile_backlog(topics: list[Topic], today: date, command: str) -> str:
    """The whole of `work/Backlog.md` as text."""
    out = [
        *generated_banner(command, today, "edit work/topics/*.md, not this file"),
        "",
        "# Backlog",
        "",
    ]
    out += _section("Portfolio", portfolio_lines(topics))
    out += _section(SECTION_ME, next_action_lines(topics))
    out += _section("Delegated", delegated_lines(topics))
    out += _section("Overdue review", overdue_lines(topics, today))
    out += _section(f"Deadlines within {DEADLINE_WINDOW_DAYS // 7} weeks",
                    deadline_lines(topics, today))
    out += _section("Smells", smell_lines(topics))
    out += _section("Watching and parked", watching_lines(topics))
    return "\n".join(out).rstrip("\n") + "\n"


# --------------------------------------------------------------------------- #
# Mode 2 — archive done work into the log


def _done_block(page: _Page, start: int, end: int) -> tuple[list[int], int]:
    """A checked box plus the lines belonging to it → `(indices, next line)`.

    Everything indented under the checkbox is part of the task — child list
    items, lazy continuations, and the blank lines between them in a loose
    list — so the whole block travels to the log together. The block stops at
    the first line back at the margin, at a heading, and at the section end.
    """
    block = [start]
    blanks: list[int] = []
    i = start + 1
    while i < end:
        line = page.lines[i]
        if not line.strip():
            blanks.append(i)
            i += 1
            continue
        if (_indent_width(line) > 0 and not page.code[i]
                and not _HEADING_RE.match(line)):
            block += blanks
            blanks = []
            block.append(i)
            i += 1
            continue
        break
    return sorted(block), i


def _nested(lines: list[str]) -> list[str]:
    """Indent the children of a moved checkbox so they still nest under it.

    Relative indentation is preserved — the block renders under its log entry
    exactly as it did under its checkbox — with the one exception of a child
    indented by a single space, which would not nest under a `- ` marker.
    """
    widths = [_indent_width(line) for line in lines if line.strip()]
    pad = " " * max(0, 2 - min(widths)) if widths else ""
    return [pad + line if line.strip() else line for line in lines]


def archive_done(content: str, day: str) -> tuple[str, list[str]]:
    """Move every `- [x]` block into `## Log` as `- <day> — done: <text>`.

    Line surgery, not a re-serialisation: only the checked blocks are removed,
    only the log entries are inserted, and the file's own newline is what the
    result is joined with. Returns the new text (identical to the old when
    nothing moved) and the moved task texts, in file order.

    Only a checkbox at the margin is archived. A checked box nested under
    another list item is left where it is: it is a subtask, and cutting it out
    of its parent would strand the parent's remaining children.
    """
    lines, newline, trailing = split_lines(content)
    page = read_page(lines)
    blocks: list[tuple[str, list[int]]] = []
    for title in (SECTION_ME, SECTION_DELEGATED):
        for span in page.spans.get(title, []):
            i = span[0]
            while i < span[1]:
                match = _CHECKBOX_RE.match(lines[i])
                if (match and match.group(1).lower() == "x" and not page.code[i]
                        and _indent_width(lines[i]) == 0):
                    indices, i = _done_block(page, i, span[1])
                    blocks.append((match.group(2), indices))
                else:
                    i += 1
    if not blocks:
        return content, []

    moved = [text for text, _ in blocks]
    drop = {i for _, indices in blocks for i in indices}
    # The raw checkbox text is carried over verbatim, which is what keeps the
    # `@Name — ` prefix on a delegated item without special-casing it.
    entries: list[str] = []
    for text, indices in blocks:
        entries.append(f"- {day} — done: {text}")
        entries += _nested([lines[i] for i in indices[1:]])
    log_spans = page.spans.get(SECTION_LOG)
    if log_spans:
        log_span = log_spans[0]
        insert_at = log_span[1]
        while insert_at > log_span[0] and not lines[insert_at - 1].strip():
            insert_at -= 1
        out: list[str] = []
        for i, line in enumerate(lines):
            if i == insert_at:
                out.extend(entries)
            if i not in drop:
                out.append(line)
        if insert_at >= len(lines):
            out.extend(entries)
    else:
        out = [line for i, line in enumerate(lines) if i not in drop]
        while out and not out[-1].strip():
            out.pop()
        out += ["", f"## {SECTION_LOG}", ""] + entries

    return newline.join(out) + (newline if trailing else ""), moved


# --------------------------------------------------------------------------- #
# Mode 3 — recap a period


def parse_period(period: str, today: date) -> tuple[str, date, date]:
    """`(label, start, end)` inclusive, from any of the five period forms.

    `last-month` and `last-week` are resolved against `today` and relabelled to
    their absolute form, so the recap filename never depends on when it ran.
    """
    period = period.strip()
    if period == "last-month":
        first_of_this = today.replace(day=1)
        last_month_end = first_of_this - timedelta(days=1)
        return parse_period(f"{last_month_end.year}-{last_month_end.month:02d}", today)
    if period == "last-week":
        monday = today - timedelta(days=today.isoweekday() - 1)
        prev = monday - timedelta(days=7)
        year, week, _ = prev.isocalendar()
        return parse_period(f"{year}-W{week:02d}", today)

    match = _PERIOD_MONTH_RE.match(period)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if not 1 <= month <= 12:
            raise PeriodError(f"no month {month:02d}: {period}")
        start = date(year, month, 1)
        end = (date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1))
        return f"{year}-{month:02d}", start, end

    match = _PERIOD_WEEK_RANGE_RE.match(period)
    if match:
        year, first, last = (int(g) for g in match.groups())
        if last < first:
            raise PeriodError(f"week range runs backwards: {period}")
        start = _week_start(year, first, period)
        end = _week_start(year, last, period) + timedelta(days=6)
        return f"{year}-W{first:02d}..W{last:02d}", start, end

    match = _PERIOD_WEEK_RE.match(period)
    if match:
        year, week = int(match.group(1)), int(match.group(2))
        start = _week_start(year, week, period)
        return f"{year}-W{week:02d}", start, start + timedelta(days=6)

    raise PeriodError(
        f"unrecognised period {period!r} — use YYYY-MM, YYYY-Www, "
        "YYYY-Www..Www, last-month or last-week"
    )


def _week_start(year: int, week: int, period: str) -> date:
    try:
        return date.fromisocalendar(year, week, 1)
    except ValueError as exc:
        raise PeriodError(f"no ISO week {week} in {year}: {period}") from exc


def parse_week_stem(stem: str) -> tuple[int, int] | None:
    """`2026-W11`, or `2026-w11 review` → `(2026, 11)` — else None.

    The one validator for a `work/weekly/` filename, shared with
    `lib.work_weekly.newest_weekly`. The two used to disagree: `2026-W99.md`
    was no snapshot at all to `load_snapshots` and the newest review to
    `newest_weekly`, so a typo in a filename silently became the start of the
    next review's window. A week that no calendar has is not a review.
    """
    match = _WEEK_STEM_RE.match(stem.strip())
    if not match:
        return None
    year, week = int(match.group(1)), int(match.group(2))
    try:
        date.fromisocalendar(year, week, 1)
    except ValueError:
        return None
    return year, week


def load_snapshots(root: Path) -> dict[date, dict[str, str]]:
    """Weekly progress snapshots, keyed by the Monday of their ISO week.

    Format, for whatever writes them (a weekly review skill, by hand):
    `work/weekly/YYYY-Www.md` with a `## Snapshot` section of
    `- [[Topic]] — <progress>` lines. Anything else in the file is ignored, and
    a vault with no `work/weekly/` simply has no start-of-period column.
    """
    folder = root / WEEKLY_DIR
    if not folder.is_dir():
        return {}
    snapshots: dict[date, dict[str, str]] = {}
    for path in sorted(folder.glob("*.md")):
        parsed = parse_week_stem(path.stem)
        if parsed is None:
            continue
        monday = date.fromisocalendar(*parsed, 1)
        lines, _, _ = split_lines(path.read_text(encoding="utf-8", errors="replace"))
        spans = all_section_spans(lines).get(SECTION_SNAPSHOT)
        if not spans:
            continue
        entries: dict[str, str] = {}
        for span in spans:
            for line in lines[span[0]:span[1]]:
                entry = _SNAPSHOT_RE.match(line)
                if entry:
                    entries[entry.group(1).strip()] = entry.group(2).strip()
        snapshots[monday] = entries
    return snapshots


def snapshot_at(snapshots: dict[date, dict[str, str]], start: date) -> dict[str, str]:
    """The newest snapshot taken at or before the start of the period."""
    candidates = [day for day in snapshots if day <= start]
    return snapshots[max(candidates)] if candidates else {}


def _closed_in_period(topic: Topic, start: date, end: date) -> bool:
    """`status: done` and a last log entry inside the period.

    The wording of the entry is deliberately not consulted: a page that closed
    with `- 2026-03-05 — handed over to the team` is as closed as one that
    wrote `done:`, and the newest entry is what dates the closure. A topic
    finished before the period is not re-reported in it.
    """
    if not topic.is_done or not topic.log:
        return False
    return start <= max(entry.day for entry in topic.log) <= end


def compile_recap(topics: list[Topic], label: str, start: date, end: date,
                  command: str, snapshot: dict[str, str] | None = None) -> str:
    """One recap page: what each topic logged in the period, closed ones last."""
    snapshot = snapshot or {}
    in_period: dict[str, list[LogEntry]] = {}
    for topic in topics:
        entries = sorted((e for e in topic.log if start <= e.day <= end),
                         key=lambda e: e.day)
        if entries or _closed_in_period(topic, start, end):
            in_period[topic.name] = entries

    selected = [t for t in _sorted_for_portfolio(topics) if t.name in in_period]
    # `is_done` is a fact about now; the split is about this period. A finished
    # topic whose last word came after the period still reports its progress
    # here rather than claiming to have been closed here.
    shut = {t.name for t in selected if _closed_in_period(t, start, end)}
    closed = [t for t in selected if t.name in shut]
    live = [t for t in selected if t.name not in shut]

    out = [
        *generated_banner(command),
        "",
        f"# Recap {label}",
        "",
        f"{start.isoformat()} .. {end.isoformat()}",
        "",
    ]

    def block(topic: Topic) -> list[str]:
        lines = [f"### {topic.link}", ""]
        if topic.name in snapshot:
            lines.append(f"- progress at start of period: {snapshot[topic.name]}")
        lines.append(f"- progress (current): {topic.progress or '(no progress)'}")
        lines.append("- log:")
        entries = in_period[topic.name]
        lines += [f"    - {e.day.isoformat()} — {e.text}" for e in entries] or \
                 ["    - (no log entries in period)"]
        lines.append("")
        return lines

    out += ["## Progress in period", ""]
    if live:
        for topic in live:
            out += block(topic)
    else:
        out += [EMPTY_LINE, ""]
    out += ["## Closed in period", ""]
    if closed:
        for topic in closed:
            out += block(topic)
    else:
        out += [EMPTY_LINE, ""]
    return "\n".join(out).rstrip("\n") + "\n"
