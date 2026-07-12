import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from . import auth, db, ingest, stats
from .config import get_settings


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
