"""Page-level provenance helpers for canonical Wiki pages (OKF v0.2).

Provenance lives in YAML frontmatter: a `sources` list, a `generated`
mapping, a `verified` list (newest entries appended), and an optional
`stale_after` date. Actors with a `human:` prefix are human-reviewed; all
other actors are machine actors. All dates use YYYY-MM-DD.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
import re
from typing import Any

from .frontmatter import FRONTMATTER_RE


PROVENANCE_KEYS = ("sources", "generated", "verified", "stale_after")

BLOCK_ID_RE = re.compile(r"(?<!\S)\^([A-Za-z0-9][A-Za-z0-9_-]*)\b")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAPPING_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
SOURCE_FOOTNOTE_REF_RE = re.compile(r"\[\^(s\d+)\]")
SOURCE_FOOTNOTE_DEF_RE = re.compile(r"^\[\^(s\d+)\]:\s*(.*)$")
INLINE_CODE_RE = re.compile(r"`[^`]*`")
WIKILINK_TARGET_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")


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


def has_error_issues(issues: list[dict[str, Any]] | None) -> bool:
    """True if any serialized issue is error-severity (warnings don't count)."""
    return any((issue.get("severity", "error") == "error") for issue in (issues or []))


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


def _parse_scalar(value: str) -> Any:
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


def _tokenize(text: str) -> list[tuple[int, str]]:
    tokens: list[tuple[int, str]] = []
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        tokens.append((len(raw) - len(raw.rstrip("\r").lstrip(" ")), raw.strip()))
    return tokens


def _parse_nested(tokens: list[tuple[int, str]], start: int, parent_indent: int) -> tuple[Any, int]:
    """Parse the value of a key whose content is nested below `parent_indent`."""
    if start >= len(tokens) or tokens[start][0] <= parent_indent:
        return None, start
    child_indent = tokens[start][0]
    if tokens[start][1].startswith("- ") or tokens[start][1] == "-":
        return _parse_list(tokens, start, child_indent)
    return _parse_mapping(tokens, start, child_indent)


def _parse_mapping(tokens: list[tuple[int, str]], start: int, indent: int) -> tuple[dict[str, Any], int]:
    data: dict[str, Any] = {}
    index = start
    while index < len(tokens):
        tok_indent, text = tokens[index]
        if tok_indent < indent:
            break
        if tok_indent > indent or text.startswith("- ") or ":" not in text:
            index += 1
            continue
        key, _, raw_value = text.partition(":")
        key = key.strip()
        raw_value = raw_value.strip()
        index += 1
        if raw_value:
            data[key] = _parse_scalar(raw_value)
        else:
            data[key], index = _parse_nested(tokens, index, indent)
    return data, index


def _parse_list(tokens: list[tuple[int, str]], start: int, indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    index = start
    while index < len(tokens):
        tok_indent, text = tokens[index]
        if tok_indent < indent or (tok_indent == indent and not (text.startswith("- ") or text == "-")):
            break
        if tok_indent > indent:
            index += 1
            continue
        rest = "" if text == "-" else text[2:].strip()
        key, _, raw_value = rest.partition(":")
        if ":" in rest and MAPPING_KEY_RE.match(key.strip()):
            item: dict[str, Any] = {key.strip(): _parse_scalar(raw_value.strip())}
            index += 1
            while (
                index < len(tokens)
                and tokens[index][0] > indent
                and not tokens[index][1].startswith("- ")
            ):
                cont = tokens[index][1]
                if ":" in cont:
                    cont_key, _, cont_value = cont.partition(":")
                    item[cont_key.strip()] = _parse_scalar(cont_value.strip())
                index += 1
            items.append(item)
        else:
            items.append(_parse_scalar(rest))
            index += 1
    return items, index


def parse_provenance(content: str) -> dict[str, Any] | None:
    """Parse page-level provenance from a Markdown page's YAML frontmatter.

    Returns ``{sources, generated, verified, stale_after}`` when at least one
    provenance key is present, else ``None``. This is a constrained parser for
    the project's own frontmatter shape, not a general YAML parser.
    """
    match = FRONTMATTER_RE.match(content)
    if not match:
        return None
    data, _ = _parse_mapping(_tokenize(match.group(1)), 0, 0)
    if not any(key in data for key in PROVENANCE_KEYS):
        return None
    return {
        "sources": data.get("sources") if isinstance(data.get("sources"), list) else (data.get("sources") or []),
        "generated": data.get("generated"),
        "verified": data.get("verified") if isinstance(data.get("verified"), list) else (data.get("verified") or []),
        "stale_after": data.get("stale_after"),
    }


def provenance_dates(provenance: dict[str, Any] | None) -> tuple[str | None, str | None]:
    """Return ``(generated_at, latest verified at)`` from parsed provenance."""
    if not provenance:
        return None, None
    generated = provenance.get("generated")
    generated_at = generated.get("at") if isinstance(generated, dict) else None
    if not (isinstance(generated_at, str) and DATE_RE.match(generated_at)):
        generated_at = None
    verified_dates = [
        entry.get("at")
        for entry in (provenance.get("verified") or [])
        if isinstance(entry, dict)
        and isinstance(entry.get("at"), str)
        and DATE_RE.match(entry["at"])
    ]
    return generated_at, max(verified_dates) if verified_dates else None


def _valid_date(value: Any) -> bool:
    return isinstance(value, str) and bool(DATE_RE.match(value))


def _validate_sources(sources: Any, path: str) -> list[ProvenanceIssue]:
    if not isinstance(sources, list):
        return [ProvenanceIssue(
            code="invalid-sources",
            message="Frontmatter sources must be a list.",
            path=path,
        )]
    issues: list[ProvenanceIssue] = []
    seen_ids: set[str] = set()
    for position, entry in enumerate(sources, start=1):
        if not isinstance(entry, dict):
            issues.append(ProvenanceIssue(
                code="invalid-source",
                message=f"Source {position} must be a mapping with id and resource.",
                path=path,
            ))
            continue
        source_id = entry.get("id")
        if not source_id:
            issues.append(ProvenanceIssue(
                code="missing-source-id",
                message=f"Source {position} has no id.",
                path=path,
            ))
        elif source_id in seen_ids:
            issues.append(ProvenanceIssue(
                code="duplicate-source-id",
                message=f"Source id '{source_id}' is used more than once.",
                path=path,
            ))
        else:
            seen_ids.add(source_id)
        if not entry.get("resource"):
            issues.append(ProvenanceIssue(
                code="missing-source-resource",
                message=f"Source {position} has no resource.",
                path=path,
            ))
        last_modified = entry.get("last_modified")
        if last_modified is not None and not _valid_date(last_modified):
            issues.append(ProvenanceIssue(
                code="invalid-date",
                message=f"last_modified for source {position} must use YYYY-MM-DD.",
                path=path,
            ))
    return issues


def _validate_actor_entry(entry: Any, label: str, path: str) -> list[ProvenanceIssue]:
    if not isinstance(entry, dict):
        return [ProvenanceIssue(
            code=f"invalid-{label}",
            message=f"{label} entry must be a mapping with by and at.",
            path=path,
        )]
    issues: list[ProvenanceIssue] = []
    if not entry.get("by"):
        issues.append(ProvenanceIssue(
            code=f"missing-{label}-by",
            message=f"{label} entry has no actor (by).",
            path=path,
        ))
    at = entry.get("at")
    if not at:
        issues.append(ProvenanceIssue(
            code=f"missing-{label}-at",
            message=f"{label} entry has no date (at).",
            path=path,
        ))
    elif not _valid_date(at):
        issues.append(ProvenanceIssue(
            code="invalid-date",
            message=f"at for {label} must use YYYY-MM-DD.",
            path=path,
        ))
    return issues


def _validate_footnotes(content: str, sources: Any, path: str) -> list[ProvenanceIssue]:
    """Cross-check `[^sN]` footnote refs/definitions against `sources[].id`."""
    id_to_resource: dict[str, Any] = {
        entry["id"]: entry.get("resource")
        for entry in (sources if isinstance(sources, list) else [])
        if isinstance(entry, dict) and entry.get("id")
    }
    match = FRONTMATTER_RE.match(content)
    body = content[match.end():] if match else content

    refs: set[str] = set()
    defs: dict[str, str] = {}
    for line in _non_fenced_lines(body):
        def_match = SOURCE_FOOTNOTE_DEF_RE.match(line)
        if def_match:
            defs.setdefault(def_match.group(1), def_match.group(2))
            continue
        for ref_match in SOURCE_FOOTNOTE_REF_RE.finditer(INLINE_CODE_RE.sub("", line)):
            refs.add(ref_match.group(1))

    issues: list[ProvenanceIssue] = []
    for source_id in sorted(refs | set(defs), key=lambda sid: int(sid[1:])):
        if source_id not in id_to_resource:
            issues.append(ProvenanceIssue(
                code="unknown-footnote-id",
                message=f"Footnote '{source_id}' has no matching sources[].id in frontmatter.",
                path=path,
            ))
            continue
        if source_id in refs and source_id not in defs:
            issues.append(ProvenanceIssue(
                code="undefined-footnote-ref",
                message=f"Footnote ref [^{source_id}] has no definition line.",
                path=path,
            ))
        if source_id in defs and source_id not in refs:
            issues.append(ProvenanceIssue(
                code="unreferenced-footnote-def",
                message=f"Footnote definition [^{source_id}] is never referenced in the body.",
                path=path,
                severity="warning",
            ))
        if source_id in defs:
            link_match = WIKILINK_TARGET_RE.search(defs[source_id])
            if link_match and link_match.group(1) != id_to_resource[source_id]:
                issues.append(ProvenanceIssue(
                    code="footnote-resource-mismatch",
                    message=(
                        f"Footnote definition [^{source_id}] links "
                        f"'{link_match.group(1)}' but frontmatter resource is "
                        f"'{id_to_resource[source_id]}'."
                    ),
                    path=path,
                ))
    return issues


def validate_provenance(content: str, path: str = "") -> list[ProvenanceIssue]:
    """Validate OKF v0.2 frontmatter provenance in a Markdown page.

    A page without any provenance fields yields no issues — coverage is
    reported separately.
    """
    issues: list[ProvenanceIssue] = []
    for block_id, count in extract_block_ids(content).items():
        if count > 1:
            issues.append(ProvenanceIssue(
                code="duplicate-block-id",
                message=f"Block ID '{block_id}' appears {count} times.",
                path=path,
                block_id=block_id,
            ))

    provenance = parse_provenance(content)
    if provenance is None:
        return issues

    issues.extend(_validate_sources(provenance["sources"], path))
    issues.extend(_validate_footnotes(content, provenance["sources"], path))

    generated = provenance["generated"]
    if generated is not None:
        issues.extend(_validate_actor_entry(generated, "generated", path))
        if isinstance(generated, dict) and not (
            isinstance(provenance["sources"], list) and provenance["sources"]
        ):
            issues.append(ProvenanceIssue(
                code="missing-sources",
                message="Page records generated provenance but lists no sources.",
                path=path,
                severity="warning",
            ))

    verified = provenance["verified"]
    if not isinstance(verified, list):
        issues.append(ProvenanceIssue(
            code="invalid-verified",
            message="Frontmatter verified must be a list.",
            path=path,
        ))
    else:
        for entry in verified:
            issues.extend(_validate_actor_entry(entry, "verified", path))

    stale_after = provenance["stale_after"]
    if stale_after is not None and not _valid_date(stale_after):
        issues.append(ProvenanceIssue(
            code="invalid-date",
            message="stale_after must use YYYY-MM-DD.",
            path=path,
        ))

    return issues
