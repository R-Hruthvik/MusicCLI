#!/usr/bin/env python3
"""MusicCLI - terminal music player (search, queue, history, radio, ASCII visualizer).

Restructured into deep modules so the interesting behaviour is testable through
small interfaces and AI-navigable. Module map (see CONTEXT.md):

  Track            - immutable domain value: parse + NA/fallback rules in one place
  Search selection - select_search_results(): de-dup + junk-filter raw candidates
  yt-dlp adapter   - search_youtube() returns list[Track]; owns transport only
  PlaybackSession  - single owner of queue / history / radio / current track
  Command map      - one key->action source; legend is generated from it
  Renderer         - pure f(snapshot); owns its own clock, never mutates session
"""

import subprocess
import threading
import time
import sys
import random
import itertools
import os
import math
import shutil
import queue as py_queue
import re
import urllib.parse as urlparse
from dataclasses import dataclass
from collections import deque

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    os.system('')
    try:
        import msvcrt
    except Exception:
        msvcrt = None
else:
    msvcrt = None

CLEAR = "\033[2J\033[H"

# how many distinct search results to show (override with MUSICCLI_RESULTS)
SEARCH_RESULTS_DEFAULT = int(os.environ.get('MUSICCLI_RESULTS', '25'))


class Color:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    RST = '\033[0m'


PLAYERS = [Color.CYAN, Color.YELLOW, Color.GREEN, Color.MAGENTA, Color.RED, Color.BLUE]

BANNER = r"""
  __  __ _____ _   _ _____ ____
 |  \/  | ____| \ | |_   _|  _ \
 | |\/| |  _| |  \| | | | |_) |
 | |  | | |___| |\  | | | |  __/
 |_|  |_|_____|_| \_| |_| |_|
"""
BANNER_SUB = "  Search . Stream . Play  -  powered by yt-dlp + ffplay"

EQ_BARS = list(".:-=+*#%@")  # ascii bar levels, shortest to tallest
EQ_CHARS = ["|", "/", "-", "\\"]  # ascii spinner


def colorize(text, color):
    return f"{color}{text}{Color.RST}"


# ----- terminal & display helpers -----
def get_size():
    try:
        st = shutil.get_terminal_size(fallback=(80, 24))
        return st.columns, st.lines
    except Exception:
        return 80, 24


def hide_cursor():
    sys.stdout.write('\033[?25l')
    sys.stdout.flush()


def show_cursor():
    sys.stdout.write('\033[?25h')
    sys.stdout.flush()


def truncate(text, width):
    text = text or ''
    if width <= 0:
        return ''
    if len(text) <= width:
        return text
    if width <= 3:
        return text[:width]
    return text[:width - 3] + '...'


def center_text(text, cols):
    text = text or ''
    if len(text) >= cols:
        return text[:cols]
    pad = (cols - len(text)) // 2
    return ' ' * pad + text


def fmt_clock(secs):
    secs = max(0, int(secs))
    m, s = divmod(secs, 60)
    return f"{m:02d}:{s:02d}"


def fmt_views(views):
    """'1234567' -> '1.2M' ; ''/junk -> '--'."""
    try:
        n = int(str(views).replace(',', ''))
    except (TypeError, ValueError):
        return '--'
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def fmt_upload_date(date):
    """'20240501' -> '2024-05-01' ; junk -> ''."""
    d = str(date or '').strip()
    if len(d) == 8 and d.isdigit():
        return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
    return d


# =====================================================================
# Track - immutable domain value. Parsing and the NA/fallback rules live
# here (construction locality), not in the adapter or in display code.
# =====================================================================
_NA_VALUES = {'', 'na', 'n/a', 'none', 'unknown'}

# trailing words stripped from titles when building the dedupe key
# (e.g. "Song - Official Audio" == "Song (Official Video)")
_TRAIL_DESCRIPTORS = {
    'official', 'video', 'audio', 'hd', 'hq', '4k', '8k', 'lyric', 'lyrics',
    'remix', 'remastered', 'visualizer', 'clean', 'explicit', 'edit',
    'extended', 'full', 'album', 'slowed', 'sped', 'with', 'live', 'mix',
    'karaoke', 'versao', 'remaster', 'original', 'youtube', 'version',
}


def _clean(v):
    v = (v or '').strip()
    return '' if v.lower() in _NA_VALUES else v


def _norm_title(title):
    """Normalised, tag/feat-stripped title used as a dedupe key.

    Two covers / remixes / re-uploads of the same song collapse to one key,
    which is what lets Radio skip 'the same song, different channel'.
    """
    t = title.lower()
    t = re.sub(r'[\(\[].*?[\)\]]', ' ', t)          # drop (official), [4K], (cover)...
    t = re.sub(r'\b(feat|feat\.|ft|ft\.|featuring)\b.*$', '', t)  # drop feat. tail
    t = re.sub(r'[^a-z0-9 ]+', ' ', t)
    words = t.split()
    while words and words[-1] in _TRAIL_DESCRIPTORS:
        words.pop()
    return ' '.join(words)


@dataclass(frozen=True)
class Track:
    title: str
    artist: str
    source: str
    duration: str
    url: str
    id: str
    views: str = ''
    upload_date: str = ''

    @classmethod
    def from_line(cls, line):
        """Parse one yt-dlp `--print '|||'-delimited line into a Track.

        Pure / testable; owns the NA handling and the fallback rules
        ('Unknown Artist', 'YouTube' source)."""
        parts = line.split(' ||| ')

        def f(i):
            return _clean(parts[i]) if len(parts) > i else ''

        title = f(0)
        vid = f(1)
        uploader = f(2)
        channel = f(3)
        playlist = f(4)
        duration = f(5)
        views = f(6)
        upload_date = f(7)

        artist = uploader or channel or 'Unknown Artist'
        source = playlist if playlist else 'YouTube'
        return cls(
            title=title or 'Untitled',
            artist=artist,
            source=source,
            duration=duration,
            url=f"https://www.youtube.com/watch?v={vid}" if vid else '',
            id=vid,
            views=views,
            upload_date=upload_date,
        )

    def core_key(self):
        return _norm_title(self.title)

    def artist_key(self):
        """Normalised artist name used for artist-diversity rules.

        Strips channel/uploader noise (Vevo, Topic, 'official') so one real
        artist's many channels count as one artist for variety/anti-fatigue."""
        a = (self.artist or '').lower()
        a = re.sub(r'\b(vevo|topic|official|various|artists|video)\b.*$', '', a)
        a = re.sub(r'[^a-z0-9 ]+', ' ', a)
        a = ' '.join(a.split())
        return a or 'unknown'

    def line(self):
        """Single-line display like 'Title by Artist  dur  views·date  source'."""
        meta = []
        if self.views:
            meta.append(colorize(fmt_views(self.views), Color.DIM))
        if self.upload_date:
            meta.append(colorize(fmt_upload_date(self.upload_date), Color.DIM))
        title_w, artist_w = (34, 18)
        if meta:
            title_w, artist_w = (26, 14)      # make room for views · date
        meta_str = (' ' + ' '.join(meta)) if meta else ''
        return (f"{truncate(self.title, title_w)} {colorize('by', Color.DIM)} "
                f"{truncate(self.artist, artist_w)}  "
                f"{colorize((self.duration or '--:--').rjust(6), Color.YELLOW)}{meta_str} "
                f"{colorize(truncate(self.source or 'YouTube', 12).ljust(12), Color.MAGENTA)}")


# =====================================================================
# yt-dlp search adapter  (one adapter = hypothetical seam -> keep one).
# Transport only: builds/runs the command and returns list[Track].
# =====================================================================
_YOUTUBE_FMT = ("%(title)s ||| %(id)s ||| %(uploader)s ||| %(channel)s "
                "||| %(playlist_title)s ||| %(duration_string)s "
                "||| %(view_count)s ||| %(upload_date)s")

# max raw candidates pulled from yt-dlp before polishing (de-dup merges many
# re-uploads, so we over-fetch to still show `max_results` distinct songs)
_SEARCH_FETCH_CAP = 60


def select_search_results(tracks, limit):
    """Polish raw search candidates into a ranked, de-duplicated results list.

    Deep module: junk filtering, re-upload collapse and duration preference
    hide behind one small interface. A (core_key, artist_key) pair collapses
    'Song (Official Audio)' / 'Song - Official Video' / re-uploads by the
    same artist to a single entry, while genuine covers by *different*
    artists still appear. YouTube relevance order is preserved; a later
    duplicate carrying a real duration replaces an early duration-less one
    in place, so the best upload surfaces without re-sorting the list.
    """
    best = {}
    for t in tracks:
        if not t.id or not t.url or not t.title or t.title == 'Untitled':
            continue
        key = (t.core_key(), t.artist_key())
        if key not in best:
            best[key] = t
        elif t.duration and not best[key].duration:
            best[key] = t          # same dict slot -> keeps relevance position
    return list(best.values())[:max(0, limit)]


def search_youtube(query, max_results=8):
    """Search YouTube for up to `max_results` *distinct* Tracks.

    Over-fetches candidates (up to _SEARCH_FETCH_CAP) then polishes them
    with select_search_results, so the list you see is the distinct songs
    behind a query, not an echo of re-uploads.
    """
    fetch_n = max(5, min(_SEARCH_FETCH_CAP, max_results * 3))
    cmd = [
        "yt-dlp",
        f"ytsearch{fetch_n}:{query}",
        "--print", _YOUTUBE_FMT,
        "--no-warnings",
        "--flat-playlist",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if not result.stdout.strip():
            return []
        tracks = [Track.from_line(line)
                  for line in result.stdout.strip().split('\n') if line.strip()]
    except Exception as e:
        print(f"  Search error: {e}")
        return []
    return select_search_results(tracks, max_results)


# =====================================================================
# RadioVariety - anti-repetition rules (Spotify/Pandora-style)
# Deep module: small interface (absorb) + internal state.
# Session accesses it through _variety.absorb(); tests call it directly.
# =====================================================================
@dataclass
class RadioVariety:
    """Stateful variety filter for radio refill.
    
    Interface: absorb(batch) → filtered list of Tracks
    Internals: recent ring, artist last-play positions, artist counts.
    """
    seen: set
    recent: deque
    artist_last: dict
    artist_count: dict
    pos: int = 0

    def __post_init__(self):
        # enforce invariants
        object.__setattr__(self, 'recent', deque(self.recent, maxlen=RING_SIZE))

    def absorb(self, batch):
        """Filter fetched candidates into the queue using variety rules.
        
        - drop same-song (core_key seen) and recent-ring repeats (Spotify-style);
        - drop an artist too recent to repeat (Pandora separation);
        - per-artist cap on batch.
        - prefer NEW artists so they queue ahead of repeats.
        """
        batch_count = {}
        added = []
        for t in batch:
            if not t.url:
                continue
            k = t.core_key()
            if k in self.seen or k in self.recent:
                continue
            ak = t.artist_key()
            last = self.artist_last.get(ak)
            if last is not None and (self.pos - last) < ARTIST_MIN_SEPARATION:
                continue
            total = self.artist_count.get(ak, 0) + batch_count.get(ak, 0)
            if total >= ARTIST_MAX_PER_BATCH:
                continue
            batch_count[ak] = batch_count.get(ak, 0) + 1
            fresh = ak not in self.artist_count
            self.seen.add(k)
            added.append((fresh, t))
        added.sort(key=lambda ft: 0 if ft[0] else 1)
        return [t for _fresh, t in added]

    def dominated(self, queue_snapshot):
        """True if a batch is >ONE_ARTIST_DOMINANCE one artist."""
        if len(queue_snapshot) < 2:
            return False
        counts = {}
        for t in queue_snapshot:
            counts[t.artist_key()] = counts.get(t.artist_key(), 0) + 1
        top = max(counts.values())
        return (top / len(queue_snapshot)) >= ONE_ARTIST_DOMINANCE

    def update_after_advance(self):
        """Call after consuming tracks from queue. No-op here; pos managed externally."""
        pass


# =====================================================================
# Radio - fetch genuinely *different* songs and enforce variety.
#
# Transport: refill from YouTube's own auto "Mix" for the seed video
# (`list=RD<id>` / `RDAM<id>`). YouTube's recommender yields related but
# DIFFERENT songs across DIFFERENT artists, instead of a keyword echo of
# the same artist. A discovery fallback re-seeds from a random mood/genre.
#
# Variety is enforced by RadioVariety. The fetcher below is pure transport.
# =====================================================================
_STOPWORDS = {
    'official', 'video', 'audio', 'music', 'hd', 'hq', '4k', '8k', 'lyric',
    'lyrics', 'feat', 'ft', 'remix', 'mix', 'live', 'full', 'album', 'song',
    'officialvideo', 'officialaudio', 'the', 'a', 'an', 'of', 'and', 'on',
}

# Deezer-style "discovery dial": fallback seeds that walk AWAY from the
# current artist so the station keeps discovering new ones.
_DISCOVERY_QUERIES = [
    "lofi beats to focus", "chill acoustic mix", "indie rock 2026",
    "jazz late night", "synthwave retrowave", "lo-fi hip hop study",
    "bossa nova lounge", "ambient electronic", "classical piano focus",
    "90s alt rock", "motown soul", "latin pop 2026", "nedm workout mix",
    "r&b slow jam", "indie folk", "city pop", "deep house", "guitar instrumental",
    "acoustic coffee shop", "jazzhop study",
]

# Variety tuning constants (Pandora/Spotify/YT-style anti-repetition).
RING_SIZE = 8                 # Spotify-style: don't repeat a recent song
ARTIST_MIN_SEPARATION = 3     # Pandora-style: tracks before artist can return
ARTIST_MAX_PER_BATCH = 2      # per-artist cap on one radio refill
ONE_ARTIST_DOMINANCE = 0.7    # >70% one artist => treat as dominated


def _keyword_seed(title):
    t = re.sub(r'[\(\[].*?[\)\]]', ' ', title)
    t = re.sub(r'\b(feat|feat\.|ft|ft\.|featuring)\b.*$', '', t, flags=re.I)
    words = [w for w in re.findall(r"[a-z0-9']+", t.lower()) if w not in _STOPWORDS]
    return ' '.join(words[:3])


def radio_seed(track):
    """Last-resort search seed (only used if the RD Mix returns nothing)."""
    artist = (track.artist or '').strip()
    if artist and artist.lower() != 'unknown artist':
        return f"{artist}"
    kw = _keyword_seed(track.title)
    return f"{kw} music" if kw else track.title


def _run_ytdlp(urls, max_results):
    """Run yt-dlp --flat-playlist over the given URLs and parse Tracks."""
    cmd = ['yt-dlp', '--flat-playlist', '--print', _YOUTUBE_FMT,
           '--no-warnings', '--playlist-end', str(max_results)] + list(urls)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except Exception as e:
        print(f"  yt-dlp error: {e}")
        return []
    if not result.stdout.strip():
        return []
    return [Track.from_line(line)
            for line in result.stdout.strip().split('\n') if line.strip()]


def fetch_radio_tracks(seed_track, ctx=None):
    """Retrieve radio candidates around `seed_track` (pure transport).

    `ctx` carries session state the fetcher trades on:
      - discovery : bool -> use a random mood/genre seed (Deezer dial)
      - max       : int  -> how many candidates to fetch
    Variety filtering is delegated to RadioVariety.absorb()."""
    ctx = ctx or {}
    max_results = ctx.get('max', 10)
    if ctx.get('discovery'):
        return search_youtube(random.choice(_DISCOVERY_QUERIES),
                              max_results=max_results)
    if seed_track is not None and seed_track.id:
        base = f"https://www.youtube.com/watch?v={seed_track.id}"
        for lid in (f"RD{seed_track.id}", f"RDAM{seed_track.id}"):
            tracks = _run_ytdlp([f"{base}&list={lid}"], max_results)
            if tracks:
                return tracks
    # last resort: keyword/artist search so radio never dies
    return search_youtube(radio_seed(seed_track), max_results=max_results)


# ----- playlist / single-video / URL adapters --------------------------
def is_url(text):
    return (text or '').startswith(('http://', 'https://'))


def is_playlist_url(text):
    if not is_url(text):
        return False
    return ('youtube.com/playlist' in text) or ('list=' in urlparse.urlsplit(text).query)


def fetch_playlist(url, max_results=50):
    """Enumerate a playlist's tracks without downloading (--flat-playlist)."""
    return _run_ytdlp([url], max_results)


def fetch_single(url, max_results=1):
    """Resolve a single video URL into one Track."""
    tracks = _run_ytdlp([url], max_results)
    return tracks[0] if tracks else None



# =====================================================================
# Command map - one source of truth for keys -> actions.
# The renderer legend and the dispatcher both derive from action_for(), so
# an on-screen key can never disagree with the code that handles it.
# =====================================================================
_PLAY_KEYS = [
    ('x', 'Stop'),
    ('z', 'Restart'),
    ('n', 'Next'),
    ('p', 'Prev'),
    ('q', 'Queue'),
    ('r', 'Radio'),
    ('v', 'Vis'),
]

_PLAY_ACTION = {
    'x': 'stop', 'stop': 'stop',
    'z': 'restart', 'restart': 'restart',
    'n': 'next', 's': 'next', 'next': 'next', 'skip': 'next',
    'p': 'prev', 'b': 'prev', 'prev': 'prev', 'previous': 'prev',
    'q': 'queue', 'queue': 'queue',
    'r': 'radio', 'radio': 'radio',
    'v': 'vis', 'visualizer': 'vis',
    '^C': 'quit', 'quit': 'quit',
}


def action_for(cmd):
    """Translate a raw (lowercased) playback command to a canonical action."""
    return _PLAY_ACTION.get(cmd)


def player_legend():
    return ' '.join(f"[{k}] {label}" for k, label in _PLAY_KEYS)


def radio_status_text(radio):
    return colorize("ON", Color.GREEN) if radio else colorize("OFF", Color.RED)


# =====================================================================
# Flag - tiny thread-safe boolean for renderer on/off and similar toggles.
# =====================================================================
class Flag:
    def __init__(self, value):
        self._v = value
        self._l = threading.Lock()

    def get(self):
        with self._l:
            return self._v

    def set(self, value):
        with self._l:
            self._v = value

    def toggle(self):
        with self._l:
            self._v = not self._v
            return self._v


# =====================================================================
# PlaybackSession - single owner of queue / history / radio / current track.
# All writes go through methods; the renderer reads an immutable snapshot.
# Radio refill is injected (`fetcher`) so transitions are testable.
# Variety filtering delegated to RadioVariety._variety.
# =====================================================================
class PlaybackSession:
    def __init__(self, results, start_index=0, radio=False, fetcher=fetch_radio_tracks):
        self._lock = threading.Lock()
        all_tracks = list(results or [])
        self._radio = bool(radio)
        self._fetcher = fetcher
        self._seen = {t.core_key() for t in all_tracks}
        self._queue = list(all_tracks[start_index + 1:]) if all_tracks else []
        self._current = all_tracks[start_index] if all_tracks else None
        self._history = []
        self._overlay_until = 0.0
        # variety state delegated to RadioVariety
        self._variety = RadioVariety(seen=set(), recent=deque(maxlen=RING_SIZE),
                                     artist_last={}, artist_count={}, pos=0)
        self._pos = 0  # monotonic play counter

    # -- public interface -------------------------------------------------
    def remember(self, track):
        """Record that `track` is now playing (seen + history + variety state)."""
        if track is None:
            return
        with self._lock:
            self._seen.add(track.core_key())
            self._variety.recent.append(track.core_key())
            self._pos += 1
            ak = track.artist_key()
            self._variety.artist_last[ak] = self._pos
            self._variety.artist_count[ak] = self._variety.artist_count.get(ak, 0) + 1
            if not self._history or self._history[-1].id != track.id:
                self._history.append(track)

    def advance(self):
        """Return next Track to play, or None.

        Pops the queue; if empty and radio is on, refills via the fetcher and
        applies the variety filters (recent ring, artist separation/cap, new-
        artist preference) before giving up. Falls back to a discovery refill
        when dominated or empty."""
        with self._lock:
            if self._queue:
                t = self._queue.pop(0)
                self._current = t
                return t
            want_radio = self._radio
            seed = self._current
        if not want_radio or seed is None:
            return None
        ctx = {'seen': self._seen, 'recent': list(self._variety.recent),
               'artist_last': dict(self._variety.artist_last),
               'artist_count': dict(self._variety.artist_count),
               'pos': self._pos, 'max': 10}
        batch = self._fetcher(seed, ctx)
        with self._lock:
            filtered = self._variety.absorb(batch)
            self._seen.update(t.core_key() for t in filtered)
            # new-artist preference: fresh artists first
            filtered.sort(key=lambda t: 0 if t.artist_key() not in self._variety.artist_count else 1)
            self._queue = filtered + self._queue
            if self._variety.dominated(self._queue):
                # need discovery refill
                dctx = dict(ctx)
                dctx['discovery'] = True
                batch2 = self._fetcher(seed, dctx)
                with self._lock:
                    filtered2 = self._variety.absorb(batch2)
                    filtered2.sort(key=lambda t: 0 if t.artist_key() not in self._variety.artist_count else 1)
                    self._queue = filtered2 + self._queue
        with self._lock:
            if self._queue:
                t = self._queue.pop(0)
                self._current = t
                return t
        return None

    def back(self):
        """Rewind to the previously played Track, or None if only one so far."""
        with self._lock:
            if len(self._history) < 2:
                return None
            current = self._history.pop()
            prev = self._history.pop()
            self._queue.insert(0, current)
            self._current = prev
            return prev

    def current(self):
        with self._lock:
            return self._current

    def toggle_radio(self):
        with self._lock:
            self._radio = not self._radio
            return self._radio

    def enqueue(self, tracks):
        """Add fresh tracks to the queue (deduped against seen)."""
        with self._lock:
            for t in tracks:
                if t.core_key() in self._seen or not t.url:
                    continue
                self._seen.add(t.core_key())
                self._queue.append(t)
            return list(self._queue)

    def show_overlay(self, seconds=6):
        with self._lock:
            self._overlay_until = time.time() + seconds

    def snapshot(self):
        """Immutable read-only view for the renderer / UI."""
        with self._lock:
            cur = self._current
            return {
                'title': cur.title if cur else '',
                'artist': cur.artist if cur else '',
                'radio': self._radio,
                'queue': list(self._queue),
                'history': list(self._history),
                'overlay': time.time() < self._overlay_until,
            }


# =====================================================================
# Playback adapter - owns the yt-dlp|ffplay subprocess and how to kill it.
# Playback adapter - owns the yt-dlp|ffplay subprocess and how to kill it.
# (Deep module: importantly the process-tree kill on Windows.)
# =====================================================================
def play_track(track):
    return subprocess.Popen(
        f'yt-dlp -f "ba" -o - "{track.url}" 2>nul | ffplay -nodisp -autoexit -',
        shell=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def kill_playback(process):
    """Stop playback, killing the shell AND all of its children.

    `play_track` runs the `yt-dlp ... | ffplay ...` pipeline via
    `Popen(shell=True)`, so Windows `process.kill()` only kills the cmd.exe
    wrapper and leaves ffplay orphaned (still playing). `taskkill /F /T`
    walks the whole live process tree and must run BEFORE a terminate()."""
    if process is None:
        return
    if sys.platform == 'win32':
        try:
            subprocess.run('taskkill /F /T /PID %d' % process.pid,
                           shell=True, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
        except Exception:
            pass
        try:
            process.wait(timeout=3)
        except Exception:
            pass
    else:
        try:
            process.terminate()
        except Exception:
            pass
        try:
            process.wait(timeout=2)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass


# ----- input helpers -----
def read_key_msvcrt():
    try:
        b = msvcrt.getch()
    except Exception:
        return None
    if b in (b'\x00', b'\xe0'):
        try:
            msvcrt.getch()
        except Exception:
            pass
        return None
    if b in (b'\x03', b'\x1b'):
        return '^C'
    try:
        return b.decode('utf-8', errors='ignore').lower() or chr(b[0]).lower()
    except Exception:
        try:
            return chr(b[0]).lower()
        except Exception:
            return None


def input_reader(stop_event, action_queue, single_key):
    while not stop_event.is_set():
        try:
            if single_key and msvcrt is not None:
                if msvcrt.kbhit():
                    k = read_key_msvcrt()
                    if k:
                        action_queue.put(k)
            else:
                line = sys.stdin.readline()
                if not line:
                    break
                cmd = line.strip().lower()
                if cmd:
                    action_queue.put(cmd)
        except Exception:
            break
        time.sleep(0.03)


# =====================================================================
# Renderer (fullscreen visualizer) - pure f(snapshot); owns its own clock.
# It never writes to the session: it draws whatever session.snapshot() says.
# The legend comes from the same command map the dispatcher uses.
# =====================================================================
DEF_VIS_COLORS = [Color.CYAN, Color.YELLOW, Color.GREEN, Color.MAGENTA, Color.CYAN, Color.BLUE]


def render_frame_plasma(cols, rows, snap, on, elapsed):
    n = len(EQ_BARS) - 1
    t = elapsed
    rows_out = []
    for r in range(rows):
        color = DEF_VIS_COLORS[int(r + t * 1.5) % len(DEF_VIS_COLORS)]
        s = []
        for c in range(cols):
            v1 = math.sin(c * 0.22 + t * 3.0 + r * 0.13)
            v2 = math.sin(r * 0.20 - t * 2.3 + c * 0.11)
            v = 0.5 + 0.5 * math.sin(v1 * 2.0 + v2 * 3.0 + c * 0.05 + r * 0.08)
            idx = int(v * n)
            s.append(EQ_BARS[max(0, min(idx, n))])
        rows_out.append([color, ''.join(s)])

    hp = f"NOW PLAYING  -  {snap['title']}  -  {snap['artist']}"
    hr = max(0, (rows * 2) // 7)
    rows_out[hr] = [Color.BOLD + Color.CYAN, center_text(truncate(hp, cols - 2), cols)]

    info = (f"\u25b6 {fmt_clock(elapsed)}   "
            f"Radio: {'ON' if snap['radio'] else 'OFF'}   "
            f"Visualizer: {'ON' if on else 'OFF'}")
    rows_out[rows - 3] = [Color.YELLOW, center_text(truncate(info, cols - 2), cols)]

    rows_out[rows - 2] = [Color.DIM, center_text(truncate(player_legend(), cols - 2), cols)]

    eq = ''.join(random.choice(EQ_BARS) for _ in range(cols))
    rows_out[rows - 1] = [Color.CYAN, eq]

    if snap.get('overlay'):
        qlines = [" UPCOMING QUEUE:"]
        if snap['queue']:
            for qi, qt in enumerate(snap['queue'][:8], 1):
                qlines.append(f"  {qi}. {truncate(qt.title, 34)} by {truncate(qt.artist, 16)}")
        else:
            qlines.append("  (queue empty)")
        qlines.append(" HISTORY:")
        if snap['history']:
            for hi, ht in enumerate(snap['history'][-5:], 1):
                qlines.append(f"  {hi}. {truncate(ht.title, 34)} by {truncate(ht.artist, 16)}")
        box_w = max(10, cols - 4)
        start = max(1, (rows - len(qlines)) // 2)
        for i, ln in enumerate(qlines):
            rr = start + i
            if 0 <= rr < rows:
                c = (Color.BOLD + Color.CYAN) if (i == 0 or ln.startswith(' HISTORY')) else Color.MAGENTA
                rows_out[rr] = [c, center_text(truncate(ln, box_w), cols)]

    return rows_out


def render_frame_simple(cols, rows, snap, on, elapsed):
    rows_out = []
    for _ in range(rows):
        rows_out.append([Color.DIM, ''])
    hp = f"Now Playing: {snap['title']}  by  {snap['artist']}"
    hr = max(0, rows // 3)
    rows_out[hr] = [Color.BOLD + Color.CYAN, center_text(truncate(hp, cols - 2), cols)]
    info = f"\u25b6 {fmt_clock(elapsed)}  Radio: {'ON' if snap['radio'] else 'OFF'}"
    rows_out[rows - 3] = [Color.YELLOW, center_text(truncate(info, cols - 2), cols)]
    rows_out[rows - 2] = [Color.DIM, center_text(truncate(player_legend(), cols - 2), cols)]
    eq = ''.join(random.choice(EQ_BARS) for _ in range(cols))
    rows_out[rows - 1] = [Color.CYAN, eq]
    return rows_out


def draw_frame(cols, rows, snap, on, elapsed):
    rows_out = (render_frame_plasma(cols, rows, snap, on, elapsed) if on
                else render_frame_simple(cols, rows, snap, on, elapsed))
    out = ['\033[H']
    for i, (color, text) in enumerate(rows_out):
        out.append(color + text + '\033[K' + Color.RST)
        if i < len(rows_out) - 1:
            out.append('\n')
    out.append('\033[J')
    sys.stdout.write(''.join(out))
    sys.stdout.flush()


def animate_fullscreen(stop_event, session, visual_on):
    hide_cursor()
    t0 = time.time()
    last_title = None
    try:
        while not stop_event.is_set():
            cols, rows = get_size()
            if cols > 0 and rows > 0:
                snap = session.snapshot()
                if last_title is None or snap['title'] != last_title:
                    t0 = time.time()
                    last_title = snap['title']
                on = visual_on.get()
                draw_frame(cols, rows, snap, on, time.time() - t0)
            time.sleep(0.06 if visual_on.get() else 0.2)
    finally:
        show_cursor()


def start_visualizer(stop_event, session, visual_on):
    th = threading.Thread(target=animate_fullscreen,
                          args=(stop_event, session, visual_on), daemon=True)
    th.start()
    return th


# ----- startup / transient animations -----
def animate_banner():
    colors = itertools.cycle(PLAYERS)
    for _ in range(12):
        c = next(colors)
        sys.stdout.write(CLEAR)
        for line in BANNER.split('\n'):
            print(colorize(line, c))
        print(colorize(BANNER_SUB, Color.DIM))
        sys.stdout.flush()
        time.sleep(0.12)


def spinner(msg, duration=60, stop_event=None):
    chars = itertools.cycle(EQ_CHARS)
    start = time.time()
    while True:
        if stop_event is not None and stop_event.is_set():
            break
        if time.time() - start > duration:
            break
        c = next(chars)
        bar = ''.join(random.choice(EQ_BARS) for _ in range(8))
        line = f"  {colorize(c, Color.CYAN)} {colorize(msg, Color.BOLD)} {colorize(bar, random.choice(PLAYERS))}"
        sys.stdout.write(f"\r{line}")
        sys.stdout.flush()
        time.sleep(0.08)
    sys.stdout.write("\r" + " " * 80 + "\r")
    sys.stdout.flush()


# ----- results list (paginated) -----
def page_size_for(rows):
    return max(3, rows - 8)


def display_results(results, radio, offset=0):
    cols, rows = get_size()
    width = min(cols, 120)
    bar = '=' * width
    psize = page_size_for(rows)
    page = results[offset:offset + psize]
    more = offset + psize < len(results)
    if results and not page:
        offset = 0
        page = results[:psize]

    print(f"\n  {colorize(f'Search results - {len(results)} found', Color.BOLD)}  "
          f"{colorize(f'(page {offset // max(1, psize) + 1})', Color.DIM)}")
    print(f"  {Color.DIM}{bar}{Color.RST}")
    for i, r in enumerate(page, offset + 1):
        color = PLAYERS[i % len(PLAYERS)]
        print("  " + colorize(f"[{i:>2}]", color) + " " + r.line())
    print(f"  {Color.DIM}{bar}{Color.RST}")

    footer = (f"{colorize('Select a number', Color.YELLOW)} | "
              f"{colorize('[R]', Color.CYAN)} Radio: {radio_status_text(radio)} | "
              f"{colorize('[A]', Color.CYAN)} All | "
              f"{colorize('[N]', Color.YELLOW)} New search | {colorize('[Q]', Color.YELLOW)} Quit")
    if more:
        footer += f" | {colorize('[M]', Color.CYAN)} More ({len(results) - (offset + len(page))} left)"
    print("  " + footer + "\n")
    return more


def _print_queue(session):
    s = session.snapshot()
    qlen = len(s['queue'])
    hlen = len(s['history'])
    print(f"\n  {colorize('--- Queue Inspection ---', Color.BOLD)}")
    print(f"  {colorize('Playing:', Color.CYAN)} {s['title']} by {s['artist']}")
    print(f"  {colorize(f'Upcoming Queue ({qlen} tracks):', Color.YELLOW)}")
    if s['queue']:
        for qi, qt in enumerate(s['queue'][:10], 1):
            print(f"    {qi}. {qt.title} by {qt.artist}")
    else:
        print(f"    {Color.DIM}(Queue empty){Color.RST}")
    print(f"  {colorize(f'History ({hlen} tracks):', Color.MAGENTA)}")
    for hi, ht in enumerate(s['history'][-5:], 1):
        print(f"    {hi}. {ht.title} by {ht.artist}")
    print(f"  {colorize('-' * 30, Color.DIM)}")


def idle_prompt(session):
    """Shown when playback ends with nothing queued. Returns a choice."""
    print(CLEAR)
    cur = session.current()
    name = cur.title if cur else ''
    print(f"\n  {colorize(f'Finished: {name}', Color.YELLOW)}\n")
    while True:
        snap = session.snapshot()
        print(f"  {colorize('[P]', Color.CYAN)}lay again   "
              f"{colorize('[N]', Color.YELLOW)}ew search   "
              f"{colorize('[Q]', Color.YELLOW)}uit   "
              f"{colorize('[R]', Color.CYAN)}adio: {radio_status_text(snap['radio'])}\n")
        print(f"  {colorize('> ', Color.GREEN)}", end='', flush=True)
        try:
            cmd = input().strip().lower()
        except (KeyboardInterrupt, EOFError):
            return 'quit'
        if cmd in ('q', 'quit', 'exit'):
            return 'quit'
        if cmd in ('n', 'new'):
            return 'new_search'
        if cmd in ('p', 'play', 'again'):
            return 'play'
        if cmd in ('r', 'radio'):
            session.toggle_radio()
            if session.snapshot()['radio']:
                nxt = session.advance()
                if nxt:
                    return 'play'
            print(CLEAR)
            print(f"  {colorize('Radio on - no fresh tracks to start. Play again to advance.', Color.CYAN)}\n")
        else:
            return 'results'


        if action == 'restart':
            print(f"\n  {colorize(f'Restarting: {current.title}', Color.CYAN)}\n")
            time.sleep(0.4)
            continue
        if action == 'next':
            nxt = session.advance()
            if nxt:
                current = nxt
                print(f"\n  {colorize(f'Playing next: {nxt.title}', Color.GREEN)}\n")
                continue
            stop_vis()
            print(f"\n  {colorize('Queue is empty.', Color.YELLOW)}\n")
            return 'results'
        if action == 'prev':
            p = session.back()
            if p:
                current = p
                print(f"\n  {colorize(f'Playing previous: {p.title}', Color.GREEN)}\n")
                continue
            print(f"\n  {colorize('No previous track in history.', Color.YELLOW)}\n")
            time.sleep(0.6)
            continue

        # track finished naturally -> auto-advance the queue / radio refill
        print(f"\n  {colorize(f'Track finished: {current.title}', Color.YELLOW)}\n")
        nxt = session.advance()
        if nxt:
            current = nxt
            print(f"\n  {colorize(f'Playing next: {nxt.title}', Color.GREEN)}\n")
            continue
        stop_vis()
        outcome = idle_prompt(session)
        if outcome == 'quit':
            return 'quit'
        if outcome == 'new_search':
            return 'new_search'
        if outcome == 'results':
            return 'results'
        current = session.current()
        continue

    return 'results'


def main():
    os.system('')
    animate_banner()
    print(CLEAR)
    has_renderer = msvcrt is not None
    visual_on = Flag(bool(has_renderer))

    while True:
        print(colorize(BANNER, Color.CYAN))
        print(colorize(BANNER_SUB, Color.DIM))
        print(f"\n  {colorize('What do you want to listen to?', Color.BOLD)}\n")
        print(f"  {colorize('> ', Color.GREEN)}", end='', flush=True)
        try:
            query = input().strip()
        except KeyboardInterrupt:
            print(f"\n\n  {colorize('Goodbye!', Color.CYAN)}")
            return
        except EOFError:
            print(f"\n\n  {colorize('Goodbye!', Color.CYAN)}")
            return
        if not query:
            continue
        if query.lower() in ('q', 'quit', 'exit'):
            break
        # Selection block starts here
        try:
            idx = int(choice) - 1
        except ValueError:
            print(f"  {colorize('Invalid command or number', Color.RED)}\n")
            continue
            if not (0 <= idx < len(results)):
                print(f"  {colorize('Invalid number', Color.RED)}\n")
                continue

            session = PlaybackSession(results, start_index=idx, radio=radio_pref)
            outcome = run_playback(session, visual_on, has_renderer)
            if outcome == 'quit':
                return
            if outcome == 'new_search':
                print(CLEAR)
                break
            print(CLEAR)
            continue


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  {colorize('Goodbye!', Color.CYAN)}")
        sys.exit(0)





class PlaybackController:
    """Controls playback of a single track and handles playback events."""
    def __init__(self, session, visualizer_factory):
        self.session, self.visualizer_factory, self.vis_thread = session, visualizer_factory, None

    def start(self, track, visual_on, has_renderer):
        self.track, self.has_renderer, self.visual_on = track, has_renderer, visual_on
        self.process = play_track(track); self.stop_event = threading.Event(); self.action_queue = py_queue.Queue()
        self.listener = threading.Thread(target=input_reader, args=(self.stop_event, self.action_queue, has_renderer), daemon=True); self.listener.start()
        self._ensure_vis()

    def _ensure_vis(self):
        if self.visual_on.get():
            if self.vis_thread is None or not self.vis_thread.is_alive():
                self.vis_thread = threading.Thread(target=run_visualizer, args=(self.session, self.visual_on), daemon=True); self.vis_thread.start()
        else: self.stop_vis()

    def stop_vis(self):
        if self.vis_thread: self.vis_thread.join(timeout=1)
        self.vis_thread = None

    def run_until_event(self):
        while self.process.poll() is None:
            try:
                if self.has_renderer and msvcrt:
                    if msvcrt.kbhit(): cmd = read_key_msvcrt()
                    else: cmd = None
                else: cmd = self.action_queue.get_nowait()
                if cmd:
                    act = action_for(cmd)
                    if act: return act
            except (py_queue.Empty, Exception): pass
            time.sleep(0.1)
        return "finished"

    def cleanup(self):
        self.stop_event.set(); kill_playback(self.process); time.sleep(0.1); self.stop_vis()

def get_ascii_frame(rows, cols, elapsed):
    frame = []
    for r in range(rows):
        line = []
        for c in range(cols):
            val = math.sin(r * 0.1 + elapsed) + math.cos(c * 0.1 + elapsed)
            line.append('@' if val > 1.2 else '#' if val > 0.6 else '*' if val > 0 else ' ')
        frame.append(''.join(line))
    return frame

def run_visualizer(session, visual_on):
    cols, rows = get_size(); elapsed = 0; sys.stdout.write(CLEAR)
    while visual_on.get():
        frame = get_ascii_frame(rows, cols, elapsed)
        sys.stdout.write('\033[H')
        print('\n'.join(frame))
        elapsed += 0.1; time.sleep(0.05)
    sys.stdout.write(CLEAR)

class CLIFlow:
    def __init__(self, auto_play):
        self.auto_play = auto_play
    
    def handle_outcome(self, outcome):
        return outcome not in ('quit', 'new_search')
