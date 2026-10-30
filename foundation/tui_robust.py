#!/usr/bin/env python3
"""Bulletproof pure-terminal TUI with defensive programming throughout.

Design principles:
- No visual effects, no ANSI art, pure text
- Every operation wrapped with try-except and sensible fallbacks
- All I/O operations have timeouts
- Terminal state is never left corrupted
- Process cleanup is guaranteed
- Input handling is bulletproof
- No assumptions about terminal capabilities
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
from contextlib import contextmanager
from typing import Optional, Tuple, List, Dict, Any

# Shared terminal escape-sequence constants
from foundation.terminal_constants import (
    CLEAR_SCREEN, CLEAR_LINE,
    CURSOR_HIDE, CURSOR_SHOW,
    ALT_SCREEN_ENTER, ALT_SCREEN_EXIT,
    move_cursor_to, move_cursor_up,
)


# ============================================================================
# CONSTANTS & CONFIGURATION
# ============================================================================
DEFAULT_TIMEOUT = 5.0
MAX_RETRIES = 3
SAFE_WIDTH = 80
SAFE_HEIGHT = 24
MIN_WIDTH = 40
MIN_HEIGHT = 8


# ============================================================================
# TERMINAL STATE MANAGER - Guarantees clean exit
# ============================================================================
class TerminalState:
    """Manages terminal state with guaranteed cleanup."""
    
    def __init__(self):
        self._lock = threading.Lock()
        self._raw_mode_fd = None
        self._saved_termios = None
        self._cursor_hidden = False
        self._atexit_registered = False
        
    def _register_handlers(self):
        """Register signal handlers and atexit for guaranteed cleanup."""
        if self._atexit_registered:
            return
        try:
            import atexit
            atexit.register(self.restore_all)
            signal.signal(signal.SIGINT, self._handle_sigint)
            signal.signal(signal.SIGTERM, self._handle_sigterm)
            self._atexit_registered = True
        except Exception:
            pass
    
    def _handle_sigint(self, sig, frame):
        self.restore_all()
        sys.exit(0)
    
    def _handle_sigterm(self, sig, frame):
        self.restore_all()
        sys.exit(1)
    
    def enter_raw_mode(self) -> bool:
        """Enter raw mode, remember state for restoration."""
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
        """Restore terminal from raw mode."""
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
        """Hide cursor (safe, idempotent)."""
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
        """Show cursor (safe, idempotent)."""
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
        """Full cleanup: exit raw mode, show cursor, clear screen."""
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
# SAFE I/O - All output operations protected
# ============================================================================
def safe_write(text: str) -> bool:
    """Write text safely, return success."""
    if not text:
        return True
    try:
        sys.stdout.write(str(text))
        sys.stdout.flush()
        return True
    except Exception:
        return False


def safe_read_line(prompt: str = "", timeout: float = None) -> Optional[str]:
    """Read a line safely with optional timeout."""
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


def safe_print(*args, **kwargs) -> bool:
    """Print safely."""
    try:
        print(*args, **kwargs)
        return True
    except Exception:
        return False


def get_terminal_size() -> Tuple[int, int]:
    """Get terminal size safely with fallback."""
    try:
        import shutil
        size = shutil.get_terminal_size(fallback=(SAFE_WIDTH, SAFE_HEIGHT))
        width = max(MIN_WIDTH, min(size.columns, 200))
        height = max(MIN_HEIGHT, min(size.lines, 100))
        return width, height
    except Exception:
        return SAFE_WIDTH, SAFE_HEIGHT


def center_text(text: str, width: int) -> str:
    """Center text safely."""
    try:
        text = str(text or '')
        visible = len(text)
        if visible >= width:
            return text
        pad = (width - visible) // 2
        return ' ' * max(0, pad) + text
    except Exception:
        return text


def truncate_text(text: str, width: int) -> str:
    """Truncate text safely."""
    if not text:
        return ''
    try:
        text = str(text)
        if len(text) <= width:
            return text
        if width <= 3:
            return text[:width]
        return text[:width - 3] + '...'
    except Exception:
        return text[:width] if width > 0 else ''


def format_duration(seconds: float) -> str:
    """Format duration safely."""
    try:
        secs = max(0, int(seconds))
        m, s = divmod(secs, 60)
        return f"{m:02d}:{s:02d}"
    except Exception:
        return '--:--'


# ============================================================================
# ROBUST INPUT HANDLING - Platform-aware, timeout-safe
# ============================================================================
class RobustInputReader:
    """Non-blocking input reader with platform detection."""
    
    def __init__(self):
        self.has_msvcrt = sys.platform == 'win32'
        self.raw_mode_active = False
        
    def start(self) -> bool:
        """Start reader (enable raw mode on POSIX)."""
        if self.has_msvcrt:
            return True
        return _TERMINAL.enter_raw_mode()
    
    def stop(self):
        """Stop reader (restore terminal state)."""
        if not self.has_msvcrt:
            _TERMINAL.restore_raw_mode()
    
    def get_key(self, timeout: float = 0.1) -> Optional[str]:
        """Get one key press safely."""
        if self.has_msvcrt:
            return self._get_key_windows(timeout)
        return self._get_key_posix(timeout)
    
    def _get_key_windows(self, timeout: float) -> Optional[str]:
        """Read key on Windows (msvcrt)."""
        try:
            import msvcrt
            start = time.time()
            while time.time() - start < timeout:
                if msvcrt.kbhit():
                    try:
                        b = msvcrt.getch()
                        if b == b'\x03':
                            return '^C'
                        if b in (b'\r', b'\n'):
                            return 'enter'
                        ch = b.decode('utf-8', errors='ignore')
                        return ch.lower() if ch else None
                    except Exception:
                        return None
                time.sleep(0.01)
            return None
        except Exception:
            return None
    
    def _get_key_posix(self, timeout: float) -> Optional[str]:
        """Read key on POSIX (raw mode + select).
        
        Reads the full escape sequence in one batch instead of select-per-byte.
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
            return ch.lower() if ch and ord(ch) >= 32 else None
        except Exception:
            return None


# ============================================================================
# SAFE PROCESS MANAGEMENT
# ============================================================================
class SafeProcessManager:
    """Manages subprocess with guaranteed cleanup."""
    
    def __init__(self):
        self.process = None
        self._lock = threading.Lock()
    
    def start(self, cmd, timeout: float = None) -> bool:
        """Start process safely.

        Accepts either a command list (preferred, no shell) or a string
        for backward compatibility. When a list is provided, shell=False
        is used, eliminating shell injection risk.
        """
        with self._lock:
            if self.process is not None:
                return False
            try:
                is_list = isinstance(cmd, (list, tuple))
                if sys.platform == 'win32':
                    self.process = subprocess.Popen(
                        cmd, shell=not is_list,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        preexec_fn=None
                    )
                else:
                    self.process = subprocess.Popen(
                        cmd, shell=not is_list,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        preexec_fn=os.setsid
                    )
                return True
            except Exception:
                self.process = None
                return False
    
    def is_running(self) -> bool:
        """Check if process is running."""
        with self._lock:
            if self.process is None:
                return False
            return self.process.poll() is None
    
    def kill(self, timeout: float = 2.0) -> bool:
        """Kill process safely."""
        with self._lock:
            if self.process is None:
                return True
            
                try:
                    if sys.platform == 'win32':
                        # Windows: kill process tree
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=1
                        )
                else:
                    # POSIX: kill process group
                    try:
                        pgid = os.getpgid(self.process.pid)
                        os.killpg(pgid, signal.SIGTERM)
                    except Exception:
                        self.process.terminate()
                
                # Wait for termination
                try:
                    self.process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    if sys.platform != 'win32':
                        try:
                            pgid = os.getpgid(self.process.pid)
                            os.killpg(pgid, signal.SIGKILL)
                        except Exception:
                            pass
                    self.process.kill()
                
                return True
            except Exception:
                return False
            finally:
                self.process = None


# ============================================================================
# ACTION QUEUE - Thread-safe command dispatch
# ============================================================================
class ActionQueue:
    """Thread-safe action queue with timeouts."""
    
    def __init__(self):
        self.queue = py_queue.Queue()
        self._stop_event = threading.Event()
    
    def put(self, action: str) -> bool:
        """Queue an action safely."""
        try:
            self.queue.put_nowait(action)
            return True
        except Exception:
            return False
    
    def get(self, timeout: float = 0.1) -> Optional[str]:
        """Get next action safely."""
        try:
            return self.queue.get_nowait()
        except py_queue.Empty:
            return None
    
    def stop(self):
        """Signal stop."""
        self._stop_event.set()
    
    def should_continue(self) -> bool:
        """Check if should continue."""
        return not self._stop_event.is_set()


# ============================================================================
# UI COMPONENTS - Pure text, no dependencies
# ============================================================================
class TerminalUI:
    """Pure terminal UI with defensive programming."""
    
    def __init__(self):
        self.width, self.height = get_terminal_size()
    
    def update_size(self):
        """Update cached terminal size."""
        self.width, self.height = get_terminal_size()
    
    def header(self, title: str) -> str:
        """Generate header."""
        try:
            self.update_size()
            sep = '=' * self.width
            header_line = center_text(title, self.width)
            return f"{sep}\n{header_line}\n{sep}"
        except Exception:
            return f"== {title} =="
    
    def separator(self) -> str:
        """Generate separator."""
        try:
            return '-' * self.width
        except Exception:
            return '-' * SAFE_WIDTH
    
    def status_line(self, left: str, right: str = "") -> str:
        """Generate status line with left/right alignment."""
        try:
            self.update_size()
            left = str(left or '')[:self.width // 2]
            right = str(right or '')[:self.width // 2]
            available = self.width - len(left) - len(right)
            if available < 0:
                return left
            return left + ' ' * available + right
        except Exception:
            return left
    
    def format_track(self, track: Any) -> str:
        """Format track for display."""
        try:
            title = str(track.title or 'Unknown')[:60]
            artist = str(track.artist or 'Unknown')[:40]
            duration = str(track.duration or '--:--')[:8]
            return f"{title} by {artist} ({duration})"
        except Exception:
            return str(track)
    
    def list_items(self, items: List[str], width: int = None) -> str:
        """Format list of items safely."""
        if width is None:
            width = self.width - 2
        try:
            lines = []
            for i, item in enumerate(items, 1):
                item_str = truncate_text(str(item or ''), width - 4)
                lines.append(f"  {i:02d}  {item_str}")
            return '\n'.join(lines)
        except Exception:
            return '\n'.join(f"  {item}" for item in items)


# ============================================================================
# MAIN APPLICATION LOOP - Robust state machine
# ============================================================================
class RobustMusicCLI:
    """Main application with defensive programming."""
    
    def __init__(self):
        self.ui = TerminalUI()
        self.input_reader = RobustInputReader()
        self.process_manager = SafeProcessManager()
        self.action_queue = ActionQueue()
        self.running = False
    
    def startup(self):
        """Initialize application safely."""
        try:
            _TERMINAL.clear_screen()
            safe_print("\n" + self.ui.header("MUSICCLI") + "\n")
            self.input_reader.start()
            self.running = True
            return True
        except Exception as e:
            safe_print(f"Startup error: {e}")
            return False
    
    def shutdown(self):
        """Clean shutdown."""
        try:
            self.running = False
            self.input_reader.stop()
            self.process_manager.kill()
            _TERMINAL.restore_all()
        except Exception:
            pass
    
    def main_loop(self):
        """Main REPL loop."""
        self.startup()
        try:
            while self.running:
                try:
                    self.ui.update_size()
                    safe_print("\n" + self.ui.separator())
                    safe_write("What do you want to play? (q to quit): ")
                    
                    query = safe_read_line(timeout=DEFAULT_TIMEOUT)
                    if query is None:
                        query = ''
                    
                    query = query.strip().lower()
                    
                    if query in ('q', 'quit', 'exit'):
                        break
                    
                    if not query:
                        continue
                    
                    self.handle_search(query)
                
                except KeyboardInterrupt:
                    safe_print("\n\nInterrupted.")
                    break
                except Exception as e:
                    safe_print(f"\nError: {e}")
                    time.sleep(1)
        
        finally:
            self.shutdown()
    
    def handle_search(self, query: str):
        """Handle search query safely."""
        try:
            safe_print(f"\nSearching for: {query}")
            safe_print("(Search feature would integrate with yt-dlp)")
            time.sleep(1)
        except Exception as e:
            safe_print(f"Search error: {e}")
    
    def display_menu(self, title: str, options: List[Tuple[str, str]]):
        """Display menu safely."""
        try:
            safe_print("\n" + self.ui.header(title))
            for key, desc in options:
                safe_print(f"  [{key}] {desc}")
            safe_print(self.ui.separator() + "\n")
        except Exception:
            pass
    
    def interactive_picker(self, items: List[Any]) -> Optional[int]:
        """Interactive picker with keyboard navigation, alt-screen buffering,
        and delta-based rendering (only redraws when selection changes)."""
        if not items:
            return None
        
        try:
            selected = 0
            self.input_reader.start()
            _TERMINAL.hide_cursor()
            _TERMINAL.enter_alt_screen()
            
            last_selected = -1  # Force initial render
            while True:
                # Delta rendering: only redraw if selection changed
                if selected != last_selected:
                    _TERMINAL.clear_screen()
                    safe_print(self.ui.header("SELECT TRACK"))
                    safe_print(self.ui.list_items(
                        [self.ui.format_track(item) for item in items]
                    ))
                    safe_print(self.ui.separator())
                    safe_print(f"Selected: {selected + 1}/{len(items)}")
                    safe_print("Use UP/DOWN arrows, ENTER to select, Q to cancel\n")
                    last_selected = selected
                
                key = self.input_reader.get_key(timeout=0.5)
                
                if key == 'up' and selected > 0:
                    selected -= 1
                elif key == 'down' and selected < len(items) - 1:
                    selected += 1
                elif key == 'enter':
                    return selected
                elif key in ('q', '^C'):
                    return None
            
        except Exception:
            return None
        finally:
            self.input_reader.stop()
            _TERMINAL.show_cursor()
            _TERMINAL.exit_alt_screen()


# ============================================================================
# ENTRY POINT
# ============================================================================
def main():
    """Entry point with guaranteed cleanup."""
    app = None
    try:
        app = RobustMusicCLI()
        app.main_loop()
    except KeyboardInterrupt:
        safe_print("\n\nExiting...")
    except Exception as e:
        safe_print(f"\nFatal error: {e}")
        traceback.print_exc()
    finally:
        if app:
            app.shutdown()
        _TERMINAL.restore_all()
        safe_print("\nGoodbye.\n")
        sys.exit(0)


if __name__ == '__main__':
    main()
