"""Tag vocabulary tooling — inventory, inline-hashtag escaping, excerpt building.

Phases 0-2 of `INBOX/Plan Systematic Tags.md`. The LLM-backed phases (taxonomy,
assign) and the destructive remap are separate work and are not implemented here.

Three invariants hold throughout:

* **PDFs and images are never opened.** `![[...]]` embeds are dropped from the
  segment stream (`_segments`), so nothing ever resolves an attachment path.
* **Obsidian is the authority on what a tag is.** The inventory comes from
  `obsidian tags`, not from grep, because the CLI also sees inline hashtags.
  Its output includes phantom *parent aggregates* (`#year` is reported with the
  summed count of every `year/*`), which `parent_aggregates` strips.
* **Nothing is written without an explicit apply.** The write helpers here take
  the text and hand back new text; only the CLI touches the filesystem, and it
  backs a file up — flushed and fsynced — before rewriting it.
"""

import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator, Sequence

from .frontmatter import FRONTMATTER_RE
# Reused rather than reimplemented: locating the CLI (PATH, then the macOS
# app-bundle fallback) and probing whether a running Obsidian answers queries
# are already solved and tested in fixers.
from .fixers import _find_obsidian_cli, _obsidian_responds


# Excerpt budget. 400 words is ~1.5 pages of prose — enough to establish a
# note's subject. It is kept as a *bound* rather than a saving: uncapped, one
# 20k-word transcript overruns its whole bundle and loses every note in it.
CAP_WORDS = 400
MAX_CALLOUT_SAMPLES = 8
MIN_CALLOUT_WORDS = 20
LOW_WORD_FLOOR = 20

# Vocabulary shape: `namespace/term` or `namespace/term/term`. Never 1 segment
# (too coarse to mean anything), never 4. Hyphens inside a segment, matching the
# vault's existing 4444 tags and the spellings wiki-find documents.
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9.\-]*(?:/[a-z0-9][a-z0-9.\-]*){1,2}$")

# `year/YYYY` is the one exempt pattern — a browsing axis, not a concept.
YEAR_TAG_RE = re.compile(r"^year/\d{4}$")

# Directories holding notes. `scripts/`, `templates/` and `config/` are excluded
# so that config/tags.md can never register its own vocabulary as usage.
SCAN_DIRS = ("raw", "wiki", "INBOX")

# Files that live among the notes but are not notes: generated navigation pages,
# agent instructions, the changelog, the backlog. Tagging them is meaningless —
# `wiki/systems/index.md` is a rebuilt table of contents, and RELEASE-NOTES.md is
# a changelog — and it pollutes the tag counts for everything else.
NON_NOTE_FILES = frozenset({
    "index.md", "CLAUDE.md", "AGENTS.md", "README.md",
    "RELEASE-NOTES.md", "BACKLOG.md",
})

# Escaping has to reach further than note discovery does. Obsidian indexes
# *every* `.md` in the vault — including the attachment payloads under
# `_resources/<note>.resources/` that `iter_notes` deliberately skips, and
# root-level files like README.md — so a stray hashtag there pollutes the tag
# pane just the same. These directories hold no notes and are excluded instead.
ESCAPE_SKIP_DIRS = frozenset({
    "scripts", "templates", "config", ".git", ".githooks",
    ".claude", ".agents", ".codex", ".obsidian", ".import", ".tags",
})

SCRATCH_DIRNAME = ".tags"

_OBSIDIAN_TIMEOUT = 60


class ObsidianUnavailable(RuntimeError):
    """The Obsidian CLI returned nothing.

    Raised rather than shrugged: the CLI is the *only* source of inline
    hashtags, so a silent fall back to a frontmatter-only scan would report a
    plausible-looking inventory with every stray tag missing, and would make the
    escape phase find zero targets and claim success having done nothing.
    """

_BLOCK_TAGS_RE = re.compile(r"^tags:[ \t]*\n((?:[ \t]+-[^\n]*\n?)+)", re.MULTILINE)
_INLINE_LIST_RE = re.compile(r"^tags:[ \t]*\[(.*)\][ \t]*$", re.MULTILINE)
_SCALAR_TAGS_RE = re.compile(r"^tags:[ \t]*([^\[\n][^\n]*)$", re.MULTILINE)

_EMBED_RE = re.compile(r"^!\[\[.*\]\]$")
_FENCE_RE = re.compile(r"^(?:```|~~~)")
_CALLOUT_HEAD_RE = re.compile(r"^>\s*\[!([A-Za-z0-9_-]+)\][-+]?\s*(.*)$")
_QUOTE_RE = re.compile(r"^>\s?(.*)$")
_RULE_RE = re.compile(r"^-{3,}$")
_CODE_SPAN_RE = re.compile(r"`[^`\n]*`")

# The boilerplate OCR callout title. Dropped so it neither burns excerpt words
# nor biases every scanned note towards the same tags.
_OCR_TITLE = "extracted text"


# --------------------------------------------------------------------------- #
# Frontmatter tags
# --------------------------------------------------------------------------- #

def split_document(content: str) -> tuple[str, str]:
    """Split into (frontmatter text, body). ``("", content)`` when there is none."""
    match = FRONTMATTER_RE.match(content)
    if not match:
        return "", content
    return match.group(1), content[match.end():]


def _clean_tags(items: Iterable[str]) -> list[str]:
    """Strip quotes, a leading `#`, and blanks; dedupe keeping first appearance."""
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        tag = item.strip().strip("\"'").lstrip("#").strip()
        if tag and tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


def parse_tags(fm_text: str) -> list[str]:
    """Frontmatter tags, from any of the three shapes present in this vault.

    A YAML block list, an inline ``tags: [a, b]``, or a bare scalar
    ``tags: a b``. ``lib.topic_search.page_tags`` handles only the first two and
    ``lib.frontmatter.split_frontmatter`` is scalar-only (it reports ``""`` for a
    block list), so tag parsing needs its own reader.
    """
    if not fm_text:
        return []
    fm = fm_text if fm_text.endswith("\n") else fm_text + "\n"
    block = _BLOCK_TAGS_RE.search(fm)
    if block:
        return _clean_tags(
            line.strip().lstrip("-").strip() for line in block.group(1).splitlines()
        )
    inline = _INLINE_LIST_RE.search(fm)
    if inline:
        return _clean_tags(inline.group(1).split(","))
    scalar = _SCALAR_TAGS_RE.search(fm)
    if scalar:
        return _clean_tags(re.split(r"[,\s]+", scalar.group(1)))
    return []


def write_tags(content: str, tags: Sequence[str]) -> str:
    """Return `content` with its frontmatter `tags:` replaced by `tags`.

    Line surgery, not a YAML round-trip: every other frontmatter line survives
    byte-for-byte, so hand-written `description:` quoting, block `sources:`
    lists and `^block-id` anchors are untouched. A generic frontmatter renderer
    cannot be used here — the repo's own `split_frontmatter` is scalar-only and
    reports `""` for a block list, so rendering from it would delete the tags
    line and orphan the list items beneath it.

    The note's existing *shape* is preserved (inline list stays inline, block
    list stays block), because switching 8000 notes from `tags: [a, b]` to a
    block list would be a huge diff for no gain. A bare scalar becomes an
    inline list, and an empty result is written as `tags: []` rather than
    dropping the key.
    """
    match = FRONTMATTER_RE.match(content)
    inline = "[" + ", ".join(tags) + "]"
    if not match:
        if not tags:
            return content
        return f"---\ntags: {inline}\n---\n" + content

    fm, body = match.group(1), content[match.end():]
    fm_lines = fm.split("\n")

    start = None
    for i, line in enumerate(fm_lines):
        if re.match(r"^tags\s*:", line):
            start = i
            break

    if start is None:
        if not tags:
            return content
        fm_lines.insert(0, f"tags: {inline}")
        return "---\n" + "\n".join(fm_lines) + "\n---\n" + body

    # Consume a block list's items so they are replaced, not orphaned.
    end = start + 1
    while end < len(fm_lines) and re.match(r"^[ \t]+-", fm_lines[end]):
        end += 1

    was_block = end > start + 1
    if was_block and tags:
        replacement = ["tags:"] + [f"  - {tag}" for tag in tags]
    else:
        replacement = [f"tags: {inline}"]
    fm_lines[start:end] = replacement
    return "---\n" + "\n".join(fm_lines) + "\n---\n" + body


def frontmatter_backup_record(path: Path, root: Path, content: str) -> dict:
    """Backup for a frontmatter-only edit: path, whole-file hash, frontmatter text.

    `had_frontmatter` distinguishes a note that had none from one whose
    frontmatter was empty. Without it a restore rebuilds a hollow
    ``---\\n\\n---\\n`` block onto a file that never had one, the hash never
    matches, and the note is unrevertible — which is exactly what happened to
    23 notes on the first write run.
    """
    fm, _ = split_document(content)
    return {
        "path": str(path.relative_to(root)),
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        "frontmatter": fm,
        "had_frontmatter": bool(FRONTMATTER_RE.match(content)),
    }


def restore_frontmatter(record: dict, root: Path) -> str:
    """Put a recorded frontmatter back on the note's current body.

    Verified, not hopeful: the rebuilt file must hash back to the recorded
    original, otherwise the body has changed since the backup and the note is
    left alone rather than half-reverted.
    """
    path = root / record["path"]
    if not path.is_file():
        return "missing"
    current = path.read_text(encoding="utf-8", errors="replace")
    if hashlib.sha256(current.encode("utf-8")).hexdigest() == record["sha256"]:
        return "unchanged"
    _fm, body = split_document(current)
    # Older records predate `had_frontmatter`; infer it from the stored text.
    had_fm = record.get("had_frontmatter", bool(record["frontmatter"]))
    rebuilt = ("---\n" + record["frontmatter"] + "\n---\n" + body) if had_fm else body
    if hashlib.sha256(rebuilt.encode("utf-8")).hexdigest() != record["sha256"]:
        return "mismatch"
    path.write_text(rebuilt, encoding="utf-8")
    return "restored"


def valid_tag(tag: str) -> bool:
    """True if the tag conforms to the curated shape (or is an exempt year tag)."""
    return bool(TAG_RE.match(tag) or YEAR_TAG_RE.match(tag))


# --------------------------------------------------------------------------- #
# Note discovery
# --------------------------------------------------------------------------- #

def iter_notes(root: Path, subdirs: Sequence[str] = SCAN_DIRS) -> Iterator[Path]:
    """Yield every `.md` note under the given subdirs, sorted, skipping `.`/`_` dirs."""
    for subdir in subdirs:
        base = root / subdir
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(
                d for d in dirnames if not d.startswith(".") and not d.startswith("_")
            )
            for name in sorted(filenames):
                # Structural files sit among the notes but are not notes.
                if name.endswith(".md") and name not in NON_NOTE_FILES:
                    yield Path(dirpath) / name


def iter_vault_md(root: Path) -> Iterator[Path]:
    """Every `.md` file Obsidian indexes, for the escape phase.

    Unlike `iter_notes` this includes root-level files and the `_resources`
    attachment payloads, because Obsidian counts their hashtags as tags.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        if rel.parts and rel.parts[0] in ESCAPE_SKIP_DIRS:
            dirnames[:] = []
            continue
        dirnames[:] = sorted(d for d in dirnames if d not in ESCAPE_SKIP_DIRS)
        for name in sorted(filenames):
            if name.endswith(".md"):
                yield Path(dirpath) / name


def declared_tags(root: Path, subdirs: Sequence[str] = SCAN_DIRS) -> Counter:
    """Count frontmatter tag usage across the note trees."""
    counts: Counter = Counter()
    for path in iter_notes(root, subdirs):
        content = path.read_text(encoding="utf-8", errors="replace")
        fm, _ = split_document(content)
        for tag in parse_tags(fm):
            counts[tag] += 1
    return counts


def normalize_key(text: str) -> str:
    """Loose comparison key: lowercase, every run of non-alphanumerics becomes `-`."""
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def wiki_type_index(root: Path) -> dict[str, set[str]]:
    """Map a normalized wiki page name to the topic type(s) holding a page of that name.

    This is the free namespace signal for the taxonomy phase: a tag matching a
    `wiki/systems/` page wants a `system/` namespace, one matching
    `wiki/projects/` wants `project/`, and only genuinely ambiguous names — a
    page of the same name under two types — need a judgement call.
    """
    index: dict[str, set[str]] = {}
    wiki = root / "wiki"
    if not wiki.is_dir():
        return index
    for type_dir in sorted(p for p in wiki.iterdir() if p.is_dir()):
        for page in sorted(type_dir.glob("*.md")):
            if page.name == "index.md":
                continue
            index.setdefault(normalize_key(page.stem), set()).add(type_dir.name)
    return index


# --------------------------------------------------------------------------- #
# Obsidian CLI — the authority on what is a tag
# --------------------------------------------------------------------------- #

def _default_obsidian_runner(root: Path) -> str | None:
    """Run `obsidian tags counts` for the vault at `root`, or None if the call fails.

    **Obsidian must already be running.** With the app running this is a fast
    client call that exits on its own (~0.3s for 4457 tags). With the app
    closed, the `obsidian` shim *is* the app binary, so it boots the app and
    stays in the foreground — the query answer never comes and any wait on the
    process, `subprocess.run(capture_output=True)` included, hangs. The
    pre-flight `_obsidian_responds` check separates those two worlds cheaply.

    This deliberately does not launch Obsidian. A GUI appearing as a side
    effect of a tag scan is not wanted, and `fixers.fix_loose_files` already
    owns the decision to start it.

    stdin is closed deliberately: the CLI waits on it otherwise.
    """
    cli = _find_obsidian_cli()
    if cli is None:
        raise ObsidianUnavailable(
            "the obsidian CLI was not found — is Obsidian installed?"
        )
    if not _obsidian_responds(cli, root):
        raise ObsidianUnavailable(
            f"Obsidian is not answering CLI queries for vault {root.name!r}. "
            "Start Obsidian with this vault open and re-run."
        )
    try:
        proc = subprocess.run(
            [cli, f"vault={root.name}", "tags", "counts", "format=tsv"],
            capture_output=True,
            text=True,
            timeout=_OBSIDIAN_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.stdout if proc.returncode == 0 else None


def parse_obsidian_tags(output: str) -> dict[str, int]:
    """Parse `obsidian tags counts format=tsv` into {tag without '#': count}."""
    counts: dict[str, int] = {}
    for line in (output or "").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        tag = parts[0].strip().lstrip("#")
        try:
            counts[tag] = int(parts[1].strip())
        except ValueError:
            continue
    return counts


def obsidian_tags(root: Path, runner: Callable[[Path], str | None] | None = None) -> dict[str, int]:
    """Every tag Obsidian sees in the vault, inline hashtags included.

    Raises ObsidianUnavailable when the CLI yields nothing usable.
    """
    run = runner or _default_obsidian_runner
    counts = parse_obsidian_tags(run(root) or "")
    if not counts:
        raise ObsidianUnavailable(
            f"`obsidian vault={root.name} tags counts` returned no tags. "
            "Is Obsidian running with this vault open?"
        )
    return counts


def parent_aggregates(counts: dict[str, int], declared: Counter) -> set[str]:
    """Tags Obsidian reports that are really just the roll-up of their children.

    Obsidian lists `#year` alongside `#year/2022`, carrying the summed count of
    every child, even though no note declares a bare `year`. Such a phantom is
    identified by having at least one `tag/...` child while never appearing in
    frontmatter itself — anything a note genuinely declares is a real tag.
    """
    aggregates: set[str] = set()
    for tag in counts:
        if declared.get(tag, 0):
            continue
        if any(other.startswith(tag + "/") for other in counts):
            aggregates.add(tag)
    return aggregates


# --------------------------------------------------------------------------- #
# Phase 0 — inventory
# --------------------------------------------------------------------------- #

_LEGAL_TAG_CHARS = re.compile(r"^[A-Za-z0-9_/\-]+$")


def blind_reason(tag: str, seen: dict[str, int]) -> str:
    """Why Obsidian does not report a tag a note declares. "" when it does.

    A declared tag missing from Obsidian's own list is not automatically a lost
    tag, and the difference decides what the remap should do with it:

    * ``malformed-frontmatter`` — a key leaked into the tag list
      (``tags: [..., stub: true]``). The note needs repairing, not remapping.
    * ``case-variant`` — Obsidian folds tags case-insensitively, so ``DataSpec`` is
      counted under ``dataspec``. Nothing is lost; the remap just normalizes case.
    * ``numeric-only`` — Obsidian requires at least one non-numeric character,
      so a bare ``2026`` is not a tag at all.
    * ``illegal-char`` — ``:``, ``&``, ``+`` and friends are not valid in an
      Obsidian tag, so ``1:1``, ``t&d`` and ``c++`` are invisible in the tag
      pane however many notes declare them.
    """
    if ": " in tag or tag.endswith(":"):
        return "malformed-frontmatter"
    if tag in seen:
        return ""
    lowered = {t.lower() for t in seen}
    if tag.lower() in lowered:
        return "case-variant"
    if tag.isdigit():
        return "numeric-only"
    if not _LEGAL_TAG_CHARS.match(tag):
        return "illegal-char"
    return "unindexed"


@dataclass
class InventoryRow:
    tag: str
    obsidian_count: int
    declared_count: int
    wiki_types: list[str] = field(default_factory=list)
    inline_only: bool = False
    depth: int = 1
    blind: str = ""

    def to_dict(self) -> dict:
        return {
            "tag": self.tag,
            "obsidian_count": self.obsidian_count,
            "declared_count": self.declared_count,
            "wiki_types": list(self.wiki_types),
            "inline_only": self.inline_only,
            "depth": self.depth,
            "blind": self.blind,
        }


def build_inventory(
    root: Path,
    runner: Callable[[Path], str | None] | None = None,
) -> tuple[list[InventoryRow], dict[str, int]]:
    """The real tag inventory, with parent aggregates removed.

    Returns (rows sorted by declared count then Obsidian count, stats).
    """
    seen = obsidian_tags(root, runner)
    declared = declared_tags(root)
    aggregates = parent_aggregates(seen, declared)

    rows: list[InventoryRow] = []
    types = wiki_type_index(root)
    for tag, count in seen.items():
        if tag in aggregates:
            continue
        declared_count = declared.get(tag, 0)
        rows.append(InventoryRow(
            tag=tag,
            obsidian_count=count,
            declared_count=declared_count,
            wiki_types=sorted(types.get(normalize_key(tag), ())),
            inline_only=declared_count == 0,
            depth=tag.count("/") + 1,
        ))
    # Tags a note declares that Obsidian does not report. These are not simply
    # missing — `blind_reason` says whether the tag is illegal, a case variant,
    # or frontmatter damage, which is what the remap needs to know.
    for tag, declared_count in declared.items():
        if tag not in seen:
            rows.append(InventoryRow(
                tag=tag,
                obsidian_count=0,
                declared_count=declared_count,
                wiki_types=sorted(types.get(normalize_key(tag), ())),
                inline_only=False,
                depth=tag.count("/") + 1,
                blind=blind_reason(tag, seen),
            ))

    rows.sort(key=lambda r: (-r.declared_count, -r.obsidian_count, r.tag))
    stats = {
        "obsidian_reported": len(seen),
        "parent_aggregates": len(aggregates),
        "real_tags": len(rows),
        "declared_distinct": len(declared),
        "declared_occurrences": sum(declared.values()),
        "inline_only": sum(1 for r in rows if r.inline_only),
        "singletons": sum(1 for r in rows if r.declared_count == 1),
        "conforming": sum(1 for r in rows if valid_tag(r.tag)),
        "with_wiki_type": sum(1 for r in rows if r.wiki_types),
        "ambiguous_wiki_type": sum(1 for r in rows if len(r.wiki_types) > 1),
    }
    blind: Counter = Counter(r.blind for r in rows if r.blind)
    stats["blind"] = dict(sorted(blind.items(), key=lambda kv: -kv[1]))
    stats["blind_occurrences"] = sum(r.declared_count for r in rows if r.blind)
    return rows, stats


def format_inventory_tsv(rows: Sequence[InventoryRow]) -> str:
    """TSV with a header, one row per real tag."""
    out = ["tag\tobsidian_count\tdeclared_count\tdepth\twiki_types"
           "\tinline_only\tconforming\tblind"]
    for r in rows:
        out.append("\t".join([
            r.tag,
            str(r.obsidian_count),
            str(r.declared_count),
            str(r.depth),
            ",".join(r.wiki_types),
            "yes" if r.inline_only else "no",
            "yes" if valid_tag(r.tag) else "no",
            r.blind,
        ]))
    return "\n".join(out) + "\n"


# --------------------------------------------------------------------------- #
# Phase 1 — escape unlisted inline hashtags
# --------------------------------------------------------------------------- #

def _ancestors(tag: str) -> Iterator[str]:
    """`a/b/c` -> `a/b`, `a`."""
    parts = tag.split("/")
    for i in range(len(parts) - 1, 0, -1):
        yield "/".join(parts[:i])


def unlisted_inline_tags(
    root: Path,
    runner: Callable[[Path], str | None] | None = None,
) -> dict[str, int]:
    """Tags Obsidian sees that no note declares in frontmatter.

    Every declared tag is subtracted, and so is every *ancestor* of a declared
    tag — `#sw` is implied by `sw/agile` and is not a stray inline hashtag.
    What remains is the escape target set: OCR artefacts, pasted hex colours,
    Slack channel names, C directives and the like.

    The protected set is computed over the *wide* scope, so a tag declared in
    an attachment payload's frontmatter still shields its inline twin.
    """
    seen = obsidian_tags(root, runner)
    declared: Counter = Counter()
    for path in iter_vault_md(root):
        fm, _ = split_document(path.read_text(encoding="utf-8", errors="replace"))
        for tag in parse_tags(fm):
            declared[tag] += 1
    protected: set[str] = set(declared)
    for tag in declared:
        protected.update(_ancestors(tag))
    return {t: c for t, c in seen.items() if t not in protected}


def _escape_pattern(targets: Sequence[str]) -> re.Pattern[str]:
    """Match `#tag` for any target, longest first so a longer tag always wins.

    The lookbehind rejects an already-escaped `\\#`, an HTML entity `&#`, a `##`
    heading and a word-internal `a#b`; the lookahead stops `#sig` matching
    inside `#sig-claude`.
    """
    alternation = "|".join(
        re.escape(t) for t in sorted(set(targets), key=lambda t: (-len(t), t))
    )
    return re.compile(r"(?<![\w&#\\])#(" + alternation + r")(?![\w/-])")


def escape_inline_tags(body: str, targets: Sequence[str]) -> tuple[str, int]:
    """Rewrite `#foo` as `\\#foo` in body text. Returns (new body, count).

    Escaping rather than spacing is deliberate: many occurrences start a line
    inside an OCR callout (`> #define NULL 0`), where inserting a space would
    turn the line into an H1. An escaped hash still renders as a plain `#`.

    Fenced code blocks and inline code spans are left untouched.
    """
    if not targets or not body:
        return body, 0
    pattern = _escape_pattern(targets)
    out: list[str] = []
    changed = 0
    in_fence = False
    for line in body.splitlines(keepends=True):
        if _FENCE_RE.match(line.lstrip()):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        parts: list[str] = []
        pos = 0
        for span in _CODE_SPAN_RE.finditer(line):
            text, n = pattern.subn(r"\\#\1", line[pos:span.start()])
            changed += n
            parts.append(text)
            parts.append(span.group(0))
            pos = span.end()
        text, n = pattern.subn(r"\\#\1", line[pos:])
        changed += n
        parts.append(text)
        out.append("".join(parts))
    return "".join(out), changed


def escape_document(content: str, targets: Sequence[str]) -> tuple[str, int]:
    """Apply `escape_inline_tags` to the body only, leaving frontmatter alone."""
    match = FRONTMATTER_RE.match(content)
    if not match:
        return escape_inline_tags(content, targets)
    body, changed = escape_inline_tags(content[match.end():], targets)
    return content[:match.end()] + body, changed


# --------------------------------------------------------------------------- #
# Phase 2 — excerpts
# --------------------------------------------------------------------------- #

def _spread(items: Sequence[str], limit: int) -> list[str]:
    """Up to `limit` items sampled evenly across the sequence, not from the front.

    A scanned newsletter puts its masthead on page 1, so a head-of-document
    sample gives every issue of a series the same useless excerpt — and
    therefore the same tags.
    """
    if limit <= 0:
        return []
    if len(items) <= limit:
        return list(items)
    if limit == 1:
        return [items[len(items) // 2]]
    step = (len(items) - 1) / (limit - 1)
    return [items[round(i * step)] for i in range(limit)]


def _segments(body: str) -> list[tuple[str, str]]:
    """Split a body into ("prose"|"callout", text) segments.

    Dropped entirely: `![[...]]` embeds (a PDF or image is never opened),
    fenced code blocks, markdown tables and horizontal rules.
    """
    segments: list[tuple[str, str]] = []
    buf: list[str] = []
    kind = "prose"
    in_fence = False

    def flush(current: str) -> None:
        text = " ".join(" ".join(buf).split())
        if text:
            segments.append((current, text))
        buf.clear()

    for raw in body.splitlines():
        line = raw.strip()
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or not line:
            continue
        if _EMBED_RE.match(line):       # PDF / image embed -> never opened
            continue
        if line.startswith("|") or _RULE_RE.match(line):
            continue

        head = _CALLOUT_HEAD_RE.match(line)
        if head:
            flush(kind)
            kind = "callout"
            title = head.group(2).strip()
            if title and title.lower() != _OCR_TITLE:
                buf.append(title)
            continue

        quoted = _QUOTE_RE.match(line)
        if quoted:
            inner = quoted.group(1).strip()
            if inner and not inner.startswith("|"):
                buf.append(inner)
            continue

        if kind == "callout":
            flush(kind)
            kind = "prose"
        if line.startswith("#"):        # heading text is good tag signal
            buf.append(line.lstrip("#").strip())
            continue
        buf.append(line)

    flush(kind)
    return segments


def build_excerpt(body: str, cap: int = CAP_WORDS) -> tuple[str, int, bool]:
    """Build a capped excerpt. Returns (text, word count, title_only).

    Prose — the note's own words — is consumed first and may take the whole
    budget. Only if room is left are OCR callouts sampled, spread across the
    document rather than taken from the top.
    """
    segments = _segments(body)
    words: list[str] = []
    for kind, text in segments:
        if kind != "prose":
            continue
        words.extend(text.split())
        if len(words) >= cap:
            break

    if len(words) < cap:
        callouts = [text for kind, text in segments if kind == "callout"]
        picks = _spread(callouts, MAX_CALLOUT_SAMPLES)
        if picks:
            per = max(MIN_CALLOUT_WORDS, (cap - len(words)) // len(picks))
            for text in picks:
                if len(words) >= cap:
                    break
                words.extend(text.split()[:per])

    words = words[:cap]
    # A note is "title only" when it genuinely has too little text to tag from,
    # so the floor can never exceed the budget we allowed it — otherwise a small
    # --cap-words would flag every note in the vault as too thin.
    return " ".join(words), len(words), len(words) < min(cap, LOW_WORD_FLOOR)


def note_record(path: Path, root: Path, cap: int = CAP_WORDS) -> dict:
    """One excerpt record for a note. Never opens anything but the `.md` itself."""
    content = path.read_text(encoding="utf-8", errors="replace")
    fm, body = split_document(content)
    excerpt, words, title_only = build_excerpt(body, cap)
    return {
        "path": str(path.relative_to(root)),
        "title": path.stem,
        "tags": parse_tags(fm),
        "excerpt": excerpt,
        "words": words,
        "title_only": title_only,
    }


def series_key(title: str) -> str:
    """Strip a leading date and keep the first three words.

    Phase 2 reports the largest title series so a human can spot 70 near-identical
    scanned issues *before* any tokens are spent on them.
    """
    stripped = re.sub(r"^\d{4}(-\d{2}){0,2}\s*", "", title).strip()
    return " ".join(stripped.split()[:3]).lower()


# --------------------------------------------------------------------------- #
# Scratch state, checkpoints, backups
# --------------------------------------------------------------------------- #

def scratch_dir(root: Path) -> Path:
    """`<root>/.tags`, created on demand. Ignored by the allowlist .gitignore."""
    path = root / SCRATCH_DIRNAME
    path.mkdir(exist_ok=True)
    return path


def append_jsonl(path: Path, record: dict) -> None:
    """Append one record, flushed and fsynced before returning.

    For backups, durability is not optional: `raw/` and `wiki/` are outside git,
    so a backup record still sitting in a buffer when the process dies is no
    backup at all. Reopens the file per call — fine for the one-per-edited-note
    rate it is used at.
    """
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


class JsonlWriter:
    """Append-only JSONL sink holding the file open across many records.

    `durable=True` fsyncs every record, for anything that is a backup or an
    LLM-phase checkpoint (an interruption must cost at most one bundle). The
    buffered default is for regenerable artefacts such as excerpts, where
    13,000 fsyncs would buy nothing a re-run cannot.
    """

    def __init__(self, path: Path, durable: bool = False) -> None:
        self.path = path
        self.durable = durable
        self._handle = None

    def __enter__(self) -> "JsonlWriter":
        self._handle = self.path.open("a", encoding="utf-8")
        return self

    def __exit__(self, *exc_info) -> None:
        if self._handle is not None:
            self._handle.flush()
            os.fsync(self._handle.fileno())
            self._handle.close()
            self._handle = None

    def write(self, record: dict) -> None:
        assert self._handle is not None, "JsonlWriter used outside its context"
        self._handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        if self.durable:
            self._handle.flush()
            os.fsync(self._handle.fileno())


def load_jsonl(path: Path) -> list[dict]:
    """Read a JSONL checkpoint, skipping malformed lines. Missing file -> []."""
    if not path.is_file():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def full_backup_record(path: Path, root: Path, text: str) -> dict:
    """Backup for a *body* edit: path, hash, and the entire original text."""
    return {
        "path": str(path.relative_to(root)),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "text": text,
    }


def restore_full(record: dict, root: Path) -> str:
    """Restore a file from a full backup. Returns a status string.

    Byte-for-byte or nothing: a file already matching the backup is reported as
    unchanged, and one that does not is left alone rather than guessed at.
    """
    path = root / record["path"]
    if not path.is_file():
        return "missing"
    current = path.read_text(encoding="utf-8", errors="replace")
    if hashlib.sha256(current.encode("utf-8")).hexdigest() == record["sha256"]:
        return "unchanged"
    path.write_text(record["text"], encoding="utf-8")
    return "restored"
