#!/usr/bin/env python3
"""Shared terminal escape-sequence constants and helpers.

Centralizes all ANSI/VT100 escape sequences so that UI rendering code avoids
scattered raw '\033[...' strings.  This makes the terminal I/O layer testable,
consistent, and easy to swap for alternate backends (e.g. Windows vt100).

Reference: ECMA-48 / VT100 escape sequences.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Cursor visibility
# ---------------------------------------------------------------------------
CURSOR_HIDE = "\033[?25l"
CURSOR_SHOW = "\033[?25h"

# ---------------------------------------------------------------------------
# Alt-screen buffer (save/restore main screen)
# ---------------------------------------------------------------------------
# Enter alt-screen: saves the current screen contents and switches to a
# fresh alternate buffer.  Exiting restores the saved screen.
ALT_SCREEN_ENTER = "\033[?1049h\033[?25l"   # altscreen + hide cursor
ALT_SCREEN_EXIT = "\033[?1049l\033[?25h"    # restore altscreen + show cursor

# ---------------------------------------------------------------------------
# Clear & home
# ---------------------------------------------------------------------------
CLEAR_SCREEN = "\033[2J\033[H"   # Erase all + move cursor home (row 0, col 0)
CLEAR_LINE = "\033[2K"            # Erase entire current line
CLEAR_TO_EOL = "\033[K"           # Erase from cursor to end of line

# ---------------------------------------------------------------------------
# Cursor movement
# ---------------------------------------------------------------------------
CURSOR_HOME = "\033[H"          # Move cursor to home (1,1) – same as ESC[H]
CURSOR_UP = "\033[{}A"          # Move up N lines (fill with count)
CURSOR_DOWN = "\033[{}B"        # Move down N lines
CURSOR_FORWARD = "\033[{}C"     # Move forward N columns
CURSOR_BACK = "\033[{}D"        # Move back N columns
CURSOR_NEXT_LINE = "\033[{}E"    # Move to next line, col 1
CURSOR_PREV_LINE = "\033[{}F"    # Move to previous line, col 1
CURSOR_SAVE = "\033[s"          # Save cursor position
CURSOR_RESTORE = "\033[u"       # Restore cursor position

# ---------------------------------------------------------------------------
# SGR (Select Graphic Rendition) attributes
# ---------------------------------------------------------------------------
SGR_RESET = "\033[0m"

# Colors (foreground)
SGR_FG_BLACK = "\033[30m"
SGR_FG_RED = "\033[31m"
SGR_FG_GREEN = "\033[32m"
SGR_FG_YELLOW = "\033[33m"
SGR_FG_BLUE = "\033[34m"
SGR_FG_MAGENTA = "\033[35m"
SGR_FG_CYAN = "\033[36m"
SGR_FG_WHITE = "\033[37m"
SGR_FG_DEFAULT = "\033[39m"

# Background colors
SGR_BG_BLACK = "\033[40m"
SGR_BG_RED = "\033[41m"
SGR_BG_GREEN = "\033[42m"
SGR_BG_YELLOW = "\033[43m"
SGR_BG_BLUE = "\033[44m"
SGR_BG_MAGENTA = "\033[45m"
SGR_BG_CYAN = "\033[46m"
SGR_BG_WHITE = "\033[47m"
SGR_BG_DEFAULT = "\033[49m"

# Bright variants
SGR_FG_BRIGHT_BLACK = "\033[90m"
SGR_FG_BRIGHT_RED = "\033[91m"
SGR_FG_BRIGHT_GREEN = "\033[92m"
SGR_FG_BRIGHT_YELLOW = "\033[93m"
SGR_FG_BRIGHT_BLUE = "\033[94m"
SGR_FG_BRIGHT_MAGENTA = "\033[95m"
SGR_FG_BRIGHT_CYPAN = "\033[96m"
SGR_FG_BRIGHT_WHITE = "\033[97m"


# ---------------------------------------------------------------------------
# Module-level escape buffer (used by escape_string helpers below)
# ---------------------------------------------------------------------------
# A pre-computed ESC byte avoids the overhead of ``"\033"`` string creation
# on every render path.
ESC = "\033"


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------
def move_cursor_to(row: int, col: int) -> str:
    """Return escape sequence to move cursor to *row*, *col* (1-indexed)."""
    return f"\033[{row};{col}H"


def move_cursor_up(n: int = 1) -> str:
    """Return escape sequence to move cursor up *n* lines."""
    if n <= 0:
        return ""
    if n == 1:
        return "\033[A"
    return f"\033[{n}A"


def move_cursor_down(n: int = 1) -> str:
    """Return escape sequence to move cursor down *n* lines."""
    if n <= 0:
        return ""
    if n == 1:
        return "\033[B"
    return f"\033[{n}B"


def move_cursor_forward(n: int = 1) -> str:
    """Return escape sequence to move cursor forward *n* columns."""
    if n <= 0:
        return ""
    if n == 1:
        return "\033[C"
    return f"\033[{n}C"


def move_cursor_back(n: int = 1) -> str:
    """Return escape sequence to move cursor back *n* columns."""
    if n <= 0:
        return ""
    if n == 1:
        return "\033[D"
    return f"\033[{n}D"


def erase_lines(n: int = 1) -> str:
    """Return escape sequences to erase *n* lines upward (clearing visual rows)."""
    seq = CLEAR_LINE + move_cursor_up(n) if n > 0 else ""
    for _ in range(max(0, n - 1)):
        seq += CLEAR_LINE + move_cursor_up(1)
    if n == 0:
        seq = ""
    elif n == 1:
        seq = CLEAR_LINE
    return seq


def write_esc(text: str) -> str:
    """Wrap *text* with SGR reset on both ends (convenience for colored output)."""
    return f"{SGR_RESET}{text}{SGR_RESET}"
