"""Scrollable preview popup for orphan and stub pages.

Replaces the two near-identical `show_orphan_preview` / `show_stub_preview`
functions from the original script with one parametric `show_preview`.
"""

import curses
from pathlib import Path

from .help import show_help


_PREVIEW_PROFILE = {
    "orphan": {
        "title": "Orphan preview",
        "hint": "[ d=delete   k=keep as orphan   e=edit   ↑↓=prev/next   PgUp/PgDn=scroll   h=help   Enter/q=close ]",
    },
    "stub": {
        "title": "Stub preview",
        "hint": "[ d=delete   k=acknowledge as stub (add stub: true)   e=edit   ↑↓=prev/next   PgUp/PgDn=scroll   h=help   Enter/q=close ]",
    },
}


def show_preview(stdscr, entry: dict, idx: int, total: int, kind: str, root: Path) -> "str | None":
    """Show scrollable file contents for an orphan or stub. Returns one of:
    'd', 'k', 'e', 'prev', 'next', or None."""
    profile = _PREVIEW_PROFILE[kind]

    try:
        file_lines = (root / entry["file"]).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        file_lines = [f"(error reading file: {e})"]

    height, width = stdscr.getmaxyx()
    pop_w = min(max(40, width - 4), width - 2)
    pop_h = min(max(10, height - 4), height - 2)
    pop_y = max(0, (height - pop_h) // 2)
    pop_x = max(0, (width - pop_w) // 2)
    inner_w = pop_w - 4
    list_h = pop_h - 5

    win = curses.newwin(pop_h, pop_w, pop_y, pop_x)
    win.keypad(True)
    scroll = 0
    sep = "─" * (pop_w - 2)
    title = f" {profile['title']} {idx + 1}/{total} "
    hint = profile["hint"]

    while True:
        win.erase()
        win.box()
        try:
            win.addstr(0, max(1, (pop_w - len(title)) // 2), title)
            win.addstr(1, 2, entry["file"][:pop_w - 3])
            win.addstr(2, 1, sep[:pop_w - 2])
        except curses.error:
            pass
        for row in range(list_h):
            li = scroll + row
            if li >= len(file_lines):
                break
            try:
                win.addstr(3 + row, 2, file_lines[li][:inner_w])
            except curses.error:
                pass
        try:
            win.addstr(pop_h - 2, max(1, (pop_w - len(hint)) // 2), hint[:pop_w - 2])
        except curses.error:
            pass
        win.refresh()

        key = win.getch()
        if key in (10, 13, ord("q"), ord("Q"), 27):
            break
        elif key == curses.KEY_UP:
            del win; stdscr.touchwin(); stdscr.refresh()
            return "prev"
        elif key == curses.KEY_DOWN:
            del win; stdscr.touchwin(); stdscr.refresh()
            return "next"
        elif key == curses.KEY_PPAGE:
            scroll = max(0, scroll - list_h)
        elif key == curses.KEY_NPAGE:
            scroll = min(max(0, len(file_lines) - list_h), scroll + list_h)
        elif key in (ord("d"), ord("D")):
            del win; stdscr.touchwin(); stdscr.refresh()
            return "d"
        elif key in (ord("k"), ord("K")):
            del win; stdscr.touchwin(); stdscr.refresh()
            return "k"
        elif key in (ord("e"), ord("E")):
            del win; stdscr.touchwin(); stdscr.refresh()
            return "e"
        elif key in (ord("h"), ord("H")):
            show_help(stdscr)

    del win
    stdscr.touchwin()
    stdscr.refresh()
    return None
