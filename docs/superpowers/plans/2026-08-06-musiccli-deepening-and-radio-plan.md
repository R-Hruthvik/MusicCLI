# MusicCLI — Deepening + Radio-Improvement Plan (2026-08-06)

Implements the architecture *deepening* candidates from the review, plus three
behaviour fixes the user asked for. The old monolithic `main()` is restructured
into deep modules (see `CONTEXT.md` for domain terms).

## 1. Deepen into modules (all four review candidates)

| Candidate | What changed |
|---|---|
| Track module | immutable `Track` dataclass; `from_line()` owns `|||` parse + NA/fallback rules; `core_key()` dedupe |
| yt-dlp adapter | `search_youtube()` returns `list[Track]`, transport only |
| Playback Session | single owner of queue/history/radio/current; thread-safe `snapshot()`; injectable `fetcher` |
| Command map | `action_for()` + generated `player_legend()` (**fixes the `[R] Restart` lie**: `R`=Radio, `Z`=Restart) |
| Renderer snapshot | visualizer = pure `f(snapshot)` with its own clock; never mutates the session |

## 2. Radio now plays *different* songs

**Problem:** `ytsearch:similar to {title}` returned covers/remixes of the same
song — "same song, different author/channel".

**Fix (two changes):**
1. **Seed from the artist, not the title.** `radio_seed(track)` returns the
   artist when known, else title keywords — so the refill searches that
   artist's body of *different* songs instead of the one song's covers.
2. **Dedupe on a normalised song key.** `core_key()` strips tags,
   `feat.`-tails, and trailing descriptors (`official`, `audio`, `remix`,
   `cover`...), collapsing every upload of the same song to one key. The
   session's `seen` set (everything played or queued) filters those out, so a
   refill never returns the current song or an already-played one.

## 3. Stop / Restart no longer look like a full restart

The old code re-printed the big banner + result list on Stop, which read as a
fresh launch. Now:
- **Stop** stops the renderer and returns straight to the (banner-free) result
  list — `run_playback` returns `'results'` and `main()` redraws results only.
- **Restart** (`Z`) replays the current Track in place, staying on the playback
  screen. The legend truthfully shows `[Z] Restart` / `[R] Radio`.

## 4. Better search results & selection

- Results are **paginated** (`M`ore) instead of capped at a guessed count; the
  header shows "N found (page k)" with stable global numbering.
- `Select a number` plays that Track and queues the rest; **`A`ll** plays the
  whole list; **`R`** toggles radio; **`N`** new search; **`Q`**uit — all
  without re-printing the banner.

## 5. Testability

`test_musiccli.py` (stdlib `unittest`, no network/subprocess) covers:
`Track.from_line` parsing + fallbacks, `core_key` dedupe, `radio_seed`,
`fetch_radio_tracks` dedupe, and `PlaybackSession` transitions (queue order,
radio refill dedupe, prev, snapshot immutability) using a fake fetcher.

Run: `python -m unittest test_musiccli -v`
