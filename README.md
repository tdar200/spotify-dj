# spotify-dj

Personal Spotify DJ: logs your listening history locally and (in later
phases) live-DJs your Spotify with a taste model trained on your own
skips and likes. Spec: `docs/superpowers/specs/2026-07-12-spotify-dj-design.md`.

## One-time setup

1. Create an app at https://developer.spotify.com/dashboard
   - Redirect URI: `http://127.0.0.1:8765/auth/callback`
   - Check "Web API"
2. `cp backend/.env.example backend/.env` and set `SPOTIFY_CLIENT_ID`.
3. (Recommended) Create a https://listenbrainz.org account and connect
   your Spotify under Settings → Music Services — free weekly discovery
   playlists, zero code.

## Run

Backend:

    cd backend
    python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # first time
    .venv/bin/uvicorn app.main:app --port 8765

Frontend:

    cd frontend
    npm install        # first time
    npm run dev        # http://localhost:3001

Open http://localhost:3001 and click **Connect Spotify**. The backend
polls your recently-played every 2 minutes into `backend/spotify_dj.sqlite3`.

## Tests

    cd backend && .venv/bin/pytest
