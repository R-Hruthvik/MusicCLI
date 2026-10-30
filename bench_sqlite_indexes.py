#!/usr/bin/env python3
"""SQLite index impact benchmark for Musicly MusiclyDB.

Demonstrates the performance degradation from missing indexes on
feedback_logs, trends, and taste_analysis tables.
"""

import os
import sys
import json
import time
import sqlite3
import tempfile
import shutil
from collections import OrderedDict

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from mcp.db import MusiclyDB

def bench(name, func, iterations=1):
    start = time.perf_counter_ns()
    for _ in range(iterations):
        func()
    elapsed_ns = time.perf_counter_ns() - start
    avg_ms = elapsed_ns / iterations / 1_000_000
    print(f"  {name}: {elapsed_ns/1_000_000:.2f}ms total, {avg_ms:.4f}ms avg")
    return avg_ms


def create_test_db_with_data(db_path, num_feedback=1000, num_tracks=500, num_trends=500):
    """Create a test DB with substantial data to expose index issues."""
    os.makedirs(os.path.dirname(db_path) + "/dummy", exist_ok=True) if False else None
    db = MusiclyDB(db_path=db_path)

    # Insert tracks
    for i in range(num_tracks):
        track = {
            "id": f"vid{i:05d}",
            "title": f"Song {i}",
            "artist": f"Artist {i % 20}",
            "duration": "3:30",
            "url": f"https://youtu.be/vid{i:05d}",
            "genre_tags": ["lofi", "chill"]
        }
        db.upsert_track(track)

    # Insert feedback logs (various actions and situations)
    situations = ["build_failed", "out_of_ideas", "git_stuck", "build_success", "flow_state", "general"]
    actions = ["like", "dislike", "skip", "play", "complete"]
    for i in range(num_feedback):
        track = {
            "id": f"vid{i:05d}",
            "title": f"Song {i}",
            "artist": f"Artist {i % 20}",
            "duration": "3:30",
            "url": f"https://youtu.be/vid{i:05d}",
        }
        sit = situations[i % len(situations)]
        act = actions[i % len(actions)]
        db.log_feedback(track, sit, act, feedback_text=f"feedback {i}")

    # Insert trends
    for i in range(num_trends):
        track = {
            "id": f"trend{i:04d}",
            "title": f"Trend {i}",
            "artist": f"TrendArtist {i % 10}",
        }
        db.add_trend(track, source="agent_search", query=f"query {i % 5}")

    # Insert taste analysis
    for i in range(50):
        db.save_taste_analysis(
            situation=situations[i % len(situations)],
            preference_summary=f"Pref summary {i}",
            top_genres=json.dumps(["lofi", "chill"]),
            disliked_themes=json.dumps(["noisy"]),
        )

    return db


def create_indexed_db(db_path, num_feedback=1000, num_tracks=500, num_trends=500):
    """Create a test DB with the same data but WITH indexes."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Create tables (same schema as MusiclyDB)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tracks (
            track_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            artist TEXT NOT NULL,
            duration TEXT,
            url TEXT NOT NULL,
            genre_tags TEXT DEFAULT '[]',
            play_count INTEGER DEFAULT 0,
            like_count INTEGER DEFAULT 0,
            dislike_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS feedback_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id TEXT NOT NULL,
            situation TEXT NOT NULL,
            action TEXT NOT NULL,
            feedback_text TEXT DEFAULT '',
            user_id TEXT DEFAULT 'default_user',
            device_id TEXT DEFAULT 'local',
            sync_status TEXT DEFAULT 'pending',
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS situation_seeds (
            situation TEXT PRIMARY KEY,
            mood_name TEXT NOT NULL,
            query_seeds TEXT NOT NULL,
            weight REAL DEFAULT 1.0,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS trends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id TEXT NOT NULL,
            title TEXT,
            artist TEXT,
            source TEXT NOT NULL,
            query TEXT,
            user_liked INTEGER DEFAULT 0,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS taste_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT DEFAULT 'default_user',
            situation TEXT NOT NULL,
            preference_summary TEXT NOT NULL,
            top_genres TEXT DEFAULT '[]',
            disliked_themes TEXT DEFAULT '[]',
            confidence_score REAL DEFAULT 0.8,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Insert default situation seeds
    defaults = [
        ("build_failed", "Calm Focus & Reset", json.dumps(["lofi hip hop study focus"])),
        ("out_of_ideas", "Creative Spark", json.dumps(["synthwave chillwave focus"])),
        ("git_stuck", "Steady Methodical Rhythm", json.dumps(["deep focus techno beats"])),
        ("build_success", "Victory & High Energy", json.dumps(["upbeat funk disco music"])),
        ("flow_state", "Deep Coding Flow", json.dumps(["binaural beats deep focus"])),
        ("general", "Balanced Station", json.dumps(["chill coding music"])),
    ]
    conn.executemany("""
        INSERT INTO situation_seeds (situation, mood_name, query_seeds)
        VALUES (?, ?, ?)
    """, defaults)
    conn.commit()

    # NOW CREATE INDEXES (the improvement)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_action ON feedback_logs(action)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_situation ON feedback_logs(situation)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_track_situation ON feedback_logs(track_id, situation)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_timestamp ON feedback_logs(timestamp)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_feedback_action_situation ON feedback_logs(action, situation)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trends_timestamp ON trends(timestamp)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trends_track_id ON trends(track_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_taste_situation ON taste_analysis(situation)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_taste_updated_at ON taste_analysis(updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_like_count ON tracks(like_count DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_dislike_count ON tracks(dislike_count)")
    conn.commit()

    # Insert same data
    situations = ["build_failed", "out_of_ideas", "git_stuck", "build_success", "flow_state", "general"]
    actions = ["like", "dislike", "skip", "play", "complete"]

    for i in range(num_tracks):
        conn.execute("""
            INSERT OR REPLACE INTO tracks (track_id, title, artist, duration, url, genre_tags, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (f"vid{i:05d}", f"Song {i}", f"Artist {i % 20}", "3:30",
              f"https://youtu.be/vid{i:05d}", json.dumps(["lofi", "chill"])))

    conn.commit()

    for i in range(num_feedback):
        track_id = f"vid{i:05d}"
        sit = situations[i % len(situations)]
        act = actions[i % len(actions)]
        # Upsert track
        conn.execute("""
            INSERT OR REPLACE INTO tracks (track_id, title, artist, duration, url, genre_tags, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (track_id, f"Song {i}", f"Artist {i % 20}", "3:30",
              f"https://youtu.be/vid{i:05d}", json.dumps([])))
        # Insert feedback
        conn.execute("""
            INSERT INTO feedback_logs (track_id, situation, action, feedback_text, user_id, device_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (track_id, sit, act, f"feedback {i}", "default_user", "local"))
        # Update counts
        if act == "like":
            conn.execute("UPDATE tracks SET like_count = like_count + 1 WHERE track_id = ?", (track_id,))
        elif act == "dislike":
            conn.execute("UPDATE tracks SET dislike_count = dislike_count + 1 WHERE track_id = ?", (track_id,))
        elif act in ("play", "complete"):
            conn.execute("UPDATE tracks SET play_count = play_count + 1 WHERE track_id = ?", (track_id,))

    conn.commit()

    for i in range(num_trends):
        conn.execute("""
            INSERT INTO trends (track_id, title, artist, source, query)
            VALUES (?, ?, ?, ?, ?)
        """, (f"trend{i:04d}", f"Trend {i}", f"TrendArtist {i % 10}", "agent_search", f"query {i % 5}"))
        # Upsert track
        conn.execute("""
            INSERT OR REPLACE INTO tracks (track_id, title, artist, duration, url, genre_tags, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """, (f"trend{i:04d}", f"Trend {i}", f"TrendArtist {i % 10}", "3:00",
              f"https://youtu.be/trend{i:04d}", json.dumps([])))

    conn.commit()

    for i in range(50):
        conn.execute("""
            INSERT INTO taste_analysis (user_id, situation, preference_summary, top_genres, disliked_themes, confidence_score)
            VALUES (?, ?, ?, ?, ?, ?)
        """, ("default_user", situations[i % len(situations)], f"Pref summary {i}",
              json.dumps(["lofi", "chill"]), json.dumps(["noisy"]), 0.8))

    conn.commit()
    conn.close()
    return db_path


def run_benchmarks():
    print()
    print("=" * 60)
    print("SQLITE INDEX IMPACT BENCHMARK")
    print("=" * 60)
    print()

    tmp_dir = tempfile.mkdtemp()
    
    # Create unindexed DB (current schema)
    no_index_db = os.path.join(tmp_dir, "no_index.db")
    db_no = create_test_db_with_data(no_index_db, num_feedback=1000, num_tracks=500, num_trends=500)

    # Create indexed DB (with proper indexes)
    indexed_db = os.path.join(tmp_dir, "indexed.db")
    create_indexed_db(indexed_db, num_feedback=1000, num_tracks=500, num_trends=500)

    # Create separate MusiclyDB instances for indexed DB
    db_idx = MusiclyDB(db_path=indexed_db)

    print("--- Without Indexes (current schema) ---")
    bench("get_feedback_summary (4 COUNTs, 1000+ rows)", 
          lambda: db_no.get_feedback_summary(), iterations=20)
    
    bench("get_recent_trends (JOIN + ORDER BY, 500 trends)",
          lambda: db_no.get_recent_trends(limit=15), iterations=20)
    
    bench("get_liked_tracks(situation='general', limit=20) (JOIN+WHERE+ORDER BY)",
          lambda: db_no.get_liked_tracks(situation="general", limit=20), iterations=20)
    
    bench("get_raw_feedback_logs (JOIN + ORDER BY, 20 rows)",
          lambda: db_no.get_raw_feedback_logs(limit=20), iterations=20)
    
    bench("get_disliked_track_ids (WHERE dislike_count > 0, 500 tracks)",
          lambda: db_no.get_disliked_track_ids(), iterations=20)
    
    bench("get_taste_analysis(situation='general', limit=5) (WHERE + ORDER BY)",
          lambda: db_no.get_taste_analysis(situation="general", limit=5), iterations=20)
    
    bench("upsert_track (connection-per-call, 500 existing tracks)",
          lambda: db_no.upsert_track({"id": "vid00001", "title": "Updated", "artist": "Artist", "url": "https://youtu.be/vid00001"}),
          iterations=50)

    print()
    print("--- With Indexes (proposed schema) ---")
    bench("get_feedback_summary (4 COUNTs, indexed)",
          lambda: db_idx.get_feedback_summary(), iterations=20)
    
    bench("get_recent_trends (JOIN + ORDER BY, indexed)",
          lambda: db_idx.get_recent_trends(limit=15), iterations=20)
    
    bench("get_liked_tracks(situation='general', limit=20) (indexed)",
          lambda: db_idx.get_liked_tracks(situation="general", limit=20), iterations=20)
    
    bench("get_raw_feedback_logs (JOIN + ORDER BY, indexed)",
          lambda: db_idx.get_raw_feedback_logs(limit=20), iterations=20)
    
    bench("get_disliked_track_ids (indexed)",
          lambda: db_idx.get_disliked_track_ids(), iterations=20)
    
    bench("get_taste_analysis(situation='general', limit=5) (indexed)",
          lambda: db_idx.get_taste_analysis(situation="general", limit=5), iterations=20)
    
    bench("upsert_track (indexed)",
          lambda: db_idx.upsert_track({"id": "vid00001", "title": "Updated", "artist": "Artist", "url": "https://youtu.be/vid00001"}),
          iterations=50)

    # Explain query plans
    print()
    print("--- Query Plan Analysis (WITHOUT indexes) ---")
    conn = sqlite3.connect(no_index_db)
    queries = [
        ("get_feedback_summary (COUNT)", "SELECT COUNT(*) as c FROM feedback_logs WHERE action='like'"),
        ("get_recent_trends (JOIN+ORDER)", """
            SELECT t.*, tr.title, tr.artist, tr.url, tr.duration
            FROM trends t
            LEFT JOIN tracks tr ON t.track_id = tr.track_id
            ORDER BY t.timestamp DESC
            LIMIT 15
        """),
        ("get_liked_tracks", """
            SELECT DISTINCT t.* FROM tracks t
            JOIN feedback_logs f ON t.track_id = f.track_id
            WHERE f.action = 'like' AND f.situation = 'general'
            ORDER BY t.like_count DESC, t.updated_at DESC
            LIMIT 20
        """),
        ("get_disliked_track_ids", "SELECT DISTINCT track_id FROM tracks WHERE dislike_count > 0"),
    ]
    for label, sql in queries:
        plan = conn.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
        print(f"  {label}:")
        for row in plan:
            print(f"    {' → '.join(str(x) for x in row)}")
    conn.close()

    print()
    print("--- Query Plan Analysis (WITH indexes) ---")
    conn = sqlite3.connect(indexed_db)
    for label, sql in queries:
        plan = conn.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
        print(f"  {label}:")
        for row in plan:
            print(f"    {' → '.join(str(x) for x in row)}")
    conn.close()

    # Cleanup
    shutil.rmtree(tmp_dir)
    print()


if __name__ == "__main__":
    run_benchmarks()
