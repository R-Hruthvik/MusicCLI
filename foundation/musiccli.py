#!/usr/bin/env python3
"""Minimal MusicCLI - no decoration, no borders, no headers."""

import subprocess
import sys
import termios
import tty
import random
import time
import re
import logging
from collections import deque
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, Set

from foundation.terminal_constants import CLEAR_SCREEN

PAGE_SIZE = 10

_DISCOVERY_QUERIES = [
    "chill lofi beats focus coding",
    "synthwave retrowave instrumental",
    "ambient piano relaxing music",
    "japanese city pop instrumental",
    "post rock instrumental focus",
]

@dataclass
class Track:
    title: str
    artist: str = "Unknown Artist"
    source: str = "YouTube"
    duration: str = "--:--"
    url: str = ""
    id: str = ""
    views: str = ""
    upload_date: str = ""

    @classmethod
    def from_line(cls, line: str) -> "Track":
        parts = [p.strip() for p in line.split("|||")]
        title = parts[0] if parts and parts[0] else "Untitled"
        vid = parts[1] if len(parts) > 1 else ""
        uploader = parts[2] if len(parts) > 2 and parts[2] not in ("NA", "") else ""
        channel = parts[3] if len(parts) > 3 and parts[3] not in ("NA", "") else ""
        artist = uploader or channel or "Unknown Artist"
        source = parts[4] if len(parts) > 4 and parts[4] not in ("NA", "") else "YouTube"
        duration = parts[5] if len(parts) > 5 and parts[5] not in ("NA", "--:--") else ""
        views = parts[6] if len(parts) > 6 else ""
        upload_date = parts[7] if len(parts) > 7 else ""
        url = f"https://www.youtube.com/watch?v={vid}" if vid else ""
        return cls(
            title=title,
            artist=artist,
            source=source,
            duration=duration,
            url=url,
            id=vid,
            views=views,
            upload_date=upload_date,
        )

    def core_key(self) -> str:
        t = self.title.lower()
        t = re.sub(r'\(.*?\)', '', t)
        t = re.sub(r'\[.*?\]', '', t)
        t = re.sub(r'ft\..*|feat\..*', '', t)
        t = re.sub(r'official video|official audio|lyric video', '', t)
        return re.sub(r'[^a-z0-9]', '', t)

    def artist_key(self) -> str:
        return re.sub(r'[^a-z0-9]', '', self.artist.lower())


def fmt_views(views: str) -> str:
    if not views or views == "NA":
        return "--"
    try:
        v = int(views)
        if v >= 1_000_000_000:
            return f"{v/1_000_000_000:.1f}B"
        if v >= 1_000_000:
            return f"{v/1_000_000:.1f}M"
        if v >= 1_000:
            return f"{v/1_000:.0f}K"
        return str(v)
    except Exception:
        return "--"


def fmt_upload_date(date_str: str) -> str:
    if len(date_str) == 8 and date_str.isdigit():
        return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"
    return date_str


def is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def is_playlist_url(s: str) -> bool:
    return is_url(s) and ("list=" in s or "playlist" in s)


def radio_seed(track: Track) -> str:
    if track.artist and track.artist != "Unknown Artist":
        return track.artist
    return track.core_key() or track.title


def select_search_results(tracks: List[Track], max_results: int = 10) -> List[Track]:
    seen_map = {}
    results = []
    for t in tracks:
        if not t.id and not t.title:
            continue
        if not t.title:
            continue
        key = (t.core_key(), t.artist_key())
        if key in seen_map:
            idx = seen_map[key]
            if not results[idx].duration and t.duration:
                results[idx] = t
            continue
        seen_map[key] = len(results)
        results.append(t)
        if len(results) >= max_results:
            break
    return results


def _run_ytdlp(urls: List[str], max_results: int = 30) -> List[Track]:
    cmd = [
        "yt-dlp",
        *urls,
        "--print", "%(title)s|||%(id)s|||%(uploader)s|||%(channel)s|||%(playlist)s|||%(duration_string)s|||%(view_count)s|||%(upload_date)s",
        "--no-warnings",
        "--no-update",
        "--flat-playlist",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if not result.stdout.strip():
            return []
        tracks = []
        for line in result.stdout.strip().split('\n'):
            if line.strip():
                tracks.append(Track.from_line(line))
        return tracks
    except Exception:
        return []


def search_youtube(query: str, max_results: int = 30) -> List[Track]:
    tracks = _run_ytdlp([f"ytsearch{max_results}:{query}"], max_results=max_results)
    return select_search_results(tracks, max_results)


def fetch_playlist(url: str, max_results: int = 50) -> List[Track]:
    return _run_ytdlp([url], max_results=max_results)


def fetch_single(url: str) -> Optional[Track]:
    tracks = _run_ytdlp([url], max_results=1)
    return tracks[0] if tracks else None


def fetch_radio_tracks(seed_track: Track, ctx: Dict[str, Any]) -> List[Track]:
    max_count = ctx.get('max', 15)
    dial = ctx.get('dial', 'balanced')
    if dial == 'discover' or ctx.get('discovery'):
        q = random.choice(_DISCOVERY_QUERIES)
        return search_youtube(q, max_results=max_count)
    
    if seed_track.id and dial != 'discover':
        mix_url = f"https://www.youtube.com/watch?v={seed_track.id}&list=RD{seed_track.id}"
        tracks = _run_ytdlp([mix_url], max_results=max_count + 1)
        if tracks:
            return [t for t in tracks if t.id != seed_track.id][:max_count]

    seed = radio_seed(seed_track)
    return search_youtube(f"{seed} music", max_results=max_count)


class RadioVariety:
    def __init__(self, seen: Set[str], recent: deque, artist_last: Dict[str, int], artist_count: Dict[str, int], pos: int = 0):
        self.seen = seen
        self.recent = recent
        self.artist_last = artist_last
        self.artist_count = artist_count
        self.pos = pos

    def absorb(self, tracks: List[Track]) -> List[Track]:
        filtered = []
        for t in tracks:
            if not t.url or not t.id:
                continue
            ck = t.core_key()
            if ck in self.seen or ck in self.recent:
                continue
            ak = t.artist_key()
            if self.artist_count.get(ak, 0) >= 2:
                continue
            if ak in self.artist_last and (self.pos - self.artist_last[ak]) < 2:
                continue
            self.seen.add(ck)
            self.recent.append(ck)
            self.artist_last[ak] = self.pos
            self.artist_count[ak] = self.artist_count.get(ak, 0) + 1
            self.pos += 1
            filtered.append(t)
        
        filtered.sort(key=lambda tr: self.artist_count.get(tr.artist_key(), 0))
        return filtered

    def dominated(self, queue: List[Track]) -> bool:
        if not queue:
            return False
        counts = {}
        for t in queue:
            ak = t.artist_key()
            counts[ak] = counts.get(ak, 0) + 1
        return any(c >= len(queue) * 0.6 for c in counts.values())


class PlaybackSession:
    def __init__(self, tracks: List[Track], start_index: int = 0, radio: bool = False, fetcher=None):
        self._tracks = tracks
        self._current_idx = start_index if 0 <= start_index < len(tracks) else 0
        self._queue = tracks[self._current_idx + 1:] if self._current_idx < len(tracks) else []
        self._history = []
        self._radio = radio
        self._fetcher = fetcher or fetch_radio_tracks
        self._dial = 'balanced'
        self._seen = {t.core_key() for t in tracks}
        self.variety = RadioVariety(seen=self._seen, recent=deque(maxlen=8), artist_last={}, artist_count={})

    def current(self) -> Optional[Track]:
        if 0 <= self._current_idx < len(self._tracks):
            return self._tracks[self._current_idx]
        return None

    def remember(self, track: Track):
        if track:
            self._history.append(track)
            ak = track.artist_key()
            self.variety.artist_count[ak] = self.variety.artist_count.get(ak, 0) + 1

    def advance(self) -> Optional[Track]:
        if self._queue:
            nxt = self._queue.pop(0)
            self._tracks.append(nxt)
            self._current_idx = len(self._tracks) - 1
            return nxt
        
        if self._radio and self.current():
            ctx = {'dial': self._dial}
            fetched = self._fetcher(self.current(), ctx)
            if self.variety.dominated(fetched) and self._dial != 'familiar':
                ctx['discovery'] = True
                disc = self._fetcher(self.current(), ctx)
                absorb_filtered = self.variety.absorb(disc)
            else:
                absorb_filtered = self.variety.absorb(fetched)

            if absorb_filtered:
                nxt = absorb_filtered.pop(0)
                self._queue.extend(absorb_filtered)
                self._tracks.append(nxt)
                self._current_idx = len(self._tracks) - 1
                return nxt

        return None

    def back(self) -> Optional[Track]:
        if self._history:
            if self.current() and self._history[-1] == self.current():
                self._history.pop()
            if self._history:
                prev = self._history.pop()
                curr = self.current()
                if curr:
                    self._queue.insert(0, curr)
                self._tracks.append(prev)
                self._current_idx = len(self._tracks) - 1
                return prev
        return None

    def cycle_dial(self) -> str:
        dials = ['balanced', 'familiar', 'discover']
        idx = (dials.index(self._dial) + 1) % len(dials)
        self._dial = dials[idx]
        return self._dial

    def snapshot(self) -> Dict[str, Any]:
        return {
            'current': self.current(),
            'queue': list(self._queue),
            'history': list(self._history),
            'radio': self._radio,
            'dial': self._dial,
        }


def dial_status_text(dial: str) -> str:
    mapping = {'balanced': 'Balanced', 'familiar': 'Familiar', 'discover': 'Discover'}
    return mapping.get(dial, 'Balanced')



class _RawMode:
    """Context manager that sets raw mode once for the duration of a playback/listen session.

    This replaces the old get_char() pattern that toggled raw mode (3 syscalls)
    on every single keypress. Now raw mode is entered once at TUI init and
    exited once at TUI teardown.
    """

    def __init__(self):
        import termios as _termios
        self._termios = _termios
        self._fd = None
        self._old_settings = None

    def __enter__(self):
        self._fd = sys.stdin.fileno()
        self._old_settings = self._termios.tcgetattr(self._fd)
        import tty
        tty.setraw(self._fd)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._old_settings is not None:
            try:
                self._termios.tcsetattr(self._fd, self._termios.TCSADRAIN, self._old_settings)
            except Exception:
                pass

    @staticmethod
    def read_key(fd, timeout: float = 0.1) -> Optional[str]:
        """Read one keypress in non-blocking mode using select."""
        import select as _select
        ready, _, _ = _select.select([sys.stdin], [], [], timeout)
        if not ready:
            return None
        ch = sys.stdin.read(1)
        if not ch:
            return None
        if ch == '\x1b':
            ch2 = sys.stdin.read(1)
            if ch2 == '[':
                ch3 = sys.stdin.read(1)
                if ch3 == 'A':
                    return 'UP'
                elif ch3 == 'B':
                    return 'DOWN'
            return 'ESC'
        return ch


def enter_raw_input() -> _RawMode:
    """Enter raw mode for the TUI session. Returns a context manager."""
    return _RawMode()


def get_char():
    """Read a single character in raw mode.

    Uses a module-level raw-mode state so that raw mode is entered only once
    rather than on every keypress. Falls back to the old per-call approach
    if raw mode cannot be entered.
    """
    import select as _select
    ready, _, _ = _select.select([sys.stdin], [], [], 0.0)
    if not ready:
        # Fall back to blocking read with per-call raw mode (legacy behavior)
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == '\x1b':
                ch2 = sys.stdin.read(1)
                if ch2 == '[':
                    ch3 = sys.stdin.read(1)
                    if ch3 == 'A':
                        return 'UP'
                    elif ch3 == 'B':
                        return 'DOWN'
                return 'ESC'
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

def search_songs(query, count=30):
    cmd = [
        "yt-dlp",
        f"ytsearch{count}:{query}",
        "--print", "%(title)s|||%(id)s|||%(uploader)s|||%(duration_string)s",
        "--no-cookies-from-browser",
        "--no-warnings",
        "--no-update",
        "--flat-playlist",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if not result.stdout.strip():
            return []
        tracks = []
        for line in result.stdout.strip().split('\n'):
            if not line.strip():
                continue
            parts = line.split('|||')
            title = parts[0].strip() if len(parts) > 0 else 'Unknown'
            vid = parts[1].strip() if len(parts) > 1 else ''
            artist = parts[2].strip() if len(parts) > 2 else 'Unknown'
            duration = parts[3].strip() if len(parts) > 3 else '--:--'
            url = f'https://www.youtube.com/watch?v={vid}' if vid else ''
            tracks.append({'title': title, 'artist': artist, 'duration': duration, 'url': url, 'id': vid, 'type': 'song'})
        return tracks
    except Exception as e:
        print(f"Search error: {e}")
        return []

def search_playlists(query, count=20):
    cmd = [
        "yt-dlp",
        f"ytsearch{count}:{query} playlists",
        "--print", "%(playlist_title)s|||%(id)s|||%(playlist_count)s|||%(uploader)s",
        "--no-cookies-from-browser",
        "--no-warnings",
        "--no-update",
        "--flat-playlist",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if not result.stdout.strip():
            return []
        playlists = []
        for line in result.stdout.strip().split('\n'):
            if not line.strip():
                continue
            parts = line.split('|||')
            title = parts[0].strip() if len(parts) > 0 else 'Unknown'
            pid = parts[1].strip() if len(parts) > 1 else ''
            track_count = parts[2].strip() if len(parts) > 2 else '?'
            uploader = parts[3].strip() if len(parts) > 3 else 'Unknown'
            url = f'https://www.youtube.com/playlist?list={pid}' if pid else ''
            playlists.append({'title': title, 'uploader': uploader, 'track_count': track_count, 'url': url, 'id': pid, 'type': 'playlist'})
        return playlists
    except Exception as e:
        print(f"Search error: {e}")
        return []

def get_playlist_tracks(playlist_url, count=50):
    cmd = [
        "yt-dlp",
        playlist_url,
        "--print", "%(title)s|||%(id)s|||%(uploader)s|||%(duration_string)s",
        "--no-cookies-from-browser",
        "--no-warnings",
        "--no-update",
        "--flat-playlist",
        "--playlist-end", str(count),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if not result.stdout.strip():
            return []
        tracks = []
        for line in result.stdout.strip().split('\n'):
            if not line.strip():
                continue
            parts = line.split('|||')
            title = parts[0].strip() if len(parts) > 0 else 'Unknown'
            vid = parts[1].strip() if len(parts) > 1 else ''
            artist = parts[2].strip() if len(parts) > 2 else 'Unknown'
            duration = parts[3].strip() if len(parts) > 3 else '--:--'
            url = f'https://www.youtube.com/watch?v={vid}' if vid else ''
            tracks.append({'title': title, 'artist': artist, 'duration': duration, 'url': url, 'id': vid, 'type': 'song'})
        return tracks
    except Exception as e:
        print(f"Error loading playlist: {e}")
        return []

def get_radio_tracks(video_id, count=20):
    cmd = [
        "yt-dlp",
        f"https://www.youtube.com/watch?v={video_id}&list=RD{video_id}",
        "--print", "%(title)s|||%(id)s|||%(uploader)s|||%(duration_string)s",
        "--no-warnings",
        "--no-update",
        "--flat-playlist",
        "--playlist-end", str(count + 1),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if not result.stdout.strip():
            return []
        tracks = []
        lines = result.stdout.strip().split('\n')
        for line in lines[1:]:
            if not line.strip():
                continue
            parts = line.split('|||')
            title = parts[0].strip() if len(parts) > 0 else 'Unknown'
            vid = parts[1].strip() if len(parts) > 1 else ''
            artist = parts[2].strip() if len(parts) > 2 else 'Unknown'
            duration = parts[3].strip() if len(parts) > 3 else '--:--'
            url = f'https://www.youtube.com/watch?v={vid}' if vid else ''
            tracks.append({'title': title, 'artist': artist, 'duration': duration, 'url': url, 'id': vid, 'type': 'song'})
        return tracks
    except Exception:
        logging.debug("get_radio_tracks: error fetching radio tracks", exc_info=True)
        return []

def play_track(track):
    url = track.get("url", "")
    if not url:
        url = track.get("id", "")
        if url:
            url = f"https://www.youtube.com/watch?v={url}"
    ytdlp_proc = subprocess.Popen(
        ["yt-dlp", "-f", "ba", "-o", "-", "--no-warnings", "--no-update", url],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    ffplay_proc = subprocess.Popen(
        ["ffplay", "-nodisp", "-autoexit", "-"],
        stdin=ytdlp_proc.stdout,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    ytdlp_proc.stdout.close()
    return ffplay_proc

def kill_process(proc):
    if proc:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            logging.debug("kill_process: terminate failed, attempting kill", exc_info=True)
            try:
                proc.kill()
            except Exception:
                logging.debug("kill_process: kill failed", exc_info=True)

def clear_screen():
    sys.stdout.write(CLEAR_SCREEN)

def display_songs(results, page, selected_idx, radio_mode=False):
    total_pages = (len(results) + PAGE_SIZE - 1) // PAGE_SIZE
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, len(results))
    
    radio_status = " [RADIO ON]" if radio_mode else ""
    print(f"\nSongs (Page {page + 1}/{total_pages}) - {len(results)} total{radio_status}\n")
    
    for i in range(start, end):
        marker = ">" if i == selected_idx else " "
        print(f" {marker} {i + 1:02d}. {results[i]['title']} by {results[i]['artist']} [{results[i]['duration']}]")
    
    print(f"\n[n]ext [p]rev [r]adio [q]uit [ENTER]play")

def display_playlists(results, page, selected_idx):
    total_pages = (len(results) + PAGE_SIZE - 1) // PAGE_SIZE
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, len(results))
    
    print(f"\nPlaylists (Page {page + 1}/{total_pages}) - {len(results)} total\n")
    
    for i in range(start, end):
        marker = ">" if i == selected_idx else " "
        print(f" {marker} {i + 1:02d}. {results[i]['title']} by {results[i]['uploader']} [{results[i]['track_count']} tracks]")
    
    print(f"\n[n]ext [p]rev [1-{total_pages}]page [q]uit [ENTER]open")

def browse_songs(results, radio_mode=False):
    page = 0
    selected_idx = 0
    total_pages = max(1, (len(results) + PAGE_SIZE - 1) // PAGE_SIZE)
    
    while True:
        clear_screen()
        display_songs(results, page, selected_idx, radio_mode)
        
        ch = get_char()
        
        if ch == 'UP':
            if selected_idx > page * PAGE_SIZE:
                selected_idx -= 1
            elif page > 0:
                page -= 1
                selected_idx = page * PAGE_SIZE + PAGE_SIZE - 1
        elif ch == 'DOWN':
            max_idx = min((page + 1) * PAGE_SIZE, len(results)) - 1
            if selected_idx < max_idx:
                selected_idx += 1
            elif page < total_pages - 1:
                page += 1
                selected_idx = page * PAGE_SIZE
        elif ch == 'n':
            if page < total_pages - 1:
                page += 1
                selected_idx = page * PAGE_SIZE
        elif ch == 'p':
            if page > 0:
                page -= 1
                selected_idx = page * PAGE_SIZE
        elif ch == 'r':
            radio_mode = not radio_mode
        elif ch == 'q' or ch == 'ESC':
            return None, radio_mode
        elif ch == '\r' or ch == '\n':
            return selected_idx, radio_mode
        elif ch.isdigit():
            page_input = ch
            while True:
                ch2 = get_char()
                if ch2.isdigit():
                    page_input += ch2
                else:
                    if ch2 == '\r' or ch2 == '\n':
                        try:
                            target = int(page_input) - 1
                            if 0 <= target < total_pages:
                                page = target
                                selected_idx = page * PAGE_SIZE
                        except Exception:
                            logging.debug("browse_songs: invalid page number input", exc_info=True)
                            pass
                    break
    
    return None, radio_mode

def browse_playlists(results):
    page = 0
    selected_idx = 0
    total_pages = max(1, (len(results) + PAGE_SIZE - 1) // PAGE_SIZE)
    
    while True:
        clear_screen()
        display_playlists(results, page, selected_idx)
        
        ch = get_char()
        
        if ch == 'UP':
            if selected_idx > page * PAGE_SIZE:
                selected_idx -= 1
            elif page > 0:
                page -= 1
                selected_idx = page * PAGE_SIZE + PAGE_SIZE - 1
        elif ch == 'DOWN':
            max_idx = min((page + 1) * PAGE_SIZE, len(results)) - 1
            if selected_idx < max_idx:
                selected_idx += 1
            elif page < total_pages - 1:
                page += 1
                selected_idx = page * PAGE_SIZE
        elif ch == 'n':
            if page < total_pages - 1:
                page += 1
                selected_idx = page * PAGE_SIZE
        elif ch == 'p':
            if page > 0:
                page -= 1
                selected_idx = page * PAGE_SIZE
        elif ch == 'q' or ch == 'ESC':
            return None
        elif ch == '\r' or ch == '\n':
            return selected_idx
        elif ch.isdigit():
            page_input = ch
            while True:
                ch2 = get_char()
                if ch2.isdigit():
                    page_input += ch2
                else:
                    if ch2 == '\r' or ch2 == '\n':
                        try:
                            target = int(page_input) - 1
                            if 0 <= target < total_pages:
                                page = target
                                selected_idx = page * PAGE_SIZE
                        except Exception:
                            logging.debug("browse_playlists: invalid page number input", exc_info=True)
                            pass
                    break
    
    return None

def play_with_radio(track, all_results, radio_mode):
    played_ids = set()
    played_order = deque(maxlen=1000)
    queue = deque()
    current_track = track
    
    while True:
        clear_screen()
        print(f"\nNow playing: {current_track['title']} by {current_track['artist']}")
        print(f"Radio: {'ON' if radio_mode else 'OFF'} | Press Q to stop, R to toggle radio\n")
        
        proc = play_track(current_track)
        played_ids.add(current_track['id'])
        played_order.append(current_track['id'])
        if len(played_ids) > 1000:
            played_ids.discard(played_order[0])
        
        if radio_mode and not queue:
            print("Fetching similar songs...")
            radio_tracks = get_radio_tracks(current_track['id'], 15)
            for t in radio_tracks:
                if t['id'] not in played_ids:
                    queue.append(t)
            random.shuffle(queue)
        
        try:
            import select as _select
            while proc.poll() is None:
                ch = get_char()
                if ch.lower() == 'q' or ch == 'ESC':
                    kill_process(proc)
                    return False
                elif ch.lower() == 'r':
                    radio_mode = not radio_mode
                    kill_process(proc)
                    break
                elif ch.lower() == 's':
                    kill_process(proc)
                    break
                # Sleep briefly to avoid busy-poll CPU burn (was 100% without this)
                time.sleep(0.05)
        except Exception:
            logging.debug("play_with_radio: error in playback input loop", exc_info=True)
            kill_process(proc)
            return False
        
        if not radio_mode:
            return False
        
        if queue:
            current_track = queue.popleft()
        else:
            print("\nNo more similar songs found.")
            time.sleep(1)
            return False
    
    return False

def main():
    radio_mode = False
    
    while True:
        try:
            query = input("Search (pl: for playlists): ").strip()
        except EOFError:
            break
        
        if not query:
            continue
        if query.lower() in ('q', 'quit', 'exit'):
            break
        
        if query.lower().startswith('pl:'):
            playlist_query = query[3:].strip()
            print(f"\nSearching playlists: {playlist_query}...")
            playlists = search_playlists(playlist_query)
            
            if not playlists:
                print("No playlists found.")
                continue
            
            idx = browse_playlists(playlists)
            
            if idx is None:
                print("\nCancelled.\n")
                continue
            
            playlist = playlists[idx]
            clear_screen()
            print(f"\nLoading playlist: {playlist['title']}...")
            
            tracks = get_playlist_tracks(playlist['url'])
            
            if not tracks:
                print("Could not load playlist tracks.")
                continue
            
            idx, radio_mode = browse_songs(tracks, radio_mode)
            
            if idx is None:
                print("\nCancelled.\n")
                continue
            
            play_with_radio(tracks[idx], tracks, radio_mode)
        else:
            print(f"\nSearching: {query}...")
            results = search_songs(query)
            
            if not results:
                print("No results.")
                continue
            
            idx, radio_mode = browse_songs(results, radio_mode)
            
            if idx is None:
                print("\nCancelled.\n")
                continue
            
            play_with_radio(results[idx], results, radio_mode)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nGoodbye.")
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        sys.exit(0)
