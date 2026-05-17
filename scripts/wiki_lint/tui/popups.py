"""Broken-link detail popup with source-context highlighting."""

import curses
from pathlib import Path

from .colors import PAIR_BROKEN_LINK
from .help import show_help


def read_source_context(entry: dict, root: Path, context: int = 2) -> list:
    """Return list of (lineno, text, is_current) for the line and `context` lines around it."""
    try:
        fp = root / entry["file"]
        lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
        current = entry["line"] - 1  # 0-indexed
        start = max(0, current - context)
        end = min(len(lines), current + context + 1)
        return [(i + 1, lines[i], i == current) for i in range(start, end)]
    except Exception as e:
        return [(entry["line"], f"(error reading file: {e})", True)]


def show_popup(stdscr, entry: dict, idx: int, total: int, root: Path) -> "str | None":
    """Draw a wide popup with source context and missing link; close on Enter.
    Returns the action key the user pressed ('prev', 'next', 'd', 'b', 'r', 'n', 's', 'e') or None."""
    context_lines = read_source_context(entry, root)
    missing = entry["target"]

    height, width = stdscr.getmaxyx()
    pop_w = min(max(40, width - 4), width - 2)
    inner_w = pop_w - 4

    def _wrap(lineno, text):
        """Yield (display_str, char_start, char_end, text_offset) per wrapped row."""
        prefix = f"{lineno:4d}  "
        prefix_len = len(prefix)
        text_w = max(1, inner_w - prefix_len)
        indent = " " * prefix_len
        if not text:
            yield (prefix, 0, 0, prefix_len)
            return
        for i in range(0, len(text), text_w):
            chunk = text[i:i + text_w]
            yield ((prefix if i == 0 else indent) + chunk, i, i + len(chunk), prefix_len)

    # Find the link's char span in the source line before wrapping.
    # Use raw_link to locate the link, then narrow to just tgt within it
    # so that surrounding syntax (e.g. [[ ]]) is not highlighted.
    raw_link = entry.get("raw", "")
    tgt = entry.get("target", "")
    link_start = link_end = -1
    for _, src_text, is_cur in context_lines:
        if is_cur:
            if raw_link:
                raw_pos = src_text.find(raw_link)
                if raw_pos != -1:
                    tgt_off = raw_link.find(tgt) if tgt else -1
                    if tgt_off != -1:
                        link_start = raw_pos + tgt_off
                        link_end = link_start + len(tgt)
                    else:
                        link_start = raw_pos
                        link_end = raw_pos + len(raw_link)
            if link_start == -1 and tgt:
                pos = src_text.find(tgt)
                if pos != -1:
                    link_start = pos
                    link_end = pos + len(tgt)
            break

    # Pre-wrap all context lines so pop_h reflects actual row count
    display_rows: list[tuple[str, bool, int, int, int]] = []
    for lineno, text, is_current in context_lines:
        for disp, cstart, cend, toff in _wrap(lineno, text):
            display_rows.append((disp, is_current, cstart, cend, toff))

    # Layout: 4 header rows + content rows + sep + missing + hint + border = +4 fixed footer
    pop_h = min(4 + len(display_rows) + 4, height - 2)
    pop_y = max(0, (height - pop_h) // 2)
    pop_x = max(0, (width - pop_w) // 2)

    sep = "─" * (pop_w - 2)
    hint = "[ ↑/↓ prev/next   d=delete   b=mark broken   p=plain text   n=navigate   s=search   e=edit   h=help   Enter/q=close ]"

    win = curses.newwin(pop_h, pop_w, pop_y, pop_x)
    win.keypad(True)
    win.box()
    title = f" Broken link detail {idx + 1}/{total} "
    win.addstr(0, (pop_w - len(title)) // 2, title)
    win.addstr(1, 2, f"file: {entry['file']}"[:pop_w - 3])
    win.addstr(2, 2, f"line: {entry['line']}"[:pop_w - 3])
    win.addstr(3, 1, sep[:pop_w - 2])
    max_content_rows = max(0, pop_h - 8)
    hl_attr = curses.color_pair(PAIR_BROKEN_LINK) | curses.A_BOLD
    for i, (display, is_current, cstart, cend, toff) in enumerate(display_rows[:max_content_rows]):
        base_attr = curses.A_NORMAL if is_current else curses.A_DIM
        text = display[:pop_w - 3]
        try:
            if is_current and link_start != -1 and cstart < link_end and cend > link_start:
                # Map source-text char offsets to display positions for this row
                row_hl_s = max(0, link_start - cstart)
                row_hl_e = min(cend - cstart, link_end - cstart)
                d_s = min(toff + row_hl_s, len(text))
                d_e = min(toff + row_hl_e, len(text))
                if d_s > 0:
                    win.addstr(4 + i, 2, text[:d_s], base_attr)
                if d_s < d_e:
                    win.addstr(4 + i, 2 + d_s, text[d_s:d_e], hl_attr)
                if d_e < len(text):
                    win.addstr(4 + i, 2 + d_e, text[d_e:], base_attr)
            else:
                win.addstr(4 + i, 2, text, base_attr)
        except curses.error:
            pass
    sep_row = 4 + min(len(display_rows), max_content_rows)
    try:
        win.addstr(sep_row, 1, sep[:pop_w - 2])
        win.addstr(sep_row + 1, 2, f"Missing link: {missing}"[:pop_w - 3])
    except curses.error:
        pass
    try:
        win.addstr(pop_h - 2, max(1, (pop_w - len(hint)) // 2), hint[:pop_w - 2])
    except curses.error:
        pass
    win.refresh()

    action = None
    while True:
        key = win.getch()
        if key in (10, 13, ord("q"), ord("Q"), 27):
            break
        elif key == curses.KEY_UP:
            action = "prev"
            break
        elif key == curses.KEY_DOWN:
            action = "next"
            break
        elif key in (ord("d"), ord("D")):
            action = "d"
            break
        elif key in (ord("b"), ord("B")):
            action = "b"
            break
        elif key in (ord("p"), ord("P")):
            action = "r"
            break
        elif key in (ord("n"), ord("N")):
            action = "n"
            break
        elif key in (ord("s"), ord("S")):
            action = "s"
            break
        elif key in (ord("e"), ord("E")):
            action = "e"
            break
        elif key in (ord("h"), ord("H")):
            show_help(stdscr)
            win.touchwin()
            win.refresh()

    del win
    stdscr.touchwin()
    stdscr.refresh()
    return action
