"""Curses help dialog."""

import curses


HELP_LINES = [
    "NAVIGATION",
    "  ↑ / ↓          Navigate list items",
    "  PgUp / PgDn    Jump a full page",
    "  Enter          Open detail / preview popup",
    "  h              Show this help",
    "  q / Esc        Quit",
    "",
    "BROKEN LINK ACTIONS  (when a broken link is selected)",
    "  d              Delete the broken link from the file",
    "  b              Rewrite as [[broken-link|…]]",
    "  p              Strip [[ ]] brackets — leave plain text",
    "  n              Open file browser to navigate and pick a replacement",
    "  s              Search files in raw/ and wiki/ by regex for a replacement",
    "  e              Open source file in default editor",
    "",
    "ORPHAN PAGE ACTIONS  (when an orphan page is selected)",
    "  d              Delete the orphan page file from disk",
    "  k              Keep orphan, add 'orphan: false' to frontmatter",
    "  e              Open source file in default editor",
    "",
    "STUB PAGE ACTIONS  (when a stub page is selected)",
    "  d              Delete the stub page file from disk",
    "  k              Acknowledge as stub (add 'stub: true' to frontmatter)",
    "  e              Open source file in default editor",
    "",
    "DETAIL / PREVIEW POPUP  (opened with Enter)",
    "  ↑ / ↓          Prev / next item (links); scroll (orphans)",
    "  PgUp / PgDn    Scroll content (orphans)",
    "  d  b  p  n  s  k  e  Same actions as in the main list",
    "  h              Show this help",
    "  Enter / q      Close popup",
]


def show_help(stdscr) -> None:
    """Show a full-command help dialog. Close with Enter, Esc, or h."""
    height, width = stdscr.getmaxyx()
    pop_w = min(max(54, width - 8), width - 2)
    inner_w = pop_w - 4
    content_h = min(len(HELP_LINES), height - 6)
    pop_h = min(content_h + 4, height - 2)
    pop_y = max(0, (height - pop_h) // 2)
    pop_x = max(0, (width - pop_w) // 2)
    sep = "─" * (pop_w - 2)
    close_hint = "[ ↑↓/PgUp/PgDn scroll   Esc / Enter / h to close ]"

    win = curses.newwin(pop_h, pop_w, pop_y, pop_x)
    win.keypad(True)
    scroll = 0

    while True:
        win.erase()
        win.box()
        title = " Help "
        try:
            win.addstr(0, max(1, (pop_w - len(title)) // 2), title, curses.A_BOLD)
            win.addstr(1, 1, sep[:pop_w - 2])
        except curses.error:
            pass

        rows_avail = pop_h - 4
        for row in range(rows_avail):
            li = scroll + row
            if li >= len(HELP_LINES):
                break
            line = HELP_LINES[li]
            try:
                attr = curses.A_BOLD if (line and not line.startswith(" ")) else curses.A_NORMAL
                win.addstr(2 + row, 2, line[:inner_w], attr)
            except curses.error:
                pass

        try:
            win.addstr(pop_h - 2, max(1, (pop_w - len(close_hint)) // 2), close_hint[:pop_w - 2])
        except curses.error:
            pass
        if len(HELP_LINES) > rows_avail:
            pct = int(100 * scroll / max(1, len(HELP_LINES) - rows_avail))
            try:
                win.addstr(pop_h - 2, pop_w - 5, f"{pct:3d}%")
            except curses.error:
                pass

        win.refresh()
        key = win.getch()
        if key in (10, 13, 27, ord("q"), ord("Q"), ord("h"), ord("H")):
            break
        elif key == curses.KEY_UP:
            scroll = max(0, scroll - 1)
        elif key == curses.KEY_DOWN:
            scroll = min(max(0, len(HELP_LINES) - rows_avail), scroll + 1)
        elif key == curses.KEY_PPAGE:
            scroll = max(0, scroll - rows_avail)
        elif key == curses.KEY_NPAGE:
            scroll = min(max(0, len(HELP_LINES) - rows_avail), scroll + rows_avail)

    del win
    stdscr.touchwin()
    stdscr.refresh()
