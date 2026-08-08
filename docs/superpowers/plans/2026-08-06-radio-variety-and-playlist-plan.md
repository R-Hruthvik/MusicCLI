# MusicCLI — Radio Variety + Real Playlist Playback (Plan, 2026-08-06)

Scope: research-backed plan. No code changed yet — this is the deepened design
the user asked me to research and plan. Implementation is a follow-up.

## Problem (user feedback)

1. **Radio is too artist-centric.** Seeding by `current.artist` plays mostly
   that one artist's catalog. User wants *variety* — different songs *and*
   different artists — like a real radio station, not an artist deep-dive.
2. **Playlist playing is unclear / missing.** Today `musiccli` only plays a
   search's results (selecting a number queues the rest). There is no way to
   open an actual YouTube playlist URL and play its whole track list.

## Research findings (OpenCLI `brave` + `web read` + yt-dlp docs)

- yt-dlp can list any playlist's videos *without downloading* using
  `--flat-playlist`:
  - `yt-dlp --flat-playlist --print url PLAYLIST_URL`
  - `yt-dlp --flat-playlist --dump-json PLAYLIST_URL` (full metadata, no download)
  - `--flat-playlist` doc: "Do not extract a playlist's URL result entries;
    some entry metadata may be missing and downloading may be bypassed."
- YouTube generates **auto "Mix"/Radio playlists** that resolve through yt-dlp:
  `watch?v=<ID>&list=RD<ID>` (RD = Radio), `RDAM<ID>` = alternate mix,
  `RDAMPL` = radio playlist. These mixes are curated by YouTube's recommender
  and span *related but different* songs across *multiple artists* — that's the
  "radio station" effect, unlike `ytsearch` by artist.
- Output-template fields available for a Track: `%(title)s`, `%(id)s`,
  `%(channel)s`, `%(uploader)s`, `%(duration)s`, `%(playlist_title)s`,
  `%(playlist_index)s`, `%(tags)s`.

## Proposed design

### A. Radio = variety, not one artist

Replace the single-artist seed with a **three-layer** radio refill:

1. **Transport — YouTube's real Radio mix.** For the current Track,
   refill from `watch?v=<seed.id>&list=RD<seed.id>` via
   `--flat-playlist --print <fmt> --playlist-end N`. This pulls YouTube's
   curated mix (varied songs, varied artists) instead of a keyword search.
   Fall back to `RDAM<seed.id>` if the first yields nothing.
2. **Artist-variety filter** (new, in the session/fetcher):
   - Skip any Track whose `core_key()` is already seen (same song ever played).
   - **Per-artist cap**: allow at most `MAX_SAME_ARTIST` (default ~2) tracks
     from the *same* artist in one refill, so no single artist dominates.
   - **No consecutive same-artist**: when picking the next track, prefer an
     artist different from the current Track's artist.
   - **New-artist preference**: rank candidates so fresh artists are queued
     before repeats of already-seen artists.
   - `PlaybackSession` tracks `seen_artists` (artist -> count) alongside `seen`
     and passes it to the injectable `fetcher` (keeps the seam testable).
3. **Discovery safety net.** If the Radio mix returns nothing fresh or is
   >70% one artist, re-seed from a randomized **genre/mood discovery** query
   (e.g. `"lofi beats focus"`, `"indie rock 2024"`, `"jazz workout"`) layered on
   top of the existing dedupe. This guarantees the station walks AWAY from the
   current artist.

Explicitly removed: seeding radio by `current.artist` alone (the cause of the
"same artist" complaint). `core_key()` dedupe stays so covers/remixes of the
same song are still filtered.

### B. Real playlist playback

1. Add a `fetch_playlist(url, max_results)` **adapter** function beside
   `search_youtube` (same `Track.from_line` seam, same `--print` format, plus
   `--flat-playlist --playlist-end N --no-download`). It sets
   `Track.source = playlist_title`.
2. In `main`, **detect the input type**:
   - Search text → current flow.
   - Playlist URL (`youtube.com/playlist?...` or `watch?v=…&list=PL…`) →
     `fetch_playlist(url)`, then start a `PlaybackSession` over **all** the
     playlist's tracks (start_index 0) so they play queue-style with full
     Prev/Next/Stop/Restart/Radio.
   - Single video URL (`watch?v=…` no playlist) → just play that one Track.
3. Clarified "how playlist play works today" (for the docs):
   selecting a result number queues the remaining search results — a
   *search-built queue*. The new playlist URL path makes a *named playlist*
   playable end-to-end, with the playlist title shown as the Track `source`.

### C. Session/fetcher interface changes (kept testable)

- `fetch_radio_tracks(seed, seen_keys, seen_artists, max)` — new `seen_artists`
  argument drives the artist-variety filter.
- `PlaybackSession.advance()` computes `seen_artists` and passes it through the
  injected fetcher; tests use a fake fetcher that inspects the arguments.

## Risks / notes
- RD Radio quality depends on YouTube's recommender & the local player client;
  the artist-variety filter + discovery fallback keep variety regardless.
- `--flat-playlist` omits some metadata, but `title/id/channel/duration` are
  enough for the Track; playback streams by URL later.
- No new pip packages; pure `yt-dlp` subprocess (same constraint as today).

## Test additions (when implemented)
- `fetch_radio_tracks` with a fake search: assert same-core, same-artist-cap,
  and new-artist-preference logic.
- `PlaybackSession` with a fake radio fetcher asserting `seen_artists` is
  passed and respected.
- URL-detection + `fetch_playlist` parsing (fake subprocess output).
