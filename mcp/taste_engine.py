"""Adaptive Taste Engine & Situation Vibe Engine for Musicly.

Manages situation states, 80/20 exploitation/exploration queue generation,
feedback-driven seed updates, and trend integration.
"""

import random
from collections import OrderedDict, deque
from typing import List, Dict, Any, Optional, Set
from foundation import search_songs, get_radio_tracks
from .db import MusiclyDB

# Maximum number of track IDs to retain in the seen set to prevent
# unbounded memory growth in the long-lived daemon process.
SEEN_TRACK_IDS_MAX = 1000
MAX_QUEUE_SIZE = 50


class TasteEngine:
    def __init__(self, db: Optional[MusiclyDB] = None):
        self.db = db or MusiclyDB()
        self.autodj_enabled: bool = True
        self.endless_enabled: bool = True
        self.current_situation: str = "general"
        self.queue: deque = deque(maxlen=MAX_QUEUE_SIZE)
        self.seen_track_ids: OrderedDict = OrderedDict()
        self.pivot_prompt_needed: bool = False
        self.active_pivot_genre: Optional[str] = None
        self.active_pivot_track: Optional[Dict[str, Any]] = None
        self.pivot_mode: bool = False

    def clear_queue(self):
        """Clear pending queue of tracks."""
        self.queue.clear()

    def reset_session(self):
        """Reset queue, pivot state, and seen tracks."""
        self.clear_queue()
        self.clear_pivot()
        self.seen_track_ids.clear()

    def _mark_seen(self, track_id: str) -> None:
        """Record a track ID as seen, capping the OrderedDict at SEEN_TRACK_IDS_MAX."""
        if track_id in self.seen_track_ids:
            # Move to end to mark as most-recently-seen
            self.seen_track_ids.move_to_end(track_id)
        else:
            self.seen_track_ids[track_id] = None
            # Evict oldest entries if over the cap
            while len(self.seen_track_ids) > SEEN_TRACK_IDS_MAX:
                self.seen_track_ids.popitem(last=False)

    def set_explicit_pivot_track(self, track: Dict[str, Any]):
        artist = track.get("artist")
        title = track.get("title")
        seeds = []
        if artist and artist not in ("Unknown Artist", "YouTube"):
            self.active_pivot_genre = f"{artist} and similar artists"
            seeds.append(f"artists similar to {artist}")
            seeds.append(f"{artist} top hits")
        if title:
            clean_t = title.replace("Official Video", "").replace("Audio", "").strip()
            if clean_t and clean_t not in ("Web Stream", "Track"):
                seeds.append(f"songs like {clean_t}")

        for s in seeds:
            self.db.add_query_seed_for_situation(self.current_situation, s)

        # Activate pivot mode so endless play keeps playing similar songs.
        # Only tracks with a resolvable id (search results) can anchor radio similarity.
        if track.get("id") or track.get("url"):
            self.active_pivot_track = track
            self.pivot_mode = True
        self.pivot_prompt_needed = True

    def clear_pivot(self):
        self.active_pivot_track = None
        self.active_pivot_genre = None
        self.pivot_mode = False
        self.pivot_prompt_needed = False

    def confirm_pivot(self, keep_pivot: bool):
        if keep_pivot and self.active_pivot_genre:
            self.db.add_query_seed_for_situation(self.current_situation, self.active_pivot_genre)
            self.pivot_mode = True
        else:
            self.pivot_mode = False
            self.active_pivot_track = None
            self.active_pivot_genre = None
        self.pivot_prompt_needed = False

    def set_autodj(self, enabled: bool) -> bool:
        self.autodj_enabled = enabled
        self.endless_enabled = enabled
        if not enabled:
            self.clear_pivot()
        return self.autodj_enabled

    def set_situation(self, situation: str) -> str:
        valid_situations = {
            "build_failed", "out_of_ideas", "git_stuck",
            "build_success", "flow_state", "general"
        }
        if situation in valid_situations:
            self.current_situation = situation
        else:
            self.current_situation = "general"
        # Switching situation reverts to that mood's music, not the last pivot.
        self.pivot_mode = False
        self.active_pivot_track = None
        self.active_pivot_genre = None
        return self.current_situation

    def detect_cultural_anchor(self, track: Dict[str, Any]) -> str:
        """Detect cultural / language / genre anchor from track metadata."""
        if not track:
            return "general"

        title = track.get("title", "").lower()
        artist = track.get("artist", "").lower()
        combined = f"{title} {artist}"

        # Unicode Devanagari (Hindi, Marathi)
        if any('\u0900' <= char <= '\u097F' for char in combined):
            return "hindi"
        # Unicode Gurmukhi (Punjabi)
        if any('\u0A00' <= char <= '\u0A7F' for char in combined):
            return "punjabi"
        # Unicode Japanese / CJK
        if any(('\u3040' <= char <= '\u309F') or ('\u30A0' <= char <= '\u30FF') or ('\u4E00' <= char <= '\u9FFF') for char in combined):
            return "japanese"

        # Keyword matching
        if any(w in combined for w in ["hindi", "bollywood", "arijit", "pritam", "lata", "kishore", "shreya"]):
            return "hindi"
        if any(w in combined for w in ["punjabi", "diljit", "sidhu", "ap dhillon", "bhangra"]):
            return "punjabi"
        if any(w in combined for w in ["synthwave", "retrowave", "outrun", "the midnight"]):
            return "synthwave"
        if any(w in combined for w in ["lofi", "lo-fi", "chillhop", "study beat"]):
            return "lofi"
        if any(w in combined for w in ["anime", "city pop", "j-pop", "jpop"]):
            return "japanese"

        return "general"

    def process_implicit_feedback(self, track: Dict[str, Any], listen_duration: float, total_duration: float):
        """Process implicit behavioral signals (completion rate, dwell time, quick skips)."""
        if not track or total_duration <= 0:
            return

        ratio = listen_duration / total_duration
        tid = track.get("id") or track.get("track_id")

        if ratio >= 0.8:
            # Strong implicit positive: listened to >80% of track
            self.record_feedback(track, action="like", feedback_text="Implicit: high completion rate", situation=self.current_situation)
        elif ratio < 0.15 and total_duration >= 30:
            # Soft implicit negative: skipped within first 15% of track
            sit = self.current_situation
            self.db.log_feedback(track, sit, action="skip", feedback_text="Implicit: quick skip")
            anchor = self.detect_cultural_anchor(track)
            if anchor != "general":
                # Apply situation-bound soft penalty with decay
                self.db.log_contextual_penalty(anchor, sit, weight=0.5)

    def record_feedback(
        self,
        track: Dict[str, Any],
        action: str,
        feedback_text: str = "",
        situation: Optional[str] = None
    ) -> Dict[str, Any]:
        sit = situation or self.current_situation
        result = self.db.log_feedback(track, sit, action, feedback_text)

        # Extract negative themes on dislike for contextual penalty tracking
        if action == "dislike":
            anchor = self.detect_cultural_anchor(track)
            if anchor != "general":
                self.db.log_contextual_penalty(anchor, sit, weight=0.8)

            if feedback_text:
                fb_lower = feedback_text.lower()
                for theme in ["lofi", "synthwave", "rock", "metal", "remix", "piano", "pop"]:
                    if theme in fb_lower:
                        self.db.log_contextual_penalty(theme, sit, weight=0.9)

        # Adapt taste seeds upon positive feedback
        if action == "like":
            artist = track.get("artist")
            if artist and artist != "Unknown Artist":
                self.db.add_query_seed_for_situation(sit, f"{artist} chill music")
            title = track.get("title")
            if title:
                clean_title = title.replace("Official", "").replace("Video", "").replace("Audio", "").strip()
                self.db.add_query_seed_for_situation(sit, clean_title[:40])

        return result

    def get_disliked_ids(self) -> Set[str]:
        return set(self.db.get_disliked_track_ids())

    def fetch_next_endless_track(self, current_track: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        disliked = self.get_disliked_ids()

        # 1. Pop from active queue if populated and not disliked
        while self.queue:
            candidate = self.queue.popleft()
            cid = candidate.get("id") or candidate.get("track_id")
            if cid and cid not in disliked and cid not in self.seen_track_ids:
                self._mark_seen(cid)
                return candidate

        # 2. Refill Queue using Hybrid Recommendation Pool & Cognitive Load Governor
        refilled_tracks = self._refill_autodj_pool(current_track, disliked)
        if refilled_tracks:
            self.queue.extend(refilled_tracks)
            candidate = self.queue.popleft()
            cid = candidate.get("id") or candidate.get("track_id")
            if cid:
                self._mark_seen(cid)
            return candidate

        return None

    def fetch_next_autodj_track(self, current_track: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Alias for backward compatibility."""
        return self.fetch_next_endless_track(current_track)

    def _refill_autodj_pool(
        self,
        current_track: Optional[Dict[str, Any]],
        disliked_ids: Set[str]
    ) -> List[Dict[str, Any]]:
        pool: List[Dict[str, Any]] = []
        active_penalties = self.db.get_active_contextual_penalties(self.current_situation)

        # Determine the anchor for similar-song generation
        anchor = None
        if current_track and current_track.get("id"):
            anchor = current_track
        elif self.active_pivot_track and self.active_pivot_track.get("id"):
            anchor = self.active_pivot_track

        anchor_domain = self.detect_cultural_anchor(anchor) if anchor else "general"

        if self.pivot_mode and anchor:
            # 1. YouTube Mix Radio of the anchor track (natural language & vibe flow)
            radio = get_radio_tracks(anchor["id"], count=10)
            for tr in radio:
                tid = tr.get("id")
                if tid and tid not in self.seen_track_ids and tid not in disliked_ids:
                    pool.append(tr)

            # 2. Fused Seed Searches matching anchor artist + situation mood
            if len(pool) < 10:
                seeds = self._build_pivot_seeds(anchor)
                for seed in seeds:
                    searched = search_songs(seed, count=6)
                    for tr in searched:
                        tid = tr.get("id")
                        if tid and tid not in self.seen_track_ids and tid not in disliked_ids:
                            pool.append(tr)
                    if len(pool) >= 10:
                        break

            # 3. Sprinkle in liked tracks matching situation
            if len(pool) < 6:
                liked_tracks = self.db.get_liked_tracks(situation=self.current_situation, limit=10)
                unseen_liked = [t for t in liked_tracks if t.get("track_id") not in self.seen_track_ids and t.get("track_id") not in disliked_ids]
                pool.extend(unseen_liked[:3])
            if len(pool) < 8:
                trends = self.db.get_recent_trends(limit=10)
                unseen_trends = [t for t in trends if t.get("track_id") not in self.seen_track_ids and t.get("track_id") not in disliked_ids]
                if unseen_trends:
                    pool.insert(min(2, len(pool)), random.choice(unseen_trends))
        else:
            # DEFAULT FLUID MODE: Blended Pool with Cognitive Load Governor
            liked_tracks = self.db.get_liked_tracks(situation=self.current_situation, limit=10)
            unseen_liked = [t for t in liked_tracks if t.get("track_id") not in self.seen_track_ids and t.get("track_id") not in disliked_ids]

            if unseen_liked and random.random() < 0.5:
                pool.extend(unseen_liked)

            # Radio mix from current track if available
            if current_track and current_track.get("id") and len(pool) < 5:
                radio = get_radio_tracks(current_track["id"], count=10)
                for tr in radio:
                    tid = tr.get("id")
                    if tid and tid not in self.seen_track_ids and tid not in disliked_ids:
                        pool.append(tr)

            # Fused situation seed queries: blend anchor domain with situation intent
            if len(pool) < 8:
                seed_data = self.db.get_situation_seed(self.current_situation)
                query_seeds = seed_data.get("query_seeds", ["chill coding music"])

                # Fuse with anchor domain if specific
                if anchor_domain != "general":
                    selected_query = f"{anchor_domain} {random.choice(query_seeds)}"
                else:
                    selected_query = random.choice(query_seeds)

                # Cognitive Load Governor: Add soft acoustic filter for debugging
                if self.current_situation == "build_failed":
                    selected_query += " soft acoustic relaxed"

                searched = search_songs(selected_query, count=10)
                for tr in searched:
                    tid = tr.get("id")
                    if tid and tid not in self.seen_track_ids and tid not in disliked_ids:
                        pool.append(tr)

            # 20% Exploration: Recent trends
            trends = self.db.get_recent_trends(limit=10)
            unseen_trends = [t for t in trends if t.get("track_id") not in self.seen_track_ids and t.get("track_id") not in disliked_ids]
            if unseen_trends:
                pool.insert(min(2, len(pool)), random.choice(unseen_trends))

        # Filter duplicates, disliked IDs, and contextual decay penalties
        unique_pool = []
        seen_in_pool: Set[str] = set()
        for tr in pool:
            tid = tr.get("id") or tr.get("track_id")
            if not tid or tid in disliked_ids or tid in seen_in_pool:
                continue

            # Check contextual decay penalties
            tr_title = (tr.get("title") or "").lower()
            tr_artist = (tr.get("artist") or "").lower()
            combined = f"{tr_title} {tr_artist}"

            penalty_hit = False
            for theme, weight in active_penalties.items():
                if weight > 0.6 and theme in combined:
                    penalty_hit = True
                    break

            if not penalty_hit:
                seen_in_pool.add(tid)
                unique_pool.append(tr)

        return unique_pool

    def _build_pivot_seeds(self, track: Dict[str, Any]) -> List[str]:
        """Build search queries that surface tracks similar to the pivot track."""
        seeds: List[str] = []
        artist = track.get("artist")
        title = track.get("title")
        if artist and artist not in ("Unknown Artist", "YouTube"):
            seeds.append(f"artists similar to {artist}")
            seeds.append(f"{artist} top hits")
        if title:
            clean_t = title.replace("Official Video", "").replace("Audio", "").strip()
            if clean_t and clean_t not in ("Web Stream",):
                seeds.append(f"songs like {clean_t}")
        if self.active_pivot_genre:
            seeds.append(self.active_pivot_genre)
        return seeds
