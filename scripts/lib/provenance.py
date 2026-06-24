"""Block-level provenance helpers for canonical Wiki pages.

The durable format is intentionally small: Obsidian block IDs in the prose and
one page-level `> [!provenance]` callout containing `kb-prov-v1` metadata.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any


SCHEMA = "kb-prov-v1"
ALLOWED_STATUSES = {
    "current",
    "historical",
    "stale",
    "disputed",
    "superseded",
    "open",
    "unknown",
}
ALLOWED_CONFIDENCE = {"high", "medium", "low"}

BLOCK_ID_RE = re.compile(r"(?<!\S)\^([A-Za-z0-9][A-Za-z0-9_-]*)\b")
CALLOUT_RE = re.compile(r"^\s*>\s*\[!provenance\]", re.IGNORECASE)
TOP_LEVEL_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$")
BLOCK_RE = re.compile(r"^  ([A-Za-z0-9][A-Za-z0-9_-]*)\s*:\s*$")
FIELD_RE = re.compile(r"^    ([A-Za-z0-9_-]+)\s*:\s*(.*)$")
SOURCE_BOUNDARY_RE = re.compile(r"\s*[\"']?(?:raw/|wiki/|raw:|wiki:|qmd://|https?://|/|\./)")


@dataclass(frozen=True)
class ProvenanceIssue:
    code: str
    message: str
    path: str = ""
    block_id: str = ""
    severity: str = "error"

    def as_dict(self) -> dict[str, str]:
        out = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
        }
        if self.path:
            out["path"] = self.path
        if self.block_id:
            out["block_id"] = self.block_id
        return out


def _non_fenced_lines(content: str):
    in_fence = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if not in_fence:
            yield line


def extract_block_ids(content: str) -> dict[str, int]:
    """Return block-id occurrence counts, ignoring fenced code blocks."""
    counts: dict[str, int] = {}
    for line in _non_fenced_lines(content):
        for match in BLOCK_ID_RE.finditer(line):
            block_id = match.group(1)
            counts[block_id] = counts.get(block_id, 0) + 1
    return counts


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def _parse_value(value: str) -> Any:
    value = value.strip()
    if value.lower() in ("null", "none", "~"):
        return None
    if value == "[]":
        return []
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [
            _unquote(part.strip())
            for part in next(csv.reader([inner], skipinitialspace=True))
        ]
    return _unquote(value)


def _parse_sources_value(value: str) -> Any:
    value = value.strip()
    if not (value.startswith("[") and value.endswith("]")):
        return _parse_value(value)
    inner = value[1:-1].strip()
    if not inner:
        return []

    parts: list[str] = []
    start = 0
    quote: str | None = None
    for index, char in enumerate(inner):
        if char in ("'", '"') and (index == 0 or inner[index - 1] != "\\"):
            quote = None if quote == char else char if quote is None else quote
            continue
        if char == "," and quote is None and SOURCE_BOUNDARY_RE.match(inner[index + 1:]):
            parts.append(inner[start:index].strip())
            start = index + 1
    parts.append(inner[start:].strip())
    return [_unquote(part) for part in parts if part]


def _callout_payload_lines(content: str) -> list[str] | None:
    lines = content.splitlines()
    for index, line in enumerate(lines):
        if not CALLOUT_RE.match(line):
            continue
        payload: list[str] = []
        for candidate in lines[index + 1:]:
            if not candidate.lstrip().startswith(">"):
                break
            body = candidate.lstrip()[1:]
            if body.startswith(" "):
                body = body[1:]
            payload.append(body.rstrip())
        return payload
    return None


def parse_provenance_callout(content: str) -> dict[str, Any] | None:
    """Parse the first page-level provenance callout.

    This is a constrained parser for the project's own compact format, not a
    general YAML parser.
    """
    payload = _callout_payload_lines(content)
    if payload is None:
        return None

    data: dict[str, Any] = {}
    blocks: dict[str, dict[str, Any]] = {}
    in_blocks = False
    current_block: str | None = None

    for line in payload:
        if not line.strip():
            continue
        top_match = TOP_LEVEL_RE.match(line)
        if top_match and not line.startswith(" "):
            key, raw_value = top_match.groups()
            if key == "blocks" and raw_value.strip() == "":
                in_blocks = True
                data["blocks"] = blocks
                current_block = None
            else:
                data[key] = _parse_value(raw_value)
                in_blocks = False
                current_block = None
            continue

        if not in_blocks:
            continue

        block_match = BLOCK_RE.match(line)
        if block_match:
            current_block = block_match.group(1)
            blocks.setdefault(current_block, {})
            continue

        field_match = FIELD_RE.match(line)
        if field_match and current_block:
            key, raw_value = field_match.groups()
            if key == "sources":
                blocks[current_block][key] = _parse_sources_value(raw_value)
            else:
                blocks[current_block][key] = _parse_value(raw_value)

    if "blocks" not in data:
        data["blocks"] = blocks
    return data


def _date_value(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise ValueError("date must be a string")
    return datetime.strptime(value, "%Y-%m-%d")


def validate_provenance(content: str, path: str = "") -> list[ProvenanceIssue]:
    """Validate `kb-prov-v1` metadata embedded in a Markdown page."""
    issues: list[ProvenanceIssue] = []
    block_counts = extract_block_ids(content)
    for block_id, count in block_counts.items():
        if count > 1:
            issues.append(ProvenanceIssue(
                code="duplicate-block-id",
                message=f"Block ID '{block_id}' appears {count} times.",
                path=path,
                block_id=block_id,
            ))

    parsed = parse_provenance_callout(content)
    if parsed is None:
        return issues

    if parsed.get("schema") != SCHEMA:
        issues.append(ProvenanceIssue(
            code="invalid-schema",
            message=f"Expected schema '{SCHEMA}'.",
            path=path,
        ))

    blocks = parsed.get("blocks")
    if not isinstance(blocks, dict):
        return issues + [ProvenanceIssue(
            code="invalid-blocks",
            message="Provenance callout must contain a blocks mapping.",
            path=path,
        )]

    for block_id, metadata in blocks.items():
        if block_id not in block_counts:
            issues.append(ProvenanceIssue(
                code="missing-block-id",
                message=f"Provenance references '{block_id}', but no matching block ID exists.",
                path=path,
                block_id=block_id,
            ))
        if not isinstance(metadata, dict):
            issues.append(ProvenanceIssue(
                code="invalid-block",
                message=f"Provenance for '{block_id}' must be a mapping.",
                path=path,
                block_id=block_id,
            ))
            continue

        sources = metadata.get("sources")
        if sources is not None and not isinstance(sources, list):
            issues.append(ProvenanceIssue(
                code="invalid-sources",
                message=f"Sources for '{block_id}' must be a list.",
                path=path,
                block_id=block_id,
            ))

        status = metadata.get("status")
        if status is not None and status not in ALLOWED_STATUSES:
            issues.append(ProvenanceIssue(
                code="invalid-status",
                message=f"Status '{status}' is not allowed.",
                path=path,
                block_id=block_id,
            ))

        confidence = metadata.get("confidence")
        if confidence is not None and confidence not in ALLOWED_CONFIDENCE:
            issues.append(ProvenanceIssue(
                code="invalid-confidence",
                message=f"Confidence '{confidence}' is not allowed.",
                path=path,
                block_id=block_id,
            ))

        if status == "superseded" and not metadata.get("superseded_by"):
            issues.append(ProvenanceIssue(
                code="missing-superseded-by",
                message=f"Superseded block '{block_id}' must name superseded_by.",
                path=path,
                block_id=block_id,
            ))

        observed = checked = None
        for key in ("observed", "checked"):
            try:
                parsed_date = _date_value(metadata.get(key))
            except ValueError:
                issues.append(ProvenanceIssue(
                    code="invalid-date",
                    message=f"{key} for '{block_id}' must use YYYY-MM-DD.",
                    path=path,
                    block_id=block_id,
                ))
                continue
            if key == "observed":
                observed = parsed_date
            else:
                checked = parsed_date
        if observed and checked and observed > checked:
            issues.append(ProvenanceIssue(
                code="date-order",
                message=f"observed must not be later than checked for '{block_id}'.",
                path=path,
                block_id=block_id,
            ))

    return issues
