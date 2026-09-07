"""Find every wiki page about a subject, cheaply, via the per-type index files.

Each `wiki/<type>/index.md` holds one line per page:

    - [[wiki/<type>/<File>|<Title>]] — <one-line description>

Scanning those ~8k lines is far cheaper than opening ~7k pages, so
`search_indexes()` is the first pass. `search_pages()` is the second pass:
it reads every page's frontmatter to match `tags:` (the vault's own
taxonomy) and, with `body=True`, also greps the body text for terms the
index lines miss.

Backs `scripts/wiki-find.py` and the `wiki-find` skill.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .frontmatter import FRONTMATTER_RE, split_frontmatter
from .paths import should_skip_md

# Order used when grouping output; mirrors wiki/index.md.
TOPIC_TYPES = (
    "competition", "concepts", "conversations", "decisions",
    "people", "problems", "projects", "systems",
)

_INDEX_LINE_RE = re.compile(
    r"^- \[\[(?P<path>wiki/(?P<type>[^/|\]]+)/[^|\]]+)\|(?P<title>.*?)\]\]"
    r"(?:\s+—\s+(?P<desc>.*))?$"
)

# Match rank: lower is better.
_RANK = {"title": 0, "description": 1, "tags": 2, "body": 3}

_INLINE_TAGS_RE = re.compile(r"^tags:\s*\[(.*)\]\s*$", re.MULTILINE)
_BLOCK_TAGS_RE = re.compile(r"^tags:\s*\n((?:[ \t]+-[^\n]*\n?)+)", re.MULTILINE)


@dataclass
class Hit:
    path: str            # vault-relative, no .md — usable as a wikilink target
    title: str
    topic_type: str
    description: str
    matched_in: str      # "title" | "description" | "tags" | "body"
    terms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "title": self.title,
            "type": self.topic_type,
            "description": self.description,
            "matched_in": self.matched_in,
            "terms": list(self.terms),
        }


def expand_terms(raw: list[str]) -> list[str]:
    """Split comma-separated inputs, strip, and dedupe case-insensitively (first spelling wins)."""
    out: list[str] = []
    seen: set[str] = set()
    for chunk in raw:
        for term in chunk.split(","):
            term = term.strip()
            if term and term.lower() not in seen:
                seen.add(term.lower())
                out.append(term)
    return out


def parse_index_line(line: str) -> Hit | None:
    """Parse one index entry line; None for headings, 'Recently updated' rows, blanks."""
    m = _INDEX_LINE_RE.match(line.rstrip())
    if not m:
        return None
    return Hit(
        path=m.group("path"),
        title=m.group("title"),
        topic_type=m.group("type"),
        description=(m.group("desc") or "").strip(),
        matched_in="",
    )


def _matching_terms(text: str, terms: list[str]) -> list[str]:
    low = text.lower()
    return [t for t in terms if t.lower() in low]


def _normalize_tag(text: str) -> str:
    """Compare terms and tags loosely: lowercase, spaces/underscores become hyphens."""
    return re.sub(r"[\s_]+", "-", text.strip().strip("\"'").lower())


def page_tags(content: str) -> list[str]:
    """Frontmatter tags, from either `tags: [a, b]` or a `tags:` block list."""
    m = FRONTMATTER_RE.match(content)
    if not m:
        return []
    fm = m.group(1)
    inline = _INLINE_TAGS_RE.search(fm)
    if inline:
        return [t.strip().strip("\"'") for t in inline.group(1).split(",") if t.strip()]
    block = _BLOCK_TAGS_RE.search(fm)
    if block:
        return [ln.strip().lstrip("-").strip().strip("\"'") for ln in block.group(1).splitlines() if ln.strip()]
    return []


def _matching_tag_terms(tags: list[str], terms: list[str]) -> list[str]:
    normalized = {_normalize_tag(t) for t in tags}
    return [t for t in terms if _normalize_tag(t) in normalized]


def _sort_key(hit: Hit):
    return (-len(hit.terms), _RANK[hit.matched_in], hit.topic_type, hit.title.lower())


def _selected_types(types: list[str] | None) -> tuple[str, ...]:
    return tuple(types) if types else TOPIC_TYPES


def search_indexes(root: Path, terms: list[str], types: list[str] | None = None) -> list[Hit]:
    """First pass: match terms against title, filename and description in wiki/<type>/index.md."""
    hits: dict[str, Hit] = {}
    for topic_type in _selected_types(types):
        index = root / "wiki" / topic_type / "index.md"
        if not index.is_file():
            continue
        for line in index.read_text(encoding="utf-8", errors="replace").splitlines():
            hit = parse_index_line(line)
            if hit is None or hit.path in hits:
                continue
            stem = hit.path.rsplit("/", 1)[-1]
            title_terms = _matching_terms(f"{hit.title}\n{stem}", terms)
            desc_terms = _matching_terms(hit.description, terms)
            if not title_terms and not desc_terms:
                continue
            hit.matched_in = "title" if title_terms else "description"
            hit.terms = sorted(set(title_terms) | set(desc_terms), key=str.lower)
            hits[hit.path] = hit
    return sorted(hits.values(), key=_sort_key)


def search_pages(
    root: Path,
    terms: list[str],
    types: list[str] | None = None,
    exclude: set[str] | None = None,
    body: bool = False,
) -> list[Hit]:
    """Second pass over page files: match frontmatter tags, and body text when `body` is set.

    Skips index files and any vault-relative path in `exclude` (typically the
    first-pass hits, so each page is reported once).
    """
    exclude = exclude or set()
    hits: list[Hit] = []
    for topic_type in _selected_types(types):
        folder = root / "wiki" / topic_type
        if not folder.is_dir():
            continue
        for page in sorted(folder.rglob("*.md")):
            if should_skip_md(page, root):
                continue
            rel = str(page.relative_to(root))[:-3]
            if rel in exclude:
                continue
            text = page.read_text(encoding="utf-8", errors="replace")
            tag_terms = _matching_tag_terms(page_tags(text), terms)
            body_terms = _matching_terms(text, terms) if body and not tag_terms else []
            if not tag_terms and not body_terms:
                continue
            fm, _ = split_frontmatter(text)
            hits.append(Hit(
                path=rel,
                title=page.stem,
                topic_type=topic_type,
                description=str(fm.get("description") or "").strip(),
                matched_in="tags" if tag_terms else "body",
                terms=sorted(tag_terms or body_terms, key=str.lower),
            ))
    return sorted(hits, key=_sort_key)


def format_markdown(hits: list[Hit]) -> str:
    """Group hits by topic type (wiki/index.md order); annotate tag/body-only hits with their terms."""
    if not hits:
        return "_No pages matched._\n"
    lines: list[str] = []
    for topic_type in TOPIC_TYPES + tuple(sorted({h.topic_type for h in hits} - set(TOPIC_TYPES))):
        group = [h for h in hits if h.topic_type == topic_type]
        if not group:
            continue
        lines.append(f"## {topic_type.capitalize()} ({len(group)})")
        lines.append("")
        for h in group:
            entry = f"- [[{h.path}|{h.title}]]"
            if h.description:
                entry += f" — {h.description}"
            if h.matched_in in ("tags", "body"):
                entry += f" ({h.matched_in}: {', '.join(h.terms)})"
            lines.append(entry)
        lines.append("")
    return "\n".join(lines)
