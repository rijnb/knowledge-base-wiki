"""Regex search dialog for picking a replacement file."""

import curses
import re
from pathlib import Path

from ..resolve import _PROBLEMATIC_CHARS
from .colors import PAIR_BROKEN_LINK
from .keys import read_alt_sequence


def _word_left(text: str, pos: int) -> int:
    """Return cursor position after jumping one word to the left."""
    i = pos
    while i > 0 and not text[i - 1].isalnum():
        i -= 1
    while i > 0 and text[i - 1].isalnum():
        i -= 1
    return i


def _word_right(text: str, pos: int) -> int:
    """Return cursor position after jumping one word to the right."""
    n = len(text)
    i = pos
    while i < n and not text[i].isalnum():
        i += 1
    while i < n and text[i].isalnum():
        i += 1
    return i


def show_search_dialog(stdscr, root: Path, broken_target: str = "") -> "Path | None":
    """Search for a replacement link by regex across filenames in raw/ and wiki/.
    Default search text is the stem of broken_target (filename only, no directories).
    Returns path relative to root, or None if cancelled."""
    if broken_target:
        # Replace filesystem-problematic chars with '.' (regex wildcard, since they
        # may have been substituted on disk), and regex-escape everything else so
        # parens/dots/etc. in the filename match literally. Space and hyphen pass
        # through verbatim — they have no special meaning at the top level and
        # escaping them just makes the prefilled pattern harder to read/edit.
        _PASSTHROUGH = {" ", "-"}
        search_text = "".join(
            "." if _PROBLEMATIC_CHARS.match(ch)
            else ch if ch in _PASSTHROUGH
            else re.escape(ch)
            for ch in Path(broken_target).name
        )
    else:
        search_text = ""
    cursor_pos = len(search_text)

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

        # Row 2: search input — scroll so cursor stays visible
        field_w = max(10, pop_w - 6)
        if cursor_pos < 0:
            cursor_pos = 0
        if cursor_pos > len(search_text):
            cursor_pos = len(search_text)
        if len(search_text) <= field_w:
            view_start = 0
        else:
            view_start = max(0, cursor_pos - field_w + 1)
            if view_start + field_w > len(search_text) and cursor_pos < len(search_text):
                view_start = max(0, len(search_text) - field_w)
        display_text = search_text[view_start:view_start + field_w]
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

        # Position cursor in search input (row 2)
        cursor_x = min(4 + (cursor_pos - view_start), pop_w - 2)
        try:
            win.move(2, cursor_x)
        except curses.error:
            pass

        win.refresh()
        key = win.getch()

        if key == 27:  # Escape — may also start an Alt/Option sequence
            alt = read_alt_sequence(win)
            if alt is None:
                break
            action = alt[0]
            if action == 'left':
                cursor_pos = _word_left(search_text, cursor_pos)
            elif action == 'right':
                cursor_pos = _word_right(search_text, cursor_pos)
            elif action == 'home':
                cursor_pos = 0
            elif action == 'end':
                cursor_pos = len(search_text)
            # 'unknown' — swallow the sequence, do nothing
            continue
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
        elif key == curses.KEY_LEFT:
            if cursor_pos > 0:
                cursor_pos -= 1
        elif key == curses.KEY_RIGHT:
            if cursor_pos < len(search_text):
                cursor_pos += 1
        elif key in (curses.KEY_HOME, 1):  # Home or Ctrl-A
            cursor_pos = 0
        elif key in (curses.KEY_END, 5):  # End or Ctrl-E
            cursor_pos = len(search_text)
        elif key in (8, 127, curses.KEY_BACKSPACE):
            if cursor_pos > 0:
                search_text = search_text[:cursor_pos - 1] + search_text[cursor_pos:]
                cursor_pos -= 1
                results = do_search(search_text)
                result_sel = 0
        elif key in (curses.KEY_DC, 4):  # Delete or Ctrl-D
            if cursor_pos < len(search_text):
                search_text = search_text[:cursor_pos] + search_text[cursor_pos + 1:]
                results = do_search(search_text)
                result_sel = 0
        elif 32 <= key <= 126:  # printable ASCII — insert at cursor
            search_text = search_text[:cursor_pos] + chr(key) + search_text[cursor_pos:]
            cursor_pos += 1
            results = do_search(search_text)
            result_sel = 0

    curses.curs_set(0)
    del win
    stdscr.touchwin()
    stdscr.refresh()
    return None
