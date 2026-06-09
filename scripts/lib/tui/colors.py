"""Named curses color-pair constants and one-shot initialiser."""


PAIR_SELECTED = 1        # selected row
PAIR_DELETED = 2         # deleted state / file numbering
PAIR_BROKEN_MARKED = 3   # marked as broken
PAIR_REPLACED = 4        # replaced state
PAIR_BROKEN_LINK = 5     # broken link in popup / link column
PAIR_FILENAME = 6        # filename in list
PAIR_LINENO = 7          # file line number in list
PAIR_DELINKED = 8        # delinked (plain text)
PAIR_KEPT = 9            # kept orphan
PAIR_ORPHAN = 10         # unhandled orphan
PAIR_STUB = 11           # unhandled stub


def init_pairs(curses_mod) -> None:
    curses_mod.start_color()
    curses_mod.use_default_colors()
    curses_mod.init_pair(PAIR_SELECTED, curses_mod.COLOR_BLACK, curses_mod.COLOR_CYAN)
    curses_mod.init_pair(PAIR_DELETED, curses_mod.COLOR_GREEN, -1)
    curses_mod.init_pair(PAIR_BROKEN_MARKED, curses_mod.COLOR_YELLOW, -1)
    curses_mod.init_pair(PAIR_REPLACED, curses_mod.COLOR_MAGENTA, -1)
    curses_mod.init_pair(PAIR_BROKEN_LINK, curses_mod.COLOR_YELLOW, -1)
    curses_mod.init_pair(PAIR_FILENAME, curses_mod.COLOR_WHITE, -1)
    curses_mod.init_pair(PAIR_LINENO, curses_mod.COLOR_CYAN, -1)
    curses_mod.init_pair(PAIR_DELINKED, curses_mod.COLOR_BLUE, -1)
    curses_mod.init_pair(PAIR_KEPT, curses_mod.COLOR_GREEN, -1)
    curses_mod.init_pair(PAIR_ORPHAN, curses_mod.COLOR_RED, -1)
    curses_mod.init_pair(PAIR_STUB, curses_mod.COLOR_CYAN, -1)
