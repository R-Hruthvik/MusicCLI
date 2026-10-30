"""Clean, unbloated SQLite storage for Musicly MCP Server."""

import os
import sqlite3
import json
from typing import List, Dict, Any, Optional

DEFAULT_DB_DIR = os.path.expanduser("~/.config/musicly")
DEFAULT_DB_PATH = os.path.join(DEFAULT_DB_DIR, "musicly.db")


class MusiclyDB:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            # Tracks table
            cursor.execute("""
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

            # Feedback Logs (Sync-ready for cloud)
            cursor.execute("""
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

            # Situation seeds mapping (Evolvable taste seeds)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS situation_seeds (
                    situation TEXT PRIMARY KEY,
                    mood_name TEXT NOT NULL,
                    query_seeds TEXT NOT NULL,
                    weight REAL DEFAULT 1.0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Trends table
            cursor.execute("""
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

            # Taste Analysis Table (AI Agent Refined Preferences)
            cursor.execute("""
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

            # Contextual penalties table for situation-bound soft penalties with time decay
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS contextual_penalties (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain_or_theme TEXT NOT NULL,
                    situation TEXT NOT NULL,
                    penalty_weight REAL DEFAULT 1.0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Indexes for performance
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_action ON feedback_logs(action)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_situation ON feedback_logs(situation)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_action_situation ON feedback_logs(action, situation)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_timestamp ON feedback_logs(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trends_timestamp ON trends(timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_trends_track_id ON trends(track_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_taste_analysis_situation ON taste_analysis(situation)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_taste_analysis_updated_at ON taste_analysis(updated_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_contextual_penalties_sit ON contextual_penalties(situation)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracks_like_count ON tracks(like_count DESC)")

            # Populate default situation seeds if empty
            cursor.execute("SELECT COUNT(*) as cnt FROM situation_seeds")
            if cursor.fetchone()["cnt"] == 0:
                defaults = [
                    ("build_failed", "Calm Focus & Reset", json.dumps([
                        "lofi hip hop study focus",
                        "relaxing piano anime lofi",
                        "japanese city pop instrumental",
                        "calming acoustic ambient"
                    ])),
                    ("out_of_ideas", "Creative Spark", json.dumps([
                        "synthwave chillwave focus",
                        "post rock instrumental",
                        "ambient electronica background",
                        "modern jazz fusion chill"
                    ])),
                    ("git_stuck", "Steady Methodical Rhythm", json.dumps([
                        "deep focus techno beats",
                        "chiptune 8bit focus",
                        "math rock instrumental",
                        "classical piano focus"
                    ])),
                    ("build_success", "Victory & High Energy", json.dumps([
                        "upbeat funk disco music",
                        "triumphant synthpop energy",
                        "feel good indie rock",
                        "upbeat video game OST victory"
                    ])),
                    ("flow_state", "Deep Coding Flow", json.dumps([
                        "binaural beats deep focus",
                        "minecraft volume alpha chill",
                        "celeste soundtrack chill",
                        "ambient synth coding"
                    ])),
                    ("general", "Balanced Station", json.dumps([
                        "chill coding music",
                        "lofi beats to study work to",
                        "relaxing background music"
                    ]))
                ]
                cursor.executemany("""
                    INSERT INTO situation_seeds (situation, mood_name, query_seeds)
                    VALUES (?, ?, ?)
                """, defaults)

            conn.commit()

    # --- Tracks CRUD ---
    def upsert_track(self, track: Dict[str, Any]) -> None:
        tid = track.get("id") or track.get("track_id")
        if not tid:
            return
        title = track.get("title", "Untitled")
        artist = track.get("artist", "Unknown Artist")
        duration = track.get("duration", "--:--")
        url = track.get("url", f"https://www.youtube.com/watch?v={tid}")
        genre_tags = json.dumps(track.get("genre_tags", []))

        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO tracks (track_id, title, artist, duration, url, genre_tags, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(track_id) DO UPDATE SET
                    title=excluded.title,
                    artist=excluded.artist,
                    duration=excluded.duration,
                    url=excluded.url,
                    updated_at=CURRENT_TIMESTAMP
            """, (tid, title, artist, duration, url, genre_tags))

    def get_track(self, track_id: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM tracks WHERE track_id = ?", (track_id,)).fetchone()
            if row:
                d = dict(row)
                d["genre_tags"] = json.loads(d["genre_tags"] or "[]")
                return d
            return None

    # --- Feedback Logging & Taste Evolution ---
    def log_feedback(
        self,
        track: Dict[str, Any],
        situation: str,
        action: str,
        feedback_text: str = "",
        user_id: str = "default_user",
        device_id: str = "local"
    ) -> Dict[str, Any]:
        tid = track.get("id") or track.get("track_id")
        with self._get_conn() as conn:
            cursor = conn.cursor()
            if tid:
                title = track.get("title", "Untitled")
                artist = track.get("artist", "Unknown Artist")
                duration = track.get("duration", "--:--")
                url = track.get("url", f"https://www.youtube.com/watch?v={tid}")
                genre_tags = json.dumps(track.get("genre_tags", []))
                cursor.execute("""
                    INSERT INTO tracks (track_id, title, artist, duration, url, genre_tags, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(track_id) DO UPDATE SET
                        title=excluded.title,
                        artist=excluded.artist,
                        duration=excluded.duration,
                        url=excluded.url,
                        updated_at=CURRENT_TIMESTAMP
                """, (tid, title, artist, duration, url, genre_tags))

            cursor.execute("""
                INSERT INTO feedback_logs (track_id, situation, action, feedback_text, user_id, device_id)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (tid or "unknown", situation, action, feedback_text, user_id, device_id))
            log_id = cursor.lastrowid

            if tid:
                if action == "like":
                    conn.execute("UPDATE tracks SET like_count = like_count + 1 WHERE track_id = ?", (tid,))
                elif action == "dislike":
                    conn.execute("UPDATE tracks SET dislike_count = dislike_count + 1 WHERE track_id = ?", (tid,))
                elif action in ("play", "complete"):
                    conn.execute("UPDATE tracks SET play_count = play_count + 1 WHERE track_id = ?", (tid,))

            conn.commit()

        return {
            "id": log_id,
            "track_id": tid,
            "situation": situation,
            "action": action,
            "feedback_text": feedback_text,
            "sync_status": "pending"
        }

    def get_liked_tracks(self, situation: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            if situation:
                query = """
                    SELECT DISTINCT t.* FROM tracks t
                    JOIN feedback_logs f ON t.track_id = f.track_id
                    WHERE f.action = 'like' AND f.situation = ?
                    ORDER BY t.like_count DESC, t.updated_at DESC
                    LIMIT ?
                """
                rows = conn.execute(query, (situation, limit)).fetchall()
            else:
                query = """
                    SELECT * FROM tracks
                    WHERE like_count > 0
                    ORDER BY like_count DESC, updated_at DESC
                    LIMIT ?
                """
                rows = conn.execute(query, (limit,)).fetchall()

            result = []
            for r in rows:
                d = dict(r)
                d["genre_tags"] = json.loads(d["genre_tags"] or "[]")
                result.append(d)
            return result

    def get_disliked_track_ids(self) -> List[str]:
        with self._get_conn() as conn:
            rows = conn.execute("SELECT DISTINCT track_id FROM tracks WHERE dislike_count > 0").fetchall()
            return [r["track_id"] for r in rows]

    # --- Situation Seeds ---
    def get_situation_seed(self, situation: str) -> Dict[str, Any]:
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM situation_seeds WHERE situation = ?", (situation,)).fetchone()
            if not row:
                row = conn.execute("SELECT * FROM situation_seeds WHERE situation = 'general'").fetchone()
            if row is None:
                return {
                    "situation": situation,
                    "mood_name": "focus",
                    "query_seeds": ["chill coding music"],
                    "weight": 1.0,
                    "updated_at": None,
                }
            d = dict(row)
            d["query_seeds"] = json.loads(d["query_seeds"])
            return d

    def add_query_seed_for_situation(self, situation: str, new_seed: str) -> None:
        seed_data = self.get_situation_seed(situation)
        seeds = seed_data.get("query_seeds", [])
        if new_seed not in seeds:
            seeds.insert(0, new_seed)
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE situation_seeds
                    SET query_seeds = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE situation = ?
                """, (json.dumps(seeds), situation))
                if cursor.rowcount == 0:
                    cursor.execute("""
                        INSERT INTO situation_seeds (situation, mood_name, query_seeds)
                        VALUES (?, ?, ?)
                    """, (situation, seed_data.get("mood_name", "focus"), json.dumps(seeds)))
                conn.commit()

    # --- Trends Logging ---
    def add_trend(self, track: Dict[str, Any], source: str = "agent_search", query: str = "") -> None:
        tid = track.get("id") or track.get("track_id")
        if not tid:
            return
        with self._get_conn() as conn:
            title = track.get("title", "Untitled")
            artist = track.get("artist", "Unknown Artist")
            duration = track.get("duration", "--:--")
            url = track.get("url", f"https://www.youtube.com/watch?v={tid}")
            genre_tags = json.dumps(track.get("genre_tags", []))
            conn.execute("""
                INSERT INTO tracks (track_id, title, artist, duration, url, genre_tags, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(track_id) DO UPDATE SET
                    title=excluded.title,
                    artist=excluded.artist,
                    duration=excluded.duration,
                    url=excluded.url,
                    updated_at=CURRENT_TIMESTAMP
            """, (tid, title, artist, duration, url, genre_tags))
            conn.execute("""
                INSERT INTO trends (track_id, title, artist, source, query)
                VALUES (?, ?, ?, ?, ?)
            """, (tid, track.get("title", ""), track.get("artist", ""), source, query))
            conn.commit()

    def get_recent_trends(self, limit: int = 15) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT t.*, tr.title, tr.artist, tr.url, tr.duration
                FROM trends t
                LEFT JOIN tracks tr ON t.track_id = tr.track_id
                ORDER BY t.timestamp DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_raw_feedback_logs(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT f.id, f.track_id, f.situation, f.action, f.feedback_text, f.timestamp,
                       t.title, t.artist, t.duration
                FROM feedback_logs f
                LEFT JOIN tracks t ON f.track_id = t.track_id
                ORDER BY f.timestamp DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]

    # --- Taste Analysis CRUD ---
    def save_taste_analysis(
        self,
        situation: str,
        preference_summary: str,
        top_genres: Optional[List[str]] = None,
        disliked_themes: Optional[List[str]] = None,
        confidence_score: float = 0.8,
        user_id: str = "default_user"
    ) -> int:
        top_genres_json = json.dumps(top_genres or [])
        disliked_json = json.dumps(disliked_themes or [])
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO taste_analysis (user_id, situation, preference_summary, top_genres, disliked_themes, confidence_score)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (user_id, situation, preference_summary, top_genres_json, disliked_json, confidence_score))
            conn.commit()
            return cursor.lastrowid

    def get_taste_analysis(self, situation: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            if situation:
                rows = conn.execute("""
                    SELECT * FROM taste_analysis
                    WHERE situation = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                """, (situation, limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM taste_analysis
                    ORDER BY updated_at DESC
                    LIMIT ?
                """, (limit,)).fetchall()

            result = []
            for r in rows:
                d = dict(r)
                d["top_genres"] = json.loads(d["top_genres"] or "[]")
                d["disliked_themes"] = json.loads(d["disliked_themes"] or "[]")
                result.append(d)
            return result

    def get_feedback_summary(self) -> Dict[str, Any]:
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT action, COUNT(*) as cnt
                FROM feedback_logs
                WHERE action IN ('like', 'dislike', 'skip')
                GROUP BY action
            """).fetchall()

            counts = {row["action"]: row["cnt"] for row in rows}
            total_logs = conn.execute("SELECT COUNT(*) as c FROM feedback_logs").fetchone()["c"]
            return {
                "total_logs": total_logs,
                "likes": counts.get("like", 0),
                "dislikes": counts.get("dislike", 0),
                "skips": counts.get("skip", 0),
            }

    def log_contextual_penalty(self, theme: str, situation: str, weight: float = 1.0):
        with self._get_conn() as conn:
            conn.execute("""
                INSERT INTO contextual_penalties (domain_or_theme, situation, penalty_weight, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """, (theme.lower(), situation, weight))
            conn.commit()

    def get_active_contextual_penalties(self, situation: str) -> Dict[str, float]:
        """Fetch active penalties with time-decay calculations."""
        with self._get_conn() as conn:
            rows = conn.execute("""
                SELECT domain_or_theme, penalty_weight,
                       (julianday('now') - julianday(updated_at)) * 24.0 as hours_old
                FROM contextual_penalties
                WHERE situation = ?
            """, (situation,)).fetchall()
            penalties = {}
            for r in rows:
                theme = r["domain_or_theme"]
                base_w = r["penalty_weight"]
                hours_old = r["hours_old"] if r["hours_old"] is not None else 0
                # 20% decay per 24 hours
                decay_factor = max(0.1, 1.0 - (hours_old / 24.0) * 0.2)
                effective_weight = base_w * decay_factor
                if theme not in penalties or effective_weight > penalties[theme]:
                    penalties[theme] = effective_weight
            return penalties
