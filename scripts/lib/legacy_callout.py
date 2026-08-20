"""Parser for legacy `kb-prov-v1` provenance callouts.

Vendored from the pre-OKF `scripts/lib/provenance.py` (see the
`tomtom-pre-okf-*` vault backup). The live vault no longer carries these
callouts; this parser exists to read them out of backup snapshots when
restoring per-claim source footnotes.
"""

from __future__ import annotations

import csv
import re
from typing import Any


SCHEMA = "kb-prov-v1"

CALLOUT_RE = re.compile(r"^\s*>\s*\[!provenance\]", re.IGNORECASE)
TOP_LEVEL_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$")
BLOCK_RE = re.compile(r"^  ([A-Za-z0-9][A-Za-z0-9_-]*)\s*:\s*$")
FLOW_BLOCK_RE = re.compile(r"^  ([A-Za-z0-9][A-Za-z0-9_-]*)\s*:\s*\{(.*)\}\s*$")
FLOW_SOURCES_RE = re.compile(r"sources\s*:\s*(\[[^\]]*\])")
FLOW_FIELD_RE = re.compile(r"([A-Za-z0-9_-]+)\s*:\s*([^,{}\[\]]+)")
FIELD_RE = re.compile(r"^    ([A-Za-z0-9_-]+)\s*:\s*(.*)$")
# A source reference starts with a scheme (`raw:`, `slack:`, `https:`, …), a
# path segment (`raw/notes/…`), an absolute path, or `./`. Used to decide
# whether an unquoted comma separates two sources or sits inside one value.
SOURCE_BOUNDARY_RE = re.compile(
    r"""\s*["']?(?:[A-Za-z][A-Za-z0-9+.-]*:|[A-Za-z0-9._-]+/|/|\./)"""
)


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


def _looks_like_source(value: str) -> bool:
    return bool(SOURCE_BOUNDARY_RE.match(value))


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
        if char == "," and quote is None:
            # A comma separates two sources unless it sits inside an unquoted,
            # recognized source value (e.g. a comma in a filename) and the next
            # token does not itself start a new source. A fully quoted current
            # value is always complete — split unconditionally, so bare quoted
            # filenames like "README.md" never merge into their predecessor.
            current = inner[start:index]
            following = inner[index + 1:]
            stripped = current.strip()
            fully_quoted = (
                len(stripped) >= 2
                and stripped[0] == stripped[-1]
                and stripped[0] in ("'", '"')
            )
            if not fully_quoted and _looks_like_source(current) and not _looks_like_source(following):
                continue
            parts.append(current.strip())
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

        flow_match = FLOW_BLOCK_RE.match(line)
        if flow_match:
            block_id, inner = flow_match.groups()
            fields: dict[str, Any] = {}
            sources_match = FLOW_SOURCES_RE.search(inner)
            if sources_match:
                fields["sources"] = _parse_sources_value(sources_match.group(1))
                inner = inner.replace(sources_match.group(0), "")
            for key, raw_value in FLOW_FIELD_RE.findall(inner):
                fields[key] = _parse_value(raw_value)
            blocks[block_id] = fields
            current_block = None
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
