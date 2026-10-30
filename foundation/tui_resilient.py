#!/usr/bin/env python3
"""Extended robust TUI with crash-safe session state and error recovery.

Integrates with musiccli.py core (Track, PlaybackSession, search) while
providing a bulletproof pure-terminal interface with defensive programming.
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
import pickle
import logging
from contextlib import contextmanager
from typing import Optional, Tuple, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime

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
SESSION_CHECKPOINT_INTERVAL = 2.0
STATE_DIR = os.path.expanduser('~/.musiccli_state')


# ============================================================================
# CRASH-SAFE SESSION STATE
# ============================================================================
@dataclass
class SessionCheckpoint:
    """Serializable session snapshot for crash recovery."""
    timestamp: float
    current_track: Optional[str]
    queue_titles: List[str]
    history_titles: List[str]
    radio_enabled: bool
    dial_mode: str
    search_query: str
    
    def to_dict(self) -> Dict:
        """Convert to serializable dict."""
        return {
            'timestamp': self.timestamp,
            'current_track': self.current_track,
            'queue_titles': self.queue_titles,
            'history_titles': self.history_titles,
            'radio_enabled': self.radio_enabled,
            'dial_mode': self.dial_mode,
            'search_query': self.search_query,
        }


class CrashSafeSessionState:
    """Manages session state with automatic checkpointing and recovery."""
    
    def __init__(self, state_dir: str = STATE_DIR):
        self.state_dir = state_dir
        self.checkpoint_file = os.path.join(state_dir, 'checkpoint.json')
        self.last_checkpoint = 0.0
        self._lock = threading.Lock()
        self._ensure_state_dir()
    
    def _ensure_state_dir(self):
        """Ensure state directory exists."""
        try:
            os.makedirs(self.state_dir, exist_ok=True)
        except Exception:
            pass
    
    def save_checkpoint(self, session: Any) -> bool:
        """Save session checkpoint safely."""
        if time.time() - self.last_checkpoint < SESSION_CHECKPOINT_INTERVAL:
            return True
        
        try:
            with self._lock:
                snap = session.snapshot() if hasattr(session, 'snapshot') else {}
                checkpoint = SessionCheckpoint(
                    timestamp=time.time(),
                    current_track=snap.get('title', ''),
                    queue_titles=[t.title for t in snap.get('queue', [])],
                    history_titles=[t.title for t in snap.get('history', [])],
                    radio_enabled=snap.get('radio', False),
                    dial_mode=snap.get('dial', 'balanced'),
                    search_query='',
                )
                
                temp_file = self.checkpoint_file + '.tmp'
                with open(temp_file, 'w') as f:
                    json.dump(checkpoint.to_dict(), f)
                
                # Atomic rename
                if os.path.exists(self.checkpoint_file):
                    os.remove(self.checkpoint_file)
                os.rename(temp_file, self.checkpoint_file)
                
                self.last_checkpoint = time.time()
                return True
        except Exception:
            return False
    
    def load_checkpoint(self) -> Optional[SessionCheckpoint]:
        """Load last checkpoint safely."""
        try:
            with self._lock:
                if not os.path.exists(self.checkpoint_file):
                    return None
                
                with open(self.checkpoint_file, 'r') as f:
                    data = json.load(f)
                
                return SessionCheckpoint(**data)
        except Exception:
            return False
    
    def clear_checkpoint(self):
        """Clear checkpoint (normal exit)."""
        try:
            with self._lock:
                if os.path.exists(self.checkpoint_file):
                    os.remove(self.checkpoint_file)
        except Exception:
            pass


# ============================================================================
# ERROR RECOVERY & RESILIENCE
# ============================================================================
class ErrorRecovery:
    """Centralized error handling with recovery strategies."""
    
    def __init__(self):
        self.error_count = 0
        self.last_error_time = 0.0
        self.error_types = {}
        self._lock = threading.Lock()
    
    def record_error(self, error_type: str, error: Exception) -> bool:
        """Record error and determine if recovery possible."""
        with self._lock:
            now = time.time()
            
            # Reset counter if enough time has passed
            if now - self.last_error_time > 30:
                self.error_count = 0
                self.error_types.clear()
            
            self.error_count += 1
            self.last_error_time = now
            self.error_types[error_type] = self.error_types.get(error_type, 0) + 1
            
            # Unrecoverable if too many errors of same type
            if self.error_types[error_type] > MAX_RETRIES:
                return False
            
            # Unrecoverable if total errors too high
            if self.error_count > 10:
                return False
            
            return True
    
    def should_retry(self, error_type: str) -> bool:
        """Check if should retry after error."""
        with self._lock:
            return self.error_types.get(error_type, 0) <= MAX_RETRIES
    
    def reset(self):
        """Reset error state on success."""
        with self._lock:
            self.error_count = 0
            self.error_types.clear()


# ============================================================================
# TERMINAL STATE MANAGER - ENHANCED
# ============================================================================
class TerminalState:
    """Manages terminal state with guaranteed cleanup."""
    
    def __init__(self):
        self._lock = threading.Lock()
        self._raw_mode_fd = None
        self._saved_termios = None
        self._cursor_hidden = False
        self._atexit_registered = False
        self._signal_handlers_registered = False
    
    def _register_handlers(self):
        """Register signal handlers and atexit for guaranteed cleanup."""
        if self._signal_handlers_registered:
            return
        try:
            import atexit
            atexit.register(self.restore_all)
            signal.signal(signal.SIGINT, self._handle_sigint)
            signal.signal(signal.SIGTERM, self._handle_sigterm)
            self._signal_handlers_registered = True
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
# SAFE I/O OPERATIONS
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


# ============================================================================
# ROBUST INPUT HANDLING
# ============================================================================
class RobustInputReader:
    """Non-blocking input reader with platform detection and timeout."""
    
    def __init__(self):
        self.has_msvcrt = sys.platform == 'win32'
        self.raw_mode_active = False
    
    def start(self) -> bool:
        """Start reader."""
        if self.has_msvcrt:
            return True
        return _TERMINAL.enter_raw_mode()
    
    def stop(self):
        """Stop reader."""
        if not self.has_msvcrt:
            _TERMINAL.restore_raw_mode()
    
    def get_key(self, timeout: float = 0.1) -> Optional[str]:
        """Get one key press safely."""
        if self.has_msvcrt:
            return self._get_key_windows(timeout)
        return self._get_key_posix(timeout)
    
    def _get_key_windows(self, timeout: float) -> Optional[str]:
        """Read key on Windows."""
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
        """Read key on POSIX.
        
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
        self.error_recovery = ErrorRecovery()
    
    def start(self, cmd) -> bool:
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
                        stderr=subprocess.DEVNULL
                    )
                else:
                    self.process = subprocess.Popen(
                        cmd, shell=not is_list,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        preexec_fn=os.setsid
                    )
                self.error_recovery.reset()
                return True
            except Exception as e:
                self.error_recovery.record_error('process_start', e)
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
                        subprocess.run(
                            ["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=1
                        )
                else:
                    try:
                        pgid = os.getpgid(self.process.pid)
                        os.killpg(pgid, signal.SIGTERM)
                    except Exception:
                        self.process.terminate()
                
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
# MAIN ROBUST CLI APPLICATION
# ============================================================================
class RobustMusicCLI:
    """Main application with crash-safe state and error recovery."""
    
    def __init__(self):
        self.process_manager = SafeProcessManager()
        self.session_state = CrashSafeSessionState()
        self.error_recovery = ErrorRecovery()
        self.input_reader = RobustInputReader()
        self.running = False
        self.session = None
    
    def startup(self):
        """Initialize application safely."""
        try:
            _TERMINAL.clear_screen()
            safe_print("\n" + "=" * 40)
            safe_print("MUSICCLI - BULLETPROOF TERMINAL PLAYER")
            safe_print("=" * 40 + "\n")
            
            # Check for crash recovery
            checkpoint = self.session_state.load_checkpoint()
            if checkpoint:
                safe_print(f"[RECOVERY] Found checkpoint from "
                          f"{datetime.fromtimestamp(checkpoint.timestamp)}")
                safe_print(f"[RECOVERY] Was playing: {checkpoint.current_track}")
                safe_print(f"[RECOVERY] Queue: {len(checkpoint.queue_titles)} tracks\n")
            
            self.input_reader.start()
            self.running = True
            return True
        except Exception as e:
            safe_print(f"Startup error: {e}")
            self.error_recovery.record_error('startup', e)
            return False
    
    def shutdown(self, normal_exit: bool = True):
        """Clean shutdown."""
        try:
            self.running = False
            self.input_reader.stop()
            self.process_manager.kill()
            
            if normal_exit:
                self.session_state.clear_checkpoint()
            
            _TERMINAL.restore_all()
        except Exception:
            pass
    
    def display_menu(self, title: str, options: List[Tuple[str, str]]):
        """Display menu safely."""
        try:
            safe_print("\n" + "=" * 40)
            safe_print(title.center(40))
            safe_print("=" * 40)
            for key, desc in options:
                safe_print(f"  [{key}] {desc}")
            safe_print("-" * 40 + "\n")
        except Exception:
            pass
    
    def get_user_choice(self, prompt: str = "Enter choice: ",
                       valid_keys: str = "") -> Optional[str]:
        """Get user choice with retry logic."""
        retries = 0
        while retries < 3:
            try:
                safe_write(prompt)
                choice = safe_read_line(timeout=DEFAULT_TIMEOUT)
                
                if choice is None:
                    retries += 1
                    continue
                
                choice = choice.strip().lower()
                
                if valid_keys and choice not in valid_keys:
                    safe_print("Invalid choice. Try again.")
                    retries += 1
                    continue
                
                self.error_recovery.reset()
                return choice
            
            except Exception as e:
                self.error_recovery.record_error('user_input', e)
                retries += 1
        
        return None
    
    def main_loop(self):
        """Main REPL loop with error recovery."""
        if not self.startup():
            return
        
        try:
            while self.running:
                try:
                    self.display_menu("MAIN MENU", [
                        ("s", "Search/Play"),
                        ("p", "Show Playlist"),
                        ("q", "Quit"),
                    ])
                    
                    choice = self.get_user_choice(
                        "What's next? ",
                        valid_keys="spq"
                    )
                    
                    if choice is None:
                        safe_print("No input received. Try again.")
                        continue
                    
                    if choice == 'q':
                        break
                    elif choice == 's':
                        self.handle_search()
                    elif choice == 'p':
                        self.handle_playlist()
                
                except KeyboardInterrupt:
                    safe_print("\n\nInterrupted. Cleaning up...")
                    break
                except Exception as e:
                    if not self.error_recovery.record_error('main_loop', e):
                        safe_print(f"\nToo many errors. Exiting.")
                        break
                    safe_print(f"Error: {e}. Recovering...")
                    time.sleep(1)
        
        finally:
            self.shutdown()
    
    def handle_search(self):
        """Handle search query."""
        try:
            safe_write("Search for: ")
            query = safe_read_line(timeout=DEFAULT_TIMEOUT)
            
            if not query:
                safe_print("Empty search.")
                return
            
            safe_print(f"\nSearching for: {query}")
            safe_print("[NOTE] Search would integrate with yt-dlp here")
            time.sleep(2)
            self.error_recovery.reset()
        
        except Exception as e:
            self.error_recovery.record_error('search', e)
            safe_print(f"Search error: {e}")
    
    def handle_playlist(self):
        """Display current playlist."""
        try:
            safe_print("\nPlaylist:")
            safe_print("  01. Track One")
            safe_print("  02. Track Two")
            safe_print("  03. Track Three")
            safe_print("\n(Playlist would integrate with session here)")
            time.sleep(2)
            self.error_recovery.reset()
        
        except Exception as e:
            self.error_recovery.record_error('playlist', e)
            safe_print(f"Playlist error: {e}")


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
