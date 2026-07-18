# Spotify DJ — Phase 2: Discovery — Design

**Date:** 2026-07-18
**Status:** Approved by user (design conversation, 2026-07-18).
**Parent spec:** `2026-07-12-spotify-dj-design.md` (approved). This document
refines Phase 2 ("Discovery") of that spec; it changes nothing in it.

## Goal

An explainable discovery feed: candidate tracks sourced from Last.fm and
ListenBrainz similarity graphs, scored against a taste profile built from the
user's own logged plays, saved library, and Spotify top artists/tracks. The
user can play/queue picks, give 👍/👎/"more like this" feedback (labeled
training data for Phase 4), and save picks as a real Spotify playlist.

## Decisions made in this conversation

- **Last.fm key:** build both sources now; Last.fm stays dormant until the
  user puts `LASTFM_API_KEY` in `backend/.env`. ListenBrainz (keyless) works
  from day one. The ranker must degrade gracefully with zero Last.fm data.
- **Cold start:** only ~50 plays are logged at time of writing. The taste
  profile therefore also draws on the Spotify saved library and long-term top
  artists/tracks, which encode years of taste.

## Components

### Enrichment module (`app/enrichment/`)

- **Last.fm client** (httpx, async): `track.getSimilar`, `artist.getSimilar`,
  `track.getTopTags`, `artist.getTopTags`. Returns empty results without
  logging errors when no API key is configured.
- **ListenBrainz client** (httpx, async, keyless): similar-artists and
  recommendation read APIs.
- **Cache:** every successful response is written to SQLite (`tags`,
  `similar_edges`) and never re-fetched. Cache key includes the source
  (`lastfm` / `listenbrainz`).
- **Matching:** Spotify ↔ external catalogs matched by normalized
  artist + title (lowercase, strip punctuation/feat.-clauses, collapse
  whitespace). Unmatched tracks are logged and skipped — never fuzzy-guessed.
- Both clients honor 429 `Retry-After` like the existing Spotify client.

### Taste profile (`app/taste/profile.py`)

Pure functions over local data — no network:

- **Artist vector:** weight per artist from `plays` (exponential recency
  decay, half-life ~30 days), saved library membership, and Spotify
  long-term top-artists rank.
- **Tag vector:** play-weighted aggregation of cached tags of played/saved
  artists and tracks, normalized.
- Feedback (`feedback` table) adjusts weights: 👍 boosts, 👎 suppresses.
- Golden tests pin the math.

### Candidate generator (`app/taste/candidates.py`)

1. Seeds: top-N artists and tracks from the taste profile.
2. Expand via cached/fetched `similar_edges` (both sources).
3. Subtract already-known: anything in `plays`, saved library, or previously
   surfaced `candidates`.
4. Resolve external names → Spotify track IDs via Spotify search (normalized
   match required); store in `candidates` with provenance (which seed/edge
   produced it).

### Heuristic ranker (`app/taste/ranker.py`)

Explainable linear score per candidate:

- **+ tag overlap** — cosine-style similarity of candidate tags vs. profile
  tag vector
- **+ artist-graph proximity** — edge weight / hops from seed artists
- **+ novelty bonus** — unknown artist scores higher than a new track by a
  heavily-played artist
- **− recent-skip penalty** — candidate artists of recently 👎'd/skipped
  tracks are suppressed
- Output keeps the top contributing features per track so the API can
  return a human-readable "why".
- Golden tests pin scores for fixture profiles/candidates.

### API endpoints

- `GET /discover?limit=N` — ranked candidate feed; each item: track metadata,
  score, "why" (top features), provenance.
- `POST /feedback` — `{track_id, verdict: up|down|more_like_this}`; stored in
  `feedback` with timestamp. `more_like_this` additionally enqueues the track
  as a candidate seed.
- `POST /playlists/from-feed` — `{track_ids, name?}`; creates a private
  Spotify playlist and adds the tracks; returns the playlist URL.
- Refresh of enrichment/candidates happens on-demand (first `/discover` call
  or explicit `POST /discover/refresh`), not on a background timer — Phase 2
  has no always-on enrichment worker.

### Frontend

- **Discover page** (alongside existing stats page): ranked feed with
  artwork, "why this" line, play/queue buttons (Spotify deep links + existing
  queue endpoint scope), 👍 / 👎 / "more like this" buttons, checkbox
  selection + "Save as playlist".
- Minimal component tests for the feedback controls only.

### New SQLite tables

`artists`, `tags`, `similar_edges`, `candidates`, `feedback` — schema
finalized in the implementation plan; all created via the existing schema
module's idempotent DDL.

## Error handling

- No Last.fm key → Last.fm client returns empty, feed still works from
  ListenBrainz.
- 429s honored with `Retry-After`; enrichment gives up on a source for the
  current refresh rather than hammering.
- Unmatched external tracks logged + skipped.
- Spotify search resolution failures skip the candidate, keep the rest.

## Testing

- pytest TDD; Last.fm/ListenBrainz/Spotify mocked with respx.
- Golden tests: taste-profile vectors and ranker scores on fixtures.
- Normalization/matching unit tests (feat.-clauses, punctuation, unicode).

## Out of scope (Phase 2)

- Live DJ session / skip detection (Phase 3).
- LightGBM learned ranker and audio embeddings (Phase 4).
- Scrobbling, rich stats, vibe playlists (parent spec's out-of-scope list).
