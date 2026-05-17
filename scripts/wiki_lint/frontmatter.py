"""YAML-frontmatter has/add/remove helpers.

The original script had six near-identical functions for two keys (orphan,
stub); they are collapsed here into three generics plus thin wrappers.
"""

import re
from pathlib import Path


def _key_value_re(key: str, value: str) -> re.Pattern[str]:
    return re.compile(rf'\s*{re.escape(key)}\s*:\s*{re.escape(value)}\s*$')


def has_key(content: str, key: str, value: str) -> bool:
    """Return True if YAML frontmatter contains `key: value`."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    kv_re = _key_value_re(key, value)
    for line in lines[1:]:
        if line.strip() in ("---", "..."):
            break
        if kv_re.match(line):
            return True
    return False


def add_key(file_path: Path, key: str, value: str) -> bool:
    """Add `key: value` to the file's YAML frontmatter. Returns True if changed."""
    content = file_path.read_text(encoding="utf-8", errors="replace")
    if has_key(content, key, value):
        return False
    lines = content.splitlines(keepends=True)
    if lines and lines[0].strip() == "---":
        for i, line in enumerate(lines[1:], 1):
            if line.strip() in ("---", "..."):
                lines.insert(i, f"{key}: {value}\n")
                file_path.write_text(''.join(lines), encoding="utf-8")
                return True
        return False  # unclosed frontmatter
    file_path.write_text(f"---\n{key}: {value}\n---\n" + content, encoding="utf-8")
    return True


def remove_key(file_path: Path, key: str, value: str) -> bool:
    """Remove `key: value` from the file's YAML frontmatter. Returns True if changed."""
    content = file_path.read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return False
    fm_end = None
    for i, line in enumerate(lines[1:], 1):
        if line.strip() in ("---", "..."):
            fm_end = i
            break
    if fm_end is None:
        return False
    kv_re = _key_value_re(key, value)
    new_lines = [
        line for i, line in enumerate(lines)
        if not (0 < i < fm_end and kv_re.match(line.rstrip('\r\n')))
    ]
    if len(new_lines) < len(lines):
        file_path.write_text(''.join(new_lines), encoding="utf-8")
        return True
    return False


# Named wrappers — keep the original call-site names readable.

def has_orphan_false_in_frontmatter(content: str) -> bool:
    return has_key(content, "orphan", "false")


def add_orphan_false_to_frontmatter(file_path: Path) -> bool:
    return add_key(file_path, "orphan", "false")


def remove_orphan_false_from_frontmatter(file_path: Path) -> bool:
    return remove_key(file_path, "orphan", "false")


def has_stub_in_frontmatter(content: str) -> bool:
    return has_key(content, "stub", "true")


def add_stub_to_frontmatter(file_path: Path) -> bool:
    return add_key(file_path, "stub", "true")


def remove_stub_from_frontmatter(file_path: Path) -> bool:
    return remove_key(file_path, "stub", "true")
