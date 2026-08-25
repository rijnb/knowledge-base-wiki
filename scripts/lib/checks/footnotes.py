"""Validate markdown footnotes in wiki pages: refs, definitions, duplicates.

`[^s2]` is a footnote reference, not a link — it points at a `[^s2]: …`
definition line in the same file, so the link checker never resolves it as a
vault path. What can go wrong instead is the reference itself: a ref with no
definition (Obsidian renders it as literal text), a definition nothing refers
to, or the same id defined twice (only the first one wins).

The OKF cross-check — whether a `[^sN]` id matches `sources[].id` in the
frontmatter and points at that source's resource — lives in
`scripts/system/wiki-provenance-lint.py` and is not repeated here.
"""

import re
from pathlib import Path

from ..links import strip_frontmatter


# A footnote id as Obsidian writes it: the vault's source footnotes are `s1`,
# `s2`, … but prose footnotes carry word labels too. Deliberately narrow (no
# '/', '"', '\', whitespace) so an unfenced regex character class — `[^/]+`,
# `[^"\r\\]` — is not mistaken for a footnote reference.
_FOOTNOTE_ID = r"[A-Za-z0-9][A-Za-z0-9_-]*"
FOOTNOTE_REF_RE = re.compile(rf"\[\^({_FOOTNOTE_ID})\]")
FOOTNOTE_DEF_RE = re.compile(rf"^\[\^({_FOOTNOTE_ID})\]:")
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_FENCE_RE = re.compile(r"^\s*(?:```|~~~)")


def _collect(content: str) -> tuple[dict[str, int], dict[str, list[int]]]:
    """Return (refs: id -> first line, defs: id -> every definition line).

    Frontmatter is blanked (line numbers stay intact), fenced blocks and
    inline code are skipped — a footnote in an example is not a reference.
    """
    body, _ = strip_frontmatter(content)
    refs: dict[str, int] = {}
    defs: dict[str, list[int]] = {}
    in_fence = False
    for lineno, line in enumerate(body.splitlines(), 1):
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        def_match = FOOTNOTE_DEF_RE.match(line)
        if def_match:
            defs.setdefault(def_match.group(1), []).append(lineno)
            continue  # the definition's own `[^id]` is not a reference
        for ref_match in FOOTNOTE_REF_RE.finditer(_INLINE_CODE_RE.sub("", line)):
            refs.setdefault(ref_match.group(1), lineno)
    return refs, defs


def _validate_page(content: str) -> list[dict]:
    """Return the footnote issues in one page (file key added by the caller)."""
    refs, defs = _collect(content)
    issues: list[dict] = []

    for footnote_id, lineno in refs.items():
        if footnote_id not in defs:
            issues.append({
                "line": lineno,
                "severity": "error",
                "reason": (
                    f"footnote ref [^{footnote_id}] has no "
                    f"[^{footnote_id}]: definition line"
                ),
            })

    for footnote_id, def_lines in defs.items():
        if len(def_lines) > 1:
            issues.append({
                "line": def_lines[1],
                "severity": "error",
                "reason": (
                    f"footnote [^{footnote_id}] is defined {len(def_lines)} times "
                    f"(lines {', '.join(str(n) for n in def_lines)}); "
                    "only the first definition is rendered"
                ),
            })
        if footnote_id not in refs:
            issues.append({
                "line": def_lines[0],
                "severity": "warning",
                "reason": (
                    f"footnote definition [^{footnote_id}] is never "
                    "referenced in the body"
                ),
            })

    return sorted(issues, key=lambda i: (i["line"], i["reason"]))


def check_footnotes(root: Path, quiet: bool) -> dict:
    """Validate footnote refs/definitions of wiki pages (wiki/**/*.md).

    Errors: a ref without a definition, an id defined more than once.
    Warnings: a definition no ref points at.
    """
    wiki_dir = root / "wiki"
    empty = {
        "footnote_issues": [],
        "summary": {
            "wiki_pages_checked": 0,
            "footnote_errors": 0,
            "footnote_warnings": 0,
        },
    }
    if not wiki_dir.is_dir():
        return empty

    footnote_issues: list[dict] = []
    wiki_pages_checked = 0
    for md_file in sorted(wiki_dir.rglob("*.md")):
        if md_file.name == "index.md":
            continue
        if "_resources" in md_file.relative_to(root).parts:
            continue  # companion notes for converted attachments, not wiki pages
        wiki_pages_checked += 1
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(md_file.relative_to(root))
        for issue in _validate_page(content):
            footnote_issues.append({"file": rel, **issue})

    errors = sum(1 for i in footnote_issues if i["severity"] == "error")
    warnings = sum(1 for i in footnote_issues if i["severity"] == "warning")
    return {
        "footnote_issues": footnote_issues,
        "summary": {
            "wiki_pages_checked": wiki_pages_checked,
            "footnote_errors": errors,
            "footnote_warnings": warnings,
        },
    }
