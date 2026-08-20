"""Minimal frontmatter provenance stamping for reviewed legacy Wiki pages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import re
from pathlib import Path
from typing import Any

from .frontmatter import FRONTMATTER_RE


DEFAULT_CHECKED = date.today().isoformat()
GENERATED_BY = "agent:wiki-ingest"
VERIFIED_BY = "agent:wiki-freshness"

MODES = {
    "historical",
    "source-specific",
    "no-source-claim",
    "source-mismatch",
    "needs-currentness-answer",
    "sensitive-review",
    "manual-review",
}

_PROVENANCE_KEY_RE = re.compile(r"^(?:sources|generated)\s*:", re.MULTILINE)


@dataclass(frozen=True)
class StampSpec:
    page: str
    mode: str = "historical"
    reason: str = ""
    sources: tuple[str, ...] = ()
    latest_related_raw_date: str | None = None


def load_stamp_specs(path: Path) -> list[StampSpec]:
    """Load stamp specs from a JSON manifest."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        raw_specs = payload
    elif isinstance(payload, dict):
        raw_specs = payload.get("auto_ok", [])
    else:
        raw_specs = []
    specs: list[StampSpec] = []
    for item in raw_specs:
        if not isinstance(item, dict) or not item.get("page"):
            continue
        specs.append(StampSpec(
            page=item["page"],
            mode=item.get("stamp_mode") or item.get("mode") or "historical",
            reason=item.get("reason", ""),
            sources=tuple(item.get("sources") or item.get("related_raw") or ()),
            latest_related_raw_date=item.get("latest_related_raw_date"),
        ))
    return specs


def _safe_mode(mode: str) -> str:
    return mode if mode in MODES else "historical"


def _provenance_lines(spec: StampSpec, checked: str, verified: bool) -> list[str]:
    lines: list[str] = []
    if spec.sources:
        lines.append("sources:")
        for index, resource in enumerate(spec.sources, start=1):
            lines.append(f"  - id: s{index}")
            lines.append(f"    resource: {json.dumps(resource, ensure_ascii=False)}")
    lines.append("generated:")
    lines.append(f'  by: "{GENERATED_BY}"')
    lines.append(f"  at: {checked}")
    if verified:
        lines.append("verified:")
        lines.append(f'  - by: "{VERIFIED_BY}"')
        lines.append(f"    at: {checked}")
    return lines


def stamp_content(
    content: str,
    spec: StampSpec,
    checked: str = DEFAULT_CHECKED,
    verified: bool = False,
) -> str:
    """Return content with frontmatter provenance, or raise ValueError if unsafe."""
    match = FRONTMATTER_RE.match(content)
    if match and _PROVENANCE_KEY_RE.search(match.group(1)):
        raise ValueError("page already has provenance")
    lines = _provenance_lines(spec, checked, verified)
    if match:
        head = content[:match.end()].splitlines()
        # Insert before the closing frontmatter delimiter.
        head = head[:-1] + lines + [head[-1]]
        return "\n".join(head) + "\n" + content[match.end():]
    return "---\n" + "\n".join(lines) + "\n---\n" + content


def stamp_page(root: Path, spec: StampSpec, checked: str = DEFAULT_CHECKED, dry_run: bool = False) -> dict[str, Any]:
    """Apply one minimal stamp, returning a structured result."""
    try:
        page_path = (root / spec.page).resolve()
        page_path.relative_to((root / "wiki").resolve())
    except ValueError:
        return {
            "page": spec.page,
            "action": "skipped",
            "reason": "invalid-path",
        }
    if not page_path.is_file():
        return {"page": spec.page, "action": "missing"}
    content = page_path.read_text(encoding="utf-8", errors="replace")
    try:
        stamped = stamp_content(content, spec, checked)
    except ValueError as error:
        return {"page": spec.page, "action": "skipped", "reason": str(error)}
    if not dry_run:
        page_path.write_text(stamped, encoding="utf-8")
    return {
        "page": spec.page,
        "action": "would-stamp" if dry_run else "stamped",
        "mode": _safe_mode(spec.mode),
    }


def stamp_pages(root: Path, specs: list[StampSpec], checked: str = DEFAULT_CHECKED, dry_run: bool = False) -> dict[str, Any]:
    """Apply minimal stamps to a batch of low-risk pages."""
    results = [stamp_page(root, spec, checked=checked, dry_run=dry_run) for spec in specs]
    summary: dict[str, int] = {}
    for result in results:
        action = result["action"]
        summary[action] = summary.get(action, 0) + 1
    return {"summary": summary, "results": results}
