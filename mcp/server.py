"""Musicly MCP Server implementation over JSON-RPC 2.0 STDIO.

Acts as an MCP front-end that routes tools and slash commands to the shared
Musicly Daemon (`mcp/daemon.py`) over a Unix Domain Socket IPC.
"""

import sys
import os
import json
import time
import subprocess
import logging
from typing import Dict, Any, List, Optional

from .daemon import send_daemon_request
from .instructions import ensure_agent_instructions

logging.basicConfig(level=logging.ERROR, stream=sys.stderr)


class MusiclyMCPServer:
    def __init__(self, session_id: str = "default_session"):
        self.session_id = session_id
        self.last_banner_time = 0
        self.banner_interval = 900  # Prompt periodically every 15 minutes
        ensure_agent_instructions()
        self._ensure_daemon_running()

    def _ensure_daemon_running(self):
        res = send_daemon_request({"command": "ping"}, timeout=1.0)
        if not res:
            # Clean up stale socket if daemon is not responding
            sock_path = os.path.expanduser("~/.config/musicly/musicly.sock")
            if os.path.exists(sock_path):
                try:
                    os.unlink(sock_path)
                except Exception:
                    pass
            # Spawn daemon in background
            try:
                env = os.environ.copy()
                cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                env["PYTHONPATH"] = cwd
                subprocess.Popen(
                    [sys.executable, "-m", "mcp.daemon"],
                    cwd=cwd,
                    env=env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True
                )
                time.sleep(1.0)
            except Exception as e:
                logging.error("Failed to spawn Musicly Daemon: %s", e)

    def execute_daemon_command(self, cmd: str, args: Dict[str, Any], user_initiated: bool = True) -> Dict[str, Any]:
        self._ensure_daemon_running()
        req = {
            "command": cmd,
            "args": args,
            "session_id": self.session_id,
            "user_initiated": user_initiated
        }
        res = send_daemon_request(req, timeout=35.0)
        if not res:
            return {"status": "error", "message": "Could not connect to Musicly Daemon."}
        return res

    def format_response_with_banner(self, text_content: str, force_banner: bool = False) -> str:
        """Inject compact, gentle Markdown banner periodically (or when forced)."""
        now = time.time()
        if not force_banner and (now - self.last_banner_time) < self.banner_interval:
            return text_content

        status_res = self.execute_daemon_command("get_status", {}, user_initiated=False)
        player_status = status_res.get("player_status", {})
        current_track = player_status.get("track")

        if not current_track:
            return text_content

        self.last_banner_time = now
        track_title = current_track.get("title", "Unknown")
        artist = current_track.get("artist", "Unknown Artist")
        duration = current_track.get("duration", "--:--")
        sit = status_res.get("current_situation", "general")
        autodj_status = "ON" if status_res.get("autodj_enabled") else "OFF"

        banner = (
            f"\n\n---\n"
            f"🎵 **Now Playing**: \"{track_title}\" by **{artist}** [{duration}]\n"
            f"🎯 **Situation**: `{sit}` | 🎵 **Endless Playlist**: `ACTIVE`\n"
            f"*Enjoying the vibe? Tune your taste anytime with `/like`, `/dislike`, `/feedback <thoughts>`, or `/skip` to jump ahead.*"
        )
        return text_content + banner

    # --- MCP Tools Definition ---
    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        return [
            {
                "name": "musicly_slash_command",
                "description": "Execute a Musicly slash command for AI agents (e.g., /skip, /next, /play <query>, /stop, /reset, /like, /dislike, /situation build_failed, /trend-add <query>).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Slash command string starting with '/' (e.g., '/skip', '/play lofi beats', '/like great beats', '/situation build_failed')"
                        }
                    },
                    "required": ["command"]
                }
            },
            {
                "name": "musicly_search",
                "description": "Search YouTube for songs or playlists.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"},
                        "type": {"type": "string", "enum": ["song", "playlist"], "default": "song"},
                        "count": {"type": "integer", "default": 10}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "musicly_play",
                "description": "Play a track immediately by search query, direct URL, or track ID. Clears queue and starts endless playlist with requested track as anchor.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Song title / artist search query or URL"},
                        "track_id": {"type": "string", "description": "YouTube video ID"}
                    }
                }
            },
            {
                "name": "musicly_pause",
                "description": "Pause current audio playback.",
                "inputSchema": {"type": "object", "properties": {}}
            },
            {
                "name": "musicly_resume",
                "description": "Resume paused audio playback.",
                "inputSchema": {"type": "object", "properties": {}}
            },
            {
                "name": "musicly_stop",
                "description": "Stop current audio playback and clear queue.",
                "inputSchema": {"type": "object", "properties": {}}
            },
            {
                "name": "musicly_skip",
                "description": "Skip to the next song in the endless playlist queue without applying taste penalty.",
                "inputSchema": {"type": "object", "properties": {}}
            },
            {
                "name": "musicly_reset",
                "description": "Reset playback session, clear queue, clear pivot anchor, and clear seen track cache.",
                "inputSchema": {"type": "object", "properties": {}}
            },
            {
                "name": "musicly_set_volume",
                "description": "Set system audio volume (0-100%).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "level": {"type": "integer", "description": "Volume level from 0 to 100"}
                    },
                    "required": ["level"]
                }
            },
            {
                "name": "musicly_get_status",
                "description": "Get current playback status, current track details, endless playlist state, and active situation.",
                "inputSchema": {"type": "object", "properties": {}}
            },
            {
                "name": "musicly_feedback",
                "description": "Record explicit user feedback (like, dislike, or text feedback) for current or specified track.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["like", "dislike", "comment"], "description": "Feedback action"},
                        "feedback_text": {"type": "string", "description": "Optional user feedback comment"},
                        "track_id": {"type": "string", "description": "Optional target track ID; defaults to currently playing track"}
                    },
                    "required": ["action"]
                }
            },
            {
                "name": "musicly_trigger_situation",
                "description": "Trigger a developer situation (e.g. build_failed, out_of_ideas, git_stuck, build_success, flow_state, general) to automatically switch the music mood.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "situation": {
                            "type": "string",
                            "enum": ["build_failed", "out_of_ideas", "git_stuck", "build_success", "flow_state", "general"],
                            "description": "Developer situation"
                        },
                        "auto_play": {"type": "boolean", "default": True, "description": "Automatically start playing a track matching this situation"}
                    },
                    "required": ["situation"]
                }
            },
            {
                "name": "musicly_add_trends",
                "description": "Log trending tracks found via AI agent search tools into Musicly's trend database for endless playlist exploration.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query used to discover trend"},
                        "tracks": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "title": {"type": "string"},
                                    "artist": {"type": "string"},
                                    "duration": {"type": "string"},
                                    "url": {"type": "string"}
                                },
                                "required": ["id", "title"]
                            },
                            "description": "List of discovered trend tracks"
                        }
                    },
                    "required": ["tracks"]
                }
            },
            {
                "name": "musicly_get_feedback_history",
                "description": "Get raw user feedback comments and logs from SQLite database for AI agent taste analysis and preference refining.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 20, "description": "Max feedback records to fetch"}
                    }
                }
            },
            {
                "name": "musicly_update_taste_analysis",
                "description": "Save AI agent's refined taste analysis summary, top genres, and disliked themes into Musicly SQLite database for future reference.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "situation": {"type": "string", "description": "Developer situation (e.g. build_failed, general)"},
                        "preference_summary": {"type": "string", "description": "Human-readable summary of user preferences and mood affinities"},
                        "top_genres": {"type": "array", "items": {"type": "string"}, "description": "List of user's favorite genres for this situation"},
                        "disliked_themes": {"type": "array", "items": {"type": "string"}, "description": "List of genres or features to avoid"}
                    },
                    "required": ["preference_summary"]
                }
            },
            {
                "name": "musicly_get_taste_analysis",
                "description": "Get stored taste analysis records and refined preferences from SQLite database for the current or specified situation.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "situation": {"type": "string", "description": "Optional situation filter"}
                    }
                }
            },
            {
                "name": "musicly_ensure_instructions",
                "description": "Verify or append Musicly AI Agent Workflows and Daily Trend Discovery instructions into AGENTS.md / CLAUDE.md in the workspace root.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workspace_dir": {"type": "string", "description": "Optional workspace directory path"}
                    }
                }
            }
        ]

    # --- Tool Execution Router ---
    def call_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if name == "musicly_slash_command":
            res = self.execute_daemon_command("slash_command", args)
            out = res.get("output", res.get("message", "Executed command."))
            return {"content": [{"type": "text", "text": self.format_response_with_banner(out)}]}

        elif name == "musicly_search":
            res = self.execute_daemon_command("search", args)
            results = res.get("results", [])
            q = args.get("query", "")
            stype = args.get("type", "song")
            if stype == "playlist":
                text = f"Found {len(results)} playlists for '{q}':\n" + "\n".join(
                    [f"- {p['title']} by {p.get('uploader')} ({p.get('track_count')} tracks)" for p in results]
                )
            else:
                text = f"Found {len(results)} tracks for '{q}':\n" + "\n".join(
                    [f"- {t['title']} by {t['artist']} [{t['duration']}] (ID: {t['id']})" for t in results]
                )
            return {"content": [{"type": "text", "text": self.format_response_with_banner(text)}]}

        elif name == "musicly_play":
            res = self.execute_daemon_command("play", args)
            if res.get("status") == "error":
                text = f"❌ {res.get('message', 'Failed to play track.')}"
                return {"content": [{"type": "text", "text": text}]}
            track = res.get("track")
            if track:
                text = f"▶️ Now Playing: '{track.get('title')}' by {track.get('artist')}"
            else:
                text = res.get("message", "Failed to play track.")
            return {"content": [{"type": "text", "text": self.format_response_with_banner(text)}]}

        elif name == "musicly_pause":
            res = self.execute_daemon_command("pause", args)
            text = res.get("message", "Paused.")
            return {"content": [{"type": "text", "text": self.format_response_with_banner(text)}]}

        elif name == "musicly_resume":
            res = self.execute_daemon_command("resume", args)
            text = res.get("message", "Resumed.")
            return {"content": [{"type": "text", "text": self.format_response_with_banner(text)}]}

        elif name == "musicly_stop":
            res = self.execute_daemon_command("stop", args)
            text = res.get("message", "⏹️ Audio playback stopped and queue cleared.")
            return {"content": [{"type": "text", "text": text}]}

        elif name == "musicly_skip":
            res = self.execute_daemon_command("skip", args)
            track = res.get("track")
            if track:
                text = f"⏭️ Skipped to next track: '{track.get('title')}' by {track.get('artist')}"
            else:
                text = res.get("message", "Skipped.")
            return {"content": [{"type": "text", "text": self.format_response_with_banner(text)}]}

        elif name == "musicly_reset":
            res = self.execute_daemon_command("reset", args)
            text = res.get("message", "🔄 Playback session, queue, and taste cache reset.")
            return {"content": [{"type": "text", "text": text}]}

        elif name == "musicly_set_volume":
            res = self.execute_daemon_command("set_volume", args)
            lvl = res.get("level", 80)
            return {"content": [{"type": "text", "text": self.format_response_with_banner(f"🔊 Volume set to {lvl}%")}]}

        elif name == "musicly_get_status":
            res = self.execute_daemon_command("get_status", {}, user_initiated=False)
            player_status = res.get("player_status", {})
            current_track = player_status.get("track")
            track_str = f"'{current_track.get('title')}' by {current_track.get('artist')}" if current_track else "None"
            stats = res.get("feedback_stats", {})

            output = (
                f"🎵 **Musicly System Status**\n"
                f"- **State**: `{player_status.get('state')}`\n"
                f"- **Now Playing**: {track_str}\n"
                f"- **Elapsed**: {player_status.get('elapsed_seconds', 0)} seconds\n"
                f"- **Volume**: {player_status.get('volume')}%\n"
                f"- **Endless Playlist**: 🟢 ACTIVE\n"
                f"- **Situation**: `{res.get('current_situation')}`\n"
                f"- **Active Session**: `{res.get('active_session')}`\n"
                f"- **Feedback Stats**: 👍 {stats.get('likes', 0)} Likes | 👎 {stats.get('dislikes', 0)} Dislikes"
            )
            return {"content": [{"type": "text", "text": self.format_response_with_banner(output)}]}

        elif name == "musicly_feedback":
            res = self.execute_daemon_command("feedback", args)
            track = res.get("track")
            action = args.get("action", "like")
            if track:
                out = f"👍 Recorded {action} for '{track.get('title')}'. Musicly taste profile evolved!"
            else:
                out = res.get("message", "Logged feedback.")
            return {"content": [{"type": "text", "text": self.format_response_with_banner(out)}]}

        elif name == "musicly_trigger_situation":
            res = self.execute_daemon_command("trigger_situation", args)
            sit = res.get("situation", args.get("situation"))
            track = res.get("track")
            msg = f"🎯 Switched situation to `{sit}`."
            if track:
                msg += f" Playing matching vibe: '{track.get('title')}' by {track.get('artist')}"
            return {"content": [{"type": "text", "text": self.format_response_with_banner(msg)}]}

        elif name == "musicly_add_trends":
            res = self.execute_daemon_command("add_trends", args)
            cnt = res.get("count", 0)
            text = f"🔥 Logged {cnt} trend tracks for Auto-DJ exploration!"
            return {"content": [{"type": "text", "text": self.format_response_with_banner(text)}]}

        elif name == "musicly_update_taste_analysis":
            res = self.execute_daemon_command("update_taste_analysis", args)
            sit = res.get("situation", "general")
            return {"content": [{"type": "text", "text": f"🧠 Saved AI taste analysis for situation `{sit}` to SQLite database."}]}

        elif name == "musicly_get_taste_analysis":
            res = self.execute_daemon_command("get_taste_analysis", args)
            analysis_list = res.get("taste_analysis", [])
            output = f"📊 **Stored Musicly Taste Analyses ({len(analysis_list)} records)**:\n" + "\n".join(
                [f"- [{a.get('updated_at')}] Situation: `{a.get('situation')}` | Summary: \"{a.get('preference_summary')}\" | Genres: {a.get('top_genres')} | Avoid: {a.get('disliked_themes')}" for a in analysis_list]
            )
            return {"content": [{"type": "text", "text": output}]}

        elif name == "musicly_ensure_instructions":
            wdir = args.get("workspace_dir")
            res = ensure_agent_instructions(workspace_dir=wdir)
            text = f"📄 Musicly instructions status in `{res.get('file')}`: `{res.get('status')}`"
            return {"content": [{"type": "text", "text": text}]}

        elif name == "musicly_get_feedback_history":
            res = self.execute_daemon_command("get_feedback_history", args)
            logs = res.get("feedback_logs", [])
            output = f"📜 **Raw Musicly Feedback Logs ({len(logs)} entries)**:\n" + "\n".join(
                [f"- [{l.get('timestamp')}] Track '{l.get('title')}' by {l.get('artist')} | Action: `{l.get('action')}` | Situation: `{l.get('situation')}` | Comment: \"{l.get('feedback_text')}\"" for l in logs]
            )
            return {"content": [{"type": "text", "text": output}]}

        return {"content": [{"type": "text", "text": f"Unknown tool: {name}"}]}

    # --- JSON-RPC 2.0 Loop over STDIO ---
    def run_stdio(self):
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                request = json.loads(line)
                response = self.handle_jsonrpc(request)
                if response is not None:
                    sys.stdout.write(json.dumps(response) + "\n")
                    sys.stdout.flush()
            except Exception as e:
                err_res = {
                    "jsonrpc": "2.0",
                    "error": {"code": -32603, "message": str(e)},
                    "id": None
                }
                sys.stdout.write(json.dumps(err_res) + "\n")
                sys.stdout.flush()

    def handle_jsonrpc(self, req: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        msg_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "musicly", "version": "2.0.0"}
                }
            }
        elif method == "notifications/initialized":
            return None
        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": self.get_tool_definitions()}
            }
        elif method == "tools/call":
            tool_name = params.get("name")
            tool_args = params.get("arguments", {})
            try:
                res = self.call_tool(tool_name, tool_args)
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": res
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32602, "message": str(e)}
                }

        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        }


def main():
    server = MusiclyMCPServer()
    server.run_stdio()


if __name__ == "__main__":
    main()
