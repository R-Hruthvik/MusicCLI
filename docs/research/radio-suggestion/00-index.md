# Radio / Song-Suggestion Research — Index (2026-08-06)

Research question: **how do real music apps turn one seed song into an endless,
VARIED radio station without getting stuck on the same artist or the same song?**
Goal: apply the mechanisms to MusicCLI's radio (yt-dlp-based).

## TL;DR findings

- Every major service (Spotify, Pandora, Deezer, YouTube Music) treats **variety
  and anti-repetition as an *explicit, enforced* concern**, not an accident of
  the recommender. Key shared mechanisms:
  1. Build a **candidate pool by similarity** (audio features / behaviour),
     *not by genre* — Pandora famously "matches" across genres, which is exactly
     the variety you felt was missing from `ytsearch:similar to {title}`.
  2. **Suppress recently played tracks and artists** (Spotify's "radio" penalizes
     recent IDs; Pandora enforces artist-separation limits before an artist can
     repeat; YouTube Music's ranking applies a diversity post-filter).
  3. **Diversity feed-back is shaped by behaviour** (skips/saves/completion) and
     a **freshness/discovery dial** (Deezer Flow).
- What MusicCLI can copy *without* user accounts / multi-listener data: the
  **anti-repetition + artist-diversity constraints** and a **similarity-transport
  mined from the seed** (YouTube's own auto "Mix"), plus a **discovery fallback**
  to walk away from the artist.

## Docs

- [01 — How the apps build a varied radio](01-how-apps-build-radio.md)
- [02 — What to copy into MusicCLI](02-what-to-copy-into-musiccli.md)

## PRD / decision-update checklist

Backs the plan in
`docs/superpowers/plans/2026-08-06-radio-variety-and-playlist-plan.md`.
Decisions to lock before implementing:

- [ ] Radio transport: seed refill from YouTube's auto **Mix** (`list=RD<id>` /
      `RDAM<id>`), not `ytsearch` by artist.
- [ ] **Recent-track ring buffer** (suppress immediate repeats of a core_key).
- [ ] **Artist-separation constraint** (≥N since an artist last played; maintain
      `artist_last_pos`).
- [ ] **Per-artist cap + new-artist preference** when absorbing a fetched batch
      (YouTube-style diversity post-filter; Pandora-style cap).
- [ ] **Discovery fallback**: if a batch is empty or >70% one artist, re-seed
      from a randomized mood/genre query (Deezer-style discovery dial).
- [ ] Keep **`core_key()` same-song dedupe** as the first line of defence.
- [ ] Add unit tests for each filter (recent, separation, per-artist cap, and
      new-artist preference) via the injectable radio fetcher.
