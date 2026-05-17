"""Regex search dialog for picking a replacement file."""

import curses
import re
from pathlib import Path

from .colors import PAIR_BROKEN_LINK


def show_search_dialog(stdscr, root: Path, broken_target: str = "") -> "Path | None":
    """Search for a replacement link by regex across filenames in raw/ and wiki/.
    Default search text is the stem of broken_target (filename only, no directories).
    Returns path relative to root, or None if cancelled."""
    search_text = Path(broken_target).name if broken_target else ""

    top_dirs = [root / name for name in ("wiki", "raw") if (root / name).is_dir()]
    all_files: list[Path] = []
    for td in top_dirs:
        for p in sorted(td.rglob("*")):
            if p.is_file() and not p.name.startswith("."):
                all_files.append(p.relative_to(root))

    def do_search(pattern: str) -> list[Path]:
        if not pattern:
            return []
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error:
            return []
        return [p for p in all_files if rx.search(p.name)]

    results: list[Path] = do_search(search_text)
    result_sel = 0

    height, width = stdscr.getmaxyx()
    pop_w = min(max(60, width - 6), width - 2)
    pop_h = min(max(13, height - 4), height - 2)
    pop_y = max(0, (height - pop_h) // 2)
    pop_x = max(0, (width - pop_w) // 2)

    win = curses.newwin(pop_h, pop_w, pop_y, pop_x)
    win.keypad(True)
    curses.curs_set(1)

    while True:
        if result_sel < 0:
            result_sel = 0
        if results and result_sel >= len(results):
            result_sel = len(results) - 1

        win.erase()
        win.box()
        title = " Search for link "
        try:
            win.addstr(0, max(1, (pop_w - len(title)) // 2), title)
        except curses.error:
            pass

        # Row 1: original broken link
        if broken_target:
            label = "broken: "
            try:
                win.addstr(1, 2, label, curses.A_DIM)
                win.addstr(1, 2 + len(label), broken_target[:pop_w - 4 - len(label)],
                           curses.color_pair(PAIR_BROKEN_LINK) | curses.A_BOLD)
            except curses.error:
                pass

        # Row 2: search input
        field_w = max(10, pop_w - 6)
        display_text = search_text[-field_w:] if len(search_text) > field_w else search_text
        try:
            win.addstr(2, 2, "> ")
            win.addstr(2, 4, display_text.ljust(field_w)[:field_w])
        except curses.error:
            pass

        # Row 3: nav hint
        nav = "type to filter   ↑↓ navigate results   Enter=select   Esc=cancel"
        try:
            win.addstr(3, max(1, (pop_w - len(nav)) // 2), nav[:pop_w - 2], curses.A_DIM)
        except curses.error:
            pass

        # Row 4: separator with match count
        n_res = len(results)
        if search_text:
            count_label = f" {n_res} match{'es' if n_res != 1 else ''} "
        else:
            count_label = " type to search "
        sep_fill = "─" * (pop_w - 2)
        mid = max(0, (pop_w - 2 - len(count_label)) // 2)
        sep_line = (sep_fill[:mid] + count_label + sep_fill)[:pop_w - 2]
        try:
            win.addstr(4, 1, sep_line)
        except curses.error:
            pass

        # Rows 5..pop_h-2: results
        list_h = pop_h - 6
        inner_w = pop_w - 4

        if not results:
            try:
                if not search_text:
                    msg = "Type to search..."
                else:
                    try:
                        re.compile(search_text)
                        msg = "No matches."
                    except re.error:
                        msg = "Invalid regex."
                win.addstr(5, 2, msg[:inner_w], curses.A_DIM)
            except curses.error:
                pass
        else:
            scroll = max(0, result_sel - list_h + 1) if result_sel >= list_h else 0
            for row in range(list_h):
                idx = scroll + row
                if idx >= len(results):
                    break
                rel = str(results[idx])
                attr = curses.A_REVERSE if idx == result_sel else curses.A_NORMAL
                try:
                    win.addstr(5 + row, 2, rel[:inner_w], attr)
                except curses.error:
                    pass

        # Position cursor at end of search input (row 2)
        cursor_x = min(4 + len(display_text), pop_w - 2)
        try:
            win.move(2, cursor_x)
        except curses.error:
            pass

        win.refresh()
        key = win.getch()

        if key == 27:  # Escape
            break
        elif key in (10, 13):  # Enter — select highlighted result
            if results and 0 <= result_sel < len(results):
                curses.curs_set(0)
                del win
                stdscr.touchwin()
                stdscr.refresh()
                return results[result_sel]
        elif key == curses.KEY_UP:
            if result_sel > 0:
                result_sel -= 1
        elif key == curses.KEY_DOWN:
            if results and result_sel < len(results) - 1:
                result_sel += 1
        elif key in (8, 127, curses.KEY_BACKSPACE):
            if search_text:
                search_text = search_text[:-1]
                results = do_search(search_text)
                result_sel = 0
        elif 32 <= key <= 126:  # printable ASCII — append to search
            search_text += chr(key)
            results = do_search(search_text)
            result_sel = 0

    curses.curs_set(0)
    del win
    stdscr.touchwin()
    stdscr.refresh()
    return None
