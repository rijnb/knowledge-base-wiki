"""Stateless action handlers used by the TUI key loop.

Each function performs one user action against a single broken-link entry,
orphan, or stub. They return a short status string for display in the footer.
"""

import os
import subprocess
from pathlib import Path

from ..frontmatter import (
    add_orphan_false_to_frontmatter,
    add_stub_to_frontmatter,
)
from ..links import is_external
from ..rewrite import (
    delete_mdlink_in_file,
    delete_wikilink_in_file,
    delink_mdlink_in_file,
    delink_wikilink_in_file,
    fix_wikilinks_in_file,
    mark_as_broken_link_in_file,
    replace_mdlink_target_in_file,
)


def is_wikilink_entry(entry: dict) -> bool:
    return entry["type"] == "wikilink" or (entry["type"] == "image" and "[[" in entry["raw"])


def is_embed_entry(entry: dict) -> bool:
    """True for Obsidian image embeds written in wikilink form (![[...]])."""
    return entry["type"] == "image" and "[[" in entry["raw"]


def is_md_image_entry(entry: dict) -> bool:
    """True for standard markdown image embeds (![alt](url))."""
    return entry["type"] == "image" and "[[" not in entry["raw"]


def do_delete(entry: dict, root: Path, broken_links: list) -> str:
    """Delete a broken link from its source file; renumber sibling entries."""
    try:
        if is_wikilink_entry(entry):
            ok, removed = delete_wikilink_in_file(root / entry["file"], entry["target"], embed=is_embed_entry(entry))
        else:
            ok, removed = delete_mdlink_in_file(root / entry["file"], entry["target"], embed=is_md_image_entry(entry))
        if ok and removed:
            # Adjust line numbers for all entries in the same file that came
            # after any deleted line, so the popup context stays accurate.
            for other in broken_links:
                if other["file"] != entry["file"]:
                    continue
                shift = sum(1 for dl in removed if dl < other["line"])
                if shift:
                    other["line"] -= shift
        return "deleted" if ok else "no match — may already be handled"
    except Exception as e:
        return f"error: {e}"


def do_broken(entry: dict, root: Path) -> str:
    try:
        ok = mark_as_broken_link_in_file(root / entry["file"], entry["target"], embed=is_embed_entry(entry))
        return "broken" if ok else "no match — may already be handled"
    except Exception as e:
        return f"error: {e}"


def do_delink(entry: dict, root: Path) -> str:
    if is_external(entry["target"]):
        return "external link — cannot delink"
    try:
        if is_wikilink_entry(entry):
            n = delink_wikilink_in_file(root / entry["file"], entry["target"], embed=is_embed_entry(entry))
        else:
            n = delink_mdlink_in_file(root / entry["file"], entry["target"], embed=is_md_image_entry(entry))
        return "delinked" if n else "no match — may already be handled"
    except Exception as e:
        return f"error: {e}"


def do_delete_file(entry: dict, root: Path) -> str:
    try:
        (root / entry["file"]).unlink()
        return "deleted"
    except Exception as e:
        return f"error: {e}"


def do_keep_orphan(entry: dict, root: Path) -> str:
    try:
        changed = add_orphan_false_to_frontmatter(root / entry["file"])
        return "kept" if changed else "already kept"
    except Exception as e:
        return f"error: {e}"


def do_mark_stub_acknowledged(entry: dict, root: Path) -> str:
    try:
        changed = add_stub_to_frontmatter(root / entry["file"])
        return "marked as stub" if changed else "already marked as stub"
    except Exception as e:
        return f"error: {e}"


def do_edit(entry: dict, root: Path) -> str:
    try:
        subprocess.Popen(["open", str(root / entry["file"])])
        return "opened in editor"
    except Exception as e:
        return f"error: {e}"


def do_find_replace(idx: int, new_rel: Path, root: Path, broken_links: list,
                    states: list, messages: list) -> str:
    """Replace the broken link at index idx with a link to new_rel (relative to root).
    Side-effect: also resolves any other entries with the same file+target."""
    entry = broken_links[idx]
    old_target = entry["target"]
    old_file = entry["file"]
    old_raw = entry.get("raw", "")
    is_wiki = is_wikilink_entry(entry)
    try:
        if is_wiki:
            # Strip the .md suffix only when the stem has no second extension
            # (e.g. foo.md → foo, but xxx.png.md → xxx.png.md, image.png → image.png).
            if new_rel.suffix == ".md" and "." not in new_rel.stem:
                new_target = str(new_rel.with_suffix(""))
            else:
                new_target = str(new_rel)
            count = fix_wikilinks_in_file(root / entry["file"], [(old_target, new_target)], embed=is_embed_entry(entry))
        else:
            source_dir = (root / entry["file"]).parent
            new_target = os.path.relpath(root / new_rel, source_dir)
            count = replace_mdlink_target_in_file(root / entry["file"], old_target, new_target, embed=is_md_image_entry(entry))
        if count:
            entry["target"] = new_target
            # fix_wikilinks_in_file replaces all occurrences in the file at once.
            # Only remap sibling entries that share the *exact same raw text* — otherwise
            # entries that look the same by file+target but carry distinct #heading/|alias
            # context would silently lose that context.
            for j, other in enumerate(broken_links):
                if (
                    j != idx
                    and states[j] is None
                    and other["file"] == old_file
                    and other["target"] == old_target
                    and other.get("raw", "") == old_raw
                ):
                    other["target"] = new_target
                    states[j] = "replaced"
                    messages[j] = f"→ {new_rel.stem}"
            return "replaced"
        return "no match — may already be changed"
    except Exception as e:
        return f"error: {e}"
