#!/usr/bin/env python3
"""Search results and song selection UI - clean, uncluttered, pure terminal.

Design: Single-page picker. No fancy rendering. Results fit in a scrollable
view that refreshes cleanly. Selection is immediate and obvious.
"""

import sys
import time
import select
import os
from typing import Optional, List, Tuple, Any
from foundation.terminal_constants import (
    CLEAR_SCREEN, CLEAR_LINE,
    CURSOR_HIDE, CURSOR_SHOW,
    ALT_SCREEN_ENTER, ALT_SCREEN_EXIT,
    CURSOR_HOME, move_cursor_to, move_cursor_up,
)
import functools


# ============================================================================
# CLEAN TEXT FORMATTING - NO CLUTTER
# ============================================================================

def get_terminal_width() -> int:
    """Get terminal width safely."""
    try:
        import shutil
        return shutil.get_terminal_size(fallback=(80, 24)).columns
    except Exception:
        return 80


def truncate(text: str, width: int) -> str:
    """Truncate to width without ANSI codes or decoration."""
    if not text:
        return ''
    text = str(text)
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[:width - 3] + '...'


def _track_cache_key(track: Any, width: int) -> Tuple:
    """Build a cache key for a track+width combination."""
    tid = getattr(track, 'id', None)
    if tid is None and hasattr(track, '__dict__'):
        tid = id(track)
    return (tid, track.title, track.artist, track.duration, width)


@functools.lru_cache(maxsize=512)
def _format_track_compact_cached(cache_key: Tuple, width: int) -> str:
    """Cached inner formatter.  Receives a pre-computed cache key tuple
    so that lru_cache can hash it efficiently."""
    tid, title, artist, duration, _ = cache_key
    title = str(title or 'Untitled')
    artist = str(artist or 'Unknown')
    duration = str(duration or '--:--')

    overhead = len(" by ") + len(" []") + len(duration)
    available = width - overhead - 2  # 2 for margins

    title_budget = max(15, int(available * 0.65))
    artist_budget = max(10, available - title_budget)

    title = truncate(title, title_budget).ljust(title_budget)
    artist = truncate(artist, artist_budget).ljust(artist_budget)

    return f"{title} by {artist} [{duration}]"


def format_track_compact(track: Any, width: int = 80) -> str:
    """Format track in one clean line for results list.
    
    Format: TITLE by ARTIST [DURATION]
    
    Allocate space as: title 60% | " by " | artist 30% | duration 8%
    No colors, no Unicode boxes, no embellishment.
    
    Results are memoized via lru_cache keyed on (track identity/title/artist/duration, width)
    so that static track data is formatted only once per unique width.
    """
    try:
        key = _track_cache_key(track, width)
        return _format_track_compact_cached(key, width)
    except Exception:
        return str(track)[:width]


# ============================================================================
# PAGINATED RESULTS PRESENTER
# ============================================================================
class ResultsPaginator:
    """Displays search results in clean pages without clutter.
    
    - One page at a time (fits terminal)
    - Arrow keys to scroll
    - Numbers to select
    - Clean redraw, no flickering
    """
    
    def __init__(self, results: List[Any], page_size: int = 10):
        """Initialize paginator.
        
        Args:
            results: List of Track objects
            page_size: How many items per page (auto-capped to terminal)
        """
        self.results = results or []
        import shutil
        term_lines = shutil.get_terminal_size(fallback=(80, 24)).lines
        self.page_size = min(page_size, max(5, term_lines))
        try:
            self.page_size = int(self.page_size) - 6  # Leave room for header/footer
        except (ValueError, TypeError):
            self.page_size = 10
        
        self.current_page = 0
        self.selected_index = 0
        self.width = get_terminal_width()
        # Cache: (page, page_size, width) -> rendered lines list.
        # Only invalidated when current_page/selected_index/data changes.
        self._render_cache: dict = {}
        self._last_render_keys: Tuple[int, int, int, int] = (None, None, None, None)
    
    def total_pages(self) -> int:
        """How many pages total."""
        if not self.results:
            return 0
        return (len(self.results) + self.page_size - 1) // self.page_size
    
    def current_page_items(self) -> List[Tuple[int, Any]]:
        """Get (index, track) tuples for current page."""
        start = self.current_page * self.page_size
        end = start + self.page_size
        return [(i, self.results[i]) for i in range(start, min(end, len(self.results)))]
    
    def render(self) -> str:
        """Render current page as string (no print).
        
        Uses a cache keyed on (current_page, selected_index, page_size, width)
        so that re-rendering without state changes is O(1).
        """
        if not self.results:
            return "No results found."
        
        cache_key = (self.current_page, self.selected_index, self.page_size, self.width)
        if cache_key == self._last_render_keys and self._render_cache:
            return self._render_cache.get('rendered', '')
        
        self._last_render_keys = cache_key
        
        lines = []
        
        # Header
        total = len(self.results)
        page_num = self.current_page + 1
        total_pages = self.total_pages()
        header = f"SEARCH RESULTS ({total} found) - PAGE {page_num}/{total_pages}"
        lines.append(header)
        lines.append('-' * self.width)
        lines.append('')
        
        # Current page items (memoized: only reformat if selection or page changed)
        page_items = self.current_page_items()
        for item_num, (idx, track) in enumerate(page_items, 1):
            is_selected = idx == self.selected_index
            prefix = '> ' if is_selected else '  '
            row = format_track_compact(track, self.width - 4)
            number = f"{idx + 1:02d}"
            
            line = f"{prefix}[{number}] {row}"
            lines.append(line)
        
        lines.append('')
        lines.append('-' * self.width)
        
        # Footer
        if total > self.page_size:
            footer = "UP/DOWN: scroll | [1-99]: select | ENTER: play | Q: cancel"
        else:
            footer = "[1-99]: select | ENTER: play | Q: cancel"
        lines.append(footer)
        
        rendered = '\n'.join(lines)
        self._render_cache = {'rendered': rendered, 'lines': lines}
        return rendered
    
    def handle_key(self, key: str) -> Optional[int]:
        """Handle keyboard input. Return selected track index or None.
        
        Returns:
            None if no selection yet
            -1 if user cancelled
            >= 0 if track selected (index into results list)
        """
        if key == 'up':
            if self.selected_index > 0:
                self.selected_index -= 1
                # Scroll page if needed
                if self.selected_index < self.current_page * self.page_size:
                    self.current_page = max(0, self.current_page - 1)
            return None
        
        elif key == 'down':
            if self.selected_index < len(self.results) - 1:
                self.selected_index += 1
                # Scroll page if needed
                if self.selected_index >= (self.current_page + 1) * self.page_size:
                    self.current_page = min(self.total_pages() - 1, self.current_page + 1)
            return None
        
        elif key == 'enter':
            return self.selected_index
        
        elif key in ('q', 'esc', '^C'):
            return -1
        
        elif key.isdigit():
            # Try to parse as 1-indexed selection
            try:
                choice = int(key)
                if 1 <= choice <= len(self.results):
                    self.selected_index = choice - 1
                    self.current_page = self.selected_index // self.page_size
                    return self.selected_index
            except ValueError:
                pass
            return None
        
        return None


# ============================================================================
# INPUT HANDLER - CLEAN KEY READING
# ============================================================================
class KeyReader:
    """Read keys without Enter. Platform-aware."""
    
    def __init__(self):
        self.has_msvcrt = sys.platform == 'win32'
        self._raw_mode = False
    
    def start(self):
        """Enable single-key input."""
        if self.has_msvcrt:
            return
        try:
            import termios, tty
            self.fd = sys.stdin.fileno()
            self.old_settings = termios.tcgetattr(self.fd)
            tty.setraw(self.fd)
            self._raw_mode = True
        except Exception:
            self._raw_mode = False
    
    def stop(self):
        """Restore normal input."""
        if self._raw_mode:
            try:
                import termios
                termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old_settings)
            except Exception:
                pass
            self._raw_mode = False
    
    def read_key(self, timeout: float = 0.1) -> Optional[str]:
        """Read one key. Return None if timeout."""
        if self.has_msvcrt:
            return self._read_key_windows(timeout)
        return self._read_key_posix(timeout)
    
    def _read_key_windows(self, timeout: float) -> Optional[str]:
        """Windows key reading."""
        try:
            import msvcrt
            start = time.time()
            while time.time() - start < timeout:
                if msvcrt.kbhit():
                    b = msvcrt.getch()
                    if b == b'\x03':
                        return '^C'
                    if b in (b'\r', b'\n'):
                        return 'enter'
                    try:
                        return b.decode('utf-8', errors='ignore').lower()
                    except Exception:
                        return None
                time.sleep(0.01)
            return None
        except Exception:
            return None
    
    def _read_key_posix(self, timeout: float) -> Optional[str]:
        """POSIX key reading with select.
        
        Reads the initial byte via select, then reads any remaining bytes
        of a multi-byte escape sequence in a single batch call with a
        short sub-timeout, avoiding the inefficiency of calling
        select.select between every byte.
        """
        try:
            ready, _, _ = select.select([sys.stdin], [], [], timeout)
            if not ready:
                return None
            
            b = os.read(sys.stdin.fileno(), 1)
            if not b:
                return None
            
            if b == b'\x03':
                return '^C'
            if b == b'\x1b':
                # Escape sequence: read remaining bytes in one batch
                # with a very short timeout instead of select-per-byte.
                seq = b''
                try:
                    # Read whatever is available in one shot (non-blocking batch)
                    ready2, _, _ = select.select([sys.stdin], [], [], 0.01)
                    if ready2:
                        seq = os.read(sys.stdin.fileno(), 8)  # ESC [ + final byte(s)
                except Exception:
                    pass
                
                if seq.startswith(b'['):
                    final = seq[1:2]
                    if final == b'A':
                        return 'up'
                    if final == b'B':
                        return 'down'
                    if final == b'C':
                        return 'right'
                    if final == b'D':
                        return 'left'
                    if final == b'H':
                        return 'home'
                    if final == b'F':
                        return 'end'
                return 'esc'
            
            if b in (b'\r', b'\n'):
                return 'enter'
            if b == b'\x7f':
                return 'backspace'
            
            ch = b.decode('utf-8', errors='ignore')
            return ch.lower() if ch and 32 <= ord(ch) < 127 else None
        except Exception:
            return None


# ============================================================================
# INTERACTIVE SEARCH RESULTS PICKER
# ============================================================================
class SearchResultsPicker:
    """Clean interactive picker for search results.
    
    Flow:
    1. Display results page
    2. Read key (arrow/number/enter)
    3. Update selection
    4. Redraw if needed
    5. Return selection when user presses Enter
    """
    
    def __init__(self, results: List[Any], page_size: int = 10):
        self.paginator = ResultsPaginator(results, page_size)
        self.reader = KeyReader()
        self.last_render = 0
        self.render_interval = 0.05  # Redraw max 20x/sec
        # Delta-detection: track last rendered state to skip redundant redraws
        self._last_render_keys: Tuple[Optional[int], Optional[int]] = (None, None)
    
    def enter_alt_screen(self):
        """Enter alternate screen buffer (preserves main screen)."""
        try:
            sys.stdout.write(ALT_SCREEN_ENTER)
            sys.stdout.flush()
        except Exception:
            pass
    
    def exit_alt_screen(self):
        """Exit alternate screen buffer, restoring main screen."""
        try:
            sys.stdout.write(ALT_SCREEN_EXIT)
            sys.stdout.flush()
        except Exception:
            pass
    
    def clear_screen(self):
        """Clear terminal using ANSI escape (no os.system subprocess)."""
        try:
            sys.stdout.write(CLEAR_SCREEN)
            sys.stdout.flush()
        except Exception:
            pass
    
    def display_results(self) -> int:
        """Run picker. Return selected index or -1 if cancelled.
        
        Uses delta-based rendering: only the lines that changed between
        renders are rewritten, and the entire screen is only cleared
        when the page changes.  Alt-screen buffering preserves the
        user's terminal scrollback.
        """
        if not self.paginator.results:
            print("No results to display.")
            return -1
        
        self.reader.start()
        try:
            self.enter_alt_screen()
            self.paginator._render_cache.clear()
            self._render_to_screen(initial=True)
            
            while True:
                key = self.reader.read_key(timeout=0.05)
                if key is None:
                    continue
                
                # Handle key
                result = self.paginator.handle_key(key)
                if result is not None:
                    return result
                
                # Delta render: only redraw if state changed
                self._render_to_screen(initial=False)
        
        finally:
            self.reader.stop()
            self.exit_alt_screen()
    
    def _render_to_screen(self, initial: bool = False):
        """Render to screen with delta detection.
        
        On initial render, full clear + print.
        On subsequent renders, only reprint if the selection or page
        actually changed compared to the last render.
        """
        cache_key = (
            self.paginator.current_page,
            self.paginator.selected_index,
            self.paginator.page_size,
            self.paginator.width,
        )
        
        if cache_key == self._last_render_keys and not initial:
            # No state change — skip re-render entirely
            return
        
        self._last_render_keys = cache_key
        
        if initial:
            # Full redraw on page change or initial entry
            sys.stdout.write(CLEAR_SCREEN)
        
        sys.stdout.write(self.paginator.render())
        sys.stdout.write('\n')
        sys.stdout.flush()


# ============================================================================
# SIMPLE FALLBACK FOR NON-INTERACTIVE TERMINALS
# ============================================================================
class SearchResultsFallback:
    """Non-interactive fallback: print results, read choice by number."""
    
    def __init__(self, results: List[Any]):
        self.results = results or []
    
    def display_results(self) -> int:
        """Display results, prompt for selection by number.
        
        Returns:
            -1: User cancelled
            0-N: Index into results
        """
        if not self.results:
            print("No results found.")
            return -1
        
        print("\nSEARCH RESULTS")
        print("=" * 80)
        for i, track in enumerate(self.results[:50], 1):  # Cap at 50 for sanity
            line = format_track_compact(track, 76)
            print(f"{i:02d}. {line}")
        print("=" * 80)
        
        while True:
            try:
                choice = input("Enter track number (1-{}) or [Q]uit: ".format(len(self.results))).strip().lower()
            except (KeyboardInterrupt, EOFError):
                return -1
            
            if choice in ('q', 'quit', 'exit'):
                return -1
            
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(self.results):
                    return idx
            except ValueError:
                pass
            
            print("Invalid choice. Try again.")


# ============================================================================
# PUBLIC API
# ============================================================================
def pick_from_results(results: List[Any], interactive: bool = True) -> Optional[Any]:
    """Pick a track from search results.
    
    Args:
        results: List of Track objects
        interactive: Try interactive picker first, fall back if not available
    
    Returns:
        Selected Track object, or None if cancelled
    """
    if not results:
        return None
    
    # Try interactive picker if TTY
    if interactive and sys.stdin.isatty():
        try:
            picker = SearchResultsPicker(results, page_size=10)
            idx = picker.display_results()
            if idx >= 0:
                return results[idx]
            return None
        except Exception:
            pass
    
    # Fall back to simple number picker
    picker = SearchResultsFallback(results)
    idx = picker.display_results()
    if idx >= 0:
        return results[idx]
    return None


# ============================================================================
# DEMO
# ============================================================================
if __name__ == '__main__':
    from dataclasses import dataclass
    
    @dataclass
    class FakeTrack:
        title: str
        artist: str
        duration: str
    
    # Create fake results
    fake_results = [
        FakeTrack("Song One", "Artist A", "3:45"),
        FakeTrack("Song Two - Official Video", "Artist B", "4:20"),
        FakeTrack("Song Three (Remix)", "Artist C ft. Artist D", "5:10"),
        FakeTrack("Song Four - Live Performance", "Artist E", "6:30"),
        FakeTrack("Song Five", "Artist F", "3:15"),
        FakeTrack("Song Six Extended Mix", "Artist G", "7:45"),
        FakeTrack("Song Seven", "Artist H", "4:00"),
        FakeTrack("Song Eight Remastered", "Artist I", "3:50"),
        FakeTrack("Song Nine", "Artist J", "5:20"),
        FakeTrack("Song Ten", "Artist K", "4:10"),
        FakeTrack("Song Eleven", "Artist L", "3:40"),
        FakeTrack("Song Twelve", "Artist M", "4:35"),
    ]
    
    print("\n\nDEMO: Search Results Picker")
    print("Controls: UP/DOWN arrows, number keys to jump, ENTER to select, Q to cancel")
    print("\nPress any key to start...\n")
    input()
    
    selected = pick_from_results(fake_results, interactive=True)
    
    if selected:
        print(f"\n\nSelected: {selected.title} by {selected.artist} ({selected.duration})")
    else:
        print("\n\nCancelled.")
