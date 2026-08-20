"""One-line page description extraction and YAML quoting helpers.

`extract_description()` derives a first-sentence summary from a wiki page's
markdown content. Shared by wiki-create-index-pages.py (fallback when a page
carries no `description:` frontmatter) and wiki-backfill-descriptions.py
(which writes the field into frontmatter).

Rules:
  - YAML frontmatter and HTML comments (<!-- ... -->) are stripped first.
  - The summary is the first sentence of the first non-heading paragraph line.
  - Wikilinks are kept intact; truncation never leaves an unclosed [[link.
  - Leading markdown emphasis (*...*, **...**, _..._) is unwrapped so the
    result never starts with characters that break YAML.
  - Result is capped at SUMMARY_MAX_CHARS characters.
"""

import re

SUMMARY_MAX_CHARS = 160

_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_BLOCK_ANCHOR_RE = re.compile(r"\s+\^[\w-]+$")
_LEADING_EMPHASIS_RE = re.compile(r"^(\*\*\*|\*\*|\*|___|__|_)(.+?)\1")
_FIRST_SENTENCE_RE = re.compile(r"^(.+?[.!?])\s")


def _balance_wikilinks(text: str) -> str:
    """Trim a truncated string so it never ends inside an unclosed [[wikilink."""
    while text.count("[[") != text.count("]]"):
        cut = text.rfind("[[")
        if cut < 0:
            break
        text = text[:cut].rstrip()
    return text


def _cap_summary(summary: str) -> str:
    """Truncate a summary to SUMMARY_MAX_CHARS without breaking wikilinks."""
    if len(summary) <= SUMMARY_MAX_CHARS:
        return summary
    cut = summary.rfind(" ", 0, SUMMARY_MAX_CHARS)
    if cut <= 0:
        cut = SUMMARY_MAX_CHARS
    return _balance_wikilinks(summary[:cut].rstrip(" ,;:—-")) + " …"


def _strip_frontmatter(content: str) -> str:
    """Return the body after a leading YAML frontmatter block, if any."""
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return content
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return "".join(lines[i + 1:])
    return content  # unclosed frontmatter: treat everything as body


def _strip_leading_emphasis(text: str) -> str:
    """Unwrap emphasis markers at the start so YAML values stay clean."""
    while True:
        m = _LEADING_EMPHASIS_RE.match(text)
        if not m:
            break
        text = m.group(2) + text[m.end():]
    return text.lstrip("*_ ").rstrip()


def extract_description(content: str) -> str | None:
    """Return a one-line first-sentence summary of a page, or None.

    None means the page has no usable body text (empty, or headings only).
    """
    body = _strip_frontmatter(content)
    body = _HTML_COMMENT_RE.sub("", body)

    summary: str | None = None
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        summary = stripped
        break
    if summary is None:
        return None

    summary = _BLOCK_ANCHOR_RE.sub("", summary)

    # Truncate to first sentence (never inside a wikilink), then cap length
    m = _FIRST_SENTENCE_RE.match(summary + " ")
    if m:
        candidate = _balance_wikilinks(m.group(1)).rstrip()
        if candidate:
            summary = candidate

    summary = _strip_leading_emphasis(summary)
    summary = _cap_summary(summary)
    return summary or None


def yaml_double_quote(text: str) -> str:
    """Encode text as a YAML double-quoted scalar (escaping \\ and \")."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def yaml_unquote(value: str) -> str:
    """Decode a scalar as written by yaml_double_quote; pass others through."""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return re.sub(r"\\(.)", r"\1", value[1:-1])
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value
