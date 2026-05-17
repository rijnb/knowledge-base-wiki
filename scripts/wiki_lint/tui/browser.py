"""File-tree browser dialog used to pick a replacement target for a broken link."""

import curses
from pathlib import Path

from .colors import PAIR_BROKEN_LINK


def show_file_browser(stdscr, root: Path, broken_target: str = "") -> "Path | None":
    """Browse the vault tree and pick a replacement .md file.
    Returns path relative to root, or None if cancelled."""
    top_names = ("wiki", "raw")
    top_dirs = [root / name for name in top_names if (root / name).is_dir()]
    if not top_dirs:
        top_dirs = sorted(d for d in root.iterdir() if d.is_dir() and not d.name.startswith("."))

    class _Node:
        __slots__ = ("path", "depth", "expanded", "_children")

        def __init__(self, path: Path, depth: int):
            self.path = path
            self.depth = depth
            self.expanded = False
            self._children: "list | None" = None

        @property
        def is_dir(self) -> bool:
            return self.path.is_dir()

        def load_children(self) -> list:
            if self._children is None:
                kids: list = []
                try:
                    for p in sorted(self.path.iterdir(),
                                    key=lambda x: (not x.is_dir(), x.name.lower())):
                        if p.name.startswith("."):
                            continue
                        if p.is_dir() or p.suffix.lower() == ".md":
                            kids.append(_Node(p, self.depth + 1))
                except PermissionError:
                    pass
                self._children = kids
            return self._children

    root_nodes = [_Node(d, 0) for d in top_dirs]

    def build_visible() -> list:
        out: list = []

        def _walk(nodes: list) -> None:
            for nd in nodes:
                out.append(nd)
                if nd.is_dir and nd.expanded:
                    _walk(nd.load_children())

        _walk(root_nodes)
        return out

    height, width = stdscr.getmaxyx()
    pop_w = min(max(50, width - 6), width - 2)
    pop_h = min(max(10, height - 4), height - 2)
    pop_y = max(0, (height - pop_h) // 2)
    pop_x = max(0, (width - pop_w) // 2)

    win = curses.newwin(pop_h, pop_w, pop_y, pop_x)
    win.keypad(True)

    selected = 0
    scroll_offset = 0

    while True:
        visible = build_visible()
        if not visible:
            del win
            stdscr.touchwin()
            stdscr.refresh()
            return None
        if selected >= len(visible):
            selected = len(visible) - 1

        win.erase()
        win.box()
        title = " Find replacement link "
        try:
            win.addstr(0, max(1, (pop_w - len(title)) // 2), title)
        except curses.error:
            pass

        if broken_target:
            try:
                label = "replacing: "
                win.addstr(1, 2, label, curses.A_DIM)
                win.addstr(1, 2 + len(label),
                           broken_target[:max(1, pop_w - 2 - len(label))],
                           curses.color_pair(PAIR_BROKEN_LINK) | curses.A_BOLD)
            except curses.error:
                pass

        nav = "↑↓ navigate   → expand   ← collapse   a-z=jump to name   Enter=select   Esc=cancel"
        try:
            win.addstr(2, max(1, (pop_w - len(nav)) // 2), nav[:pop_w - 2])
        except curses.error:
            pass
        sep = "─" * (pop_w - 2)
        try:
            win.addstr(3, 1, sep[:pop_w - 2])
        except curses.error:
            pass

        list_h = pop_h - 5  # rows 4 .. pop_h-2
        if selected < scroll_offset:
            scroll_offset = selected
        elif selected >= scroll_offset + list_h:
            scroll_offset = selected - list_h + 1

        inner_w = pop_w - 4
        for row in range(list_h):
            idx = scroll_offset + row
            if idx >= len(visible):
                break
            nd = visible[idx]
            indent = "  " * nd.depth
            if nd.is_dir:
                icon = "▼ " if nd.expanded else "▶ "
                label = indent + icon + nd.path.name + "/"
            else:
                label = indent + "  " + nd.path.name
            attr = curses.A_REVERSE if idx == selected else curses.A_NORMAL
            try:
                win.addstr(4 + row, 2, label[:inner_w], attr)
            except curses.error:
                pass

        win.refresh()
        key = win.getch()

        if key == 27:  # Escape
            del win
            stdscr.touchwin()
            stdscr.refresh()
            return None
        elif key == curses.KEY_UP:
            if selected > 0:
                selected -= 1
        elif key == curses.KEY_DOWN:
            if selected < len(visible) - 1:
                selected += 1
        elif key == curses.KEY_PPAGE:
            page = max(1, list_h - 1)
            selected = max(0, selected - page)
        elif key == curses.KEY_NPAGE:
            page = max(1, list_h - 1)
            selected = min(len(visible) - 1, selected + page)
        elif key == curses.KEY_RIGHT:
            nd = visible[selected]
            if nd.is_dir and not nd.expanded:
                nd.expanded = True
                nd.load_children()
        elif key == curses.KEY_LEFT:
            nd = visible[selected]
            if nd.is_dir and nd.expanded:
                nd.expanded = False
            else:
                # Jump to and collapse parent
                for i in range(selected - 1, -1, -1):
                    if visible[i].depth == nd.depth - 1 and visible[i].is_dir:
                        visible[i].expanded = False
                        selected = i
                        break
        elif key in (10, 13):  # Enter
            nd = visible[selected]
            if nd.is_dir:
                nd.expanded = not nd.expanded
                if nd.expanded:
                    nd.load_children()
            else:
                del win
                stdscr.touchwin()
                stdscr.refresh()
                return nd.path.relative_to(root)
        elif 32 <= key <= 126:  # printable ASCII — jump to next matching name
            ch = chr(key).lower()
            n_vis = len(visible)
            for offset in range(1, n_vis + 1):
                candidate = (selected + offset) % n_vis
                if visible[candidate].path.name.lower().startswith(ch):
                    selected = candidate
                    break
