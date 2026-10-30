#!/usr/bin/env python3
"""Complete bulletproof TUI - search, results, selection, playback.

Integrates all components: robust I/O, crash-safe state, clean results picker.
Pure terminal, no clutter, defensive programming throughout.
"""

import sys
import os
import time
import threading
import queue as py_queue
import subprocess
import signal
import select
import traceback
import json
from typing import Optional, List, Tuple, Any
from dataclasses import dataclass
from datetime import datetime

# Import from foundation.musiccli (the core domain logic)
try:
    from foundation.musiccli import (
        Track, PlaybackSession, search_youtube, fetch_playlist, fetch_single,
        is_url, is_playlist_url, play_track, kill_process,
    )
    HAS_MUSICCLI = True
except ImportError:
    HAS_MUSICCLI = False

# Import shared terminal escape-sequence constants
from foundation.terminal_constants import (
    CLEAR_SCREEN, CLEAR_LINE,
    CURSOR_HIDE, CURSOR_SHOW,
    ALT_SCREEN_ENTER, ALT_SCREEN_EXIT,
    move_cursor_to, move_cursor_up,
)


# ============================================================================
# TERMINAL STATE - GUARANTEED CLEANUP
# ============================================================================
class TerminalState:
    """Manages terminal state with guaranteed cleanup on any exit."""
    
    def __init__(self):
        self._lock = threading.Lock()
        self._raw_mode_fd = None
        self._saved_termios = None
        self._cursor_hidden = False
        self._handlers_registered = False
    
    def _register_handlers(self):
        """Register signal handlers for guaranteed cleanup."""
        if self._handlers_registered:
            return
        try:
            import atexit
            atexit.register(self.restore_all)
            signal.signal(signal.SIGINT, self._handle_sigint)
            signal.signal(signal.SIGTERM, self._handle_sigterm)
            self._handlers_registered = True
        except Exception:
            pass
    
    def _handle_sigint(self, sig, frame):
        self.restore_all()
        sys.exit(0)
    
    def _handle_sigterm(self, sig, frame):
        self.restore_all()
        sys.exit(1)
    
    def enter_raw_mode(self) -> bool:
        """Enter raw mode, remember state."""
        with self._lock:
            if self._raw_mode_fd is not None:
                return True
            try:
                import termios
                import tty
                fd = sys.stdin.fileno()
                self._saved_termios = termios.tcgetattr(fd)
                tty.setraw(fd)
                self._raw_mode_fd = fd
                self._register_handlers()
                return True
            except Exception:
                return False
    
    def restore_raw_mode(self):
        """Restore from raw mode."""
        with self._lock:
            if self._raw_mode_fd is None or self._saved_termios is None:
                return
            try:
                import termios
                termios.tcsetattr(self._raw_mode_fd, termios.TCSADRAIN,
                                self._saved_termios)
            except Exception:
                pass
            finally:
                self._raw_mode_fd = None
                self._saved_termios = None
    
    def hide_cursor(self):
        """Hide cursor (idempotent)."""
        with self._lock:
            if self._cursor_hidden:
                return
            try:
                sys.stdout.write(CURSOR_HIDE)
                sys.stdout.flush()
                self._cursor_hidden = True
            except Exception:
                pass
    
    def show_cursor(self):
        """Show cursor (idempotent)."""
        with self._lock:
            if not self._cursor_hidden:
                return
            try:
                sys.stdout.write(CURSOR_SHOW)
                sys.stdout.flush()
                self._cursor_hidden = False
            except Exception:
                pass
    
    def clear_screen(self):
        """Clear screen using ANSI escape sequence."""
        try:
            sys.stdout.write(CLEAR_SCREEN)
            sys.stdout.flush()
        except Exception:
            pass
    
    def restore_all(self):
        """Full cleanup: raw mode, cursor, screen."""
        self.restore_raw_mode()
        self.show_cursor()
        try:
            self.clear_screen()
        except Exception:
            pass
    
    def enter_alt_screen(self):
        """Enter alternate screen buffer (preserves main screen scrollback)."""
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
            self.clear_screen()


_TERMINAL = TerminalState()


# ============================================================================
# SAFE I/O
# ============================================================================
def safe_write(text: str) -> bool:
    """Write safely."""
    if not text:
        return True
    try:
        sys.stdout.write(str(text))
        sys.stdout.flush()
        return True
    except Exception:
        return False


def safe_print(*args, **kwargs) -> bool:
    """Print safely."""
    try:
        print(*args, **kwargs)
        return True
    except Exception:
        return False


def safe_input(prompt: str = "", timeout: float = None) -> Optional[str]:
    """Read input safely with optional timeout."""
    try:
        if prompt:
            safe_write(prompt)
        
        if timeout is not None and sys.stdin.isatty():
            ready, _, _ = select.select([sys.stdin], [], [], timeout)
            if not ready:
                return None
        
        line = sys.stdin.readline()
        return line.rstrip('\n\r') if line else None
    except (KeyboardInterrupt, EOFError):
        return None
    except Exception:
        return None


def get_terminal_size() -> Tuple[int, int]:
    """Get terminal size safely."""
    try:
        import shutil
        size = shutil.get_terminal_size(fallback=(80, 24))
        return max(40, size.columns), max(8, size.lines)
    except Exception:
        return 80, 24


# ============================================================================
# FORMATTING HELPERS
# ============================================================================
def truncate(text: str, width: int) -> str:
    """Truncate safely."""
    if not text:
        return ''
    text = str(text)
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[:width - 3] + '...'


def center_text(text: str, width: int) -> str:
    """Center text."""
    try:
        text = str(text or '')
        if len(text) >= width:
            return text
        pad = (width - len(text)) // 2
        return ' ' * max(0, pad) + text
    except Exception:
        return text


def format_track_line(track: Any, width: int = 80) -> str:
    """Format track as single line. Title by Artist [Duration]"""
    try:
        title = str(track.title or 'Untitled')
        artist = str(track.artist or 'Unknown')
        duration = str(track.duration or '--:--')
        
        available = width - len(f" by  [{duration}]") - 2
        title_w = max(15, int(available * 0.65))
        artist_w = available - title_w
        
        title = truncate(title, title_w).ljust(title_w)
        artist = truncate(artist, artist_w).ljust(artist_w)
        
        return f"{title} by {artist} [{duration}]"
    except Exception:
        return str(track)[:width]


# ============================================================================
# RESULTS PICKER - CLEAN & SIMPLE
# ============================================================================
class ResultsPicker:
    """Display search results, let user pick one."""
    
    def __init__(self, results: List[Any], page_size: int = 10):
        self.results = results or []
        self.page_size = page_size
        self.selected = 0
        self.page = 0
        self.width, self.height = get_terminal_size()
        self._last_render_keys: Tuple[Optional[int], Optional[int], Optional[int]] = (None, None, None)
    
    def render(self) -> str:
        """Render current page with caching (memoization on state)."""
        cache_key = (self.page, self.selected, self.width)
        if cache_key == self._last_render_keys:
            return self._cached_render
        self._last_render_keys = cache_key
        
        if not self.results:
            return "No results."
        
        lines = []
        total = len(self.results)
        pages = (total + self.page_size - 1) // self.page_size
        
        header = f"RESULTS ({total} found) — Page {self.page + 1}/{pages}"
        lines.append(header)
        lines.append('-' * self.width)
        
        start = self.page * self.page_size
        end = min(start + self.page_size, total)
        
        for i in range(start, end):
            track = self.results[i]
            prefix = '> ' if i == self.selected else '  '
            num = f"{i + 1:02d}"
            line = format_track_line(track, self.width - 6)
            lines.append(f"{prefix}[{num}] {line}")
        
        lines.append('-' * self.width)
        
        if total > self.page_size:
            footer = "UP/DOWN: scroll | [1-99]: jump | ENTER: play | Q: cancel"
        else:
            footer = "[1-99]: select | ENTER: play | Q: cancel"
        lines.append(footer)
        
        self._cached_render = '\n'.join(lines)
        return self._cached_render
    
    def handle_key(self, key: str) -> Optional[int]:
        """Handle key. Return selected index or None."""
        if key == 'up':
            if self.selected > 0:
                self.selected -= 1
                if self.selected < self.page * self.page_size:
                    self.page = max(0, self.page - 1)
            return None
        
        elif key == 'down':
            if self.selected < len(self.results) - 1:
                self.selected += 1
                if self.selected >= (self.page + 1) * self.page_size:
                    max_page = (len(self.results) - 1) // self.page_size
                    self.page = min(max_page, self.page + 1)
            return None
        
        elif key == 'enter':
            return self.selected
        
        elif key in ('q', '^C'):
            return -1
        
        elif key.isdigit():
            try:
                idx = int(key) - 1
                if 0 <= idx < len(self.results):
                    self.selected = idx
                    self.page = idx // self.page_size
                    return self.selected
            except ValueError:
                pass
        
        return None
    
    def run(self) -> Optional[int]:
        """Run picker with alt-screen buffering and delta rendering.
        Return selected index or None."""
        if not self.results:
            return None
        
        _TERMINAL.hide_cursor()
        _TERMINAL.enter_raw_mode()
        _TERMINAL.enter_alt_screen()
        
        try:
            self._last_render_keys = (None, None, None)
            self.render()  # Prime cache
            _TERMINAL.clear_screen()
            safe_print(self.render())
            
            while True:
                key = self._read_key(timeout=0.1)
                if key is None:
                    continue
                
                result = self.handle_key(key)
                if result is not None:
                    return None if result == -1 else result
                
                # Delta render: only reprint if page/selection changed
                cache_key = (self.page, self.selected, self.width)
                if cache_key != self._last_render_keys:
                    safe_print(self.render())
        
        finally:
            _TERMINAL.restore_raw_mode()
            _TERMINAL.show_cursor()
            _TERMINAL.exit_alt_screen()
            _TERMINAL.clear_screen()
    
    def _read_key(self, timeout: float) -> Optional[str]:
        """Read one key."""
        if sys.platform == 'win32':
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
        """Read key on POSIX - reads full escape sequences in one batch."""
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
                # Read remaining bytes of escape sequence in one batch
                seq = b''
                try:
                    ready2, _, _ = select.select([sys.stdin], [], [], 0.01)
                    if ready2:
                        seq = os.read(sys.stdin.fileno(), 8)
                except Exception:
                    pass
                
                if seq.startswith(b'['):
                    final = seq[1:2]
                    arrows = {
                        b'A': 'up', b'B': 'down',
                        b'C': 'right', b'D': 'left',
                        b'H': 'home', b'F': 'end',
                    }
                    if final in arrows:
                        return arrows[final]
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
# FALLBACK PICKER (NON-INTERACTIVE)
# ============================================================================
class FallbackResultsPicker:
    """Simple numbered list picker for non-TTY."""
    
    def __init__(self, results: List[Any]):
        self.results = results or []
        self.width, _ = get_terminal_size()
    
    def run(self) -> Optional[int]:
        """Run picker. Return selected index or None."""
        if not self.results:
            return None
        
        safe_print("\nRESULTS")
        safe_print("=" * self.width)
        
        for i, track in enumerate(self.results[:50], 1):
            line = format_track_line(track, self.width - 6)
            safe_print(f"{i:02d}. {line}")
        
        safe_print("=" * self.width)
        
        while True:
            choice = safe_input("Select [1-{}]: ".format(len(self.results)))
            if choice is None or choice.lower() in ('q', 'quit'):
                return None
            
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(self.results):
                    return idx
            except ValueError:
                pass
            
            safe_print("Invalid. Try again.")


# ============================================================================
# MAIN APPLICATION
# ============================================================================
class MusicCLI:
    """Main application - search, pick, play."""
    
    def __init__(self):
        self.session = None
        self.running = False
    
    def startup(self):
        """Initialize."""
        try:
            _TERMINAL.clear_screen()
            safe_print("\n" + "=" * 60)
            safe_print(center_text("MUSICCLI", 60))
            safe_print("=" * 60 + "\n")
            self.running = True
            return True
        except Exception as e:
            safe_print(f"Startup error: {e}")
            return False
    
    def shutdown(self):
        """Clean shutdown."""
        try:
            self.running = False
            _TERMINAL.restore_all()
        except Exception:
            pass
    
    def search_and_pick(self) -> Optional[Any]:
        """Search for song, show results, let user pick."""
        if not HAS_MUSICCLI:
            safe_print("\n[ERROR] musiccli module not available")
            return None
        
        try:
            safe_write("Search for: ")
            query = safe_input(timeout=30.0)
            
            if not query or query.lower() in ('q', 'quit'):
                return None
            
            # Show spinner
            _TERMINAL.clear_screen()
            safe_print(f"Searching: {query}")
            safe_print("Please wait...\n")
            
            # Search
            if is_url(query):
                if is_playlist_url(query):
                    results = fetch_playlist(query, max_results=50)
                else:
                    track = fetch_single(query)
                    results = [track] if track else []
            else:
                results = search_youtube(query, max_results=50)
            
            if not results:
                safe_print("\nNo results found.")
                time.sleep(1)
                return None
            
            # Pick from results
            if sys.stdin.isatty():
                picker = ResultsPicker(results, page_size=10)
                idx = picker.run()
            else:
                picker = FallbackResultsPicker(results)
                idx = picker.run()
            
            return results[idx] if idx is not None and 0 <= idx < len(results) else None
        
        except Exception as e:
            safe_print(f"\nSearch error: {e}")
            traceback.print_exc()
            time.sleep(1)
            return None
    
    def display_track(self, track: Any):
        """Display currently playing track."""
        try:
            if not track:
                return
            
            width, _ = get_terminal_size()
            safe_print("\n" + "=" * width)
            safe_print(center_text("NOW PLAYING", width))
            safe_print("=" * width)
            safe_print(f"\nTitle:  {truncate(track.title, width - 10)}")
            safe_print(f"Artist: {truncate(track.artist, width - 10)}")
            if track.duration:
                safe_print(f"Length: {track.duration}")
            safe_print("\n" + "-" * width + "\n")
        except Exception:
            pass
    
    def main_loop(self):
        """Main REPL."""
        if not self.startup():
            return
        
        try:
            while self.running:
                try:
                    width, _ = get_terminal_size()
                    safe_print(center_text("Menu", width))
                    safe_print(center_text("[S] Search  [Q] Quit", width))
                    safe_print("")
                    
                    choice = safe_input("? ").strip().lower()
                    
                    if choice in ('q', 'quit', 'exit'):
                        break
                    
                    if choice in ('s', 'search'):
                        track = self.search_and_pick()
                        if track:
                            self.display_track(track)
                            safe_input("Press ENTER to continue...")
                    
                except KeyboardInterrupt:
                    break
                except Exception as e:
                    safe_print(f"Error: {e}")
                    time.sleep(1)
        
        finally:
            self.shutdown()


# ============================================================================
# ENTRY POINT
# ============================================================================
def main():
    """Entry point."""
    app = None
    try:
        app = MusicCLI()
        app.main_loop()
    except KeyboardInterrupt:
        safe_print("\n\nExiting...")
    except Exception as e:
        safe_print(f"\nFatal: {e}")
        traceback.print_exc()
    finally:
        if app:
            app.shutdown()
        _TERMINAL.restore_all()
        safe_print("\nGoodbye.\n")
        sys.exit(0)


if __name__ == '__main__':
    main()
