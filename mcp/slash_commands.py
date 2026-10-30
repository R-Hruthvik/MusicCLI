"""Slash Command Parser for AI Agents and Users in Musicly.

Handles commands like /skip, /next, /play <query>, /stop, /reset, /like,
/dislike, /situation <name>, /status, /feedback <text>, /trend-add <query>.
"""

from typing import Dict, Any
from .taste_engine import TasteEngine
from .player import AudioPlayer
from foundation import search_songs


class SlashCommandHandler:
    def __init__(self, taste_engine: TasteEngine, player: AudioPlayer):
        self.taste_engine = taste_engine
        self.player = player

    def handle_command(self, command_str: str) -> Dict[str, Any]:
        cmd_raw = command_str.strip()
        if not cmd_raw.startswith("/"):
            return {
                "success": False,
                "message": f"Command must start with '/' (received: '{command_str}')",
                "output": "Invalid command format."
            }

        parts = cmd_raw.split(maxsplit=2)
        root = parts[0].lower()
        sub = parts[1].lower() if len(parts) > 1 else ""
        args = parts[2] if len(parts) > 2 else ""

        # Map legacy prefix /autodj <subcommand> or /musicly <subcommand>
        if root in ("/autodj", "/musicly"):
            if not sub:
                sub = "status"
            root_cmd = "/" + sub
            cmd_args = args
        else:
            root_cmd = root
            cmd_args = (sub + " " + args).strip() if sub else ""

        return self._route_command(root_cmd, cmd_args)

    def _route_command(self, root_cmd: str, args: str) -> Dict[str, Any]:
        if root_cmd in ("/skip", "/next"):
            current_status = self.player.get_status()
            current_track = current_status.get("track")
            self.player.stop()
            nxt = self.taste_engine.fetch_next_endless_track(current_track)
            skip_msg = ""
            if nxt:
                self.player.play(nxt)
                skip_msg = f"⏭️ Skipped to next track: '{nxt.get('title')}' by {nxt.get('artist')}"
            else:
                skip_msg = "⏹️ Stopped playback. No more tracks in endless queue."

            return {
                "success": True,
                "action": "skip",
                "output": skip_msg
            }

        elif root_cmd in ("/play", "/start"):
            if not args:
                if self.player.get_status().get("state") == "PAUSED":
                    self.player.resume()
                    return {"success": True, "action": "resume", "output": "▶️ Resumed audio playback."}
                return {"success": False, "output": "Usage: /play <song title or artist>"}

            results = search_songs(args, count=1)
            if not results:
                return {"success": False, "output": f"No tracks found for: '{args}'"}

            track = results[0]
            self.taste_engine.clear_queue()
            ok, err = self.player.play(track)
            if ok:
                self.taste_engine.set_explicit_pivot_track(track)
                return {
                    "success": True,
                    "action": "play",
                    "track": track,
                    "output": f"▶️ Now playing: '{track.get('title')}' by {track.get('artist')}. Endless playlist active!"
                }
            return {"success": False, "output": f"Failed to play track: {err}"}

        elif root_cmd in ("/stop", "/pause"):
            self.taste_engine.clear_queue()
            self.player.stop()
            return {
                "success": True,
                "action": "stop",
                "output": "⏹️ Audio playback stopped and queue cleared."
            }

        elif root_cmd in ("/reset", "/clear"):
            self.player.stop()
            self.taste_engine.reset_session()
            return {
                "success": True,
                "action": "reset",
                "output": "🔄 Playback session, queue, and taste cache reset."
            }

        elif root_cmd in ("/status", "/info"):
            status = self.player.get_status()
            stats = self.taste_engine.db.get_feedback_summary()
            current_track = status.get("track")
            track_name = f"'{current_track.get('title')}' by {current_track.get('artist')}" if current_track else "None"

            output = (
                f"📊 **Musicly System & Taste Status**\n"
                f"- **Endless Playlist**: 🟢 ACTIVE\n"
                f"- **Active Situation**: `{self.taste_engine.current_situation}`\n"
                f"- **Playback State**: `{status.get('state')}`\n"
                f"- **Now Playing**: {track_name}\n"
                f"- **Feedback Stats**: 👍 {stats.get('likes', 0)} Likes | 👎 {stats.get('dislikes', 0)} Dislikes | 📜 {stats.get('total_logs', 0)} Total Logs"
            )
            return {
                "success": True,
                "action": "status",
                "status": status,
                "stats": stats,
                "output": output
            }

        elif root_cmd in ("/on", "/enable"):
            self.taste_engine.set_autodj(True)
            return {"success": True, "action": "on", "output": "Endless Playback mode enabled! 🎵"}

        elif root_cmd in ("/off", "/disable"):
            self.taste_engine.set_autodj(False)
            return {"success": True, "action": "off", "output": "Endless Playback mode paused."}

        elif root_cmd in ("/feedback", "/comment", "/vibe-feedback"):
            if not args:
                return {"success": False, "output": "Usage: /feedback <share your overall vibe or song thoughts>"}

            status = self.player.get_status()
            current_track = status.get("track")
            sit = self.taste_engine.current_situation

            self.taste_engine.db.add_query_seed_for_situation(sit, args.strip())
            if current_track:
                self.taste_engine.record_feedback(current_track, "like", feedback_text=args)
                return {
                    "success": True,
                    "action": "feedback",
                    "output": f"💬 Thank you for your feedback! Evolved taste profile for `{sit}` with '{args}'."
                }

            return {
                "success": True,
                "action": "feedback",
                "output": f"💬 Thank you for the overall vibe feedback! Added '{args}' to `{sit}` seeds."
            }

        elif root_cmd in ("/like", "/upvote", "/thumbsup"):
            status = self.player.get_status()
            current_track = status.get("track")
            if not current_track:
                return {"success": False, "output": "No track is currently playing to like."}

            res = self.taste_engine.record_feedback(current_track, "like", feedback_text=args)
            return {
                "success": True,
                "action": "like",
                "track": current_track,
                "output": f"👍 Liked track '{current_track.get('title')}'! Endless playlist will adapt to play more songs like this."
            }

        elif root_cmd in ("/dislike", "/downvote"):
            status = self.player.get_status()
            current_track = status.get("track")
            if not current_track:
                return {"success": False, "output": "No track is currently playing to dislike."}

            res = self.taste_engine.record_feedback(current_track, "dislike", feedback_text=args)
            self.player.stop()
            nxt = self.taste_engine.fetch_next_endless_track()
            skip_msg = ""
            if nxt:
                self.player.play(nxt)
                skip_msg = f" Skipped to next track: '{nxt.get('title')}'"

            return {
                "success": True,
                "action": "dislike",
                "track": current_track,
                "output": f"👎 Disliked track '{current_track.get('title')}'.{skip_msg}"
            }

        elif root_cmd in ("/situation", "/vibe", "/mood"):
            if not args:
                return {
                    "success": False,
                    "output": "Please specify a situation: build_failed, out_of_ideas, git_stuck, build_success, flow_state, general."
                }
            new_sit = self.taste_engine.set_situation(args.strip().lower())
            return {
                "success": True,
                "action": "situation_change",
                "situation": new_sit,
                "output": f"🎯 Active situation set to `{new_sit}`. Endless playlist will now select music matching this mood."
            }

        elif root_cmd in ("/trend-add", "/trend", "/add-trend"):
            if not args:
                return {"success": False, "output": "Usage: /trend-add <song search query>"}

            results = search_songs(args, count=3)
            if not results:
                return {"success": False, "output": f"No tracks found matching trend query: '{args}'"}

            added_track = results[0]
            self.taste_engine.db.add_trend(added_track, source="agent_slash_command", query=args)
            return {
                "success": True,
                "action": "trend_added",
                "track": added_track,
                "output": f"🔥 Added trend track: '{added_track.get('title')}' by {added_track.get('artist')}. Added to endless exploration pool!"
            }

        elif root_cmd in ("/help", "/?", "/commands"):
            output = (
                "🎵 **Musicly Slash Commands Reference**\n\n"
                "- `/next` / `/skip` : Skip to the next song without penalty.\n"
                "- `/play <song>` : Play requested song immediately and start endless playlist.\n"
                "- `/stop` : Stop audio playback and clear queue.\n"
                "- `/reset` : Reset playback session, queue, and taste cache.\n"
                "- `/status` : View playback state, current track, active mood, and feedback stats.\n"
                "- `/like [comment]` : Like currently playing track and evolve taste profile.\n"
                "- `/dislike [comment]` : Dislike currently playing track and skip.\n"
                "- `/situation <name>` / `/mood <name>` : Switch situation (`build_failed`, `out_of_ideas`, `git_stuck`, `build_success`, `flow_state`, `general`).\n"
                "- `/trend-add <query>` : Add a trending song query into the exploration pool."
            )
            return {"success": True, "output": output}

        return {
            "success": False,
            "output": f"Unknown slash command '{root_cmd}'. Use `/help` for available options."
        }
