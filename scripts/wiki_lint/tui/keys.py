"""Shared keyboard helpers for the curses TUI.

Terminals send Option/Alt-modified keys (and arrow keys on terminals without
proper terminfo) as multi-byte escape sequences beginning with byte 27 (ESC),
followed by characters like `[1;3D` (Option+Left) or `b`/`f` (Alt-word). curses
delivers ESC as the first key; the trailing bytes arrive on subsequent
getch() calls. A naive `if key == 27: quit` therefore exits on Option+Arrow.

The helpers here let an input loop disambiguate a real Escape keypress from
the leading byte of such a sequence.
"""


def read_alt_sequence(win) -> "tuple[str, int] | None":
    """After receiving ESC (27), peek for an Alt/Option modifier sequence.
    Returns ('left', 0) / ('right', 0) / ('home', 0) / ('end', 0) / ('unknown', 0),
    or None for a real (bare) Escape. Consumes the trailing bytes on a match."""
    win.nodelay(True)
    try:
        ch = win.getch()
        if ch == -1:
            return None  # bare Escape
        # iTerm2 / readline: ESC b / ESC f for word movement
        if ch in (ord('b'), ord('B')):
            return ('left', 0)
        if ch in (ord('f'), ord('F')):
            return ('right', 0)
        # CSI sequence: ESC [ ... — option-arrow in Terminal.app is ESC [ 1 ; 3 D/C
        if ch == ord('['):
            buf = []
            for _ in range(8):
                c = win.getch()
                if c == -1:
                    break
                buf.append(c)
                if 0x40 <= c <= 0x7E:  # final byte of CSI
                    break
            seq = ''.join(chr(c) for c in buf)
            if seq.endswith('D'):
                return ('left', 0)
            if seq.endswith('C'):
                return ('right', 0)
            if seq.endswith('H'):
                return ('home', 0)
            if seq.endswith('F'):
                return ('end', 0)
            return ('unknown', 0)
        # Alt+Esc / double-Esc — treat as real Escape
        if ch == 27:
            return None
        return ('unknown', 0)
    finally:
        win.nodelay(False)


def is_bare_escape(win) -> bool:
    """Call right after getch() returned 27. True if it was a real Escape
    keypress; False if it was the start of an escape sequence (which is
    consumed by this call)."""
    return read_alt_sequence(win) is None
