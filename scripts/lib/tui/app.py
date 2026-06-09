"""Curses TUI for reviewing broken links, orphans, and stubs."""

import sys
from pathlib import Path

from ..paths import truncate_path
from . import actions
from .browser import show_file_browser
from .colors import (
    PAIR_BROKEN_LINK,
    PAIR_DELETED,
    PAIR_DELINKED,
    PAIR_FILENAME,
    PAIR_KEPT,
    PAIR_ORPHAN,
    PAIR_REPLACED,
    PAIR_SELECTED,
    PAIR_STUB,
    PAIR_BROKEN_MARKED,
    init_pairs,
)
from .help import show_help
from .keys import is_bare_escape
from .popups import show_popup
from .previews import show_preview
from .search import show_search_dialog


def run_interactive(broken_links: list, orphans: list, stubs: list, root: Path) -> None:
    """Curses-based TUI for reviewing broken links, orphan pages, and stub pages."""
    try:
        import curses
    except ImportError:
        print("Error: curses module not available on this platform.", file=sys.stderr)
        sys.exit(1)

    if not broken_links and not orphans and not stubs:
        print("No broken links, orphan pages, or stub pages found.")
        return

    for b in broken_links:
        b["_kind"] = "link"
    all_items = broken_links + \
                [{"_kind": "orphan", "file": o} for o in orphans] + \
                [{"_kind": "stub", "file": s} for s in stubs]
    n = len(all_items)
    states: list = [None] * n
    messages: list = [""] * n

    def _next_unhandled(start: int) -> "int | None":
        return next((i for i in range(start + 1, n) if states[i] is None), None)

    def curses_main(stdscr):
        curses.curs_set(0)
        init_pairs(curses)

        selected = 0
        offset = 0
        n_links = sum(1 for it in all_items if it["_kind"] == "link")
        n_orps = sum(1 for it in all_items if it["_kind"] == "orphan")
        n_stubs = sum(1 for it in all_items if it["_kind"] == "stub")

        def redraw():
            nonlocal offset
            stdscr.erase()
            height, width = stdscr.getmaxyx()
            list_height = height - 4

            header = f"Broken links: {n_links}   Orphans: {n_orps}   Stubs: {n_stubs}"
            stdscr.addstr(0, 0, header[:width - 1])

            sel_kind = all_items[selected]["_kind"] if n > 0 else "link"
            if sel_kind == "orphan":
                hint = "ENTER=preview   d=delete   k=keep as orphan   e=edit   h=help   q=quit"
            elif sel_kind == "stub":
                hint = "ENTER=preview   d=delete   k=acknowledge stub   e=edit   h=help   q=quit"
            else:
                hint = "ENTER=preview   d=delete   b=mark broken   p=plain text   n=navigate   s=search   e=edit   h=help   q=quit"
            stdscr.addstr(1, 0, hint[:width - 1])
            stdscr.addstr(2, 0, ("─" * (width - 1))[:width - 1])

            if selected < offset:
                offset = selected
            elif selected >= offset + list_height:
                offset = selected - list_height + 1

            # Fixed column layout: [prefix=7][num=3][gap=2][file_col][gap=2][link_col]
            avail = width - 1
            _fixed = 12   # prefix(7) + num(3) + gap(2)
            _remaining = max(20, avail - _fixed)
            _col_file_w = max(15, _remaining * 55 // 100)
            _col_link_w = max(10, _remaining - _col_file_w - 2)

            for row in range(list_height):
                idx = offset + row
                if idx >= n:
                    break
                item = all_items[idx]
                state = states[idx]
                is_orphan = item["_kind"] == "orphan"
                is_stub = item["_kind"] == "stub"
                if state == "deleted":
                    prefix = "[DELD] "; state_attr = curses.color_pair(PAIR_DELETED)
                elif state == "broken":
                    prefix = "[BRKN] "; state_attr = curses.color_pair(PAIR_BROKEN_MARKED)
                elif state == "replaced":
                    prefix = "[FIXD] "; state_attr = curses.color_pair(PAIR_REPLACED)
                elif state == "delinked":
                    prefix = "[TEXT] "; state_attr = curses.color_pair(PAIR_DELINKED)
                elif state == "kept":
                    prefix = "[KEEP] "; state_attr = curses.color_pair(PAIR_KEPT)
                elif is_orphan:
                    prefix = "[ORPH] "; state_attr = curses.color_pair(PAIR_ORPHAN)
                elif is_stub:
                    prefix = "[STUB] "; state_attr = curses.color_pair(PAIR_STUB)
                else:
                    prefix = "[LINK] "; state_attr = curses.color_pair(PAIR_BROKEN_LINK)
                y = 3 + row
                if idx == selected:
                    try:
                        if is_orphan or is_stub:
                            line = (prefix + f"{idx + 1:3d}  {item['file']}")[:avail]
                        else:
                            fp = truncate_path(item['file'], max_len=_col_file_w, prefix_len=_col_file_w // 2).ljust(_col_file_w)
                            line = (prefix + f"{idx + 1:3d}  {fp}  {item['target']}")[:avail]
                        stdscr.addstr(y, 0, line, curses.color_pair(PAIR_SELECTED) | curses.A_BOLD)
                    except curses.error:
                        pass
                    continue
                x = 0
                resolved = state is not None
                dim = curses.A_DIM
                if is_orphan or is_stub:
                    file_w = max(1, avail - _fixed)
                    segments = [
                        (prefix,                        state_attr),
                        (f"{idx + 1:3d}",               dim if resolved else curses.color_pair(PAIR_DELETED)),
                        ("  ",                          curses.A_NORMAL),
                        (item['file'][:file_w],         dim if resolved else curses.color_pair(PAIR_FILENAME) | curses.A_BOLD),
                    ]
                else:
                    fp = truncate_path(item['file'], max_len=_col_file_w, prefix_len=_col_file_w // 2).ljust(_col_file_w)
                    segments = [
                        (prefix,                                   state_attr),
                        (f"{idx + 1:3d}",                         dim if resolved else curses.color_pair(PAIR_DELETED)),
                        ("  ",                                     curses.A_NORMAL),
                        (fp,                                       dim if resolved else curses.color_pair(PAIR_FILENAME) | curses.A_BOLD),
                        ("  ",                                     curses.A_NORMAL),
                        (item['target'][:_col_link_w],            dim if resolved else curses.color_pair(PAIR_BROKEN_LINK) | curses.A_BOLD),
                    ]
                for text, attr in segments:
                    if x >= avail or not text:
                        continue
                    try:
                        stdscr.addstr(y, x, text[:avail - x], attr)
                    except curses.error:
                        pass
                    x += len(text)

            done = sum(1 for s in states if s is not None)
            status = messages[selected] if messages[selected] else ""
            footer = f"  {done}/{n} handled" + (f"  — {status}" if status else "")
            try:
                stdscr.addstr(height - 1, 0, footer[:width - 1])
            except curses.error:
                pass
            stdscr.refresh()

        while True:
            redraw()
            key = stdscr.getch()

            if key in (ord("q"), ord("Q")):
                break
            elif key == 27:
                if is_bare_escape(stdscr):
                    break
                continue  # consumed escape sequence (Option+Arrow, etc.)
            elif key in (ord("h"), ord("H")):
                show_help(stdscr)
            elif key == curses.KEY_UP:
                if selected > 0:
                    selected -= 1
            elif key == curses.KEY_DOWN:
                if selected < n - 1:
                    selected += 1
            elif key == curses.KEY_PPAGE:
                height, _ = stdscr.getmaxyx()
                page = max(1, height - 4 - 1)
                selected = max(0, selected - page)
            elif key == curses.KEY_NPAGE:
                height, _ = stdscr.getmaxyx()
                page = max(1, height - 4 - 1)
                selected = min(n - 1, selected + page)
            elif key in (10, 13):  # Enter — open popup for the selected item
                idx = selected
                while True:
                    redraw()
                    item = all_items[idx]
                    if item["_kind"] == "orphan":
                        action = show_preview(stdscr, item, idx, n, "orphan", root)
                        if action == "d":
                            res = actions.do_delete_file(item, root)
                            states[idx] = "deleted" if res == "deleted" else None
                            messages[idx] = "File deleted." if res == "deleted" else res
                        elif action == "k":
                            res = actions.do_keep_orphan(item, root)
                            states[idx] = "kept" if res in ("kept", "already kept") else None
                            messages[idx] = res
                        elif action == "e":
                            messages[idx] = actions.do_edit(item, root)
                        elif action == "next":
                            if idx < n - 1:
                                idx += 1; selected = idx
                            continue
                        elif action == "prev":
                            if idx > 0:
                                idx -= 1; selected = idx
                            continue
                    elif item["_kind"] == "stub":
                        action = show_preview(stdscr, item, idx, n, "stub", root)
                        if action == "d":
                            res = actions.do_delete_file(item, root)
                            states[idx] = "deleted" if res == "deleted" else None
                            messages[idx] = "File deleted." if res == "deleted" else res
                        elif action == "k":
                            res = actions.do_mark_stub_acknowledged(item, root)
                            states[idx] = "kept" if res == "marked as stub" else None
                            messages[idx] = "stub: true added." if res == "marked as stub" else res
                        elif action == "e":
                            messages[idx] = actions.do_edit(item, root)
                        elif action == "next":
                            if idx < n - 1:
                                idx += 1; selected = idx
                            continue
                        elif action == "prev":
                            if idx > 0:
                                idx -= 1; selected = idx
                            continue
                    else:
                        action = show_popup(stdscr, item, idx, n, root)
                        if action == "d":
                            res = actions.do_delete(item, root, broken_links)
                            states[idx] = "deleted" if res == "deleted" else None
                            messages[idx] = "Link removed." if res == "deleted" else res
                        elif action == "b":
                            res = actions.do_broken(item, root)
                            states[idx] = "broken" if res == "broken" else None
                            messages[idx] = "Marked [[broken-link|…]]." if res == "broken" else res
                        elif action == "r":
                            res = actions.do_delink(item, root)
                            states[idx] = "delinked" if res == "delinked" else None
                            messages[idx] = "Brackets removed (plain text)." if res == "delinked" else res
                        elif action == "n":
                            new_rel = show_file_browser(stdscr, root, item.get("target", ""))
                            if new_rel is not None:
                                res = actions.do_find_replace(idx, new_rel, root, broken_links, states, messages)
                                states[idx] = "replaced" if res == "replaced" else None
                                messages[idx] = f"→ {new_rel.stem}" if res == "replaced" else res
                        elif action == "s":
                            new_rel = show_search_dialog(stdscr, root, item.get("target", ""))
                            if new_rel is not None:
                                res = actions.do_find_replace(idx, new_rel, root, broken_links, states, messages)
                                states[idx] = "replaced" if res == "replaced" else None
                                messages[idx] = f"→ {new_rel.stem}" if res == "replaced" else res
                        elif action == "e":
                            messages[idx] = actions.do_edit(item, root)
                        elif action == "next":
                            if idx < n - 1:
                                idx += 1; selected = idx
                            continue
                        elif action == "prev":
                            if idx > 0:
                                idx -= 1; selected = idx
                            continue
                    if action in ("d", "b", "r", "k") or (action in ("n", "s") and states[idx] is not None):
                        next_idx = _next_unhandled(idx)
                        if next_idx is not None:
                            idx = next_idx; selected = idx
                            continue
                    selected = idx
                    break
            elif key in (ord("d"), ord("D")):
                if states[selected] is None:
                    item = all_items[selected]
                    if item["_kind"] in ("orphan", "stub"):
                        res = actions.do_delete_file(item, root)
                        states[selected] = "deleted" if res == "deleted" else None
                        messages[selected] = "File deleted." if res == "deleted" else res
                    else:
                        res = actions.do_delete(item, root, broken_links)
                        states[selected] = "deleted" if res == "deleted" else None
                        messages[selected] = "Link removed." if res == "deleted" else res
            elif key in (ord("k"), ord("K")):
                if states[selected] is None:
                    item = all_items[selected]
                    if item["_kind"] == "orphan":
                        res = actions.do_keep_orphan(item, root)
                        states[selected] = "kept" if res in ("kept", "already kept") else None
                        messages[selected] = res
                    elif item["_kind"] == "stub":
                        res = actions.do_mark_stub_acknowledged(item, root)
                        states[selected] = "kept" if res == "marked as stub" else None
                        messages[selected] = "stub: true added." if res == "marked as stub" else res
            elif key in (ord("b"), ord("B")):
                if states[selected] is None and all_items[selected]["_kind"] == "link":
                    res = actions.do_broken(all_items[selected], root)
                    states[selected] = "broken" if res == "broken" else None
                    messages[selected] = "Marked [[broken-link|…]]." if res == "broken" else res
                    if states[selected] is not None:
                        next_idx = _next_unhandled(selected)
                        if next_idx is not None:
                            selected = next_idx
            elif key in (ord("p"), ord("P")):
                if states[selected] is None and all_items[selected]["_kind"] == "link":
                    res = actions.do_delink(all_items[selected], root)
                    states[selected] = "delinked" if res == "delinked" else None
                    messages[selected] = "Brackets removed (plain text)." if res == "delinked" else res
                    if states[selected] is not None:
                        next_idx = _next_unhandled(selected)
                        if next_idx is not None:
                            selected = next_idx
            elif key in (ord("n"), ord("N")):
                if states[selected] is None and all_items[selected]["_kind"] == "link":
                    new_rel = show_file_browser(stdscr, root, all_items[selected].get("target", ""))
                    if new_rel is not None:
                        res = actions.do_find_replace(selected, new_rel, root, broken_links, states, messages)
                        states[selected] = "replaced" if res == "replaced" else None
                        messages[selected] = f"→ {new_rel.stem}" if res == "replaced" else res
                        if states[selected] is not None:
                            next_idx = _next_unhandled(selected)
                            if next_idx is not None:
                                selected = next_idx
            elif key in (ord("s"), ord("S")):
                if states[selected] is None and all_items[selected]["_kind"] == "link":
                    new_rel = show_search_dialog(stdscr, root, all_items[selected].get("target", ""))
                    if new_rel is not None:
                        res = actions.do_find_replace(selected, new_rel, root, broken_links, states, messages)
                        states[selected] = "replaced" if res == "replaced" else None
                        messages[selected] = f"→ {new_rel.stem}" if res == "replaced" else res
                        if states[selected] is not None:
                            next_idx = _next_unhandled(selected)
                            if next_idx is not None:
                                selected = next_idx
            elif key in (ord("e"), ord("E")):
                messages[selected] = actions.do_edit(all_items[selected], root)

    curses.wrapper(curses_main)

    deleted_links   = sum(1 for i, s in enumerate(states) if s == "deleted" and all_items[i]["_kind"] == "link")
    deleted_orphans = sum(1 for i, s in enumerate(states) if s == "deleted" and all_items[i]["_kind"] == "orphan")
    deleted_stubs   = sum(1 for i, s in enumerate(states) if s == "deleted" and all_items[i]["_kind"] == "stub")
    broken_count    = sum(1 for s in states if s == "broken")
    replaced_count  = sum(1 for s in states if s == "replaced")
    delinked_count  = sum(1 for s in states if s == "delinked")
    kept_orphans    = sum(1 for i, s in enumerate(states) if s == "kept" and all_items[i]["_kind"] == "orphan")
    kept_stubs      = sum(1 for i, s in enumerate(states) if s == "kept" and all_items[i]["_kind"] == "stub")
    skipped = n - sum(1 for s in states if s is not None)
    rows = [
        ("Links deleted",        deleted_links),
        ("Marked broken",        broken_count),
        ("Converted to text",    delinked_count),
        ("Replaced",             replaced_count),
        ("Orphan pages deleted", deleted_orphans),
        ("Orphans kept",         kept_orphans),
        ("Stub pages deleted",   deleted_stubs),
        ("Stubs resolved",       kept_stubs),
        ("Skipped",              skipped),
    ]
    label_w = max(len(label) for label, _ in rows)
    count_w = max(len(str(count)) for _, count in rows + [("Count", 0)])
    count_w = max(count_w, len("Count"))
    sep = f"+-{'-' * label_w}-+-{'-' * count_w}-+"
    print("\nSession complete")
    print(sep)
    print(f"| {'Action':<{label_w}} | {'Count':>{count_w}} |")
    print(sep)
    for label, count in rows:
        print(f"| {label:<{label_w}} | {count:>{count_w}} |")
    print(sep)
