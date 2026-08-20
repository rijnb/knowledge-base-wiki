"""Validate YAML frontmatter of wiki pages: type/status vocabulary and remnants."""

from pathlib import Path

from ..frontmatter import FRONTMATTER_RE, split_frontmatter


ALLOWED_TYPES = {
    "competition",
    "concept",
    "conversation",
    "decision",
    "person",
    "problem",
    "project",
    "system",
}

ALLOWED_STATUS = {"draft", "stable", "deprecated"}

_LEGACY_PROVENANCE_MARKER = "kb-prov-v1"


def _validate_page(content: str) -> list[dict]:
    """Return the issues found in one page's content (file key added by caller)."""
    issues: list[dict] = []

    fm, _ = split_frontmatter(content)
    if not FRONTMATTER_RE.match(content):
        issues.append({
            "severity": "error",
            "reason": "missing or unparseable YAML frontmatter block",
        })
    else:
        page_type = fm.get("type", "")
        if not page_type:
            issues.append({
                "severity": "error",
                "reason": "missing or empty 'type:' field",
            })
        elif page_type not in ALLOWED_TYPES:
            issues.append({
                "severity": "error",
                "reason": (
                    f"unknown type '{page_type}' "
                    f"(allowed: {', '.join(sorted(ALLOWED_TYPES))})"
                ),
            })

        if "status" in fm and fm["status"] not in ALLOWED_STATUS:
            issues.append({
                "severity": "error",
                "reason": (
                    f"invalid status '{fm['status']}' "
                    f"(allowed: {', '.join(sorted(ALLOWED_STATUS))}; "
                    "old subject-state values belong in 'state:')"
                ),
            })

        if not fm.get("description"):
            issues.append({
                "severity": "warning",
                "reason": "missing 'description:' field",
            })

    if _LEGACY_PROVENANCE_MARKER in content:
        issues.append({
            "severity": "error",
            "reason": f"legacy provenance remnant '{_LEGACY_PROVENANCE_MARKER}' found",
        })

    return issues


def check_frontmatter(root: Path, quiet: bool) -> dict:
    """Validate frontmatter of wiki pages (wiki/**/*.md, excluding index.md).

    Errors: missing/unparseable frontmatter, missing or unknown 'type:',
    'status:' outside the OKF enum (draft|stable|deprecated), and any
    'kb-prov-v1' legacy provenance remnant. Warnings: missing 'description:'.
    """
    wiki_dir = root / "wiki"
    empty = {
        "frontmatter_issues": [],
        "summary": {
            "wiki_pages_checked": 0,
            "frontmatter_errors": 0,
            "frontmatter_warnings": 0,
        },
    }
    if not wiki_dir.is_dir():
        return empty

    frontmatter_issues: list[dict] = []
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
            frontmatter_issues.append({"file": rel, **issue})

    errors = sum(1 for i in frontmatter_issues if i["severity"] == "error")
    warnings = sum(1 for i in frontmatter_issues if i["severity"] == "warning")
    return {
        "frontmatter_issues": frontmatter_issues,
        "summary": {
            "wiki_pages_checked": wiki_pages_checked,
            "frontmatter_errors": errors,
            "frontmatter_warnings": warnings,
        },
    }
