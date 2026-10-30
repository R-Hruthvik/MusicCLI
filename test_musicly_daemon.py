"""Test suite for Musicly Singleton Daemon & IPC Multi-Session Architecture."""

import unittest
import os
import json
import tempfile
import threading
import time
from unittest import mock

from mcp.db import MusiclyDB
from mcp.daemon import MusiclyDaemon, send_daemon_request


class TestMusiclyDaemonIPC(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "daemon_test.db")
        self.socket_path = os.path.join(self.tmp_dir.name, "test_musicly.sock")

        self.daemon = MusiclyDaemon(db_path=self.db_path)
        # Mock AudioPlayer.play and search calls to avoid network/subprocesses during tests
        self.daemon.player.play = mock.MagicMock(return_value=(True, None))
        self.daemon.taste_engine.fetch_next_autodj_track = mock.MagicMock(
            return_value={"id": "mock_id", "title": "Mock Song", "artist": "Mock Artist", "url": "https://youtu.be/mock"}
        )

        self.server_thread = threading.Thread(
            target=self.daemon.run_unix_socket_server,
            args=(self.socket_path,),
            daemon=True
        )
        self.server_thread.start()
        time.sleep(0.2)  # Allow socket to bind

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_ipc_ping(self):
        res = send_daemon_request({"command": "ping"}, socket_path=self.socket_path)
        self.assertIsNotNone(res)
        self.assertEqual(res["status"], "ok")
        self.assertIn("Musicly Daemon running", res["message"])

    def test_ipc_slash_command(self):
        res = send_daemon_request(
            {"command": "slash_command", "args": {"command": "/skip"}, "session_id": "session_1"},
            socket_path=self.socket_path
        )
        self.assertIsNotNone(res)
        self.assertTrue(res["success"])
        self.assertIn("Skipped", res["output"])

    def test_ipc_multi_session_status(self):
        # Session A sends slash command
        send_daemon_request(
            {"command": "slash_command", "args": {"command": "/situation build_failed"}, "session_id": "session_A"},
            socket_path=self.socket_path
        )

        # Session B queries status
        status_res = send_daemon_request(
            {"command": "get_status", "session_id": "session_B", "user_initiated": False},
            socket_path=self.socket_path
        )
        self.assertEqual(status_res["status"], "ok")
        self.assertEqual(status_res["current_situation"], "build_failed")
        self.assertEqual(status_res["active_session"], "session_A")

    def test_ipc_feedback_from_another_session(self):
        # Set track
        self.daemon.player._current_track = {"id": "song777", "title": "Shared Song", "artist": "Global Artist"}

        # Session C gives feedback
        fb_res = send_daemon_request(
            {"command": "feedback", "args": {"action": "like", "feedback_text": "Great vibe!"}, "session_id": "session_C"},
            socket_path=self.socket_path
        )
        self.assertEqual(fb_res["status"], "ok")
        self.assertEqual(fb_res["track"]["id"], "song777")

        liked = self.daemon.db.get_liked_tracks()
        self.assertTrue(len(liked) > 0)
        self.assertEqual(liked[0]["track_id"], "song777")

    def test_user_initiated_play_sets_pivot_track(self):
        res = send_daemon_request(
            {"command": "play", "args": {"track_id": "song999"}, "session_id": "session_1"},
            socket_path=self.socket_path
        )
        self.assertEqual(res["status"], "ok")
        # Endless play mode is enabled & pivot mode active so next track continues with similar songs
        self.assertTrue(self.daemon.taste_engine.endless_enabled)
        self.assertTrue(self.daemon.taste_engine.pivot_mode)
        self.assertEqual(self.daemon.taste_engine.active_pivot_track["id"], "song999")

    def test_reset_command_clears_session(self):
        res = send_daemon_request(
            {"command": "reset", "session_id": "session_1"},
            socket_path=self.socket_path
        )
        self.assertEqual(res["status"], "ok")
        self.assertFalse(self.daemon.taste_engine.pivot_mode)


if __name__ == "__main__":
    unittest.main()
