# MusicCLI — Domain Glossary

Domain terms that give names to good seams. Architecture vocabulary (module,
interface, depth, seam, adapter, leverage, locality) lives in the
`/codebase-design` skill; this file names the *domain* concepts.

## Core domain terms

- **Track** — an immutable unit of music from a search: `title`, `artist`,
  `source` (playlist/channel), `duration`, `url`, `id`. Parsing and the
  NA/fallback rules ("Unknown Artist", "YouTube") live in `Track.from_line`.
  Compare tracks by `Track.core_key()` — a normalised title used to detect that
  two uploads are the *same song* (covers/remixes/re-uploads collapse to one key).

- **Playback Session** — the single owner of the current Track, the **Queue**,
  the **History**, and the **Radio** flag for one "listening session" (from
  picking a result to stopping / starting a new search). All writes go through
  its small interface (`remember`, `advance`, `back`, `toggle_radio`,
  `enqueue`, `snapshot`); the renderer only reads `snapshot()`.

- **Queue** — the ordered list of Tracks still to play in the session. It is the
  remainder of a search plus anything Radio refills. Advancing pops the front.

- **History** — Tracks already played in the session, oldest→newest. Prev walks
  backwards through it.

- **Radio** — a session mode. When on and the Queue runs empty, the session
  refills by fetching *different* songs around the current Track (seeded from
  the artist), deduped against everything already seen so it never replays "the
  same song, different channel".

- **yt-dlp adapter** — the seam that turns a query into `list[Track]`
  (`search_youtube`). Transport only; one adapter (yt-dlp) — a hypothetical
  seam, so we deliberately keep a single implementation.

- **Search selection** — `select_search_results()` — the polish step between
  the yt-dlp adapter and the results screen. Hides junk-filtering, re-upload
  collapse ((core_key, artist_key) pair, so "Song (Official Audio)" and
  "Song - Official Video" by the same artist are one entry while covers by
  different artists still show) and duration preference behind one small
  interface. YouTube relevance order is preserved.

- **Renderer / Visualizer** — the fullscreen ASCII animation thread. It is a
  pure function of a session `snapshot()` plus its own clock; it never mutates
  the session (no shared state across threads).

- **Command map** — the single source of truth mapping playback keys to actions
  (`action_for`). The on-screen legend is generated from it, so a displayed key
  can never disagree with the code that handles it.

## Deliberate seams (archived decisions)

- Radio refill is injected into `PlaybackSession` as a `fetcher` seam so
  queue/radio transitions are unit-testable without network/subprocess.
- The `|||`-delimited yt-dlp `--print` schema is an implicit contract owned by
  `Track.from_line` — change it there and only there.
