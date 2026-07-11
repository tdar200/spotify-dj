# Spotify DJ — Design

**Date:** 2026-07-12
**Status:** Approved by user (design conversation, 2026-07-12); revised same
day to hybrid scope after prior-art review.

## What this is

A personal, local-first Spotify DJ: a self-trained recommendation engine that
live-DJs the user's Spotify session (auto-queue + learn from skips), with a
discovery feed and a minimal stats view. Single user (Spotify Premium, app in
Spotify development mode — up to 25 allowlisted users, no approval process).

**Hybrid scope (build vs buy).** Prior-art review found the stats and
weekly-discovery problems already solved, and the live learning DJ unsolved:

- [your_spotify](https://github.com/Yooooomi/your_spotify) — mature
  self-hosted Spotify stats dashboard. We do NOT rebuild rich stats; our
  dashboard keeps only a minimal stats page over our own `plays` table.
- [ListenBrainz](https://listenbrainz.org) — connects to the user's Spotify
  account, ingests listening history, and pushes free Weekly Exploration /
  Daily Jams playlists back into Spotify. This replaces our standalone
  "generated playlists" feature; the user connects it once (setup step). Its
  open APIs additionally serve as a candidate source for our ranker.
- No existing tool watches live Spotify playback, auto-queues, and trains a
  personal model from skip/completion feedback ([Deej-AI](https://github.com/teticio/Deej-AI)
  is playlist-only and predates the API lockdown). That loop is what we build.

We still run our own ingest worker (SQLite) — it is the ML training corpus
and stays fully local, independent of the external services.

## Hard constraint driving the design

Spotify removed its recommendation intelligence from the Web API for new apps
(Nov 2024, confirmed still true against the Feb 2026 changelog):

- **Gone, no path back for new apps:** Recommendations, Audio Features, Audio
  Analysis, Related Artists, 30-second previews.
- **Still available:** playback control (Premium), playlist creation
  (`POST /me/playlists`) and item management (`/playlists/{id}/items`), top
  tracks/artists, recently played (last 50 only), saved library
  (consolidated `/me/library` endpoints), search, basic track/album/artist
  metadata (fields like `popularity` and `available_markets` were removed
  Feb 2026 — do not depend on them).

Therefore all recommendation intelligence is built in this project, fed by
external open sources (Last.fm, ListenBrainz) and the user's own logged
history and feedback.

## Chosen approach: staged hybrid

Rejected alternatives:

- **A. External graph only** (Last.fm/ListenBrainz + ranker, never any audio
  analysis) — subset of the chosen approach; kept as its Phase 2.
- **B. Audio ML first** (embed 30s previews from Deezer/iTunes via
  Essentia/CLAP, nearest-neighbor recommendations) — slowest to first value,
  preview sourcing fragile and ToS-grey. Deferred to an optional Phase 4
  feature inside the ranker, not a foundation.

## Architecture

```
Next.js dashboard (:3001)  <->  FastAPI backend (:8765)  <->  Spotify Web API
                                       |                 <->  Last.fm API
                                       |                 <->  ListenBrainz API
                                    SQLite
```

- Everything runs on the user's machine. Port 3000 is occupied on this
  machine; Next.js uses 3001.
- The backend owns all secrets and OAuth tokens. The frontend only ever calls
  the backend.
- SQLite (single file) until it hurts; no Postgres.

## Components

### FastAPI backend (Python 3.12)

**Auth module**
- Spotify OAuth Authorization Code + PKCE. Redirect URI:
  `http://127.0.0.1:8765/auth/callback` (loopback IP, not `localhost`, per
  current Spotify requirements).
- Tokens persisted in SQLite; refreshed automatically before expiry.
- Scopes: `user-top-read`, `user-read-recently-played`, `user-library-read`,
  `user-read-playback-state`, `user-read-currently-playing`,
  `user-modify-playback-state`, `playlist-modify-private`,
  `playlist-modify-public`.

**Spotify client**
- Thin async wrapper (httpx) over exactly the endpoints used; respects 429
  `Retry-After`.

**Ingest worker**
- Background task polls `recently-played` every ~2 minutes, appends to
  `plays` deduped by `played_at`. Spotify exposes only the last 50 plays, so
  continuous logging is what creates the training corpus — it starts in
  Phase 1 and never stops.
- During an active live-DJ session, polls playback state every ~5 s to detect
  skip vs. completion.

**Enrichment module**
- Last.fm: `track.getSimilar`, `artist.getSimilar`, `track.getTopTags`,
  `artist.getTopTags`. Free API key, supplied by user via env.
- ListenBrainz: open recommendation/similarity APIs as a second candidate
  source (no key required for read APIs).
- All responses cached in SQLite (`tags`, `similar_edges`); never re-fetch
  what is cached.
- Spotify↔Last.fm matching by normalized artist + title. Unmatched tracks are
  logged and skipped — never fuzzy-guessed.

**Taste engine**
- Taste profile: weighted artist and tag vectors computed from `plays`,
  `feedback`, and saved library, with recency decay and time-of-day buckets.
- Candidate generator: similar-to-loved (Last.fm/ListenBrainz edges from top
  artists/tracks) minus already-known (library + play history), resolved back
  to Spotify track IDs via search.
- Ranker v1 (Phase 2): explainable heuristic score — tag overlap with
  profile, artist-graph proximity, novelty bonus, recent-skip penalty.
- Ranker v2 (Phase 4): LightGBM trained on accumulated `feedback` labels,
  same feature set (plus optional audio embeddings). Heuristic remains as
  fallback. Golden tests pin scoring behavior so retraining cannot silently
  change recommendations.

**DJ engine** — outputs over the same taste engine:
- `GET /discover`: ranked feed of candidates with per-track "why" (top
  contributing features).
- `POST /playlists/from-feed`: saves selected/top feed picks as a playlist in
  the user's Spotify account (`POST /me/playlists` + add items). Vibe-based
  standalone generation is out of scope — ListenBrainz's weekly playlists
  cover that.
- Live DJ session: start/stop; watches playback, keeps 1–2 ranked tracks in
  the Spotify queue, records skip (<~40% listened) / completion as labeled
  feedback. On repeated API errors it stops queueing and reports, rather than
  fighting the user's session.

### Next.js frontend (App Router, TypeScript, Tailwind + shadcn/ui)

- **Discover**: feed with play/queue buttons and 👍 / 👎 / "more like this" —
  every interaction is a labeled training example; "save picks as playlist"
  button.
- **DJ panel**: now playing, next up, why-this-pick, session start/stop.
- **Stats (minimal)**: one page — recent plays and top artists/tracks from
  the local `plays` table, mostly to verify ingest is healthy. Rich stats are
  your_spotify's job if the user ever wants them.

### SQLite schema (tables)

`tokens`, `plays`, `tracks`, `artists`, `tags`, `similar_edges`,
`candidates`, `feedback`, `dj_sessions`, `model_versions`.

## Build phases

1. **Foundation** — OAuth, Spotify client, ingest worker, minimal stats page.
   Training data starts accumulating. (User also connects ListenBrainz to
   Spotify — free weekly discovery playlists start arriving with zero code.)
2. **Discovery** — enrichment, taste profile, heuristic ranker, discover feed,
   save-picks-as-playlist.
3. **Live DJ** — playback watcher, auto-queue, skip/complete feedback loop.
4. **Learned ranker** — LightGBM on feedback; optional audio-embedding
   feature (Deezer/iTunes previews + Essentia/CLAP) if wanted later.

Each phase ships something usable and gets its own implementation plan.

## Error handling

- 429s: honor `Retry-After`, back off; ingest worker skips a cycle rather
  than hammering.
- Token refresh failure: dashboard shows a "reconnect Spotify" banner; no
  crash loops.
- Enrichment misses: logged, skipped.
- Live DJ: degrades to observing (or stops) on persistent errors; never
  pauses/clears the user's queue on its own.

## Testing

- Backend: pytest, TDD. Spotify/Last.fm/ListenBrainz mocked (respx).
  Golden tests for ranker scoring and taste-profile math.
- Ingest dedupe and skip-detection logic unit-tested against fixture
  timelines.
- Frontend: minimal — component tests for feedback controls; the dashboard is
  personal tooling, not a product surface.

## User setup (only the user can do these)

1. Create an app at developer.spotify.com/dashboard; set redirect URI
   `http://127.0.0.1:8765/auth/callback`; note Client ID (PKCE — no secret
   needed in the app, but Spotify still issues one; keep it out of git).
2. Get a free Last.fm API key.
3. Put both in `.env` (git-ignored).
4. Create a ListenBrainz account and connect it to Spotify (listening-history
   import + playlist export) — this delivers the weekly discovery playlists
   and improves ListenBrainz's API recommendations for us.

## Out of scope

- Rich stats dashboards (use your_spotify) and standalone vibe-based playlist
  generation (use ListenBrainz weekly playlists).
- Multi-user support, deployment, HTTPS, hosting.
- Spotify audio playback inside the dashboard (Web Playback SDK) — playback
  happens on the user's normal Spotify devices; the dashboard only controls.
- Scrobbling to Last.fm.
