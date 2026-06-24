"""Minimal provenance stamping for reviewed legacy Wiki pages."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import re
from pathlib import Path
from typing import Any

from .provenance import extract_block_ids, parse_provenance_callout


DEFAULT_BLOCK_ID = "freshness-status"
DEFAULT_CHECKED = date.today().isoformat()

MODE_TEXT = {
    "historical": (
        "This page has a minimal provenance stamp only. The listed evidence was "
        "used to judge freshness risk, not to verify every claim. Treat the "
        "existing content as a dated historical or source-specific snapshot "
        "until detailed block provenance is added."
    ),
    "source-specific": (
        "This page has a minimal provenance stamp only. The listed evidence was "
        "used to judge freshness risk, not to verify every claim. Treat the "
        "existing content as source-specific, not as a broad current-state "
        "claim, until detailed block provenance is added."
    ),
    "no-source-claim": (
        "This page has a minimal provenance stamp only. The automatic review "
        "did not use the related raw hit as evidence for page claims. Treat the "
        "existing content as legacy material until detailed block provenance is "
        "added."
    ),
    "source-mismatch": (
        "This page has a minimal provenance stamp only. Automatic review found "
        "that the related raw hit may be tangential or mismatched to the page's "
        "main claims. Treat the existing content as unverified until detailed "
        "block provenance is added."
    ),
    "needs-currentness-answer": (
        "This page has a minimal provenance stamp only. It contains current or "
        "recent claims that need an authoritative currentness answer before they "
        "are used as the main answer to present-state queries."
    ),
    "sensitive-review": (
        "This page has a minimal provenance stamp only. It may contain people, "
        "customer, commercial, privacy, security, or operational claims that "
        "need manual review before being used as current evidence."
    ),
    "manual-review": (
        "This page has a minimal provenance stamp only. It needs manual "
        "block-level curation before its detailed claims should be treated as "
        "verified canonical evidence."
    ),
}


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
    return mode if mode in MODE_TEXT else "historical"


def _unique_block_id(content: str, base: str = DEFAULT_BLOCK_ID) -> str:
    existing = extract_block_ids(content)
    if base not in existing:
        return base
    suffix = 2
    while f"{base}-{suffix}" in existing:
        suffix += 1
    return f"{base}-{suffix}"


def _quote_list(values: tuple[str, ...]) -> str:
    if not values:
        return "[]"
    return "[" + ", ".join(json.dumps(value, ensure_ascii=False) for value in values) + "]"


def _insert_after_title(content: str, section: str) -> str:
    lines = content.splitlines()
    start = 0
    if lines and lines[0].strip() == "---":
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() in {"---", "..."}:
                start = index + 1
                break

    title_index = None
    for index in range(start, len(lines)):
        if re.match(r"^#\s+\S", lines[index]):
            title_index = index
            break

    insert_at = start if title_index is None else title_index + 1
    section_lines = ["", *section.splitlines(), ""]
    new_lines = lines[:insert_at] + section_lines + lines[insert_at:]
    return "\n".join(new_lines).rstrip() + "\n"


def _callout(spec: StampSpec, block_id: str, checked: str) -> str:
    lines = [
        "> [!provenance]- Provenance",
        "> schema: kb-prov-v1",
        "> migration_status: legacy-inferred-minimal",
        "> blocks:",
        f">   {block_id}:",
        f">     sources: {_quote_list(spec.sources)}",
        f">     checked: {checked}",
        ">     status: current",
        ">     confidence: medium",
        ">     provenance_quality: minimal-risk-stamp",
        ">     scope: page-level caution only; detailed claims not yet block-mapped",
        f">     review_mode: {_safe_mode(spec.mode)}",
    ]
    if spec.latest_related_raw_date:
        lines.append(f">     evidence_latest: {spec.latest_related_raw_date}")
    if spec.reason:
        lines.append(f">     review_note: {spec.reason}")
    return "\n".join(lines)


def stamp_content(content: str, spec: StampSpec, checked: str = DEFAULT_CHECKED) -> tuple[str, str]:
    """Return stamped content and block id, or raise ValueError if unsafe."""
    if parse_provenance_callout(content) is not None:
        raise ValueError("page already has provenance")
    mode = _safe_mode(spec.mode)
    block_id = _unique_block_id(content)
    status_text = MODE_TEXT[mode]
    section = f"## Freshness Status\n\n{status_text} ^{block_id}"
    stamped = _insert_after_title(content, section)
    stamped = stamped.rstrip() + "\n\n" + _callout(spec, block_id, checked) + "\n"
    return stamped, block_id


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
        stamped, block_id = stamp_content(content, spec, checked)
    except ValueError as error:
        return {"page": spec.page, "action": "skipped", "reason": str(error)}
    if not dry_run:
        page_path.write_text(stamped, encoding="utf-8")
    return {
        "page": spec.page,
        "action": "would-stamp" if dry_run else "stamped",
        "block_id": block_id,
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
