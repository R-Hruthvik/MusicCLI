"""Unit & Integration Test Suite for Musicly MCP Server & Adaptive Engine."""

import unittest
import os
import json
import tempfile
import threading
from unittest import mock

from mcp.db import MusiclyDB
from mcp.player import AudioPlayer
from mcp.taste_engine import TasteEngine
from mcp.slash_commands import SlashCommandHandler
from mcp.server import MusiclyMCPServer


class TestMusiclyDB(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_musicly.db")
        self.db = MusiclyDB(db_path=self.db_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_upsert_and_get_track(self):
        track = {
            "id": "vid123",
            "title": "Test Song",
            "artist": "Test Artist",
            "duration": "3:30",
            "url": "https://www.youtube.com/watch?v=vid123",
            "genre_tags": ["lofi", "chill"]
        }
        self.db.upsert_track(track)
        fetched = self.db.get_track("vid123")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched["title"], "Test Song")
        self.assertEqual(fetched["artist"], "Test Artist")
        self.assertIn("lofi", fetched["genre_tags"])

    def test_feedback_logging_and_counts(self):
        track = {"id": "vid99", "title": "Good Track", "artist": "Artist A", "url": "https://youtu.be/vid99"}
        self.db.log_feedback(track, situation="build_failed", action="like", feedback_text="calming vibe")
        
        liked = self.db.get_liked_tracks("build_failed")
        self.assertEqual(len(liked), 1)
        self.assertEqual(liked[0]["track_id"], "vid99")

        summary = self.db.get_feedback_summary()
        self.assertEqual(summary["likes"], 1)

    def test_situation_seeds(self):
        seed = self.db.get_situation_seed("build_failed")
        self.assertEqual(seed["mood_name"], "Calm Focus & Reset")
        self.assertTrue(len(seed["query_seeds"]) > 0)

        self.db.add_query_seed_for_situation("build_failed", "new lofi query")
        updated_seed = self.db.get_situation_seed("build_failed")
        self.assertEqual(updated_seed["query_seeds"][0], "new lofi query")

    def test_trends_logging(self):
        track = {"id": "tr1", "title": "Trending Song", "artist": "Pop Star"}
        self.db.add_trend(track, source="agent_search", query="top hits")
        trends = self.db.get_recent_trends()
        self.assertTrue(len(trends) > 0)
        self.assertEqual(trends[0]["track_id"], "tr1")


class TestAudioPlayer(unittest.TestCase):
    def setUp(self):
        self.player = AudioPlayer()

    def test_initial_status(self):
        status = self.player.get_status()
        self.assertEqual(status["state"], "STOPPED")
        self.assertIsNone(status["track"])

    def test_volume_control(self):
        vol = self.player.set_volume(50)
        self.assertEqual(vol, 50)
        self.assertEqual(self.player.get_status()["volume"], 50)

    def test_user_stop_does_not_trigger_callback(self):
        cb_called = []
        self.player.set_track_end_callback(lambda: cb_called.append(True))
        
        stop_event = threading.Event()
        mock_proc = mock.MagicMock()
        mock_proc.pid = 1234
        mock_proc.wait.side_effect = lambda: stop_event.wait(timeout=2)

        with mock.patch("subprocess.Popen", return_value=mock_proc), \
             mock.patch("os.getpgid", return_value=1234), \
             mock.patch("os.killpg", side_effect=lambda pgid, sig: stop_event.set()):
            self.player.play({"url": "https://youtu.be/dummy", "title": "Mock"})
            self.player.stop()

        self.assertEqual(len(cb_called), 0)


class TestTasteEngine(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_musicly.db")
        self.db = MusiclyDB(db_path=self.db_path)
        self.taste_engine = TasteEngine(db=self.db)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_autodj_toggle_and_situation(self):
        self.assertTrue(self.taste_engine.endless_enabled)

        self.taste_engine.set_situation("build_failed")
        self.assertEqual(self.taste_engine.current_situation, "build_failed")

    def test_dislike_filtering(self):
        track = {"id": "bad1", "title": "Annoying Song", "artist": "Bad"}
        self.taste_engine.record_feedback(track, "dislike")
        disliked = self.taste_engine.get_disliked_ids()
        self.assertIn("bad1", disliked)

    def test_pivot_mode_prefers_similar_songs(self):
        self.taste_engine.set_explicit_pivot_track({"id": "p1", "title": "Song A", "artist": "Artist A", "url": "https://youtu.be/p1"})
        radio = [{"id": f"r{i}", "title": f"Radio {i}", "artist": "Artist A", "url": f"https://youtu.be/r{i}"} for i in range(1, 11)]

        with mock.patch("mcp.taste_engine.get_radio_tracks", return_value=radio), \
             mock.patch("mcp.taste_engine.search_songs") as mock_search:
            nxt = self.taste_engine.fetch_next_endless_track()

        # Radio (similar songs) fills the pool first; default lofi seeds are NOT used
        self.assertEqual(nxt["id"], "r1")
        mock_search.assert_not_called()

    def test_default_mode_uses_situation_seeds(self):
        seed_tracks = [{"id": f"s{i}", "title": f"Seed {i}", "artist": "Seed Artist", "url": f"https://youtu.be/s{i}"} for i in range(1, 11)]

        with mock.patch("mcp.taste_engine.get_radio_tracks", return_value=[]), \
             mock.patch("mcp.taste_engine.search_songs", return_value=seed_tracks):
            nxt = self.taste_engine.fetch_next_endless_track()

        self.assertEqual(nxt["id"], "s1")

    def test_pivot_cleared_on_situation_change(self):
        self.taste_engine.set_explicit_pivot_track({"id": "p1", "title": "Song A", "artist": "Artist A", "url": "https://youtu.be/p1"})
        self.assertTrue(self.taste_engine.pivot_mode)

        self.taste_engine.set_situation("build_failed")
        self.assertFalse(self.taste_engine.pivot_mode)

    def test_cultural_anchor_detection(self):
        hindi_track = {"title": "Tum Hi Ho", "artist": "Arijit Singh"}
        japanese_track = {"title": "夜に駆ける", "artist": "YOASOBI"}
        synthwave_track = {"title": "Sunset Synthwave", "artist": "The Midnight"}

        self.assertEqual(self.taste_engine.detect_cultural_anchor(hindi_track), "hindi")
        self.assertEqual(self.taste_engine.detect_cultural_anchor(japanese_track), "japanese")
        self.assertEqual(self.taste_engine.detect_cultural_anchor(synthwave_track), "synthwave")

    def test_implicit_feedback_processing(self):
        track = {"id": "imp1", "title": "Hindi Acoustic Song", "artist": "Artist H"}
        # High completion (>80%) triggers implicit like
        self.taste_engine.process_implicit_feedback(track, listen_duration=180, total_duration=200)
        summary = self.db.get_feedback_summary()
        self.assertTrue(summary["likes"] > 0)

        # Quick skip (<15%) triggers contextual penalty
        quick_track = {"id": "imp2", "title": "Lofi Chill Beat", "artist": "Lofi Artist"}
        self.taste_engine.process_implicit_feedback(quick_track, listen_duration=10, total_duration=200)
        penalties = self.db.get_active_contextual_penalties(self.taste_engine.current_situation)
        self.assertIn("lofi", penalties)


class TestSlashCommands(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_musicly.db")
        self.db = MusiclyDB(db_path=self.db_path)
        self.taste_engine = TasteEngine(db=self.db)
        self.player = AudioPlayer()
        self.player.play = mock.MagicMock(return_value=(True, None))
        self.handler = SlashCommandHandler(self.taste_engine, self.player)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_skip_slash_command(self):
        res_skip = self.handler.handle_command("/skip")
        self.assertTrue(res_skip["success"])

        res_next = self.handler.handle_command("/next")
        self.assertTrue(res_next["success"])

    def test_situation_slash_command(self):
        res = self.handler.handle_command("/situation build_failed")
        self.assertTrue(res["success"])
        self.assertEqual(self.taste_engine.current_situation, "build_failed")

    def test_status_command(self):
        res = self.handler.handle_command("/status")
        self.assertTrue(res["success"])
        self.assertIn("Musicly System & Taste Status", res["output"])

    def test_reset_slash_command(self):
        self.taste_engine.set_explicit_pivot_track({"id": "p1", "title": "Song A", "artist": "Artist A", "url": "https://youtu.be/p1"})
        self.assertTrue(self.taste_engine.pivot_mode)

        res = self.handler.handle_command("/reset")
        self.assertTrue(res["success"])
        self.assertFalse(self.taste_engine.pivot_mode)


class TestMusiclyMCPServer(unittest.TestCase):
    def setUp(self):
        with mock.patch.object(MusiclyMCPServer, "_ensure_daemon_running"):
            self.server = MusiclyMCPServer()
        self.server.execute_daemon_command = mock.MagicMock(return_value={"status": "ok", "output": "Skipped", "message": "Skipped"})

    def test_jsonrpc_initialize(self):
        req = {"jsonrpc": "2.0", "method": "initialize", "params": {}, "id": 1}
        res = self.server.handle_jsonrpc(req)
        self.assertEqual(res["id"], 1)
        self.assertEqual(res["result"]["serverInfo"]["name"], "musicly")

    def test_jsonrpc_tools_list(self):
        req = {"jsonrpc": "2.0", "method": "tools/list", "params": {}, "id": 2}
        res = self.server.handle_jsonrpc(req)
        tools = res["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        self.assertIn("musicly_slash_command", tool_names)
        self.assertIn("musicly_search", tool_names)
        self.assertIn("musicly_skip", tool_names)
        self.assertIn("musicly_reset", tool_names)
        self.assertIn("musicly_trigger_situation", tool_names)

    def test_call_tool_slash_command(self):
        req = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {
                "name": "musicly_slash_command",
                "arguments": {"command": "/skip"}
            },
            "id": 3
        }
        res = self.server.handle_jsonrpc(req)
        content_text = res["result"]["content"][0]["text"]
        self.assertIn("Skipped", content_text)


class TestAgentInstructions(unittest.TestCase):
    def test_ensure_agent_instructions(self):
        from mcp.instructions import ensure_agent_instructions, MUSICLY_INSTRUCTION_HEADER
        tmp_dir = tempfile.TemporaryDirectory()
        agents_md = os.path.join(tmp_dir.name, "AGENTS.md")
        with open(agents_md, "w", encoding="utf-8") as f:
            f.write("# Existing Agent Config\n- Rule 1\n")

        res1 = ensure_agent_instructions(workspace_dir=tmp_dir.name)
        self.assertEqual(res1["status"], "appended")
        self.assertTrue(res1["updated"])

        with open(agents_md, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn(MUSICLY_INSTRUCTION_HEADER, content)

        # Idempotent re-run
        res2 = ensure_agent_instructions(workspace_dir=tmp_dir.name)
        self.assertEqual(res2["status"], "already_present")
        self.assertFalse(res2["updated"])

        tmp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
