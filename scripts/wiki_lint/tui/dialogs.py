"""Pre-TUI dialogs: auto-fix confirmation prompt and progress-during-scan window."""

import sys
from pathlib import Path

from ..checks.orphans import check_orphans, fix_orphans
from ..checks.stubs import check_stubs
from ..checks.vault import check_vault


def ask_run_auto_fixes() -> bool:
    """Show a centered curses dialog asking whether to run automatic fixes first.
    Enter/Y = yes (default), N/Esc = no."""
    try:
        import curses
    except ImportError:
        curses = None

    result = [True]

    def _dialog(stdscr):
        curses.curs_set(0)
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)  # selected button
        curses.init_pair(2, curses.COLOR_YELLOW, -1)                # title

        content = [
            "Apply automatic fixes before interactive review?",
            "",
            "  fix-simple-errors  — repair normalizable broken links + wikilink raw/ refs",
            "  fix-orphans        — link plain-text references in wiki/",
            "",
            "Only remaining issues will appear in the interactive TUI.",
        ]

        height, width = stdscr.getmaxyx()
        box_w = min(max(len(l) for l in content) + 6, width - 4)
        # rows: top border + sep + content + sep + buttons + bottom border
        box_h = min(len(content) + 5, height - 4)
        by = max(0, (height - box_h) // 2)
        bx = max(0, (width - box_w) // 2)

        selected = 0  # 0 = Yes, 1 = No

        win = curses.newwin(box_h, box_w, by, bx)
        win.keypad(True)

        while True:
            win.erase()
            win.box()

            title = " Wiki Lint — Auto-fix "
            try:
                win.addstr(0, max(1, (box_w - len(title)) // 2), title,
                           curses.color_pair(2) | curses.A_BOLD)
            except curses.error:
                pass

            sep = "─" * (box_w - 2)
            try:
                win.addstr(1, 1, sep[:box_w - 2])
            except curses.error:
                pass

            for i, line in enumerate(content):
                try:
                    win.addstr(2 + i, 2, line[:box_w - 3])
                except curses.error:
                    pass

            content_end = 2 + len(content)
            try:
                win.addstr(content_end, 1, sep[:box_w - 2])
            except curses.error:
                pass

            btn_yes = " [ Yes ] "
            btn_no  = " [ No  ] "
            btn_row = content_end + 1
            gap = 2
            total_btn_w = len(btn_yes) + gap + len(btn_no)
            btn_x = max(1, (box_w - total_btn_w) // 2)
            try:
                attr_yes = (curses.color_pair(1) | curses.A_BOLD) if selected == 0 else curses.A_NORMAL
                attr_no  = (curses.color_pair(1) | curses.A_BOLD) if selected == 1 else curses.A_NORMAL
                win.addstr(btn_row, btn_x, btn_yes, attr_yes)
                win.addstr(btn_row, btn_x + len(btn_yes) + gap, btn_no, attr_no)
            except curses.error:
                pass

            hint = "Y/Enter=yes   N/Esc=no   ←→=switch"
            try:
                win.addstr(box_h - 1, max(1, (box_w - len(hint)) // 2), hint[:box_w - 2])
            except curses.error:
                pass

            win.refresh()

            key = win.getch()
            if key in (ord('y'), ord('Y')):
                result[0] = True
                break
            elif key in (10, 13):        # Enter — confirm highlighted button
                result[0] = (selected == 0)
                break
            elif key in (ord('n'), ord('N'), 27):  # N or Esc = No
                result[0] = False
                break
            elif key in (curses.KEY_LEFT, curses.KEY_RIGHT, 9):  # arrow / Tab
                selected = 1 - selected

    if curses is not None:
        try:
            curses.wrapper(_dialog)
            return result[0]
        except Exception:
            pass

    # Fallback: plain terminal prompt
    sys.stdout.write("\nRun automatic checks and fixes before interactive mode? [Y/n] ")
    sys.stdout.flush()
    try:
        import tty, termios
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write("\n")
        sys.stdout.flush()
        return ch not in ('\x1b', 'n', 'N')
    except Exception:
        return sys.stdin.readline().strip().lower() not in ('n', 'no')


def run_scan_with_dialog(root: Path, args) -> dict:
    """Run full scan (links, orphans, stubs, optional auto-fixes) inside a
    centered curses progress dialog. Only called in --interactive mode."""
    try:
        import curses
    except ImportError:
        curses = None

    def _do_scan() -> dict:
        if getattr(args, "fix_simple_errors", False):
            print("Fixing broken links...", file=sys.stderr)
        result = check_vault(root, args)
        orphan_result = check_orphans(root, args.quiet)
        result["orphans"] = orphan_result["orphans"]
        result["orphan_summary"] = orphan_result["summary"]
        stub_result = check_stubs(root, args.quiet)
        result["stubs"] = stub_result["stubs"]
        result["stub_summary"] = stub_result["summary"]
        if getattr(args, "fix_orphans", False) and orphan_result["orphans"]:
            print(f"Fixing {len(orphan_result['orphans'])} orphan(s)...", file=sys.stderr)
            fix_result = fix_orphans(orphan_result["orphans"], root, args.quiet)
            result["orphan_fix"] = fix_result
            if fix_result["orphans_resolved"] > 0:
                updated = check_orphans(root, quiet=True)
                result["orphans"] = updated["orphans"]
                result["orphan_summary"] = updated["summary"]
        return result

    if curses is None:
        return _do_scan()

    outcome: list = []

    def _curses_scan(stdscr):
        curses.curs_set(0)
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(2, curses.COLOR_YELLOW, -1)

        height, width = stdscr.getmaxyx()
        box_w = max(40, width - 4)
        box_h = min(20, height - 4)
        by = max(0, (height - box_h) // 2)
        bx = max(0, (width - box_w) // 2)
        inner_w = box_w - 4
        max_log = box_h - 3  # rows 2 … box_h-2

        win = curses.newwin(box_h, box_w, by, bx)
        log_buf: list[str] = []
        cur: list[str] = [""]

        def _wrap(line: str) -> list[str]:
            """Wrap a single line to inner_w, indenting continuation rows."""
            if len(line) <= inner_w:
                return [line]
            rows = []
            while len(line) > inner_w:
                rows.append(line[:inner_w])
                line = "  " + line[inner_w:]
            if line:
                rows.append(line)
            return rows

        def redraw():
            win.erase()
            win.box()
            title = " Scanning vault "
            try:
                win.addstr(0, max(1, (box_w - len(title)) // 2), title,
                           curses.color_pair(2) | curses.A_BOLD)
                win.addstr(1, 1, "─" * (box_w - 2))
            except curses.error:
                pass
            raw = log_buf + ([cur[0]] if cur[0] else [])
            wrapped: list[str] = []
            for ln in raw:
                wrapped.extend(_wrap(ln))
            visible = wrapped[-max_log:]
            for i, line in enumerate(visible):
                try:
                    win.addstr(2 + i, 2, line[:inner_w])
                except curses.error:
                    pass
            win.refresh()

        class _Stderr:
            def write(self, text: str):
                i = 0
                while i < len(text):
                    if text[i] == '\r':
                        cur[0] = ""
                        i += 1
                    elif text[i] == '\n':
                        log_buf.append(cur[0])
                        cur[0] = ""
                        i += 1
                    else:
                        j = i
                        while j < len(text) and text[j] not in ('\r', '\n'):
                            j += 1
                        cur[0] += text[i:j]
                        i = j
                redraw()

            def flush(self):
                pass

        old_err = sys.stderr
        sys.stderr = _Stderr()
        try:
            outcome.append(_do_scan())
        except Exception as e:
            outcome.extend([None, e])
        finally:
            sys.stderr = old_err

        if cur[0]:
            log_buf.append(cur[0])
            cur[0] = ""
        log_buf.append("")
        log_buf.append("  Done — starting interactive review…")
        redraw()
        curses.napms(1000)

    try:
        curses.wrapper(_curses_scan)
    except Exception:
        pass

    if outcome and outcome[0] is not None:
        return outcome[0]
    if len(outcome) > 1 and outcome[1] is not None:
        raise outcome[1]
    return _do_scan()
