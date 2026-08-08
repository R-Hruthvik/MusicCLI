# 01 — How the apps build a varied radio

Comparative findings. Each numbered claim carries its source; items marked
**(AI-synthesis, unverified)** come from the AI-chat synthesis and could not be
confirmed against a primary source here — treat them as plausible mechanisms,
not established fact.

## Spotify (Radio + Autoplay)

1. Spotify Radio is an **algorithmic station generated from a seed** — a song,
   artist, album, or playlist — that builds "an infinite queue of songs it
   believes that listener will enjoy" [source:
   https://emitha.com/blogs/case-studies/radio-autoplay-explained-how-spotify-decides-what-plays-next].
2. The same core signals drive Radio and Autoplay:
   **audio features** (tempo, key, energy, danceability, acousticness, valence),
   **collaborative filtering** ("listeners who like X also like Y"),
   **NLP** (how the music is described culturally), and **listener behaviour**
   (saves, skips, repeat plays, completion rate) [source:
   https://emitha.com/blogs/case-studies/radio-autoplay-explained-how-spotify-decides-what-plays-next].
3. Autoplay **seeds from whatever was just playing** when a playlist/album ends
   [source:
   https://emitha.com/blogs/case-studies/radio-autoplay-explained-how-spotify-decides-what-plays-next].
4. Similarity for Radio/Autoplay is "determined by audio features (tempo, key,
   energy) and listener behavior (which songs get played together)"
   [source: https://orphiq.com/resources/spotify-algorithm-independent-artists].
5. **High skip rate suppresses a track's placement** in Radio/Autoplay — a
   behaviour feed-back loop on variety/relevance [source:
   https://emitha.com/blogs/case-studies/radio-autoplay-explained-how-spotify-decides-what-plays-next].
6. "Artist Radio" is seeded by the **entire artist catalog**, not one track
   [source: https://emitha.com/blogs/case-studies/radio-autoplay-explained-how-spotify-decides-what-plays-next].
7. **(AI-synthesis, unverified)** Spotify's radio navigates similar tracks via
   embedded similarity and applies a **frequency-penalty ring buffer that
   suppresses recently played track and artist IDs**, forcing progression into
   adjacent sub-genres [source of the *general* similarity claim:
   https://orphiq.com/resources/spotify-algorithm-independent-artists; the
   specific "ring buffer" wording is not in the source].

## Pandora — Music Genome Project

8. Every song is scored across **~450 musicological "genes"** (attributes such
   as lead-vocalist gender, groove usage, guitar distortion level, background
   vocals) on a 0–5 scale [source:
   https://en.wikipedia.org/wiki/Music_Genome_Project].
9. Given a seed song's gene vector, a **matching algorithm**
   constructs other similar songs; the system **"matches" across genres rather
   than by genre**, which is precisely the cross-artist variety behaviour
   [source: https://en.wikipedia.org/wiki/Music_Genome_Project].
10. Genes are assigned **by musicians** (~20–30 min per song, 10% double-checked)
    — high-quality hand-curated content features [source:
    https://en.wikipedia.org/wiki/Music_Genome_Project].
11. **(AI-synthesis, unverified)** Pandora enforces hard-coded
    **artist-separation constraints** (a minimum number of intervening
    tracks/minutes before the same artist can repeat) [source for the genome
    concept: https://en.wikipedia.org/wiki/Music_Genome_Project; the specific
    separation rule is not in the source and is commonly reported anecdotally].

## Deezer — Flow

12. Flow is "a mix of your favorite tracks and fresh discoveries" — an
    **infinite mix** combining likes and *new* music [source:
    https://www.deezer.com/explore/en-us/features/flow/].
13. It analyzes **listening history**, plus **likes** (favorites) and
    **dislikes** (skips/bans) [source:
    https://www.deezer.com/explore/en-us/features/flow/].
14. It has an explicit **discovery level control** ("adjust the level of new
    discoveries you hear") and **mood / genre wheels** to steer variety
    [source: https://www.deezer.com/explore/en-us/features/flow/].
15. Needs a minimum taste baseline ("like at least 16 artists or song") to start
    [source: https://www.deezer.com/explore/en-us/features/flow/].
16. **(AI-synthesis, unverified)** Flow's core is described as a hybrid of
    collaborative filtering + deep audio features with **sequential repetition
    modeling** to limit track/artist repeat rates [source for Flow's behaviour
    signals: https://www.deezer.com/explore/en-us/features/flow/; the "sequential
    repetition modeling" phrasing is not in the source].

## YouTube Music

17. **(AI-synthesis, unverified)** YouTube Music uses a **two-stage pipeline** —
    candidate retrieval via co-listening graphs, then neural re-ranking — with a
    **diversity post-filter that penalizes duplicate artist IDs** to force
    variety across the queue [AI synthesis; cited recsys listing:
    https://recsys.acm.org/recsys25/accepted-contributions/]. The general
    two-tower retrieve-then-rank design is publicly documented elsewhere, but
    the specific "diversity post-filter" claim is flagged as unverified here.

## Cross-service patterns (what actually drives variety)

18. **Similarity transport is content/behavioural, not genre**: Pandora matches
    on audio genes; Spotify on audio features + co-listening. Genre is a
    *label*, not the matching dimension [sources:
    https://en.wikipedia.org/wiki/Music_Genome_Project,
    https://emitha.com/blogs/case-studies/radio-autoplay-explained-how-spotify-decides-what-plays-next].
19. **Anti-repetition is enforced explicitly** — every service has a mechanism to
    stop recent tracks/artists dominating: suppression of recent IDs (Spotify),
    artist-separation limits (Pandora), repeat-rate limits (Deezer), diversity
    post-filtering (YouTube Music) [sources above; the specific mechanisms 7/11/16/17
    are AI-flagged, but the shared *pattern* is corroborated by the primary
    behaviour-signal docs].
20. **Freshness/discovery is a separately controllable dial** (Deezer Flow), and
    **behavioural feedback** (skips) tunes what gets surfaced (Spotify)
    [sources: https://www.deezer.com/explore/en-us/features/flow/,
    https://emitha.com/blogs/case-studies/radio-autoplay-explained-how-spotify-decides-what-plays-next].

