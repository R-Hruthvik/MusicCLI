"""Singleton Background Daemon for Musicly.

Manages central playback, taste engine, and database state across multiple
concurrent AI agent sessions/tabs via Unix Domain Socket IPC.
"""

import os
import json
import time
import socket
import struct
import logging
import threading
from typing import Dict, Any, Optional

from foundation import search_songs, search_playlists
from .db import MusiclyDB
from .player import AudioPlayer
from .taste_engine import TasteEngine
from .slash_commands import SlashCommandHandler

SOCKET_PATH = os.path.expanduser("~/.config/musicly/musicly.sock")
LOCK_PATH = os.path.expanduser("~/.config/musicly/daemon.lock")


class MusiclyDaemon:
    def __init__(self, db_path: Optional[str] = None):
        self.db = MusiclyDB(db_path=db_path) if db_path else MusiclyDB()
        self.player = AudioPlayer()
        self.taste_engine = TasteEngine(db=self.db)
        self.slash_handler = SlashCommandHandler(self.taste_engine, self.player)

        self.last_user_activity = time.time()
        self.active_session_id = "default"
        self._lock = threading.Lock()

        # Wire Auto-DJ auto-advance callback
        self.player.set_track_end_callback(self._on_track_ended)

    def _on_track_ended(self):
        """Endless playlist auto-advance when a track finishes natively."""
        if self.taste_engine.endless_enabled:
            status = self.player.get_status()
            current_track = status.get("track")
            nxt = self.taste_engine.fetch_next_endless_track(current_track)
            if nxt:
                self.player.play(nxt)

    def handle_request(self, req: Dict[str, Any]) -> Dict[str, Any]:
        cmd = req.get("command")
        args = req.get("args", {})
        session_id = req.get("session_id", "default")
        is_user_initiated = req.get("user_initiated", True)

        with self._lock:
            if is_user_initiated:
                self.last_user_activity = time.time()
                self.active_session_id = session_id

        if cmd == "ping":
            return {"status": "ok", "message": "Musicly Daemon running."}

        elif cmd == "slash_command":
            res = self.slash_handler.handle_command(args.get("command", ""))
            return res

        elif cmd == "search":
            q = args.get("query", "")
            stype = args.get("type", "song")
            count = args.get("count", 10)
            if stype == "playlist":
                res = search_playlists(q, count=count)
            else:
                res = search_songs(q, count=count)
            return {"status": "ok", "results": res}

        elif cmd == "play":
            q = args.get("query", "")
            tid = args.get("track_id", "")
            track = None
            if tid:
                track = {"id": tid, "title": f"Track {tid}", "artist": "YouTube", "url": f"https://www.youtube.com/watch?v={tid}"}
            elif q:
                if q.startswith("http://") or q.startswith("https://"):
                    track = {"url": q, "title": "Web Stream", "artist": "YouTube"}
                else:
                    results = search_songs(q, count=1)
                    if results:
                        track = results[0]

            if not track:
                if self.player.get_status().get("state") == "PAUSED":
                    self.player.resume()
                    return {"status": "ok", "message": "Resumed audio playback."}
                return {"status": "error", "message": "No valid track found to play."}

            # Immediate playback: clear pending queue & start playing requested song immediately
            self.taste_engine.clear_queue()
            success, play_err = self.player.play(track)
            if success:
                # Set requested track as explicit pivot track for endless playlist
                self.taste_engine.set_explicit_pivot_track(track)
                # Short verification window: if yt-dlp dies immediately (e.g. YouTube 403),
                # surface the real error instead of claiming the track is playing.
                deadline = time.monotonic() + 3.0
                while time.monotonic() < deadline:
                    if not self.player.is_playing():
                        break
                    time.sleep(0.1)
                verr = self.player.get_startup_error()
                if verr:
                    success = False
                    play_err = verr
            return {"status": "ok" if success else "error", "track": track, "message": play_err}

        elif cmd == "pause":
            ok = self.player.pause()
            return {"status": "ok" if ok else "error", "message": "Audio paused." if ok else "Not playing."}

        elif cmd == "resume":
            ok = self.player.resume()
            return {"status": "ok" if ok else "error", "message": "Audio resumed." if ok else "Not paused."}

        elif cmd == "stop":
            self.taste_engine.clear_queue()
            self.player.stop()
            return {"status": "ok", "message": "Playback stopped and queue cleared."}

        elif cmd == "reset":
            self.player.stop()
            self.taste_engine.reset_session()
            return {"status": "ok", "message": "Playback session, queue, and taste cache reset."}

        elif cmd == "skip":
            current_status = self.player.get_status()
            current_track = current_status.get("track")
            self.player.stop()
            nxt = self.taste_engine.fetch_next_endless_track(current_track)
            if nxt:
                self.player.play(nxt)
                return {"status": "ok", "track": nxt}
            return {"status": "ok", "message": "Stopped. No more tracks in queue."}

        elif cmd == "set_volume":
            lvl = args.get("level", 80)
            res_lvl = self.player.set_volume(lvl)
            return {"status": "ok", "level": res_lvl}

        elif cmd == "get_feedback_history":
            limit = args.get("limit", 20)
            logs = self.db.get_raw_feedback_logs(limit=limit)
            return {"status": "ok", "feedback_logs": logs}

        elif cmd == "update_taste_analysis":
            sit = args.get("situation", self.taste_engine.current_situation)
            summary = args.get("preference_summary", "")
            top_genres = args.get("top_genres", [])
            disliked_themes = args.get("disliked_themes", [])
            conf = args.get("confidence_score", 0.8)
            record_id = self.db.save_taste_analysis(
                situation=sit,
                preference_summary=summary,
                top_genres=top_genres,
                disliked_themes=disliked_themes,
                confidence_score=conf
            )
            return {"status": "ok", "id": record_id, "situation": sit}

        elif cmd == "get_taste_analysis":
            sit = args.get("situation")
            analysis = self.db.get_taste_analysis(situation=sit)
            return {"status": "ok", "taste_analysis": analysis}

        elif cmd == "get_status":
            status = self.player.get_status()
            stats = self.db.get_feedback_summary()
            return {
                "status": "ok",
                "player_status": status,
                "autodj_enabled": self.taste_engine.autodj_enabled,
                "current_situation": self.taste_engine.current_situation,
                "active_session": self.active_session_id,
                "pivot_prompt_needed": self.taste_engine.pivot_prompt_needed,
                "active_pivot_genre": self.taste_engine.active_pivot_genre,
                "feedback_stats": stats
            }

        elif cmd == "feedback":
            action = args.get("action", "like")
            text_comment = args.get("feedback_text", "")
            tid = args.get("track_id")
            target_track = None
            if tid:
                target_track = self.db.get_track(tid)
            if not target_track:
                target_track = self.player.get_status().get("track")

            if not target_track:
                return {"status": "error", "message": "No active track to give feedback for."}

            res = self.taste_engine.record_feedback(target_track, action, feedback_text=text_comment)
            if action == "dislike":
                self.player.stop()
                nxt = self.taste_engine.fetch_next_autodj_track()
                if nxt:
                    self.player.play(nxt)

            return {"status": "ok", "feedback": res, "track": target_track}

        elif cmd == "trigger_situation":
            sit = args.get("situation", "general")
            auto_play = args.get("auto_play", True)

            # Focus & Anti-Thrashing check
            # Background autonomous tasks do NOT interrupt if user interacted recently (<90s)
            now = time.time()
            if not is_user_initiated and (now - self.last_user_activity) < 90 and self.player.get_status().get("state") == "PLAYING":
                # Soft update: set situation without mid-song cut off
                self.taste_engine.set_situation(sit)
                return {"status": "ok", "message": f"Situation set to '{sit}' (queued for next track)."}

            self.taste_engine.set_situation(sit)
            if auto_play:
                nxt = self.taste_engine.fetch_next_autodj_track()
                if nxt:
                    self.player.play(nxt)
                    return {"status": "ok", "situation": sit, "track": nxt}

            return {"status": "ok", "situation": sit}

        elif cmd == "add_trends":
            tracks = args.get("tracks", [])
            query = args.get("query", "")
            for tr in tracks:
                self.db.add_trend(tr, source="ai_agent_discovery", query=query)
            return {"status": "ok", "count": len(tracks)}

        return {"status": "error", "message": f"Unknown command: {cmd}"}

    def run_unix_socket_server(self, socket_path: str = SOCKET_PATH):
        os.makedirs(os.path.dirname(socket_path), exist_ok=True)
        if os.path.exists(socket_path):
            try:
                os.unlink(socket_path)
            except Exception:
                pass

        server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server_sock.bind(socket_path)
        server_sock.listen(10)

        logging.info(f"Musicly Daemon listening on {socket_path}")

        try:
            while True:
                conn, _ = server_sock.accept()
                threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()
        except KeyboardInterrupt:
            pass
        finally:
            server_sock.close()
            if os.path.exists(socket_path):
                os.unlink(socket_path)

    def _handle_client(self, conn: socket.socket):
        try:
            req = _recv_framed(conn)
            if req is not None:
                res = self.handle_request(req)
                _send_framed(conn, res)
        except Exception as e:
            err_res = {"status": "error", "message": str(e)}
            try:
                _send_framed(conn, err_res)
            except Exception:
                pass
        finally:
            conn.close()


def _recv_framed(sock: socket.socket, max_size: int = 10 * 1024 * 1024) -> Optional[Dict[str, Any]]:
    """Read a 4-byte length-prefixed JSON message from a socket.

    This avoids the partial-read / message-truncation problem where a single
    recv(65536) could return fewer bytes than the full message.
    """
    try:
        # Read 4-byte length header
        header = _recv_exact(sock, 4)
        if header is None:
            return None
        msg_len = struct.unpack(">I", header)[0]
        if msg_len > max_size:
            raise ValueError(f"Message too large: {msg_len} bytes (max {max_size})")
        # Read the remaining body
        body = _recv_exact(sock, msg_len)
        if body is None:
            return None
        return json.loads(body.decode("utf-8"))
    except Exception:
        return None


def _recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    """Read exactly n bytes from socket, looping until complete or connection closes."""
    chunks = []
    bytes_recd = 0
    while bytes_recd < n:
        chunk = sock.recv(n - bytes_recd)
        if not chunk:
            return None
        chunks.append(chunk)
        bytes_recd += len(chunk)
    return b"".join(chunks)


def _send_framed(sock: socket.socket, obj: Dict[str, Any]) -> None:
    """Send a 4-byte length-prefixed JSON message over a socket."""
    data = json.dumps(obj).encode("utf-8")
    sock.sendall(struct.pack(">I", len(data)))
    sock.sendall(data)


def send_daemon_request(req: Dict[str, Any], socket_path: str = SOCKET_PATH, timeout: float = 3.0) -> Optional[Dict[str, Any]]:
    if not os.path.exists(socket_path):
        return None
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect(socket_path)
        _send_framed(sock, req)
        res = _recv_framed(sock)
        sock.close()
        return res
    except Exception:
        return None


def main():
    daemon = MusiclyDaemon()
    daemon.run_unix_socket_server()


if __name__ == "__main__":
    main()
