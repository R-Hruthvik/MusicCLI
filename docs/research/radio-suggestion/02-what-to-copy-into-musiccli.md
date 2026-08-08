# 02 — What to copy into MusicCLI

How the research in `01-how-apps-build-radio.md` translates into concrete,
testable changes to MusicCLI's radio (`PlaybackSession` + the yt-dlp adapter).

We **cannot** copy the account-aware parts: MusicCLI has no multi-listener data,
no per-user history or skips, and no audio-gene analysis. But the thing the user
said is missing — "don't keep playing the same artist / same song" — is exactly
the part these services enforce *explicitly*, and **that part is copyable** with
pure logic over a seed's similar-music pool.

## 1. Transport: mine similarity, don't search the artist

Today `fetch_radio_tracks` seeds `ytsearch` by `current.artist` — that produced
the "same artist" experience (research finding: similarity shouldn't be
genre/artist-keyword matching) [source:
https://en.wikipedia.org/wiki/Music_Genome_Project,
https://emitha.com/blogs/case-studies/radio-autoplay-explained-how-spotify-decides-what-plays-next].

**Change:** refill from YouTube's *own* auto **Mix** for the seed video via
yt-dlp:
`yt-dlp --flat-playlist --print <fmt> --playlist-end N "https://www.youtube.com/watch?v=<seed.id>&list=RD<seed.id>"`
(with `RDAM<id>` as fallback). YouTube's recommender yields related-but-different
songs across artists — a real similarity pool rather than a keyword echo of one
artist. `--flat-playlist` keeps it metadata-only (fast, no download)
[source: https://github.com/yt-dlp/yt-dlp].

## 2. Recent-track ring buffer (Spotify-style suppression)

Keep a bounded `recent` deque of played `core_key`s; **never re-advance into a
key still in the window** (e.g. last 6). This is the "same song again" guard and
the first line against loops [source (pattern):
https://emitha.com/blogs/case-studies/radio-autoplay-explained-how-spotify-decides-what-plays-next].

## 3. Artist-separation constraint (Pandora-style)

Maintain `artist_last_pos`/counts. Enforce a **minimum separation**: an artist
cannot reappear for at least N tracks since it last played (e.g. 3), and at most
M tracks from the same artist per refill batch (Pandora caps repeats)
[source (pattern): https://en.wikipedia.org/wiki/Music_Genome_Project].

## 4. Diversity post-filter when absorbing a batch (YouTube/Deezer-style)

When `PlaybackSession.advance()` absorbs a fetched batch:
- drop tracks whose `core_key` is seen (same song);
- drop tracks from an artist at/over the per-artist cap;
- **prefer new artists**: order so fresh artists are queued before repeats
  (YouTube Music's diversity post-filter penalizes duplicate artist IDs)
  [source (AI-flagged): https://recsys.acm.org/recsys25/accepted-contributions/].

## 5. Discovery fail-safe (Deezer-style discovery dial)

If a batch comes back empty (RD mix returned nothing new) **or** it's >70% a
single artist, re-seed from a **randomized mood/genre query** (e.g.
"lofi beats focus", "indie rock 2026") rather than the same artist — this forces
the station to walk AWAY from the current artist and is the "fresh discoveries"
counterpart of Deezer Flow [source:
https://www.deezer.com/explore/en-us/features/flow/].

## 6. Keep `core_key()` same-song dedupe

The existing normalised-title dedupe stays as the baseline "same song, different
upload" filter (covers/remixes) [source:
https://en.wikipedia.org/wiki/Music_Genome_Project].

## Concrete seam changes (kept testable)

- `fetch_radio_tracks(seed, seen, recent, artist_seen, max)` — the radio fetcher
  now receives the session's `recent` keys and artist map so the variety rules
  live in ONE place (the fetcher), still injectable for tests.
- `PlaybackSession` maintains `recent` (deque) and `artist_seen` (artist→count /
  last position) as first-class state alongside `_seen`.
- `PlaybackSession.advance()` applies rules 2–4 when confirming a next track and
  when absorbing a batch; rule 5 triggers inside the fetcher fallback.
- New constants: `RING_SIZE`, `ARTIST_MIN_SEPARATION`, `ARTIST_MAX_PER_BATCH`,
  `ONE_ARTIST_DOMINANCE` (e.g. 0.7) — all configurable, all unit-testable.

## Tests to add

- recent ring buffer suppresses an immediate repeat;
- artist-separation blocks an artist until N tracks of separation;
- per-artist cap trims a dominating artist from an absorbed batch;
- same-core cover is filtered (existing);
- a batch of all-one-artist triggers the discovery fallback seed;
- `fetch_playlist` (from the companion plan) parses a fake `--flat-playlist`
  listing into `Track`s with `source = playlist_title`.
