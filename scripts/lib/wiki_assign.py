"""Phase 5 — assign tags from the approved vocabulary to notes that lack them.

A *closed* vocabulary pass: unlike the taxonomy phases, the model may not
invent anything. It picks from `config/tags.md` and nothing else; a suggestion
outside the list is reported to a rejects file, never written.

Only notes short of tags are targets. The excerpt each note contributes was
built by phase 2, so nothing here opens a note — and certainly not a PDF.
"""

import re
from collections import Counter
from typing import Iterable, Sequence

from .wiki_tags import valid_tag


# Notes per call. The vocabulary and the prompt rules are re-sent every call,
# so a bigger bundle amortises them — but the reply must come back as one line
# per note, and long replies are where truncation starts.
BUNDLE_SIZE = 50

MIN_TAGS = 3        # a note with fewer than this is a target
TAGS_PER_NOTE = (4, 8)

# Year tags are computed from each note's own date by
# scripts/system/wiki-assign-dates.py. Letting the model guess one would put a
# wrong year on a note, so the whole `year/` namespace is withheld from the
# vocabulary — enforced in code as well as in the prompt, because a rule stated
# only in a prompt is a rule that eventually gets broken.
#
# Deliberately the whole namespace rather than YEAR_TAG_RE: that matches only
# `year/` plus exactly four digits, so ranges like `year/2015-2016` slipped
# past it and stayed assignable.
NEVER_ASSIGN_RE = re.compile(r"^year/")

_VOCAB_LINE_RE = re.compile(r"^\s*[-*]\s*`([^`]+)`")
_HEADING_RE = re.compile(r"^##\s+(.*)$")
_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9-]*$")
_ASSIGN_LINE_RE = re.compile(r"^\s*\[?(\d+)\]?[.:\t ]\s*(.*)$")


def load_vocabulary(path, assignable: bool = True) -> list[str]:
    """The approved tags from a `config/tags.md`-shaped file.

    The file is a normal, readable Obsidian note: prose sections, then one
    `## <namespace>` section per namespace holding `` - `namespace/term` ``
    items. Harvesting is scoped to those namespace sections, and a tag must sit
    under its own namespace's heading.

    That scoping is the point. Simply matching every backticked list item also
    swallowed the *prose*: the Rules section's "- `year/YYYY` is the one exempt
    pattern." and "- `namespace/term` or `namespace/term/term`..." were both
    harvested and offered to the model as assignable tags, and the second is a
    perfectly valid tag shape, so no amount of validating the tag alone can
    tell it from a real entry.
    """
    if not path.is_file():
        return []
    tags: list[str] = []
    seen: set[str] = set()
    namespace = None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            # A prose heading ("How to use it", "Rules") is not a namespace, so
            # everything under it is skipped until the next real section.
            candidate = heading.group(1).strip()
            namespace = candidate if _NAMESPACE_RE.match(candidate) else None
            continue
        if namespace is None:
            continue
        match = _VOCAB_LINE_RE.match(line)
        if not match:
            continue
        tag = match.group(1).strip()
        if tag.split("/")[0] != namespace:
            continue
        if not valid_tag(tag) or tag in seen:
            continue
        # Year tags are valid vocabulary and valid remap targets; they are
        # only withheld from *assignment*, where a guess would be wrong.
        if assignable and NEVER_ASSIGN_RE.match(tag):
            continue
        seen.add(tag)
        tags.append(tag)
    return sorted(tags)


def is_target(record: dict, min_tags: int = MIN_TAGS) -> bool:
    """True if this note carries too few tags to be left alone."""
    return len(record.get("tags") or []) < min_tags


def assign_prompt(records: Sequence[dict], vocabulary: Sequence[str]) -> str:
    """One bundle: the closed vocabulary plus a numbered block per note."""
    low, high = TAGS_PER_NOTE
    blocks = []
    for i, record in enumerate(records, 1):
        lines = [f"[{i}] title: {record['title']}"]
        if record.get("tags"):
            lines.append(f"    current tags: {' '.join(record['tags'])}")
        text = record.get("excerpt") or ""
        lines.append(f"    text: {text}" if text
                     else "    text: (no usable text — tag from the title alone)")
        blocks.append("\n".join(lines))
    return "\n".join([
        "You are tagging notes in a work knowledge base about maps, navigation,",
        "automotive software and the engineering organisation that builds them.",
        "",
        "Use ONLY tags from the APPROVED LIST below, copied exactly. This is a",
        "closed vocabulary: a tag that is not on the list will be discarded, so",
        "inventing one loses the information instead of recording it.",
        "",
        " ".join(vocabulary),
        "",
        f"Give each note {low} to {high} tags. Rules:",
        "- Tag what the note is ABOUT, not every word it mentions in passing.",
        "- Prefer the specific tag over its broader neighbour when the note",
        "  really is about the specific thing.",
        "- A note may take tags from several namespaces; that is normal.",
        "- When a note is about a whole area rather than one thing in it, the",
        "  broad tag is `<namespace>/general` — `security/general`, not",
        "  `security/security`. Never repeat a namespace as its own term.",
        "- Never assign a `year/...` tag. Years are computed from the note's own",
        "  date elsewhere, and a guess would be wrong.",
        "- If the text is too thin to judge, tag from the title and give fewer",
        "  tags rather than padding with guesses.",
        "",
        "Notes:",
        "",
        "\n\n".join(blocks),
        "",
        f"Reply with exactly {len(records)} lines, one per note, nothing else:",
        "<number><TAB><space-separated tags>",
        "No preamble, no commentary, no blank lines, no markdown.",
    ])


def _by_term(vocabulary: Iterable[str]) -> dict[str, list[str]]:
    index: dict[str, list[str]] = {}
    for tag in vocabulary:
        if "/" in tag:
            index.setdefault(tag.split("/", 1)[1], []).append(tag)
    return index


def parse_assignments(
    reply: str | None,
    records: Sequence[dict],
    vocabulary: Iterable[str],
    rescue_namespace: bool = True,
) -> tuple[dict[str, list[str]], Counter]:
    """Parse the reply into {note path: [tags]} plus a Counter of rejected tags.

    Off-list suggestions are counted and returned rather than written: they are
    a signal about gaps in the vocabulary, and silently keeping them would
    defeat the point of a closed list.

    `rescue_namespace` recovers the most common near-miss: the model names the
    right *term* under the wrong namespace — `navigation/horizon` where the
    vocabulary has `automotive/horizon`, `org/pu-ivi` where it has
    `system/pu-ivi`. Measured over a full run, 84% of off-list suggestions were
    this, not invention. A rescue happens only when exactly one approved tag
    shares the term; where several do (`process/strategy` could be
    `ai/strategy` or `business/strategy`) the choice is a real judgement and
    the suggestion stays rejected.
    """
    approved = set(vocabulary)
    by_term = _by_term(approved) if rescue_namespace else {}
    assignments: dict[str, list[str]] = {}
    rejected: Counter = Counter()
    for line in (reply or "").splitlines():
        if not line.strip():
            continue
        match = _ASSIGN_LINE_RE.match(line.rstrip())
        if not match:
            continue
        index = int(match.group(1))
        if not 1 <= index <= len(records):
            continue
        tags: list[str] = []
        for raw in re.split(r"[,\s]+", match.group(2)):
            tag = raw.strip().strip("`").lstrip("#").strip()
            if not tag:
                continue
            if NEVER_ASSIGN_RE.match(tag):
                rejected[tag] += 1
                continue
            if tag not in approved and "/" in tag:
                candidates = by_term.get(tag.split("/", 1)[1], [])
                if len(candidates) == 1:
                    tag = candidates[0]
            if tag in approved:
                if tag not in tags:
                    tags.append(tag)
            else:
                rejected[tag] += 1
        if tags:
            assignments[records[index - 1]["path"]] = tags
    return assignments, rejected


def bundles(records: Sequence[dict], size: int = BUNDLE_SIZE) -> list[list[dict]]:
    """Split the target notes into bundles of `size`."""
    return [list(records[i:i + size]) for i in range(0, len(records), size)]
