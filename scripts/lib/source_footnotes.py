"""Restore per-claim source footnotes from legacy provenance callouts.

The pre-OKF format attributed claims via Obsidian block anchors keyed into a
`kb-prov-v1` callout. The OKF v0.2 format attributes claims via markdown
footnotes keyed to `sources[].id` in the frontmatter. This module joins the
two: backup callout (`anchor -> resources`) + current frontmatter
(`resource -> id`) => `[^sN]` refs inserted before each anchor, plus a
footnote-definitions block at the end of the page.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re

from .frontmatter import FRONTMATTER_RE
from .legacy_callout import parse_provenance_callout
from .provenance import BLOCK_ID_RE, parse_provenance


SOURCE_ID_RE = re.compile(r"^s(\d+)$")
FOOTNOTE_REF_RE = re.compile(r"\[\^(s\d+)\]")
FOOTNOTE_DEF_RE = re.compile(r"^\[\^s\d+\]: ")


@dataclass(frozen=True)
class FootnoteOutcome:
    action: str  # "update" | "unchanged" | "no-provenance"
    content: str | None
    inserted_refs: int = 0
    added_sources: tuple[str, ...] = ()
    unmapped_anchors: tuple[str, ...] = ()
    stale_blocks: tuple[str, ...] = ()


def callout_block_sources(content: str) -> dict[str, list[str]]:
    """Map block anchor -> source resources from a legacy provenance callout."""
    parsed = parse_provenance_callout(content)
    if not parsed:
        return {}
    out: dict[str, list[str]] = {}
    for block_id, fields in (parsed.get("blocks") or {}).items():
        sources = fields.get("sources")
        if isinstance(sources, list):
            resources = [s for s in sources if isinstance(s, str) and s]
            if resources:
                out[block_id] = resources
    return out


def _resource_id_map(content: str) -> dict[str, str] | None:
    provenance = parse_provenance(content)
    if provenance is None:
        return None
    mapping: dict[str, str] = {}
    for entry in provenance["sources"]:
        if isinstance(entry, dict) and entry.get("id") and entry.get("resource"):
            mapping.setdefault(entry["resource"], entry["id"])
    return mapping


def _next_source_id(ids) -> int:
    highest = 0
    for source_id in ids:
        match = SOURCE_ID_RE.match(str(source_id))
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def _append_sources(content: str, resources: list[str], id_map: dict[str, str]) -> str:
    """Append missing source entries to the frontmatter, creating `sources:` if needed."""
    match = FRONTMATTER_RE.match(content)
    if not match:
        return content
    head = content[:match.end()].splitlines()
    next_number = _next_source_id(id_map.values())
    new_lines: list[str] = []
    for resource in resources:
        source_id = f"s{next_number}"
        next_number += 1
        id_map[resource] = source_id
        new_lines.append(f"  - id: {source_id}")
        new_lines.append(f"    resource: {json.dumps(resource, ensure_ascii=False)}")

    insert_at = None
    sources_at = next(
        (i for i, line in enumerate(head) if re.match(r"^sources\s*:", line)), None
    )
    if sources_at is not None:
        insert_at = sources_at + 1
        while insert_at < len(head) and head[insert_at].startswith("  "):
            insert_at += 1
    else:
        generated_at = next(
            (i for i, line in enumerate(head) if re.match(r"^generated\s*:", line)),
            len(head) - 1,  # before the closing --- delimiter
        )
        new_lines.insert(0, "sources:")
        insert_at = generated_at

    head[insert_at:insert_at] = new_lines
    return "\n".join(head) + "\n" + content[match.end():]


def _insert_refs(content: str, anchor_ids: dict[str, list[str]]) -> tuple[str, int, list[str]]:
    """Insert missing `[^sN]` refs before each mapped anchor. Returns unmapped anchors too."""
    match = FRONTMATTER_RE.match(content)
    offset = match.end() if match else 0
    head, body = content[:offset], content[offset:]

    inserted = 0
    seen_anchors: list[str] = []
    lines = body.splitlines()
    for index, line in enumerate(lines):
        if FOOTNOTE_DEF_RE.match(line):
            continue
        for anchor_match in BLOCK_ID_RE.finditer(line):
            anchor = anchor_match.group(1)
            seen_anchors.append(anchor)
            ids = anchor_ids.get(anchor)
            if not ids:
                continue
            missing = [sid for sid in ids if f"[^{sid}]" not in line]
            if not missing:
                continue
            refs = "".join(f"[^{sid}]" for sid in missing)
            line = re.sub(
                rf"(?<!\S)\^{re.escape(anchor)}\b",
                f"{refs} ^{anchor}",
                line,
                count=1,
            )
            inserted += len(missing)
        lines[index] = line

    body = "\n".join(lines) + ("\n" if body.endswith("\n") else "")
    unmapped = [a for a in seen_anchors if a not in anchor_ids]
    return head + body, inserted, unmapped


def _rebuild_definitions(content: str, id_to_resource: dict[str, str]) -> str:
    """Regenerate the `[^sN]: [[resource]]` definitions block at the end of the page."""
    lines = [line for line in content.splitlines() if not FOOTNOTE_DEF_RE.match(line)]
    while lines and not lines[-1].strip():
        lines.pop()
    referenced = sorted(
        {ref for line in lines for ref in FOOTNOTE_REF_RE.findall(line)},
        key=lambda sid: int(SOURCE_ID_RE.match(sid).group(1)),
    )
    definitions = [
        f"[^{sid}]: [[{id_to_resource[sid]}]]"
        for sid in referenced
        if sid in id_to_resource
    ]
    if definitions:
        lines.append("")
        lines.extend(definitions)
    return "\n".join(lines) + "\n"


def apply_footnotes(content: str, block_sources: dict[str, list[str]]) -> FootnoteOutcome:
    """Apply footnote refs and definitions for one page. Pure function, no I/O."""
    id_map = _resource_id_map(content)
    if id_map is None:
        return FootnoteOutcome(action="no-provenance", content=None)

    body_anchors = set()
    match = FRONTMATTER_RE.match(content)
    for line in content[match.end() if match else 0:].splitlines():
        for anchor_match in BLOCK_ID_RE.finditer(line):
            body_anchors.add(anchor_match.group(1))

    stale_blocks = tuple(a for a in block_sources if a not in body_anchors)
    live_blocks = {a: r for a, r in block_sources.items() if a in body_anchors}

    missing_resources: list[str] = []
    for resources in live_blocks.values():
        for resource in resources:
            if resource not in id_map and resource not in missing_resources:
                missing_resources.append(resource)
    if missing_resources:
        content = _append_sources(content, missing_resources, id_map)

    anchor_ids = {
        anchor: [id_map[r] for r in resources if r in id_map]
        for anchor, resources in live_blocks.items()
    }
    new_content, inserted, unmapped = _insert_refs(content, anchor_ids)
    new_content = _rebuild_definitions(
        new_content, {sid: resource for resource, sid in id_map.items()}
    )

    return FootnoteOutcome(
        action="update",
        content=new_content,
        inserted_refs=inserted,
        added_sources=tuple(missing_resources),
        unmapped_anchors=tuple(unmapped),
        stale_blocks=stale_blocks,
    )
