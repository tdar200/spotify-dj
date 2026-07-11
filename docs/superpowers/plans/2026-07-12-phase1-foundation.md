# Phase 1 (Foundation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Spotify OAuth (PKCE) + continuous listening-history logger in SQLite + minimal stats dashboard, so training data starts accumulating from day one.

**Architecture:** FastAPI backend on :8765 owns OAuth tokens, a thin httpx Spotify client, and a background asyncio worker that polls `recently-played` every 2 minutes into SQLite. A Next.js app on :3001 renders one stats page from the backend's JSON endpoints. Spec: `docs/superpowers/specs/2026-07-12-spotify-dj-design.md`.

**Tech Stack:** Python 3.12, FastAPI, httpx, sqlite3 (stdlib, no ORM), pytest + pytest-asyncio + respx; Next.js (App Router, TypeScript, Tailwind).

## Global Constraints

- Python `>=3.12`; frontend Node 24 / Next.js latest.
- Backend port **8765**; frontend port **3001** (3000 is occupied on this machine).
- Redirect URI exactly `http://127.0.0.1:8765/auth/callback` (loopback IP, not `localhost`).
- OAuth scopes (request all now so Phase 2/3 need no re-consent): `user-top-read user-read-recently-played user-library-read user-read-playback-state user-read-currently-playing user-modify-playback-state playlist-modify-private playlist-modify-public`.
- Secrets live in `backend/.env` (git-ignored). Never commit tokens or the SQLite file.
- Honor `Retry-After` on Spotify 429 responses.
- SQLite single file; tables this phase: `tokens`, `tracks`, `plays` only (YAGNI — enrichment tables arrive in Phase 2).
- All backend work happens in `backend/`; venv at `backend/.venv`. Run tests as `.venv/bin/pytest` from `backend/`.

---

### Task 1: Backend scaffold, config, health endpoint

**Files:**
- Create: `.gitignore`, `backend/pyproject.toml`, `backend/.env.example`, `backend/app/__init__.py`, `backend/app/config.py`, `backend/app/main.py`, `backend/tests/__init__.py`, `backend/tests/conftest.py`, `backend/tests/test_config.py`, `backend/tests/test_main.py`

**Interfaces:**
- Produces: `app.config.Settings` (frozen dataclass: `spotify_client_id: str`, `redirect_uri: str`, `db_path: Path`, `frontend_origin: str`) and `app.config.get_settings() -> Settings` (reads env on every call). `app.main.app` (FastAPI instance). Test fixture `client` (TestClient with env pre-set: `DB_PATH`→tmp file, `SPOTIFY_CLIENT_ID`→`test-client-id`).

- [ ] **Step 1: Create repo hygiene + project files**

`.gitignore` (repo root):

```gitignore
.venv/
__pycache__/
*.py[cod]
*.sqlite3*
.env
node_modules/
.next/
.pytest_cache/
```

`backend/pyproject.toml`:

```toml
[project]
name = "spotify-dj-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "httpx>=0.27",
    "python-dotenv>=1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-asyncio>=0.24", "respx>=0.21"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

`backend/.env.example`:

```bash
SPOTIFY_CLIENT_ID=your-client-id-here
# Defaults below rarely need changing:
# REDIRECT_URI=http://127.0.0.1:8765/auth/callback
# DB_PATH=spotify_dj.sqlite3
# FRONTEND_ORIGIN=http://localhost:3001
```

Create empty `backend/app/__init__.py` and `backend/tests/__init__.py`.

- [ ] **Step 2: Create venv and install**

Run: `cd backend && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`
Expected: installs without error.

- [ ] **Step 3: Write failing tests for config + health**

`backend/tests/conftest.py`:

```python
import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "api.sqlite3"))
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "test-client-id")
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as tc:
        yield tc
```

`backend/tests/test_config.py`:

```python
from pathlib import Path

from app.config import get_settings


def test_defaults(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDIRECT_URI", raising=False)
    s = get_settings()
    assert s.redirect_uri == "http://127.0.0.1:8765/auth/callback"
    assert s.frontend_origin == "http://localhost:3001"
    assert s.db_path == Path("spotify_dj.sqlite3")


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "abc123")
    monkeypatch.setenv("DB_PATH", "/tmp/x.sqlite3")
    s = get_settings()
    assert s.spotify_client_id == "abc123"
    assert s.db_path == Path("/tmp/x.sqlite3")
```

`backend/tests/test_main.py`:

```python
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `.venv/bin/pytest -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'app.config'` (and `app.main`).

- [ ] **Step 5: Implement config and minimal app**

`backend/app/config.py`:

```python
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    spotify_client_id: str
    redirect_uri: str
    db_path: Path
    frontend_origin: str


def get_settings() -> Settings:
    return Settings(
        spotify_client_id=os.environ.get("SPOTIFY_CLIENT_ID", ""),
        redirect_uri=os.environ.get(
            "REDIRECT_URI", "http://127.0.0.1:8765/auth/callback"
        ),
        db_path=Path(os.environ.get("DB_PATH", "spotify_dj.sqlite3")),
        frontend_origin=os.environ.get("FRONTEND_ORIGIN", "http://localhost:3001"),
    )
```

`backend/app/main.py`:

```python
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
async def health():
    return {"ok": True}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `.venv/bin/pytest -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add .gitignore backend/
git commit -m "feat: scaffold FastAPI backend with config and health endpoint"
```

---

### Task 2: SQLite schema and connection

**Files:**
- Create: `backend/app/db.py`, `backend/tests/test_db.py`
- Modify: `backend/tests/conftest.py` (add `conn` fixture)

**Interfaces:**
- Produces: `app.db.connect(db_path) -> sqlite3.Connection` — row factory `sqlite3.Row`, WAL mode, foreign keys on, `check_same_thread=False` (endpoints/worker share the loop but TestClient seeds from another thread), schema created idempotently. Tables: `tokens(id=1 CHECK, access_token, refresh_token, expires_at REAL)`, `tracks(id TEXT PK, name, artist_id, artist_name, album_name, duration_ms)`, `plays(played_at TEXT PK, track_id REFERENCES tracks)`.
- Test fixture `conn` (fresh temp-file DB per test).

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/conftest.py`:

```python
@pytest.fixture
def conn(tmp_path):
    from app import db

    c = db.connect(tmp_path / "test.sqlite3")
    yield c
    c.close()
```

`backend/tests/test_db.py`:

```python
from app import db


def test_tables_created(conn):
    names = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"tokens", "tracks", "plays"} <= names


def test_connect_is_idempotent(tmp_path):
    path = tmp_path / "x.sqlite3"
    db.connect(path).close()
    db.connect(path).close()  # second run must not fail


def test_duplicate_play_ignored(conn):
    conn.execute(
        "INSERT INTO tracks (id, name, artist_id, artist_name) "
        "VALUES ('t1', 'Song', 'a1', 'Artist')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO plays VALUES ('2026-07-12T10:00:00.000Z', 't1')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO plays VALUES ('2026-07-12T10:00:00.000Z', 't1')"
    )
    assert conn.execute("SELECT COUNT(*) AS c FROM plays").fetchone()["c"] == 1


def test_tokens_single_row_constraint(conn):
    import sqlite3

    import pytest

    conn.execute("INSERT INTO tokens VALUES (1, 'a', 'r', 0)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO tokens VALUES (2, 'b', 'r', 0)")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_db.py -v`
Expected: ERROR with `ModuleNotFoundError` / `ImportError` for `app.db`.

- [ ] **Step 3: Implement db module**

`backend/app/db.py`:

```python
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tracks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    artist_id TEXT NOT NULL,
    artist_name TEXT NOT NULL,
    album_name TEXT,
    duration_ms INTEGER
);
CREATE TABLE IF NOT EXISTS plays (
    played_at TEXT PRIMARY KEY,
    track_id TEXT NOT NULL REFERENCES tracks(id)
);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_db.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db.py backend/tests/test_db.py backend/tests/conftest.py
git commit -m "feat: add SQLite schema (tokens, tracks, plays) with dedupe-by-played_at"
```

---

### Task 3: PKCE helpers and token store

**Files:**
- Create: `backend/app/auth.py`, `backend/tests/test_auth.py`

**Interfaces:**
- Consumes: `conn` fixture (Task 2).
- Produces (in `app.auth`): constants `AUTHORIZE_URL`, `TOKEN_URL`, `SCOPES`; `class NotConnectedError(Exception)`; `make_code_verifier() -> str`; `code_challenge(verifier: str) -> str`; `build_authorize_url(client_id: str, redirect_uri: str, verifier: str) -> str`; `save_tokens(conn, access_token: str, refresh_token: str, expires_in: float, now: float | None = None) -> None`; `load_tokens(conn) -> sqlite3.Row | None`.

- [ ] **Step 1: Write failing tests**

`backend/tests/test_auth.py`:

```python
from urllib.parse import parse_qs, urlparse

from app import auth


def test_code_challenge_rfc7636_vector():
    # Appendix B of RFC 7636
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert auth.code_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_verifier_length_and_uniqueness():
    a, b = auth.make_code_verifier(), auth.make_code_verifier()
    assert 43 <= len(a) <= 128
    assert a != b


def test_build_authorize_url():
    url = auth.build_authorize_url(
        "cid", "http://127.0.0.1:8765/auth/callback", "some-verifier"
    )
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    assert url.startswith(auth.AUTHORIZE_URL + "?")
    assert q["client_id"] == ["cid"]
    assert q["response_type"] == ["code"]
    assert q["redirect_uri"] == ["http://127.0.0.1:8765/auth/callback"]
    assert q["code_challenge_method"] == ["S256"]
    assert q["code_challenge"] == [auth.code_challenge("some-verifier")]
    assert "user-read-recently-played" in q["scope"][0]


def test_save_and_load_tokens(conn):
    auth.save_tokens(conn, "acc", "ref", 3600, now=1000.0)
    row = auth.load_tokens(conn)
    assert row["access_token"] == "acc"
    assert row["refresh_token"] == "ref"
    assert row["expires_at"] == 4600.0


def test_save_tokens_overwrites_single_row(conn):
    auth.save_tokens(conn, "acc1", "ref1", 3600, now=0.0)
    auth.save_tokens(conn, "acc2", "ref2", 3600, now=0.0)
    assert auth.load_tokens(conn)["access_token"] == "acc2"
    assert conn.execute("SELECT COUNT(*) AS c FROM tokens").fetchone()["c"] == 1


def test_load_tokens_empty(conn):
    assert auth.load_tokens(conn) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_auth.py -v`
Expected: ERROR — `app.auth` does not exist.

- [ ] **Step 3: Implement PKCE helpers + token store**

`backend/app/auth.py`:

```python
import base64
import hashlib
import secrets
import sqlite3
import time
from urllib.parse import urlencode

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
SCOPES = (
    "user-top-read user-read-recently-played user-library-read "
    "user-read-playback-state user-read-currently-playing "
    "user-modify-playback-state playlist-modify-private playlist-modify-public"
)


class NotConnectedError(Exception):
    """No Spotify tokens stored yet — user must visit /auth/login."""


def make_code_verifier() -> str:
    return secrets.token_urlsafe(64)[:128]


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def build_authorize_url(client_id: str, redirect_uri: str, verifier: str) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "code_challenge_method": "S256",
        "code_challenge": code_challenge(verifier),
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def save_tokens(
    conn: sqlite3.Connection,
    access_token: str,
    refresh_token: str,
    expires_in: float,
    now: float | None = None,
) -> None:
    expires_at = (time.time() if now is None else now) + expires_in
    conn.execute(
        "INSERT INTO tokens (id, access_token, refresh_token, expires_at) "
        "VALUES (1, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET access_token=excluded.access_token, "
        "refresh_token=excluded.refresh_token, expires_at=excluded.expires_at",
        (access_token, refresh_token, expires_at),
    )
    conn.commit()


def load_tokens(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM tokens WHERE id = 1").fetchone()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_auth.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/auth.py backend/tests/test_auth.py
git commit -m "feat: add PKCE helpers and single-row token store"
```

---

### Task 4: Token exchange and auto-refresh

**Files:**
- Modify: `backend/app/auth.py` (append functions)
- Modify: `backend/tests/test_auth.py` (append tests)

**Interfaces:**
- Consumes: `save_tokens` / `load_tokens` / `TOKEN_URL` / `NotConnectedError` (Task 3).
- Produces (in `app.auth`): `async exchange_code(client_id: str, redirect_uri: str, code: str, verifier: str) -> dict`; `async refresh_access_token(client_id: str, refresh_token: str) -> dict`; `async get_valid_access_token(conn, client_id: str) -> str` — returns stored token if >60 s from expiry, else refreshes and persists (keeping the old refresh token if Spotify omits a new one); raises `NotConnectedError` when no tokens exist, AND when refresh fails with 400/401 (revoked grant), in which case it also deletes the stored tokens so `/auth/status` flips to disconnected and the dashboard shows the Connect button again (spec: "reconnect Spotify" banner, no crash loops).

- [ ] **Step 1: Write failing tests**

Append to `backend/tests/test_auth.py`:

```python
import httpx
import pytest
import respx


@respx.mock
async def test_exchange_code_posts_pkce_form():
    route = respx.post(auth.TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "acc", "refresh_token": "ref", "expires_in": 3600},
        )
    )
    data = await auth.exchange_code("cid", "http://127.0.0.1:8765/auth/callback", "the-code", "the-verifier")
    assert data["access_token"] == "acc"
    body = route.calls.last.request.content.decode()
    assert "grant_type=authorization_code" in body
    assert "code=the-code" in body
    assert "code_verifier=the-verifier" in body
    assert "client_id=cid" in body


async def test_get_valid_token_raises_when_not_connected(conn):
    with pytest.raises(auth.NotConnectedError):
        await auth.get_valid_access_token(conn, "cid")


async def test_get_valid_token_returns_fresh_without_network(conn):
    auth.save_tokens(conn, "acc", "ref", 3600)  # expires far in the future
    assert await auth.get_valid_access_token(conn, "cid") == "acc"


@respx.mock
async def test_get_valid_token_refreshes_expired(conn):
    auth.save_tokens(conn, "old", "ref", -10)  # already expired
    route = respx.post(auth.TOKEN_URL).mock(
        return_value=httpx.Response(
            200, json={"access_token": "new", "expires_in": 3600}
        )
    )
    assert await auth.get_valid_access_token(conn, "cid") == "new"
    body = route.calls.last.request.content.decode()
    assert "grant_type=refresh_token" in body
    row = auth.load_tokens(conn)
    assert row["access_token"] == "new"
    assert row["refresh_token"] == "ref"  # kept when Spotify omits a new one


@respx.mock
async def test_refresh_failure_clears_tokens(conn):
    auth.save_tokens(conn, "old", "bad-ref", -10)
    respx.post(auth.TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    with pytest.raises(auth.NotConnectedError):
        await auth.get_valid_access_token(conn, "cid")
    assert auth.load_tokens(conn) is None  # /auth/status now reports disconnected
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_auth.py -v`
Expected: previous 6 pass; new 5 FAIL with `AttributeError` (functions missing).

- [ ] **Step 3: Implement exchange/refresh/get_valid**

Append to `backend/app/auth.py`:

```python
import httpx  # noqa: E402  (keep at top of file with the other imports)


async def exchange_code(
    client_id: str, redirect_uri: str, code: str, verifier: str
) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_access_token(client_id: str, refresh_token: str) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
            },
        )
        resp.raise_for_status()
        return resp.json()


async def get_valid_access_token(conn: sqlite3.Connection, client_id: str) -> str:
    row = load_tokens(conn)
    if row is None:
        raise NotConnectedError()
    if row["expires_at"] - time.time() > 60:
        return row["access_token"]
    try:
        data = await refresh_access_token(client_id, row["refresh_token"])
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (400, 401):
            # Grant revoked/invalid: forget it so /auth/status reports
            # disconnected and the dashboard offers to reconnect.
            conn.execute("DELETE FROM tokens")
            conn.commit()
            raise NotConnectedError() from e
        raise
    save_tokens(
        conn,
        data["access_token"],
        data.get("refresh_token", row["refresh_token"]),
        data["expires_in"],
    )
    return data["access_token"]
```

(Move the `import httpx` line up with the other imports at the top of the file.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_auth.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/auth.py backend/tests/test_auth.py
git commit -m "feat: add PKCE code exchange and auto-refreshing access tokens"
```

---

### Task 5: Spotify recently-played client

**Files:**
- Create: `backend/app/spotify.py`, `backend/tests/test_spotify.py`

**Interfaces:**
- Produces (in `app.spotify`): constant `API_BASE = "https://api.spotify.com/v1"`; `async get_recently_played(access_token: str, after_ms: int | None = None, limit: int = 50) -> dict` — sends Bearer header; passes `after` only when given; on 429 sleeps `Retry-After` seconds and retries once; raises `httpx.HTTPStatusError` on other/persistent errors.

- [ ] **Step 1: Write failing tests**

`backend/tests/test_spotify.py`:

```python
import httpx
import respx

from app import spotify

URL = f"{spotify.API_BASE}/me/player/recently-played"


@respx.mock
async def test_recently_played_success():
    route = respx.get(URL).mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    data = await spotify.get_recently_played("tok", after_ms=123)
    assert data == {"items": []}
    req = route.calls.last.request
    assert req.headers["authorization"] == "Bearer tok"
    assert req.url.params["after"] == "123"
    assert req.url.params["limit"] == "50"


@respx.mock
async def test_recently_played_omits_after_when_none():
    route = respx.get(URL).mock(return_value=httpx.Response(200, json={"items": []}))
    await spotify.get_recently_played("tok")
    assert "after" not in route.calls.last.request.url.params


@respx.mock
async def test_recently_played_retries_on_429(monkeypatch):
    slept = []

    async def fake_sleep(s):
        slept.append(s)

    monkeypatch.setattr(spotify.asyncio, "sleep", fake_sleep)
    route = respx.get(URL)
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "3"}),
        httpx.Response(200, json={"items": []}),
    ]
    data = await spotify.get_recently_played("tok")
    assert data == {"items": []}
    assert slept == [3]
    assert route.call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_spotify.py -v`
Expected: ERROR — `app.spotify` does not exist.

- [ ] **Step 3: Implement client**

`backend/app/spotify.py`:

```python
import asyncio

import httpx

API_BASE = "https://api.spotify.com/v1"


async def get_recently_played(
    access_token: str, after_ms: int | None = None, limit: int = 50
) -> dict:
    params: dict = {"limit": limit}
    if after_ms is not None:
        params["after"] = after_ms
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient() as client:
        for attempt in range(2):
            resp = await client.get(
                f"{API_BASE}/me/player/recently-played",
                params=params,
                headers=headers,
            )
            if resp.status_code == 429 and attempt == 0:
                await asyncio.sleep(int(resp.headers.get("Retry-After", "1")))
                continue
            resp.raise_for_status()
            return resp.json()
    raise AssertionError("unreachable")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_spotify.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/spotify.py backend/tests/test_spotify.py
git commit -m "feat: add Spotify recently-played client with 429 Retry-After handling"
```

---

### Task 6: Ingest worker (poll, dedupe, cursor)

**Files:**
- Create: `backend/app/ingest.py`, `backend/tests/test_ingest.py`

**Interfaces:**
- Consumes: `auth.get_valid_access_token`, `auth.NotConnectedError` (Task 4); `spotify.get_recently_played` (Task 5); `plays`/`tracks` schema (Task 2).
- Produces (in `app.ingest`): `latest_played_at_ms(conn) -> int | None`; `store_items(conn, items: list[dict]) -> int` (returns count of NEW plays; upserts tracks; `INSERT OR IGNORE` plays); `async ingest_once(conn, client_id: str) -> int`; `async run_worker(conn, client_id: str, interval_s: float = 120)` — loops forever: `ingest_once`, swallow `NotConnectedError` silently and any other exception with `logging.exception`, then sleep.

- [ ] **Step 1: Write failing tests**

`backend/tests/test_ingest.py`:

```python
import datetime as dt

import httpx
import respx

from app import auth, ingest, spotify

SAMPLE_ITEM = {
    "played_at": "2026-07-12T10:00:00.000Z",
    "track": {
        "id": "t1",
        "name": "Song One",
        "duration_ms": 200000,
        "album": {"name": "Album One"},
        "artists": [{"id": "a1", "name": "Artist One"}],
    },
}


def test_store_items_inserts_track_and_play(conn):
    assert ingest.store_items(conn, [SAMPLE_ITEM]) == 1
    track = conn.execute("SELECT * FROM tracks WHERE id='t1'").fetchone()
    assert track["name"] == "Song One"
    assert track["artist_name"] == "Artist One"
    assert track["album_name"] == "Album One"
    assert conn.execute("SELECT COUNT(*) AS c FROM plays").fetchone()["c"] == 1


def test_store_items_dedupes_by_played_at(conn):
    ingest.store_items(conn, [SAMPLE_ITEM])
    assert ingest.store_items(conn, [SAMPLE_ITEM]) == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM plays").fetchone()["c"] == 1


def test_latest_played_at_ms_empty(conn):
    assert ingest.latest_played_at_ms(conn) is None


def test_latest_played_at_ms(conn):
    ingest.store_items(conn, [SAMPLE_ITEM])
    expected = int(
        dt.datetime(2026, 7, 12, 10, 0, 0, tzinfo=dt.timezone.utc).timestamp() * 1000
    )
    assert ingest.latest_played_at_ms(conn) == expected


@respx.mock
async def test_ingest_once_fetches_and_stores(conn):
    auth.save_tokens(conn, "tok", "ref", 3600)
    route = respx.get(f"{spotify.API_BASE}/me/player/recently-played").mock(
        return_value=httpx.Response(200, json={"items": [SAMPLE_ITEM]})
    )
    assert await ingest.ingest_once(conn, "cid") == 1
    # second run passes the cursor and stores nothing new
    assert await ingest.ingest_once(conn, "cid") == 0
    assert "after" in route.calls.last.request.url.params
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_ingest.py -v`
Expected: ERROR — `app.ingest` does not exist.

- [ ] **Step 3: Implement ingest**

`backend/app/ingest.py`:

```python
import asyncio
import datetime as dt
import logging
import sqlite3

from . import auth, spotify

logger = logging.getLogger(__name__)


def latest_played_at_ms(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT MAX(played_at) AS m FROM plays").fetchone()
    if row["m"] is None:
        return None
    t = dt.datetime.fromisoformat(row["m"].replace("Z", "+00:00"))
    return int(t.timestamp() * 1000)


def store_items(conn: sqlite3.Connection, items: list[dict]) -> int:
    new = 0
    for item in items:
        track = item["track"]
        artist = track["artists"][0]
        conn.execute(
            "INSERT OR REPLACE INTO tracks "
            "(id, name, artist_id, artist_name, album_name, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                track["id"],
                track["name"],
                artist["id"],
                artist["name"],
                track.get("album", {}).get("name"),
                track.get("duration_ms"),
            ),
        )
        cur = conn.execute(
            "INSERT OR IGNORE INTO plays (played_at, track_id) VALUES (?, ?)",
            (item["played_at"], track["id"]),
        )
        new += cur.rowcount
    conn.commit()
    return new


async def ingest_once(conn: sqlite3.Connection, client_id: str) -> int:
    token = await auth.get_valid_access_token(conn, client_id)
    data = await spotify.get_recently_played(
        token, after_ms=latest_played_at_ms(conn)
    )
    return store_items(conn, data.get("items", []))


async def run_worker(
    conn: sqlite3.Connection, client_id: str, interval_s: float = 120
) -> None:
    while True:
        try:
            new = await ingest_once(conn, client_id)
            if new:
                logger.info("ingested %d new plays", new)
        except auth.NotConnectedError:
            pass  # user hasn't connected Spotify yet
        except Exception:
            logger.exception("ingest failed; will retry next cycle")
        await asyncio.sleep(interval_s)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_ingest.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/ingest.py backend/tests/test_ingest.py
git commit -m "feat: add ingest worker polling recently-played with cursor + dedupe"
```

---

### Task 7: App wiring — lifespan, CORS, auth endpoints

**Files:**
- Modify: `backend/app/main.py` (full rewrite below)
- Create: `backend/tests/test_api_auth.py`

**Interfaces:**
- Consumes: everything above. `app.state.conn` / `app.state.settings` are set in lifespan; the worker task starts there too.
- Produces routes: `GET /auth/login` → 307 to Spotify authorize URL (stores verifier in `app.state.code_verifier`); `GET /auth/callback?code=` → exchanges, saves tokens, 307 to `settings.frontend_origin`; `GET /auth/status` → `{"connected": bool}`; keeps `GET /health`. CORS allows `settings.frontend_origin` plus `http://127.0.0.1:3001`.

- [ ] **Step 1: Write failing tests**

`backend/tests/test_api_auth.py`:

```python
import httpx
import respx

from app import auth


def test_login_redirects_to_spotify(client):
    r = client.get("/auth/login", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"].startswith(auth.AUTHORIZE_URL + "?")
    assert "client_id=test-client-id" in r.headers["location"]


def test_status_disconnected(client):
    assert client.get("/auth/status").json() == {"connected": False}


@respx.mock
def test_callback_exchanges_and_connects(client):
    respx.route(host="testserver").pass_through()  # let TestClient through
    client.get("/auth/login", follow_redirects=False)  # sets the verifier
    respx.post(auth.TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "a", "refresh_token": "r", "expires_in": 3600},
        )
    )
    r = client.get("/auth/callback", params={"code": "abc"}, follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "http://localhost:3001"
    assert client.get("/auth/status").json() == {"connected": True}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_api_auth.py -v`
Expected: FAIL — 404s (routes don't exist yet).

- [ ] **Step 3: Rewrite main.py**

`backend/app/main.py` (replace entire file):

```python
import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from . import auth, db, ingest
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
async def callback(request: Request, code: str):
    s = request.app.state.settings
    data = await auth.exchange_code(
        s.spotify_client_id, s.redirect_uri, code, request.app.state.code_verifier
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
```

- [ ] **Step 4: Run full suite to verify pass (and no regressions)**

Run: `.venv/bin/pytest -v`
Expected: all tests pass (29 total).

- [ ] **Step 5: Commit**

```bash
git add backend/app/main.py backend/tests/test_api_auth.py
git commit -m "feat: wire lifespan (DB + ingest worker), CORS, and OAuth endpoints"
```

---

### Task 8: Stats queries and endpoints

**Files:**
- Create: `backend/app/stats.py`, `backend/tests/test_stats.py`
- Modify: `backend/app/main.py` (append two routes)

**Interfaces:**
- Consumes: schema (Task 2), `app.state.conn` (Task 7).
- Produces (in `app.stats`): `recent_plays(conn, limit: int = 50) -> list[dict]` — newest first, each `{"played_at", "track", "artist"}`; `top_tracks(conn, days: int = 30, limit: int = 20) -> list[dict]` — each `{"name", "artist", "plays"}`; `top_artists(conn, days: int = 30, limit: int = 20) -> list[dict]` — each `{"name", "plays"}`. Routes: `GET /stats/recent?limit=` → list; `GET /stats/top?days=` → `{"tracks": [...], "artists": [...]}`.

- [ ] **Step 1: Write failing tests**

`backend/tests/test_stats.py`:

```python
import datetime as dt

from app import stats


def seed(conn, played_at: str, track_id: str, name: str, artist: str):
    conn.execute(
        "INSERT OR REPLACE INTO tracks (id, name, artist_id, artist_name) "
        "VALUES (?, ?, ?, ?)",
        (track_id, name, f"a-{artist}", artist),
    )
    conn.execute(
        "INSERT OR IGNORE INTO plays (played_at, track_id) VALUES (?, ?)",
        (played_at, track_id),
    )
    conn.commit()


def iso(days_ago: int, hour: int = 12) -> str:
    d = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)
    return d.replace(hour=hour, minute=0, second=0, microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


def test_recent_plays_newest_first(conn):
    seed(conn, iso(2), "t1", "Old Song", "A")
    seed(conn, iso(0), "t2", "New Song", "B")
    result = stats.recent_plays(conn)
    assert [r["track"] for r in result] == ["New Song", "Old Song"]
    assert result[0]["artist"] == "B"


def test_top_tracks_counts_and_cutoff(conn):
    seed(conn, iso(1, hour=10), "t1", "Hit", "A")
    seed(conn, iso(1, hour=11), "t1", "Hit", "A")
    seed(conn, iso(2), "t2", "Other", "B")
    seed(conn, iso(90), "t3", "Ancient", "C")  # outside 30-day window
    result = stats.top_tracks(conn, days=30)
    assert result[0] == {"name": "Hit", "artist": "A", "plays": 2}
    assert all(r["name"] != "Ancient" for r in result)


def test_top_artists_aggregates_across_tracks(conn):
    seed(conn, iso(1, hour=9), "t1", "Song1", "Radiohead")
    seed(conn, iso(1, hour=10), "t2", "Song2", "Radiohead")
    seed(conn, iso(1, hour=11), "t3", "Song3", "Bjork")
    result = stats.top_artists(conn, days=30)
    assert result[0] == {"name": "Radiohead", "plays": 2}


def test_stats_endpoints(client):
    conn = client.app.state.conn
    seed(conn, iso(1), "t1", "Hit", "A")
    r = client.get("/stats/recent")
    assert r.status_code == 200
    assert r.json()[0]["track"] == "Hit"
    r = client.get("/stats/top")
    assert r.status_code == 200
    body = r.json()
    assert body["tracks"][0]["plays"] == 1
    assert body["artists"][0]["name"] == "A"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_stats.py -v`
Expected: ERROR — `app.stats` does not exist.

- [ ] **Step 3: Implement stats module and routes**

`backend/app/stats.py`:

```python
import datetime as dt
import sqlite3


def _cutoff(days: int) -> str:
    d = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    return d.strftime("%Y-%m-%dT%H:%M:%S")


def recent_plays(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT p.played_at, t.name AS track, t.artist_name AS artist "
        "FROM plays p JOIN tracks t ON t.id = p.track_id "
        "ORDER BY p.played_at DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


def top_tracks(conn: sqlite3.Connection, days: int = 30, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT t.name AS name, t.artist_name AS artist, COUNT(*) AS plays "
        "FROM plays p JOIN tracks t ON t.id = p.track_id "
        "WHERE p.played_at >= ? "
        "GROUP BY t.id ORDER BY plays DESC, name LIMIT ?",
        (_cutoff(days), limit),
    )
    return [dict(r) for r in rows]


def top_artists(conn: sqlite3.Connection, days: int = 30, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT t.artist_name AS name, COUNT(*) AS plays "
        "FROM plays p JOIN tracks t ON t.id = p.track_id "
        "WHERE p.played_at >= ? "
        "GROUP BY t.artist_id ORDER BY plays DESC, name LIMIT ?",
        (_cutoff(days), limit),
    )
    return [dict(r) for r in rows]
```

Append to `backend/app/main.py` (and add `stats` to the `from . import` line):

```python
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
```

- [ ] **Step 4: Run full suite to verify pass**

Run: `.venv/bin/pytest -v`
Expected: all tests pass (33 total).

- [ ] **Step 5: Commit**

```bash
git add backend/app/stats.py backend/tests/test_stats.py backend/app/main.py
git commit -m "feat: add recent-plays and top-tracks/artists stats endpoints"
```

---

### Task 9: Next.js frontend — stats page + README

**Files:**
- Create: `frontend/` (via create-next-app), replace `frontend/app/page.tsx`, modify `frontend/package.json` (port 3001), create `README.md` (repo root)

**Interfaces:**
- Consumes: `GET /auth/status`, `GET /stats/recent`, `GET /stats/top` (Tasks 7–8) at `http://127.0.0.1:8765`.
- Produces: one dashboard page at `http://localhost:3001` — connect button when disconnected; recent plays + top tracks/artists when connected.

- [ ] **Step 1: Scaffold Next.js app**

Run from repo root:

```bash
npx --yes create-next-app@latest frontend --typescript --tailwind --eslint --app --no-src-dir --import-alias "@/*" --use-npm --turbopack
```

Then in `frontend/package.json` change the dev script to bind port 3001:

```json
"dev": "next dev --turbopack -p 3001",
```

Verify: `cd frontend && npm run dev` → serves on `http://localhost:3001`, then stop it.

- [ ] **Step 2: Replace the home page**

`frontend/app/page.tsx` (replace entire file):

```tsx
"use client";

import { useEffect, useState } from "react";

const API = "http://127.0.0.1:8765";

type Play = { played_at: string; track: string; artist: string };
type TopTrack = { name: string; artist: string; plays: number };
type TopArtist = { name: string; plays: number };

export default function Home() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [recent, setRecent] = useState<Play[]>([]);
  const [topTracks, setTopTracks] = useState<TopTrack[]>([]);
  const [topArtists, setTopArtists] = useState<TopArtist[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${API}/auth/status`)
      .then((r) => r.json())
      .then((d) => setConnected(d.connected))
      .catch(() => setError("Backend not reachable on :8765 — is it running?"));
    fetch(`${API}/stats/recent`)
      .then((r) => r.json())
      .then(setRecent)
      .catch(() => {});
    fetch(`${API}/stats/top`)
      .then((r) => r.json())
      .then((d) => {
        setTopTracks(d.tracks);
        setTopArtists(d.artists);
      })
      .catch(() => {});
  }, []);

  return (
    <main className="mx-auto max-w-3xl p-8 space-y-8">
      <h1 className="text-2xl font-bold">Spotify DJ — Stats</h1>

      {error && <p className="text-red-500">{error}</p>}

      {connected === false && (
        <a
          href={`${API}/auth/login`}
          className="inline-block rounded bg-green-600 px-4 py-2 font-semibold text-white"
        >
          Connect Spotify
        </a>
      )}

      {connected && (
        <p className="text-sm text-green-600">
          Spotify connected — logging your listening history.
        </p>
      )}

      <section>
        <h2 className="mb-2 text-lg font-semibold">Top artists (30 days)</h2>
        <ol className="list-decimal pl-6">
          {topArtists.map((a) => (
            <li key={a.name}>
              {a.name} <span className="text-gray-500">({a.plays} plays)</span>
            </li>
          ))}
        </ol>
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Top tracks (30 days)</h2>
        <ol className="list-decimal pl-6">
          {topTracks.map((t) => (
            <li key={`${t.name}-${t.artist}`}>
              {t.name} — {t.artist}{" "}
              <span className="text-gray-500">({t.plays} plays)</span>
            </li>
          ))}
        </ol>
      </section>

      <section>
        <h2 className="mb-2 text-lg font-semibold">Recent plays</h2>
        <ul className="space-y-1">
          {recent.map((p) => (
            <li key={p.played_at} className="text-sm">
              <span className="text-gray-500">
                {new Date(p.played_at).toLocaleString()}
              </span>{" "}
              — {p.track} — {p.artist}
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}
```

- [ ] **Step 3: Write README**

`README.md` (repo root):

```markdown
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
```

- [ ] **Step 4: Manual end-to-end verification**

1. Terminal A: `cd backend && .venv/bin/uvicorn app.main:app --port 8765`
2. Terminal B: `cd frontend && npm run dev`
3. Open `http://localhost:3001` → page renders, shows **Connect Spotify**.
4. Click it → Spotify consent → redirected back to the dashboard → "Spotify connected".
5. Play a song on Spotify; within ~2 minutes `curl http://127.0.0.1:8765/stats/recent` shows it, and a page reload lists it.

Expected: all five observations hold. (Steps 3–5 need the user's Spotify app credentials in `backend/.env`; if unavailable, verify 1–3 and hand the rest to the user.)

- [ ] **Step 5: Commit**

```bash
git add frontend/ README.md
git commit -m "feat: add Next.js stats dashboard and quickstart README"
```
