import asyncio
import contextlib
import datetime as dt
import time
from contextlib import asynccontextmanager
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from . import auth, db, ingest, spotify, stats
from .config import get_settings
from .taste import candidates as taste_candidates
from .taste import ranker as taste_ranker
from .taste.profile import build_profile


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    app.state.settings = settings
    app.state.conn = db.connect(settings.db_path)
    app.state.code_verifier = None
    worker = asyncio.create_task(
        ingest.run_worker(app.state.conn, settings.spotify_client_id)
    )
    yield
    worker.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await worker
    app.state.conn.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3001", "http://127.0.0.1:3001"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/auth/login")
async def login(request: Request):
    s = request.app.state.settings
    verifier = auth.make_code_verifier()
    request.app.state.code_verifier = verifier
    return RedirectResponse(
        auth.build_authorize_url(s.spotify_client_id, s.redirect_uri, verifier)
    )


@app.get("/auth/callback")
async def callback(
    request: Request, code: str | None = None, error: str | None = None
):
    s = request.app.state.settings
    verifier = request.app.state.code_verifier
    if code is None or error is not None or verifier is None:
        return RedirectResponse(f"{s.frontend_origin}?auth_error=1")
    data = await auth.exchange_code(
        s.spotify_client_id, s.redirect_uri, code, verifier
    )
    auth.save_tokens(
        request.app.state.conn,
        data["access_token"],
        data["refresh_token"],
        data["expires_in"],
    )
    return RedirectResponse(s.frontend_origin)


@app.get("/auth/status")
async def status(request: Request):
    return {"connected": auth.load_tokens(request.app.state.conn) is not None}


@app.get("/stats/recent")
async def stats_recent(request: Request, limit: int = 50):
    return stats.recent_plays(request.app.state.conn, limit=limit)


@app.get("/stats/top")
async def stats_top(request: Request, days: int = 30):
    conn = request.app.state.conn
    return {
        "tracks": stats.top_tracks(conn, days=days),
        "artists": stats.top_artists(conn, days=days),
    }


class FeedbackIn(BaseModel):
    track_id: str
    verdict: Literal["up", "down", "more_like_this"]


class PlaylistIn(BaseModel):
    track_ids: list[str]
    name: str | None = None


class QueueIn(BaseModel):
    track_id: str


@app.get("/discover")
async def discover(request: Request, limit: int = 20):
    conn = request.app.state.conn
    profile = build_profile(conn, time.time())
    return {"items": taste_ranker.rank(conn, profile, time.time(), limit=limit)}


@app.post("/discover/refresh")
async def discover_refresh(request: Request):
    conn = request.app.state.conn
    s = request.app.state.settings
    try:
        token = await auth.get_valid_access_token(conn, s.spotify_client_id)
    except auth.NotConnectedError:
        raise HTTPException(503, "not connected")
    new = await taste_candidates.refresh_candidates(conn, s, token, time.time())
    return {"new": new}


@app.post("/feedback")
async def feedback(request: Request, body: FeedbackIn):
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    request.app.state.conn.execute(
        "INSERT INTO feedback (track_id, verdict, created_at) VALUES (?, ?, ?)",
        (body.track_id, body.verdict, now),
    )
    request.app.state.conn.commit()
    return {"ok": True}


@app.post("/playlists/from-feed")
async def playlist_from_feed(request: Request, body: PlaylistIn):
    conn = request.app.state.conn
    s = request.app.state.settings
    try:
        token = await auth.get_valid_access_token(conn, s.spotify_client_id)
    except auth.NotConnectedError:
        raise HTTPException(503, "not connected")
    name = body.name or f"Spotify DJ picks {dt.date.today().isoformat()}"
    pl = await spotify.create_playlist(token, name)
    await spotify.add_playlist_items(
        token, pl["id"], [f"spotify:track:{t}" for t in body.track_ids]
    )
    return {"url": pl["external_urls"]["spotify"]}


@app.post("/playback/queue")
async def playback_queue(request: Request, body: QueueIn):
    conn = request.app.state.conn
    s = request.app.state.settings
    try:
        token = await auth.get_valid_access_token(conn, s.spotify_client_id)
    except auth.NotConnectedError:
        raise HTTPException(503, "not connected")
    try:
        await spotify.queue_track(token, f"spotify:track:{body.track_id}")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise HTTPException(502, "no active device")
        raise
    return {"ok": True}
