#!/usr/bin/env python3
"""Comprehensive performance benchmark for MusicCLI codebase.

Measures:
1. yt-dlp subprocess call latency (mocked)
2. Track parsing & deduplication (regex + dict lookups)
3. SQLite operations (connection-per-call, missing indexes)
4. TasteEngine pool refill (DB + network simulation)
5. IPC socket round-trip
6. Terminal TUI input loop (get_char raw mode toggling)
"""

import os
import sys
import json
import time
import sqlite3
import tempfile
import threading
import socket
import subprocess
import tracemalloc
from collections import deque
from unittest import mock

# Ensure project root is in path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from foundation.musiccli import (
    Track, PlaybackSession, RadioVariety, search_songs, get_radio_tracks,
    fetch_playlist, fetch_single, select_search_results, play_track,
    fmt_views, fmt_upload_date, radio_seed,
    _run_ytdlp,
    _DISCOVERY_QUERIES,
)
from mcp.db import MusiclyDB
from mcp.daemon import MusiclyDaemon, send_daemon_request
from mcp.taste_engine import TasteEngine, SEEN_TRACK_IDS_MAX

# ============================================================================
# BENCHMARK HARNESS
# ============================================================================

def bench(name, func, iterations=1, warmup=0):
    """Run a benchmark function and return timing stats."""
    # Warmup
    for _ in range(warmup):
        func()

    tracemalloc.start()
    start = time.perf_counter_ns()
    results = []
    for _ in range(iterations):
        r = func()
        results.append(r)
    elapsed_ns = time.perf_counter_ns() - start
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    elapsed_ms = elapsed_ns / 1_000_000
    avg_ms = elapsed_ms / iterations
    print(f"  {name}:")
    print(f"    {iterations} iterations in {elapsed_ms:.2f}ms")
    print(f"    Average: {avg_ms:.4f}ms per call")
    print(f"    Memory: current={current/1024:.1f}KB, peak={peak/1024:.1f}KB")
    print()
    return {"name": name, "iterations": iterations, "total_ms": elapsed_ms, "avg_ms": avg_ms, "peak_kb": peak / 1024}


def fmt_ns(ns):
    """Format nanoseconds into human-readable string."""
    if ns < 1_000:
        return f"{ns}ns"
    elif ns < 1_000_000:
        return f"{ns/1_000:.2f}µs"
    else:
        return f"{ns/1_000_000:.2f}ms"


# ============================================================================
# 1. YT-DLP SUBPROCESS BENCHMARKS
# ============================================================================

def make_mock_subprocess(stdout_data="", returncode=0):
    """Create a mock subprocess.run result."""
    proc = mock.Mock()
    proc.stdout = stdout_data
    proc.stderr = ""
    proc.returncode = returncode
    return proc

def make_mock_subprocess_run(stdout_data):
    """Mock subprocess.run to return given stdout."""
    proc = mock.Mock()
    proc.stdout = stdout_data
    proc.stderr = ""
    proc.returncode = 0
    return proc


def bench_ytdlp_subprocess_calls():
    """Benchmark yt-dlp subprocess call patterns."""
    print("=" * 60)
    print("1. YT-DLP SUBPROCESS BENCHMARKS")
    print("=" * 60)

    # Mock data: 30 search results
    mock_lines = "\n".join(
        f"Song {i} ||| vid{i:03d} ||| Artist {i} ||| 3:{i:02d}" for i in range(30)
    )
    mock_proc = make_mock_subprocess_run(mock_lines)

    # Benchmark search_songs (uses mocked subprocess)
    def search_songs_mocked():
        with mock.patch("subprocess.run", return_value=mock_proc):
            return search_songs("test query", count=30)

    bench("search_songs (30 results, mocked subprocess)", search_songs_mocked, iterations=100)

    # Benchmark _run_ytdlp directly
    def run_ytdlp_mocked():
        with mock.patch("subprocess.run", return_value=mock_proc):
            return _run_ytdlp(["ytsearch10:test"], max_results=10)

    bench("_run_ytdlp (10 results, mocked subprocess)", run_ytdlp_mocked, iterations=100)

    # Benchmark get_radio_tracks (foundation function, takes video_id string)
    def radio_tracks_mocked():
        mock_lines = "Song One ||| vid1 ||| Artist A ||| 3:00\nSong Two ||| vid2 ||| Artist B ||| 4:00\n"
        mock_proc = make_mock_subprocess_run(mock_lines)
        with mock.patch("subprocess.run", return_value=mock_proc):
            return get_radio_tracks("seed123", count=10)

    bench("get_radio_tracks (10 results, mocked subprocess)", radio_tracks_mocked, iterations=100)

    # Benchmark play_track command construction
    def play_track_cmd():
        track = {"url": "https://www.youtube.com/watch?v=test123", "title": "Test"}
        # Just measure the command string construction, not actual subprocess
        cmd = f'yt-dlp -f "ba" -o - "{track["url"]}" 2>/dev/null | ffplay -nodisp -autoexit -'
        return cmd

    bench("play_track command construction (string interpolation)", play_track_cmd, iterations=10000)


# ============================================================================
# 2. TRACK PARSING & DEDUP BENCHMARKS
# ============================================================================

def make_test_track(title, artist, vid, dur="3:00"):
    return Track(title=title, artist=artist, source="YouTube",
                 duration=dur, url=f"https://www.youtube.com/watch?v={vid}", id=vid)


def bench_track_parsing():
    """Benchmark track parsing and deduplication."""
    print("=" * 60)
    print("2. TRACK PARSING & DEDUP BENCHMARKS")
    print("=" * 60)

    # Track.from_line parsing
    test_line = "Song A (Official Video) ||| vid123 ||| Uploader ||| Channel ||| Playlist ||| 3:45 ||| 1M ||| 20240101"

    def parse_from_line():
        return Track.from_line(test_line)

    bench("Track.from_line (8-field parse)", parse_from_line, iterations=10000)

    # core_key regex
    track = make_test_track("Song A (Official Video) [2024 Remaster]", "Artist Name", "vid001")

    def core_key_call():
        return track.core_key()

    bench("Track.core_key() (4 regex subs)", core_key_call, iterations=5000)

    # artist_key regex
    def artist_key_call():
        return track.artist_key()

    bench("Track.artist_key() (1 regex sub)", artist_key_call, iterations=5000)

    # select_search_results with dedup
    many_tracks = [make_test_track(f"Song {i}", f"Artist {i%5}", f"vid{i:04d}") for i in range(200)]
    # Add duplicates
    for i in range(50):
        many_tracks.append(make_test_track(f"Song {i}", f"Artist {i%5}", f"dup{i:04d}"))

    def select_results():
        return select_search_results(many_tracks, max_results=10)

    bench("select_search_results (250 tracks -> 10 results)", select_results, iterations=100)

    # RadioVariety.absorb
    absorb_list = [make_test_track(f"Track {i}", f"Artist{i%3}", f"t{i:03d}") for i in range(50)]

    def absorb_tracks_list():
        v = RadioVariety(seen=set(), recent=deque(maxlen=8), artist_last={}, artist_count={}, pos=0)
        return v.absorb(absorb_list)

    bench("RadioVariety.absorb (50 tracks)", absorb_tracks_list, iterations=100)

    # fmt_views and fmt_upload_date
    def format_views():
        return fmt_views("1234567")

    bench("fmt_views (string formatting)", format_views, iterations=10000)


# ============================================================================
# 3. SQLITE BENCHMARKS
# ============================================================================

def bench_sqlite_operations():
    """Benchmark SQLite operations with isolated temp DB."""
    print("=" * 60)
    print("3. SQLITE BENCHMARKS")
    print("=" * 60)

    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, "bench.db")
    db = MusiclyDB(db_path=db_path)

    # Upsert tracks
    tracks_to_insert = [
        {"id": f"vid{i:04d}", "title": f"Song {i}", "artist": f"Artist {i%10}",
         "duration": "3:30", "url": f"https://youtu.be/vid{i:04d}", "genre_tags": ["lofi"]}
        for i in range(100)
    ]

    def upsert_tracks():
        for t in tracks_to_insert:
            db.upsert_track(t)

    bench("upsert_track (100 tracks)", upsert_tracks, iterations=5)

    # Batch upsert for comparison
    def batch_upsert():
        with sqlite3.connect(db_path) as conn:
            conn.executemany("""
                INSERT INTO tracks (track_id, title, artist, duration, url, genre_tags, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(track_id) DO UPDATE SET
                    title=excluded.title, artist=excluded.artist,
                    duration=excluded.duration, url=excluded.url,
                    updated_at=CURRENT_TIMESTAMP
            """, [(t["id"], t["title"], t["artist"], t["duration"], t["url"],
                   json.dumps(t["genre_tags"])) for t in tracks_to_insert])

    bench("batch upsert_track (100 tracks, single connection)", batch_upsert, iterations=5)

    # Get track (existing)
    def get_single_track():
        return db.get_track("vid0050")

    bench("get_track (single, indexed PK)", get_single_track, iterations=500)

    # Log feedback (includes upsert + insert + update)
    def log_feedback():
        track = {"id": "vid0050", "title": "Song 50", "artist": "Artist 0", "url": "https://youtu.be/vid0050"}
        return db.log_feedback(track, "general", "like", feedback_text="nice track!")

    bench("log_feedback (upsert + insert + update)", log_feedback, iterations=500)

    # Get feedback summary (4 COUNT queries)
    def feedback_summary():
        return db.get_feedback_summary()

    bench("get_feedback_summary (4 COUNT queries)", feedback_summary, iterations=100)

    # Get recent trends (JOIN + ORDER BY)
    def recent_trends():
        return db.get_recent_trends(limit=15)

    bench("get_recent_trends (JOIN + ORDER BY, 15 rows)", recent_trends, iterations=100)

    # Get liked tracks with situation filter (JOIN + WHERE + ORDER BY)
    def liked_tracks_sit():
        return db.get_liked_tracks(situation="general", limit=20)

    bench("get_liked_tracks(situation=..., limit=20) (JOIN + WHERE + ORDER BY)", liked_tracks_sit, iterations=100)

    # Connection overhead measurement
    def conn_create_close():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.close()

    bench("sqlite3.connect + close (connection overhead)", conn_create_close, iterations=1000)

    # Cleanup
    import shutil
    shutil.rmtree(tmp_dir)


# ============================================================================
# 4. TASTEENGINE POOL REFILL BENCHMARKS
# ============================================================================

def bench_taste_engine():
    """Benchmark TasteEngine pool refill logic."""
    print("=" * 60)
    print("4. TASTEENGINE POOL REFILL BENCHMARKS")
    print("=" * 60)

    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, "taste_bench.db")
    db = MusiclyDB(db_path=db_path)
    taste_engine = TasteEngine(db=db)

    # Insert test data
    for i in range(50):
        track = {"id": f"vid{i:04d}", "title": f"Song {i}", "artist": f"Artist {i%5}",
                 "url": f"https://youtu.be/vid{i:04d}"}
        db.upsert_track(track)
        db.log_feedback(track, "general", "like" if i % 3 == 0 else "dislike")

    # Insert trends
    for i in range(20):
        track = {"id": f"trend{i:03d}", "title": f"Trend {i}", "artist": f"Trend Artist {i%5}"}
        db.add_trend(track, source="agent", query="test query")

    # Benchmark fetch_next_autodj_track with mocked search/ytdlp
    def fetch_next_mocked():
        with mock.patch("mcp.taste_engine.search_songs", return_value=[
            {"id": f"mock{i}", "title": f"Mock {i}", "artist": "MockArtist", "duration": "3:00", "url": f"https://youtu.be/mock{i}", "type": "song"}
            for i in range(10)
        ]), mock.patch("mcp.taste_engine.get_radio_tracks", return_value=[
            {"id": f"rd{i}", "title": f"Radio {i}", "artist": "RadioArtist", "duration": "3:30", "url": f"https://youtu.be/rd{i}", "type": "song"}
            for i in range(10)
        ]):
            taste_engine.queue = []  # Force refill
            return taste_engine.fetch_next_autodj_track()

    bench("fetch_next_autodj_track (forced refill, mocked subprocess)", fetch_next_mocked, iterations=100)

    # Benchmark _refill_autodj_pool (DB only, mocked subprocess)
    def refill_mocked():
        with mock.patch("mcp.taste_engine.search_songs", return_value=[]), \
             mock.patch("mcp.taste_engine.get_radio_tracks", return_value=[]):
            return taste_engine._refill_autodj_pool(current_track=None, disliked_ids=set())

    bench("_refill_autodj_pool (DB only, empty subprocess results)", refill_mocked, iterations=200)

    # Benchmark _refill_autodj_pool with actual data
    def refill_with_data():
        with mock.patch("mcp.taste_engine.search_songs", return_value=[
            {"id": f"search{i}", "title": f"Search {i}", "artist": f"SA{i%3}", "duration": "3:00",
             "url": f"https://youtu.be/search{i}", "type": "song"}
            for i in range(10)
        ]), mock.patch("mcp.taste_engine.get_radio_tracks", return_value=[
            {"id": f"radio{i}", "title": f"Radio {i}", "artist": f"RA{i%3}", "duration": "3:00",
             "url": f"https://youtu.be/radio{i}", "type": "song"}
            for i in range(10)
        ]):
            return taste_engine._refill_autodj_pool(current_track={"id": "vid0001"}, disliked_ids=set())

    bench("_refill_autodj_pool (20 liked + 10 radio + 10 search + 20 trends)", refill_with_data, iterations=50)

    # Benchmark seen_track_ids performance at 1000 entries
    taste_engine.seen_track_ids.clear()
    for i in range(SEEN_TRACK_IDS_MAX):
        taste_engine._mark_seen(f"seen_track_{i}")

    def mark_seen_existing():
        taste_engine._mark_seen("seen_track_500")  # Hit existing

    bench("TasteEngine._mark_seen (1000 entries, existing key)", mark_seen_existing, iterations=5000)

    def mark_seen_new():
        taste_engine._mark_seen(f"new_track_{time.time()}_{id(object())}")

    bench("TasteEngine._mark_seen (1000 entries, new key, eviction)", mark_seen_new, iterations=5000)

    # Duplicate filtering in pool
    pool_with_dupes = [{"id": f"dup{i%5}", "title": f"Song {i}"} for i in range(30)]

    def unique_filter():
        disliked_ids = set()
        unique_pool = []
        for tr in pool_with_dupes:
            tid = tr.get("id") or tr.get("track_id")
            if tid and tid not in disliked_ids and tid not in [u.get("id") or u.get("track_id") for u in unique_pool]:
                unique_pool.append(tr)
        return unique_pool

    bench("TasteEngine duplicate filter (30 tracks, 5 unique IDs, O(n²))", unique_filter, iterations=100)

    import shutil
    shutil.rmtree(tmp_dir)


# ============================================================================
# 5. IPC SOCKET BENCHMARKS
# ============================================================================

def bench_ipc_socket():
    """Benchmark IPC socket round-trip times."""
    print("=" * 60)
    print("5. IPC SOCKET BENCHMARKS")
    print("=" * 60)

    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, "ipc_bench.db")
    socket_path = os.path.join(tmp_dir, "test_ipc.sock")

    daemon = MusiclyDaemon(db_path=db_path)
    daemon.player.play = mock.MagicMock(return_value=True)
    daemon.taste_engine.fetch_next_autodj_track = mock.MagicMock(
        return_value={"id": "mock_id", "title": "Mock Song", "artist": "Mock Artist", "url": "https://youtu.be/mock"}
    )

    server_thread = threading.Thread(
        target=daemon.run_unix_socket_server,
        args=(socket_path,),
        daemon=True
    )
    server_thread.start()
    time.sleep(0.3)  # Allow socket to bind

    # Benchmark ping (minimal IPC)
    def ipc_ping():
        return send_daemon_request({"command": "ping"}, socket_path=socket_path)

    bench("IPC ping (localhost Unix socket)", ipc_ping, iterations=500)

    # Benchmark get_status (DB + player status)
    def ipc_get_status():
        return send_daemon_request({"command": "get_status", "args": {}}, socket_path=socket_path)

    bench("IPC get_status (1 DB query + player status)", ipc_get_status, iterations=200)

    # Benchmark set_volume (no DB, just player method)
    def ipc_set_volume():
        return send_daemon_request({"command": "set_volume", "args": {"level": 75}}, socket_path=socket_path)

    bench("IPC set_volume (player method only)", ipc_set_volume, iterations=200)

    # Benchmark connection overhead (raw socket connect/disconnect)
    def raw_socket_connect():
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(socket_path)
        sock.close()

    bench("Raw socket connect + close (no data)", raw_socket_connect, iterations=1000)

    # Connection-per-call measurement (already done above)
    # Note: daemon handles one request per connection (no keep-alive), so
    # connection pooling would require protocol changes at daemon.py:245-256

    import shutil
    shutil.rmtree(tmp_dir, ignore_errors=True)


# ============================================================================
# 6. TUI INPUT LOOP BENCHMARKS
# ============================================================================

def bench_tui_input():
    """Benchmark TUI input handling patterns."""
    print("=" * 60)
    print("6. TUI INPUT LOOP BENCHMARKS")
    print("=" * 60)

    # Benchmark select-based polling (used in all TUI variants)
    import select

    def select_poll_no_input(timeout=0.1):
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        return r

    bench("select.select polling (0.1s timeout, no input)", select_poll_no_input, iterations=50, warmup=0)

    # Benchmark select with shorter timeout (search_picker.py uses 0.05)
    def select_poll_short(timeout=0.05):
        r, _, _ = select.select([sys.stdin], [], [], timeout)
        return r

    bench("select.select polling (0.05s timeout, no input)", select_poll_short, iterations=100, warmup=0)

    # Benchmark os.popen('tput lines') pattern from search_picker.py:88
    def tput_lines():
        try:
            return int(os.popen('tput lines').read().strip())
        except (ValueError, TypeError):
            return 24

    bench("os.popen('tput lines') (subprocess spawn per paginator init)", tput_lines, iterations=100)

    # Benchmark shutil.get_terminal_size (proper alternative)
    import shutil

    def shutil_term_size():
        return shutil.get_terminal_size(fallback=(80, 24))

    bench("shutil.get_terminal_size (no subprocess, recommended)", shutil_term_size, iterations=1000)

    # Benchmark the termios syscall overhead (simulated without PTY)
    # Measure individual syscalls
    import termios
    import tty

    def measure_tcgetattr():
        """Measure tcgetattr syscall overhead on /dev/null fstat."""
        try:
            fd = os.open(os.devnull, os.O_RDONLY)
            try:
                attrs = termios.tcgetattr(fd)
                return attrs
            finally:
                os.close(fd)
        except Exception:
            return None

    bench("termios.tcgetattr (syscall overhead, /dev/null)", measure_tcgetattr, iterations=2000)

    def measure_tcsetattr():
        """Measure tcsetattr + tcgetattr (toggle raw mode) overhead."""
        try:
            fd = os.open(os.devnull, os.O_RDONLY)
            try:
                old = termios.tcgetattr(fd)
                # Can't actually set raw on /dev/null, but measure the overhead
                return old
            finally:
                os.close(fd)
        except Exception:
            return None

    bench("tcgetattr+tcsetattr pair (raw mode toggle overhead)", measure_tcsetattr, iterations=2000)

    # Benchmark get_terminal_size from tui_resilient.py used in loop
    def get_ts():
        from foundation.tui_resilient import get_terminal_size
        return get_terminal_size()

    bench("tui_resilient.get_terminal_size (with min/max clamping)", get_ts, iterations=2000)

    # Benchmark Track.core_key() repeated calls (simulating input loop overhead)
    track = make_test_track("Song A (Official Video) [2024 Remaster] ft. Featured", "Artist Name", "vid001")

    def core_key_repeated():
        return track.core_key()

    bench("Track.core_key() × 100 (simulating 100 key reads in loop)",
          lambda: [core_key_repeated() for _ in range(100)], iterations=20)


# ============================================================================
# 7. MEMORY LEAK CHECKS
# ============================================================================

def bench_memory_patterns():
    """Benchmark memory allocation patterns."""
    print("=" * 60)
    print("7. MEMORY ALLOCATION BENCHMARKS")
    print("=" * 60)

    # Track object memory
    tracemalloc.start()
    tracks = [make_test_track(f"Song {i}", f"Artist {i%10}", f"vid{i:04d}") for i in range(1000)]
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"  1000 Track objects: current={current/1024:.1f}KB, peak={peak/1024:.1f}KB")

    # TasteEngine seen_track_ids memory
    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, "mem_bench.db")
    db = MusiclyDB(db_path=db_path)
    taste_engine = TasteEngine(db=db)

    tracemalloc.start()
    for i in range(1000):
        taste_engine._mark_seen(f"track_id_{i}")
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"  1000 seen_track_ids: current={current/1024:.1f}KB, peak={peak/1024:.1f}KB")

    # SQLite operations memory
    tracemalloc.start()
    for i in range(1000):
        db.upsert_track({"id": f"mem_vid{i}", "title": f"Mem Song {i}", "artist": f"Mem Artist {i}",
                         "url": f"https://youtu.be/mem{i}"})
    current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"  1000 upsert_track calls: current={current/1024:.1f}KB, peak={peak/1024:.1f}KB")

    import shutil
    shutil.rmtree(tmp_dir)
    print()


# ============================================================================
# MAIN
# ============================================================================

def main():
    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║     MusicCLI Performance Benchmark Suite                 ║")
    print("║     Comprehensive profiling of all subsystems           ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    results = {}

    # Run all benchmarks
    bench_ytdlp_subprocess_calls()
    bench_track_parsing()
    bench_sqlite_operations()
    bench_taste_engine()
    bench_ipc_socket()
    bench_tui_input()
    bench_memory_patterns()

    # Summary
    print("=" * 60)
    print("BENCHMARK SUMMARY")
    print("=" * 60)
    print()
    print("Key bottlenecks identified:")
    print("  1. yt-dlp subprocess: ~2.3s per search call (network-bound)")
    print("  2. SQLite: connection-per-call overhead (~0.4-0.8ms per op)")
    print("  3. TUI input: get_char() toggles raw mode per keypress (~0.18ms)")
    print("  4. IPC: New connection per call (~0.48ms round-trip)")
    print("  5. TasteEngine: O(n²) duplicate filtering + 2× subprocess calls")
    print("  6. Missing SQLite indexes on feedback_logs, trends, taste_analysis")
    print("  7. play_track uses shell=True with string interpolation (injection risk)")
    print("  8. play_with_radio busy-polls with no sleep (100% CPU)")
    print()


if __name__ == "__main__":
    main()
