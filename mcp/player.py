"""Controllable Audio Player Engine for Musicly MCP Server.

Provides process-group signal control (SIGSTOP/SIGCONT) for pause/resume,
volume level management, state tracking, and track end callbacks.
"""

import os
import signal
import subprocess
import time
import threading
from typing import Optional, Dict, Any, Callable


class AudioPlayer:
    # Short window after spawn where a player exit means "startup failed"
    # rather than "track ended naturally".
    STARTUP_GRACE_SECONDS = 6.0

    def __init__(self):
        self._proc: Optional[subprocess.Popen] = None
        self._pgid: Optional[int] = None
        self._current_track: Optional[Dict[str, Any]] = None
        self._state: str = "STOPPED"  # STOPPED, PLAYING, PAUSED
        self._start_time: float = 0
        self._pause_start_time: float = 0
        self._total_paused_duration: float = 0
        self._user_stopped: bool = False
        self._lock = threading.Lock()
        self._monitor_thread: Optional[threading.Thread] = None
        self._on_track_end_cb: Optional[Callable[[], None]] = None
        self._last_error: Optional[str] = None
        self._volume: int = self._read_system_volume()

    def set_track_end_callback(self, cb: Callable[[], None]) -> None:
        self._on_track_end_cb = cb

    def _read_system_volume(self) -> int:
        """Read the real system sink volume (0-100) so status reflects reality."""
        try:
            out = subprocess.run(
                ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                capture_output=True, text=True, timeout=3.0,
            ).stdout
            # e.g. "Volume: 0.32" or "Volume: 0.32 [MUTED]"
            if "Volume:" in out:
                val = out.split("Volume:")[-1].split()[0].strip()
                return max(0, min(100, round(float(val) * 100)))
        except Exception:
            pass
        try:
            out = subprocess.run(
                ["amixer", "sget", "Master"],
                capture_output=True, text=True, timeout=3.0,
            ).stdout
            # e.g. "Front Left: Playback 21157 [32%] [on]"
            import re as _re
            m = _re.search(r"Playback\s+\d+\s+\[(\d+)%\]", out)
            if m:
                return max(0, min(100, int(m.group(1))))
        except Exception:
            pass
        return self._volume if hasattr(self, "_volume") else 80

    def play(self, track: Dict[str, Any]) -> tuple:
        """Start playback of a track.

        Returns (ok: bool, error: Optional[str]) instead of a bare bool so the
        caller/MCP can report why a track failed to play (e.g. YouTube 403).
        """
        self.stop()

        url = track.get("url")
        if not url:
            vid = track.get("id")
            if vid:
                url = f"https://www.youtube.com/watch?v={vid}"
            else:
                return False, "No track URL or ID provided."

        cmd = ["yt-dlp", "-f", "ba/b/18", "-o", "-", "--no-part", "--no-warnings", "--no-update", url]

        with self._lock:
            try:
                # Reset user_stopped flag before spawning new process
                self._user_stopped = False
                self._last_error = None
                ytdlp_proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    preexec_fn=os.setsid,
                )
                ffplay_proc = subprocess.Popen(
                    ["ffplay", "-nodisp", "-autoexit", "-volume", str(self._volume), "-"],
                    stdin=ytdlp_proc.stdout,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    preexec_fn=os.setsid,
                )
                ytdlp_proc.stdout.close()
                self._proc = ffplay_proc
                self._ytdlp_proc = ytdlp_proc
                self._pgid = os.getpgid(self._proc.pid)
                self._current_track = track
                self._state = "PLAYING"
                self._start_time = time.time()
                self._pause_start_time = 0
                self._total_paused_duration = 0
                self._startup_deadline = time.monotonic() + self.STARTUP_GRACE_SECONDS
                proc = self._proc
            except Exception as e:
                self._state = "STOPPED"
                return False, f"Failed to spawn player: {e}"

        # Start monitor thread to watch process termination
        self._monitor_thread = threading.Thread(target=self._monitor_process, args=(proc,), daemon=True)
        self._monitor_thread.start()
        return True, None

    def is_playing(self) -> bool:
        with self._lock:
            return self._state == "PLAYING"

    def get_startup_error(self) -> Optional[str]:
        """Return a failure reason captured during the startup window.

        Once the monitor thread sees the pipeline die early it records
        ``_last_error``; this simply surfaces it to the caller so the MCP can
        report why playback failed instead of claiming the track is playing.
        """
        with self._lock:
            return self._last_error

    def pause(self) -> bool:
        with self._lock:
            if self._state != "PLAYING" or not self._pgid:
                return False
            try:
                os.killpg(self._pgid, signal.SIGSTOP)
                self._state = "PAUSED"
                self._pause_start_time = time.time()
                return True
            except Exception:
                return False

    def resume(self) -> bool:
        with self._lock:
            if self._state != "PAUSED" or not self._pgid:
                return False
            try:
                os.killpg(self._pgid, signal.SIGCONT)
                self._state = "PLAYING"
                if self._pause_start_time > 0:
                    self._total_paused_duration += time.time() - self._pause_start_time
                    self._pause_start_time = 0
                return True
            except Exception:
                return False

    def stop(self) -> bool:
        with self._lock:
            self._user_stopped = True
            if self._proc and self._pgid:
                try:
                    os.killpg(self._pgid, signal.SIGTERM)
                    time.sleep(0.1)
                    if self._proc.poll() is None:
                        os.killpg(self._pgid, signal.SIGKILL)
                except Exception:
                    pass
            # Reap the yt-dlp child too so it doesn't become a zombie
            yt = getattr(self, "_ytdlp_proc", None)
            if yt:
                try:
                    if yt.poll() is None:
                        os.killpg(os.getpgid(yt.pid), signal.SIGTERM)
                    yt.wait(timeout=2.0)
                except Exception:
                    pass
                self._ytdlp_proc = None

            self._proc = None
            self._pgid = None
            self._current_track = None
            self._state = "STOPPED"
            self._start_time = 0
            self._pause_start_time = 0
            self._total_paused_duration = 0
            return True

    def set_volume(self, level: int) -> int:
        level = max(0, min(100, level))
        self._volume = level
        # Attempt PipeWire / WirePlumber volume adjustment if available
        try:
            subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{level/100:.2f}"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3.0)
        except Exception:
            try:
                subprocess.run(["amixer", "set", "Master", f"{level}%"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3.0)
            except Exception:
                pass
        # Report the value the system actually holds
        return self._read_system_volume()

    def get_status(self) -> Dict[str, Any]:
        with self._lock:
            elapsed = 0
            if self._state == "PLAYING" and self._start_time > 0:
                elapsed = int(time.time() - self._start_time - self._total_paused_duration)
            elif self._state == "PAUSED" and self._pause_start_time > 0:
                elapsed = int(self._pause_start_time - self._start_time - self._total_paused_duration)

            return {
                "state": self._state,
                "track": self._current_track,
                "elapsed_seconds": max(0, elapsed),
                "volume": self._read_system_volume(),
                "last_error": self._last_error,
            }

    def _read_ytdlp_stderr(self, max_wait: float = 1.0) -> str:
        """Read a bounded amount of yt-dlp stderr without blocking forever."""
        import select as _select
        yt = getattr(self, "_ytdlp_proc", None)
        if not yt or not yt.stderr:
            return ""
        try:
            r, _, _ = _select.select([yt.stderr], [], [], max_wait)
            if not r:
                return ""
            err = yt.stderr.read(2048)
            try:
                yt.wait(timeout=1.0)
            except Exception:
                pass
            self._ytdlp_proc = None
            return err.decode("utf-8", "replace").strip()[:500] if err else ""
        except Exception:
            return ""

    def _monitor_process(self, proc):
        if not proc:
            return
        proc.wait()

        should_trigger = False
        with self._lock:
            if not self._user_stopped and (self._proc == proc or self._proc is None):
                should_trigger = True
            if self._proc == proc:
                self._proc = None
                self._pgid = None
                self._state = "STOPPED"
                # Distinguish "startup failure" from a natural track end
                if not self._user_stopped and time.monotonic() < self._startup_deadline:
                    err = self._read_ytdlp_stderr()
                    self._last_error = err if err else "Audio stream ended before playback could start."

        if should_trigger and self._on_track_end_cb:
            try:
                self._on_track_end_cb()
            except Exception:
                pass
