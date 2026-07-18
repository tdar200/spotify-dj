# Phase 2: Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Explainable discovery feed: candidates from Last.fm/ListenBrainz similarity graphs, ranked against a taste profile built from local plays + feedback + Spotify top artists, with 👍/👎 feedback capture and save-as-playlist.

**Architecture:** New `app/enrichment/` package (Last.fm + ListenBrainz clients, SQLite cache) and `app/taste/` package (normalize, profile, candidates, ranker), five new endpoints in `app/main.py`, one new frontend page. All external HTTP mocked with respx in tests; profile/ranker math golden-tested on fixture DBs.

**Tech Stack:** Python 3.12, FastAPI, httpx, sqlite3, pytest + respx (existing). Frontend: Next.js App Router client components (mirror existing `app/page.tsx`).

**Spec:** `docs/superpowers/specs/2026-07-18-phase2-discovery-design.md`

## Global Constraints

- Backend cwd for all commands: `~/Projects/spotify-dj/backend`; run tests with `.venv/bin/pytest`.
- No new backend dependencies. Frontend: no new runtime deps; dev deps only in Task 11.
- Last.fm client MUST return empty results (no error, no log spam) when `LASTFM_API_KEY` is unset — the feed must work from ListenBrainz alone.
- All external fetches honor 429 `Retry-After` once, like `app/spotify.py:get_recently_played`.
- Enrichment responses cache permanently in SQLite; a (source, kind, key) is never re-fetched once marked fetched — even if the result was empty.
- Spotify↔external matching uses `normalize.norm_key` equality only; unmatched → log at INFO and skip. Never fuzzy-guess.
- MusicBrainz requires a User-Agent header (`spotify-dj/0.1 (personal use)`) and max 1 req/s — the code sleeps 1s between MusicBrainz calls.
- Timestamps stored as UTC ISO-8601 strings like the existing `plays.played_at`.
- Every network-touching function takes explicit params (token/api_key) — no globals. Pure math functions take `now: float` (epoch seconds) — never call `time.time()` inside them.
- Frontend: this Next.js version differs from training data — before writing any frontend code, read the relevant guide under `frontend/node_modules/next/dist/docs/`. Follow the patterns already in `frontend/app/page.tsx` (plain `"use client"` components, `const API = "http://127.0.0.1:8765"`).
- Commit messages: conventional commits, ending with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Schema extension

**Files:**
- Modify: `app/db.py` (append to `SCHEMA`)
- Test: `tests/test_db.py` (append)

**Interfaces:**
- Produces tables used by every later task: `artists(key PK, name, spotify_id, mbid)`, `tags(source, kind, key, tag, weight)`, `similar_edges(source, kind, from_key, to_name, to_artist, weight)`, `enrichment_fetches(source, kind, key, fetched_at)`, `candidates(track_id PK→tracks, seed, source, weight, added_at)`, `feedback(id, track_id, verdict, created_at)`.

- [ ] **Step 1: Write the failing test** (append to `tests/test_db.py`)

```python
def test_phase2_tables_exist(tmp_path):
    conn = db.connect(tmp_path / "p2.sqlite3")
    names = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {
        "artists", "tags", "similar_edges", "enrichment_fetches",
        "candidates", "feedback",
    } <= names
    conn.close()


def test_feedback_verdict_constrained(tmp_path):
    conn = db.connect(tmp_path / "p2b.sqlite3")
    import pytest, sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO feedback (track_id, verdict, created_at) "
            "VALUES ('t1', 'meh', '2026-07-18T00:00:00Z')"
        )
    conn.close()
```

(Match the existing import style at the top of `tests/test_db.py` — it already imports `db`; move `import pytest, sqlite3` to the top of the file.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_db.py -v`
Expected: both new tests FAIL (missing tables).

- [ ] **Step 3: Append to `SCHEMA` in `app/db.py`**

```sql
CREATE TABLE IF NOT EXISTS artists (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    spotify_id TEXT,
    mbid TEXT
);
CREATE TABLE IF NOT EXISTS tags (
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    tag TEXT NOT NULL,
    weight REAL NOT NULL,
    PRIMARY KEY (source, kind, key, tag)
);
CREATE TABLE IF NOT EXISTS similar_edges (
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    from_key TEXT NOT NULL,
    to_name TEXT NOT NULL,
    to_artist TEXT NOT NULL DEFAULT '',
    weight REAL NOT NULL,
    PRIMARY KEY (source, kind, from_key, to_name, to_artist)
);
CREATE TABLE IF NOT EXISTS enrichment_fetches (
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source, kind, key)
);
CREATE TABLE IF NOT EXISTS candidates (
    track_id TEXT PRIMARY KEY REFERENCES tracks(id),
    seed TEXT NOT NULL,
    source TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 0,
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK (verdict IN ('up','down','more_like_this')),
    created_at TEXT NOT NULL
);
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_db.py -v` — all PASS.

- [ ] **Step 5: Commit** — `git add app/db.py tests/test_db.py && git commit -m "feat: add phase-2 tables (artists, tags, edges, candidates, feedback)"`

---

### Task 2: Normalization module

**Files:**
- Create: `app/taste/__init__.py` (empty), `app/taste/normalize.py`
- Test: `tests/test_normalize.py`

**Interfaces:**
- Produces: `norm_name(s: str) -> str`; `norm_key(artist: str, title: str = "") -> str` (returns `"<artist>"` or `"<artist>|<title>"`, both normalized). Used everywhere a Spotify name meets an external name.

- [ ] **Step 1: Write the failing tests**

```python
from app.taste.normalize import norm_key, norm_name


def test_lowercases_and_strips_punctuation():
    assert norm_name("Don't Stop Me Now!") == "dont stop me now"


def test_strips_feat_clauses():
    assert norm_name("CRG (feat. Dave)") == "crg"
    assert norm_name("OBVIOUS [feat. Hasan Raheem]") == "obvious"
    assert norm_name("4U feat. Someone") == "4u"


def test_folds_unicode_accents():
    assert norm_name("Beyoncé") == "beyonce"


def test_collapses_whitespace():
    assert norm_name("  A   B  ") == "a b"


def test_norm_key_artist_only_and_pair():
    assert norm_key("Central Cee") == "central cee"
    assert norm_key("Central Cee", "CRG (feat. Dave)") == "central cee|crg"
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_normalize.py -v` → import error.

- [ ] **Step 3: Implement `app/taste/normalize.py`**

```python
import re
import unicodedata

_FEAT_PAREN = re.compile(r"[\(\[][^)\]]*\bfeat\.?[^)\]]*[\)\]]", re.IGNORECASE)
_FEAT_TAIL = re.compile(r"\s+-?\s*feat\.?\s+.*$", re.IGNORECASE)
_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = _FEAT_PAREN.sub("", s)
    s = _FEAT_TAIL.sub("", s)
    s = _PUNCT.sub("", s.lower())
    return _WS.sub(" ", s).strip()


def norm_key(artist: str, title: str = "") -> str:
    if title:
        return f"{norm_name(artist)}|{norm_name(title)}"
    return norm_name(artist)
```

- [ ] **Step 4: Run to verify pass** — all 5 PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: add artist/title normalization for cross-catalog matching"`

---

### Task 3: Last.fm client (dormant without key)

**Files:**
- Create: `app/enrichment/__init__.py` (empty), `app/enrichment/lastfm.py`
- Modify: `app/config.py` (add `lastfm_api_key`), `.env.example` (add `# LASTFM_API_KEY=`)
- Test: `tests/test_lastfm.py`

**Interfaces:**
- Consumes: nothing internal.
- Produces (all async; all return `[]` immediately if `api_key` is falsy):
  - `get_similar_artists(api_key: str, artist: str, limit: int = 50) -> list[dict]` → `[{"name": str, "match": float}]`
  - `get_artist_top_tags(api_key: str, artist: str) -> list[dict]` → `[{"tag": str, "weight": float}]` (Last.fm `count` scaled /100, capped 1.0)
  - `get_similar_tracks(api_key: str, artist: str, title: str, limit: int = 50) -> list[dict]` → `[{"artist": str, "name": str, "match": float}]`
  - `get_track_top_tags(api_key: str, artist: str, title: str) -> list[dict]` → same shape as artist tags
- `Settings.lastfm_api_key: str` (default `""`).

- [ ] **Step 1: Write the failing tests**

```python
import pytest
import respx
from httpx import Response

from app.enrichment import lastfm

ROOT = "https://ws.audioscrobbler.com/2.0/"


async def test_no_key_returns_empty_without_network():
    # respx not active: any request would raise; empty key short-circuits.
    assert await lastfm.get_similar_artists("", "Central Cee") == []
    assert await lastfm.get_artist_top_tags("", "Central Cee") == []
    assert await lastfm.get_similar_tracks("", "Central Cee", "CRG") == []
    assert await lastfm.get_track_top_tags("", "Central Cee", "CRG") == []


@respx.mock
async def test_similar_artists_parsed():
    respx.get(ROOT).mock(
        return_value=Response(
            200,
            json={
                "similarartists": {
                    "artist": [
                        {"name": "Dave", "match": "0.92"},
                        {"name": "Aitch", "match": "0.55"},
                    ]
                }
            },
        )
    )
    out = await lastfm.get_similar_artists("k", "Central Cee")
    assert out == [
        {"name": "Dave", "match": 0.92},
        {"name": "Aitch", "match": 0.55},
    ]


@respx.mock
async def test_artist_tags_scaled():
    respx.get(ROOT).mock(
        return_value=Response(
            200,
            json={"toptags": {"tag": [{"name": "uk rap", "count": 100},
                                      {"name": "drill", "count": 37}]}},
        )
    )
    out = await lastfm.get_artist_top_tags("k", "Central Cee")
    assert out == [{"tag": "uk rap", "weight": 1.0}, {"tag": "drill", "weight": 0.37}]


@respx.mock
async def test_429_honors_retry_after(monkeypatch):
    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(lastfm.asyncio, "sleep", fake_sleep)
    route = respx.get(ROOT)
    route.side_effect = [
        Response(429, headers={"Retry-After": "3"}),
        Response(200, json={"similarartists": {"artist": []}}),
    ]
    assert await lastfm.get_similar_artists("k", "X") == []
    assert sleeps == [3]


@respx.mock
async def test_missing_payload_key_returns_empty():
    respx.get(ROOT).mock(return_value=Response(200, json={"error": 6}))
    assert await lastfm.get_similar_tracks("k", "X", "Y") == []
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_lastfm.py -v` → import error.

- [ ] **Step 3: Implement `app/enrichment/lastfm.py`**

```python
import asyncio

import httpx

API_ROOT = "https://ws.audioscrobbler.com/2.0/"


async def _call(api_key: str, params: dict) -> dict:
    params = {**params, "api_key": api_key, "format": "json"}
    async with httpx.AsyncClient() as client:
        for attempt in range(2):
            resp = await client.get(API_ROOT, params=params)
            if resp.status_code == 429 and attempt == 0:
                await asyncio.sleep(int(resp.headers.get("Retry-After", "1")))
                continue
            resp.raise_for_status()
            return resp.json()
    raise AssertionError("unreachable")


def _tags(payload: dict) -> list[dict]:
    tags = payload.get("toptags", {}).get("tag", [])
    return [
        {"tag": t["name"].lower(), "weight": min(float(t["count"]) / 100, 1.0)}
        for t in tags
        if t.get("count")
    ]


async def get_similar_artists(api_key: str, artist: str, limit: int = 50) -> list[dict]:
    if not api_key:
        return []
    data = await _call(
        api_key,
        {"method": "artist.getSimilar", "artist": artist, "limit": limit,
         "autocorrect": 1},
    )
    return [
        {"name": a["name"], "match": float(a["match"])}
        for a in data.get("similarartists", {}).get("artist", [])
    ]


async def get_artist_top_tags(api_key: str, artist: str) -> list[dict]:
    if not api_key:
        return []
    data = await _call(
        api_key,
        {"method": "artist.getTopTags", "artist": artist, "autocorrect": 1},
    )
    return _tags(data)


async def get_similar_tracks(
    api_key: str, artist: str, title: str, limit: int = 50
) -> list[dict]:
    if not api_key:
        return []
    data = await _call(
        api_key,
        {"method": "track.getSimilar", "artist": artist, "track": title,
         "limit": limit, "autocorrect": 1},
    )
    return [
        {"artist": t["artist"]["name"], "name": t["name"], "match": float(t["match"])}
        for t in data.get("similartracks", {}).get("track", [])
    ]


async def get_track_top_tags(api_key: str, artist: str, title: str) -> list[dict]:
    if not api_key:
        return []
    data = await _call(
        api_key,
        {"method": "track.getTopTags", "artist": artist, "track": title,
         "autocorrect": 1},
    )
    return _tags(data)
```

- [ ] **Step 4: Add config + env example.** In `app/config.py` add field `lastfm_api_key: str` to `Settings` and `lastfm_api_key=os.environ.get("LASTFM_API_KEY", "")` in `get_settings()`. In `backend/.env.example` add a line `# LASTFM_API_KEY=your-lastfm-key` under the defaults comment. Append to `tests/test_config.py`:

```python
def test_lastfm_key_defaults_empty(monkeypatch):
    monkeypatch.delenv("LASTFM_API_KEY", raising=False)
    assert get_settings().lastfm_api_key == ""
```

- [ ] **Step 5: Run** — `.venv/bin/pytest tests/test_lastfm.py tests/test_config.py -v` → all PASS.
- [ ] **Step 6: Commit** — `git commit -m "feat: add Last.fm client, dormant without LASTFM_API_KEY"`

---

### Task 4: ListenBrainz/MusicBrainz client

**Files:**
- Create: `app/enrichment/listenbrainz.py`
- Test: `tests/test_listenbrainz.py`

**Interfaces:**
- Produces (async, keyless):
  - `resolve_artist_mbid(name: str) -> str | None` — MusicBrainz `/ws/2/artist?query=artist:"<name>"&fmt=json&limit=1`; returns top hit's `id` if its `score >= 90`, else `None`. Always sends `User-Agent: spotify-dj/0.1 (personal use)`; sleeps 1s before each MusicBrainz call (rate limit).
  - `get_similar_artists(mbid: str, limit: int = 50) -> list[dict]` → `[{"name": str, "match": float}]` from ListenBrainz Labs `https://labs.api.listenbrainz.org/similar-artists/json` with params `artist_mbids=<mbid>`, `algorithm=session_based_days_7500_session_300_contribution_5_threshold_10_limit_100_filter_True_skip_30`. `match` = each row's `score` divided by the max score in the response (so top hit = 1.0).
- Both honor 429 Retry-After once; non-200 after retry raises.

- [ ] **Step 1: Write the failing tests**

```python
import respx
from httpx import Response

from app.enrichment import listenbrainz as lb

MB = "https://musicbrainz.org/ws/2/artist"
LABS = "https://labs.api.listenbrainz.org/similar-artists/json"


@respx.mock
async def test_resolve_mbid_high_score(monkeypatch):
    async def no_sleep(s):
        pass
    monkeypatch.setattr(lb.asyncio, "sleep", no_sleep)
    respx.get(MB).mock(
        return_value=Response(
            200,
            json={"artists": [{"id": "abc-123", "score": 100, "name": "Dave"}]},
        )
    )
    assert await lb.resolve_artist_mbid("Dave") == "abc-123"


@respx.mock
async def test_resolve_mbid_low_score_none(monkeypatch):
    async def no_sleep(s):
        pass
    monkeypatch.setattr(lb.asyncio, "sleep", no_sleep)
    respx.get(MB).mock(
        return_value=Response(200, json={"artists": [{"id": "x", "score": 55}]})
    )
    assert await lb.resolve_artist_mbid("Obscure Name") is None


@respx.mock
async def test_similar_artists_scores_normalized():
    respx.get(LABS).mock(
        return_value=Response(
            200,
            json=[
                {"artist_name": "Dave", "score": 200},
                {"artist_name": "Aitch", "score": 50},
            ],
        )
    )
    out = await lb.get_similar_artists("abc-123")
    assert out == [
        {"name": "Dave", "match": 1.0},
        {"name": "Aitch", "match": 0.25},
    ]


@respx.mock
async def test_similar_artists_empty():
    respx.get(LABS).mock(return_value=Response(200, json=[]))
    assert await lb.get_similar_artists("abc-123") == []
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement `app/enrichment/listenbrainz.py`**

```python
import asyncio

import httpx

MB_ARTIST_URL = "https://musicbrainz.org/ws/2/artist"
LABS_SIMILAR_URL = "https://labs.api.listenbrainz.org/similar-artists/json"
USER_AGENT = "spotify-dj/0.1 (personal use)"
ALGORITHM = (
    "session_based_days_7500_session_300_contribution_5_"
    "threshold_10_limit_100_filter_True_skip_30"
)


async def _get(url: str, params: dict) -> httpx.Response:
    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient() as client:
        for attempt in range(2):
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code == 429 and attempt == 0:
                await asyncio.sleep(int(resp.headers.get("Retry-After", "1")))
                continue
            resp.raise_for_status()
            return resp
    raise AssertionError("unreachable")


async def resolve_artist_mbid(name: str) -> str | None:
    await asyncio.sleep(1)  # MusicBrainz rate limit: 1 req/s
    resp = await _get(
        MB_ARTIST_URL,
        {"query": f'artist:"{name}"', "fmt": "json", "limit": 1},
    )
    artists = resp.json().get("artists", [])
    if artists and artists[0].get("score", 0) >= 90:
        return artists[0]["id"]
    return None


async def get_similar_artists(mbid: str, limit: int = 50) -> list[dict]:
    resp = await _get(
        LABS_SIMILAR_URL, {"artist_mbids": mbid, "algorithm": ALGORITHM}
    )
    rows = resp.json()[:limit]
    if not rows:
        return []
    top = max(r["score"] for r in rows) or 1
    return [{"name": r["artist_name"], "match": r["score"] / top} for r in rows]
```

- [ ] **Step 4: Run** — all PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: add ListenBrainz similar-artists client with MusicBrainz mbid lookup"`

---

### Task 5: Enrichment cache

**Files:**
- Create: `app/enrichment/cache.py`
- Test: `tests/test_enrichment_cache.py`

**Interfaces:**
- Consumes: Task 1 tables.
- Produces (all sync, take `conn: sqlite3.Connection` first; `now_iso: str` where noted):
  - `was_fetched(conn, source: str, kind: str, key: str) -> bool`
  - `mark_fetched(conn, source, kind, key, now_iso: str) -> None`
  - `store_tags(conn, source, kind, key, tags: list[dict]) -> None` (tags as Task 3 shape; upsert)
  - `get_tags(conn, kind, key) -> dict[str, float]` (merged across sources; max weight wins)
  - `store_edges(conn, source, kind, from_key, edges: list[dict]) -> None` — artist edges `{"name", "match"}` stored with `to_artist=''`; track edges `{"artist", "name", "match"}` store `to_artist`
  - `get_edges(conn, kind, from_key) -> list[dict]` → `[{"source", "to_name", "to_artist", "weight"}]` ordered by weight desc
- All writes commit.

- [ ] **Step 1: Write the failing tests** (uses existing `conn` fixture from `tests/conftest.py`)

```python
from app.enrichment import cache

NOW = "2026-07-18T12:00:00Z"


def test_fetched_roundtrip(conn):
    assert not cache.was_fetched(conn, "lastfm", "artist", "dave")
    cache.mark_fetched(conn, "lastfm", "artist", "dave", NOW)
    assert cache.was_fetched(conn, "lastfm", "artist", "dave")


def test_tags_merge_max_across_sources(conn):
    cache.store_tags(conn, "lastfm", "artist", "dave",
                     [{"tag": "uk rap", "weight": 0.9}])
    cache.store_tags(conn, "listenbrainz", "artist", "dave",
                     [{"tag": "uk rap", "weight": 0.4},
                      {"tag": "grime", "weight": 0.6}])
    assert cache.get_tags(conn, "artist", "dave") == {"uk rap": 0.9, "grime": 0.6}


def test_edges_roundtrip_ordered(conn):
    cache.store_edges(conn, "lastfm", "artist", "central cee",
                      [{"name": "Aitch", "match": 0.5},
                       {"name": "Dave", "match": 0.9}])
    cache.store_edges(conn, "lastfm", "track", "central cee|crg",
                      [{"artist": "Dave", "name": "Sprinter", "match": 0.8}])
    artist_edges = cache.get_edges(conn, "artist", "central cee")
    assert [e["to_name"] for e in artist_edges] == ["Dave", "Aitch"]
    assert artist_edges[0]["to_artist"] == ""
    track_edges = cache.get_edges(conn, "track", "central cee|crg")
    assert track_edges[0] == {
        "source": "lastfm", "to_name": "Sprinter",
        "to_artist": "Dave", "weight": 0.8,
    }


def test_store_edges_idempotent(conn):
    edges = [{"name": "Dave", "match": 0.9}]
    cache.store_edges(conn, "lastfm", "artist", "x", edges)
    cache.store_edges(conn, "lastfm", "artist", "x", edges)
    assert len(cache.get_edges(conn, "artist", "x")) == 1
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement `app/enrichment/cache.py`**

```python
import sqlite3


def was_fetched(conn: sqlite3.Connection, source: str, kind: str, key: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM enrichment_fetches WHERE source=? AND kind=? AND key=?",
        (source, kind, key),
    ).fetchone()
    return row is not None


def mark_fetched(
    conn: sqlite3.Connection, source: str, kind: str, key: str, now_iso: str
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO enrichment_fetches (source, kind, key, fetched_at) "
        "VALUES (?, ?, ?, ?)",
        (source, kind, key, now_iso),
    )
    conn.commit()


def store_tags(
    conn: sqlite3.Connection, source: str, kind: str, key: str, tags: list[dict]
) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO tags (source, kind, key, tag, weight) "
        "VALUES (?, ?, ?, ?, ?)",
        [(source, kind, key, t["tag"], t["weight"]) for t in tags],
    )
    conn.commit()


def get_tags(conn: sqlite3.Connection, kind: str, key: str) -> dict[str, float]:
    rows = conn.execute(
        "SELECT tag, MAX(weight) AS weight FROM tags "
        "WHERE kind=? AND key=? GROUP BY tag",
        (kind, key),
    )
    return {r["tag"]: r["weight"] for r in rows}


def store_edges(
    conn: sqlite3.Connection, source: str, kind: str, from_key: str,
    edges: list[dict],
) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO similar_edges "
        "(source, kind, from_key, to_name, to_artist, weight) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (source, kind, from_key, e["name"], e.get("artist", ""), e["match"])
            for e in edges
        ],
    )
    conn.commit()


def get_edges(conn: sqlite3.Connection, kind: str, from_key: str) -> list[dict]:
    rows = conn.execute(
        "SELECT source, to_name, to_artist, weight FROM similar_edges "
        "WHERE kind=? AND from_key=? ORDER BY weight DESC",
        (kind, from_key),
    )
    return [dict(r) for r in rows]
```

- [ ] **Step 4: Run** — all PASS. **Step 5: Commit** — `git commit -m "feat: add SQLite enrichment cache (tags, edges, fetch markers)"`

---

### Task 6: Spotify client additions

**Files:**
- Modify: `app/spotify.py`
- Test: `tests/test_spotify.py` (append)

**Interfaces:**
- Produces (async, first param `access_token: str`):
  - `get_top_artists(access_token, limit=20, time_range="long_term") -> dict` (raw Spotify payload, `items` list)
  - `get_top_tracks(access_token, limit=20, time_range="long_term") -> dict`
  - `get_saved_tracks(access_token, limit=50, offset=0) -> dict` (GET `/me/tracks`; if Spotify has retired it at runtime, switching the path constant to the consolidated `/me/library` endpoint is the only change needed)
  - `search_track(access_token, artist: str, title: str) -> list[dict]` — GET `/search` with `q=artist:"<artist>" track:"<title>"`, `type=track`, `limit=5`; returns `tracks.items` (possibly empty). Caller does norm-matching.
  - `create_playlist(access_token, name: str, description: str = "") -> dict` — POST `/me/playlists` with `{"name": ..., "public": false, "description": ...}`
  - `add_playlist_items(access_token, playlist_id: str, uris: list[str]) -> None` — POST `/playlists/{id}/items` with `{"uris": [...]}`
  - `queue_track(access_token, uri: str) -> None` — POST `/me/player/queue?uri=...`

Refactor first: extract the 429-retry request loop in `get_recently_played` into a shared helper `_request(method, path, access_token, *, params=None, json=None) -> httpx.Response` and reimplement `get_recently_played` on top of it (existing tests must stay green).

- [ ] **Step 1: Refactor `_request` helper, keep existing tests green**

```python
async def _request(
    method: str,
    path: str,
    access_token: str,
    *,
    params: dict | None = None,
    json: dict | None = None,
) -> httpx.Response:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient() as client:
        for attempt in range(2):
            resp = await client.request(
                method, f"{API_BASE}{path}", params=params, json=json,
                headers=headers,
            )
            if resp.status_code == 429 and attempt == 0:
                await asyncio.sleep(int(resp.headers.get("Retry-After", "1")))
                continue
            resp.raise_for_status()
            return resp
    raise AssertionError("unreachable")
```

Rewrite `get_recently_played` body as:

```python
    params: dict = {"limit": limit}
    if after_ms is not None:
        params["after"] = after_ms
    resp = await _request("GET", "/me/player/recently-played",
                          access_token, params=params)
    return resp.json()
```

Run: `.venv/bin/pytest tests/test_spotify.py -v` → existing tests PASS. Commit: `git commit -m "refactor: extract shared Spotify request helper with 429 retry"`

- [ ] **Step 2: Write failing tests for the new functions** (append to `tests/test_spotify.py`; follow the file's existing respx style)

```python
@respx.mock
async def test_search_track_builds_field_query():
    route = respx.get("https://api.spotify.com/v1/search").mock(
        return_value=Response(200, json={"tracks": {"items": [{"id": "t1"}]}})
    )
    items = await spotify.search_track("tok", "Dave", "Sprinter")
    assert items == [{"id": "t1"}]
    q = route.calls[0].request.url.params["q"]
    assert q == 'artist:"Dave" track:"Sprinter"'


@respx.mock
async def test_top_artists_and_tracks_params():
    respx.get("https://api.spotify.com/v1/me/top/artists").mock(
        return_value=Response(200, json={"items": [{"name": "Atif Aslam"}]})
    )
    respx.get("https://api.spotify.com/v1/me/top/tracks").mock(
        return_value=Response(200, json={"items": []})
    )
    a = await spotify.get_top_artists("tok")
    t = await spotify.get_top_tracks("tok")
    assert a["items"][0]["name"] == "Atif Aslam"
    assert t["items"] == []


@respx.mock
async def test_saved_tracks():
    respx.get("https://api.spotify.com/v1/me/tracks").mock(
        return_value=Response(200, json={"items": [], "total": 0})
    )
    assert (await spotify.get_saved_tracks("tok"))["total"] == 0


@respx.mock
async def test_create_playlist_and_add_items():
    respx.post("https://api.spotify.com/v1/me/playlists").mock(
        return_value=Response(201, json={"id": "pl1",
                                         "external_urls": {"spotify": "u"}})
    )
    add = respx.post("https://api.spotify.com/v1/playlists/pl1/items").mock(
        return_value=Response(201, json={"snapshot_id": "s"})
    )
    pl = await spotify.create_playlist("tok", "DJ picks")
    await spotify.add_playlist_items("tok", pl["id"], ["spotify:track:t1"])
    assert add.called


@respx.mock
async def test_queue_track():
    route = respx.post("https://api.spotify.com/v1/me/player/queue").mock(
        return_value=Response(204)
    )
    await spotify.queue_track("tok", "spotify:track:t1")
    assert route.calls[0].request.url.params["uri"] == "spotify:track:t1"
```

- [ ] **Step 3: Run to verify failure**, then implement in `app/spotify.py`:

```python
async def get_top_artists(
    access_token: str, limit: int = 20, time_range: str = "long_term"
) -> dict:
    resp = await _request(
        "GET", "/me/top/artists", access_token,
        params={"limit": limit, "time_range": time_range},
    )
    return resp.json()


async def get_top_tracks(
    access_token: str, limit: int = 20, time_range: str = "long_term"
) -> dict:
    resp = await _request(
        "GET", "/me/top/tracks", access_token,
        params={"limit": limit, "time_range": time_range},
    )
    return resp.json()


async def get_saved_tracks(
    access_token: str, limit: int = 50, offset: int = 0
) -> dict:
    resp = await _request(
        "GET", "/me/tracks", access_token,
        params={"limit": limit, "offset": offset},
    )
    return resp.json()


async def search_track(access_token: str, artist: str, title: str) -> list[dict]:
    q = f'artist:"{artist}" track:"{title}"'
    resp = await _request(
        "GET", "/search", access_token,
        params={"q": q, "type": "track", "limit": 5},
    )
    return resp.json().get("tracks", {}).get("items", [])


async def create_playlist(
    access_token: str, name: str, description: str = ""
) -> dict:
    resp = await _request(
        "POST", "/me/playlists", access_token,
        json={"name": name, "public": False, "description": description},
    )
    return resp.json()


async def add_playlist_items(
    access_token: str, playlist_id: str, uris: list[str]
) -> None:
    await _request(
        "POST", f"/playlists/{playlist_id}/items", access_token,
        json={"uris": uris},
    )


async def queue_track(access_token: str, uri: str) -> None:
    await _request("POST", "/me/player/queue", access_token, params={"uri": uri})
```

- [ ] **Step 4: Run** — `.venv/bin/pytest tests/test_spotify.py -v` all PASS.
- [ ] **Step 5: Commit** — `git commit -m "feat: add Spotify search, top items, saved tracks, playlist, queue calls"`

---

### Task 7: Taste profile (golden-tested)

**Files:**
- Create: `app/taste/profile.py`
- Test: `tests/test_profile.py`

**Interfaces:**
- Consumes: `plays`, `tracks`, `feedback` tables; `cache.get_tags` (Task 5); `normalize.norm_key` (Task 2).
- Produces:
  - `@dataclass(frozen=True) Profile: artist_weights: dict[str, float]; tag_weights: dict[str, float]` (keys are normalized artist names / lowercase tags)
  - `build_profile(conn, now: float, top_artists: list[str] = (), saved_artists: list[str] = ()) -> Profile`
- Weight formula (golden-pinned; `HALF_LIFE_DAYS = 30.0`):
  - each play of artist A at age `d` days: `+ 0.5 ** (d / 30)`
  - each entry in `saved_artists` (one per saved track): `+ 0.5`
  - `top_artists` list order r (0-based, length n): `+ 3.0 * (1 - r / n)`
  - feedback on a track (joined to `tracks` for its artist): `up` `+2.0`, `more_like_this` `+3.0`, `down` `-2.0`
  - tag_weights: for each artist key with weight `w > 0`, for each cached artist tag `(tag, tw)`: `tag_weights[tag] += w * tw`; then divide all by the max so top tag = 1.0 (empty dict if no tags).

- [ ] **Step 1: Write the failing golden tests**

```python
import datetime as dt

import pytest

from app.enrichment import cache
from app.taste.profile import Profile, build_profile

NOW = dt.datetime(2026, 7, 18, tzinfo=dt.timezone.utc).timestamp()


def iso(days_ago: float) -> str:
    d = dt.datetime.fromtimestamp(NOW, dt.timezone.utc) - dt.timedelta(days=days_ago)
    return d.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def seed(conn):
    conn.execute(
        "INSERT INTO tracks VALUES ('t1','CRG','a1','Central Cee','alb',180000)"
    )
    conn.execute(
        "INSERT INTO tracks VALUES ('t2','Meri Kahani','a2','Atif Aslam','alb',200000)"
    )
    conn.execute("INSERT INTO plays VALUES (?, 't1')", (iso(0),))
    conn.execute("INSERT INTO plays VALUES (?, 't1')", (iso(30),))
    conn.execute("INSERT INTO plays VALUES (?, 't2')", (iso(60),))
    conn.commit()


def test_play_weights_decay(conn):
    seed(conn)
    p = build_profile(conn, NOW)
    # central cee: 0.5**0 + 0.5**1 = 1.5 ; atif aslam: 0.5**2 = 0.25
    assert p.artist_weights["central cee"] == pytest.approx(1.5)
    assert p.artist_weights["atif aslam"] == pytest.approx(0.25)


def test_saved_and_top_bootstrap(conn):
    seed(conn)
    p = build_profile(
        conn, NOW,
        top_artists=["Atif Aslam", "Talha Anjum"],
        saved_artists=["Central Cee", "Central Cee"],
    )
    # atif: 0.25 + 3.0*(1-0/2)=3.25 ; talha: 3.0*(1-1/2)=1.5 ; cee: 1.5+2*0.5=2.5
    assert p.artist_weights["atif aslam"] == pytest.approx(3.25)
    assert p.artist_weights["talha anjum"] == pytest.approx(1.5)
    assert p.artist_weights["central cee"] == pytest.approx(2.5)


def test_feedback_adjusts(conn):
    seed(conn)
    conn.execute(
        "INSERT INTO feedback (track_id, verdict, created_at) "
        "VALUES ('t2','down',?)", (iso(1),)
    )
    conn.commit()
    p = build_profile(conn, NOW)
    assert p.artist_weights["atif aslam"] == pytest.approx(0.25 - 2.0)


def test_tag_vector_normalized(conn):
    seed(conn)
    cache.store_tags(conn, "lastfm", "artist", "central cee",
                     [{"tag": "uk rap", "weight": 1.0}])
    cache.store_tags(conn, "lastfm", "artist", "atif aslam",
                     [{"tag": "pop", "weight": 0.5}])
    p = build_profile(conn, NOW)
    # uk rap: 1.5*1.0=1.5 ; pop: 0.25*0.5=0.125 → /1.5
    assert p.tag_weights["uk rap"] == pytest.approx(1.0)
    assert p.tag_weights["pop"] == pytest.approx(0.125 / 1.5)


def test_empty_db_empty_profile(conn):
    p = build_profile(conn, NOW)
    assert p == Profile(artist_weights={}, tag_weights={})
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement `app/taste/profile.py`**

```python
import datetime as dt
import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from ..enrichment import cache
from .normalize import norm_key

HALF_LIFE_DAYS = 30.0
SAVED_WEIGHT = 0.5
TOP_ARTIST_WEIGHT = 3.0
FEEDBACK_WEIGHTS = {"up": 2.0, "more_like_this": 3.0, "down": -2.0}


@dataclass(frozen=True)
class Profile:
    artist_weights: dict[str, float]
    tag_weights: dict[str, float]


def _age_days(played_at: str, now: float) -> float:
    t = dt.datetime.fromisoformat(played_at.replace("Z", "+00:00"))
    return max((now - t.timestamp()) / 86400, 0.0)


def build_profile(
    conn: sqlite3.Connection,
    now: float,
    top_artists: list[str] = (),
    saved_artists: list[str] = (),
) -> Profile:
    weights: dict[str, float] = defaultdict(float)

    rows = conn.execute(
        "SELECT p.played_at, t.artist_name FROM plays p "
        "JOIN tracks t ON t.id = p.track_id"
    )
    for r in rows:
        weights[norm_key(r["artist_name"])] += 0.5 ** (
            _age_days(r["played_at"], now) / HALF_LIFE_DAYS
        )

    for name in saved_artists:
        weights[norm_key(name)] += SAVED_WEIGHT

    n = len(top_artists)
    for rank, name in enumerate(top_artists):
        weights[norm_key(name)] += TOP_ARTIST_WEIGHT * (1 - rank / n)

    rows = conn.execute(
        "SELECT f.verdict, t.artist_name FROM feedback f "
        "JOIN tracks t ON t.id = f.track_id"
    )
    for r in rows:
        weights[norm_key(r["artist_name"])] += FEEDBACK_WEIGHTS[r["verdict"]]

    tag_weights: dict[str, float] = defaultdict(float)
    for key, w in weights.items():
        if w <= 0:
            continue
        for tag, tw in cache.get_tags(conn, "artist", key).items():
            tag_weights[tag] += w * tw
    if tag_weights:
        top = max(tag_weights.values())
        tag_weights = {t: v / top for t, v in tag_weights.items()}

    return Profile(artist_weights=dict(weights), tag_weights=dict(tag_weights))
```

- [ ] **Step 4: Run** — all PASS. **Step 5: Commit** — `git commit -m "feat: add taste profile with recency decay, bootstrap, feedback (golden-tested)"`

---

### Task 8: Candidate refresh orchestrator

**Files:**
- Create: `app/taste/candidates.py`
- Test: `tests/test_candidates.py`

**Interfaces:**
- Consumes: everything from Tasks 2-7. Signatures used: `lastfm.get_similar_artists/get_artist_top_tags/get_similar_tracks`, `listenbrainz.resolve_artist_mbid/get_similar_artists`, `cache.*`, `spotify.search_track/get_top_artists/get_top_tracks/get_saved_tracks`, `profile.build_profile`, `normalize.norm_key/norm_name`.
- Produces: `async def refresh_candidates(conn, settings, access_token: str, now: float, max_artist_seeds: int = 8, max_track_seeds: int = 8, per_seed: int = 10) -> int` (returns number of new candidates inserted). Also helper `known_keys(conn) -> set[str]` (norm_key(artist,title) of every row in `tracks` that appears in `plays` or `candidates`).

Flow of `refresh_candidates` (each numbered item is testable behavior):
1. Fetch bootstrap: `get_top_artists` (names), `get_top_tracks` (artist+title pairs), first page of `get_saved_tracks` (artist names). Any `httpx.HTTPStatusError` here → treat as empty (log INFO).
2. `profile = build_profile(conn, now, top_artists=..., saved_artists=...)`.
3. Artist seeds = top `max_artist_seeds` profile artists by weight; track seeds = up to `max_track_seeds` from (tracks with `more_like_this` feedback, joined to `tracks` for artist+title, first) + (Spotify top tracks).
4. Per artist seed not `was_fetched(source, 'artist', key)`: Last.fm similar+tags → `store_edges`/`store_tags`/`mark_fetched('lastfm', ...)`; ListenBrainz mbid→similar → `store_edges`/`mark_fetched('listenbrainz', ...)` (mbid=None still marks fetched). Per track seed not fetched: Last.fm `get_similar_tracks` → track edges.
5. Collect candidate (artist, title) pairs: from track edges directly; from artist edges take the edge artist with `title=''` → resolve via `search_track(token, artist, artist_top_track_query)`: for artist-only candidates call `spotify.search_track(access_token, artist, "")` is NOT valid — instead search with `q=artist:"<name>"` via `search_track(access_token, artist, "")` returning that artist's most relevant track. Implement this as: `search_track` already accepts empty title; when `title == ""` build `q = f'artist:"{artist}"'` (adjust Task 6 function: `q = f'artist:"{artist}" track:"{title}"' if title else f'artist:"{artist}"'` — add this in this task with a test appended to `tests/test_spotify.py`).
6. For each candidate pair, skip if `norm_key(artist, title)` (or artist-only key for artist edges resolved later) already in `known_keys(conn)` or artist weight source seed suppressed; else `search_track`, take the first item whose `norm_key(item_artist, item_name)` matches (for track edges) or whose `norm_name(item_artist)` matches the edge artist (for artist edges); unmatched → `logger.info` and skip.
7. Matched: upsert into `tracks` (same columns as `ingest.store_items`) and `INSERT OR IGNORE INTO candidates (track_id, seed, source, weight, added_at)` with `seed = 'artist:<seed key>'` or `'track:<seed key>'`, `weight` = edge match, `added_at` = ISO from `now`.

- [ ] **Step 1: Write the failing tests** (respx-mock all three services; this is the biggest test file — test the orchestration seams, not every permutation)

```python
import datetime as dt

import respx
from httpx import Response

from app.config import Settings
from app.enrichment import cache
from app.taste import candidates

NOW = dt.datetime(2026, 7, 18, tzinfo=dt.timezone.utc).timestamp()
SETTINGS = Settings(
    spotify_client_id="cid", redirect_uri="r", db_path=":memory:",
    frontend_origin="f", lastfm_api_key="lfm-key",
)
SPOTIFY = "https://api.spotify.com/v1"


def seed_history(conn):
    conn.execute(
        "INSERT INTO tracks VALUES ('t1','CRG','a1','Central Cee','alb',180000)"
    )
    conn.execute(
        "INSERT INTO plays VALUES ('2026-07-18T08:07:42.741Z','t1')"
    )
    conn.commit()


def mock_spotify_bootstrap():
    respx.get(f"{SPOTIFY}/me/top/artists").mock(
        return_value=Response(200, json={"items": [{"name": "Central Cee"}]})
    )
    respx.get(f"{SPOTIFY}/me/top/tracks").mock(
        return_value=Response(200, json={"items": []})
    )
    respx.get(f"{SPOTIFY}/me/tracks").mock(
        return_value=Response(200, json={"items": []})
    )


@respx.mock
async def test_refresh_inserts_matched_candidate(conn, monkeypatch):
    async def no_sleep(s):
        pass
    import asyncio as aio
    monkeypatch.setattr(aio, "sleep", no_sleep)
    seed_history(conn)
    mock_spotify_bootstrap()
    respx.get("https://ws.audioscrobbler.com/2.0/").mock(
        side_effect=lambda req: Response(
            200,
            json={"similarartists": {"artist": [{"name": "Dave", "match": "0.9"}]}}
            if req.url.params["method"] == "artist.getSimilar"
            else {"toptags": {"tag": [{"name": "uk rap", "count": 100}]}},
        )
    )
    respx.get("https://musicbrainz.org/ws/2/artist").mock(
        return_value=Response(200, json={"artists": []})
    )
    respx.get(f"{SPOTIFY}/search").mock(
        return_value=Response(200, json={"tracks": {"items": [{
            "id": "t9", "name": "Sprinter", "duration_ms": 200000,
            "album": {"name": "Alb"},
            "artists": [{"id": "a9", "name": "Dave"}],
        }]}})
    )
    n = await candidates.refresh_candidates(conn, SETTINGS, "tok", NOW)
    assert n == 1
    row = conn.execute("SELECT * FROM candidates").fetchone()
    assert row["track_id"] == "t9"
    assert row["seed"] == "artist:central cee"
    assert row["source"] == "lastfm"
    assert cache.was_fetched(conn, "lastfm", "artist", "central cee")


@respx.mock
async def test_refresh_skips_known_and_unmatched(conn, monkeypatch):
    async def no_sleep(s):
        pass
    import asyncio as aio
    monkeypatch.setattr(aio, "sleep", no_sleep)
    seed_history(conn)
    mock_spotify_bootstrap()
    # Similar artist is Central Cee himself (known) plus one that search
    # resolves to a non-matching artist name.
    respx.get("https://ws.audioscrobbler.com/2.0/").mock(
        side_effect=lambda req: Response(
            200,
            json={"similarartists": {"artist": [
                {"name": "Central Cee", "match": "0.99"},
                {"name": "Aitch", "match": "0.5"},
            ]}}
            if req.url.params["method"] == "artist.getSimilar"
            else {"toptags": {"tag": []}},
        )
    )
    respx.get("https://musicbrainz.org/ws/2/artist").mock(
        return_value=Response(200, json={"artists": []})
    )
    respx.get(f"{SPOTIFY}/search").mock(
        return_value=Response(200, json={"tracks": {"items": [{
            "id": "tX", "name": "Song", "duration_ms": 1,
            "album": {"name": "A"},
            "artists": [{"id": "aX", "name": "Totally Different"}],
        }]}})
    )
    n = await candidates.refresh_candidates(conn, SETTINGS, "tok", NOW)
    assert n == 0
    assert conn.execute("SELECT COUNT(*) c FROM candidates").fetchone()["c"] == 0


@respx.mock
async def test_second_refresh_uses_cache(conn, monkeypatch):
    async def no_sleep(s):
        pass
    import asyncio as aio
    monkeypatch.setattr(aio, "sleep", no_sleep)
    seed_history(conn)
    mock_spotify_bootstrap()
    lastfm_route = respx.get("https://ws.audioscrobbler.com/2.0/").mock(
        side_effect=lambda req: Response(
            200,
            json={"similarartists": {"artist": []}}
            if req.url.params["method"] == "artist.getSimilar"
            else {"toptags": {"tag": []}},
        )
    )
    respx.get("https://musicbrainz.org/ws/2/artist").mock(
        return_value=Response(200, json={"artists": []})
    )
    await candidates.refresh_candidates(conn, SETTINGS, "tok", NOW)
    calls_first = lastfm_route.call_count
    await candidates.refresh_candidates(conn, SETTINGS, "tok", NOW)
    assert lastfm_route.call_count == calls_first  # nothing re-fetched
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Adjust `search_track` for empty title** (test-first, append to `tests/test_spotify.py`):

```python
@respx.mock
async def test_search_track_artist_only_query():
    route = respx.get("https://api.spotify.com/v1/search").mock(
        return_value=Response(200, json={"tracks": {"items": []}})
    )
    await spotify.search_track("tok", "Dave", "")
    assert route.calls[0].request.url.params["q"] == 'artist:"Dave"'
```

Change the `q` line in `spotify.search_track` to:

```python
    q = f'artist:"{artist}" track:"{title}"' if title else f'artist:"{artist}"'
```

- [ ] **Step 4: Implement `app/taste/candidates.py`**

```python
import datetime as dt
import logging
import sqlite3

import httpx

from .. import spotify
from ..config import Settings
from ..enrichment import cache, lastfm, listenbrainz
from .normalize import norm_key, norm_name
from .profile import build_profile

logger = logging.getLogger(__name__)


def known_keys(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT t.artist_name, t.name FROM tracks t "
        "LEFT JOIN plays p ON p.track_id = t.id "
        "LEFT JOIN candidates c ON c.track_id = t.id "
        "WHERE p.track_id IS NOT NULL OR c.track_id IS NOT NULL"
    )
    out = set()
    for r in rows:
        out.add(norm_key(r["artist_name"], r["name"]))
        out.add(norm_key(r["artist_name"]))
    return out


def _upsert_track(conn: sqlite3.Connection, item: dict) -> None:
    artist = item["artists"][0]
    conn.execute(
        "INSERT OR REPLACE INTO tracks "
        "(id, name, artist_id, artist_name, album_name, duration_ms) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (item["id"], item["name"], artist["id"], artist["name"],
         item.get("album", {}).get("name"), item.get("duration_ms")),
    )


async def _bootstrap(access_token: str) -> tuple[list[str], list[dict], list[str]]:
    try:
        top_a = await spotify.get_top_artists(access_token)
        top_t = await spotify.get_top_tracks(access_token)
        saved = await spotify.get_saved_tracks(access_token)
    except httpx.HTTPStatusError:
        logger.info("spotify bootstrap unavailable; using local history only")
        return [], [], []
    return (
        [a["name"] for a in top_a.get("items", [])],
        [
            {"artist": t["artists"][0]["name"], "title": t["name"]}
            for t in top_t.get("items", [])
            if t.get("artists")
        ],
        [
            s["track"]["artists"][0]["name"]
            for s in saved.get("items", [])
            if s.get("track", {}).get("artists")
        ],
    )


async def _enrich_artist_seed(conn, api_key: str, key: str, name: str, now_iso: str):
    if not cache.was_fetched(conn, "lastfm", "artist", key):
        cache.store_edges(conn, "lastfm", "artist", key,
                          await lastfm.get_similar_artists(api_key, name))
        cache.store_tags(conn, "lastfm", "artist", key,
                         await lastfm.get_artist_top_tags(api_key, name))
        cache.mark_fetched(conn, "lastfm", "artist", key, now_iso)
    if not cache.was_fetched(conn, "listenbrainz", "artist", key):
        mbid = await listenbrainz.resolve_artist_mbid(name)
        if mbid:
            cache.store_edges(conn, "listenbrainz", "artist", key,
                              await listenbrainz.get_similar_artists(mbid))
        conn.execute(
            "INSERT OR REPLACE INTO artists (key, name, mbid) VALUES (?, ?, ?)",
            (key, name, mbid or ""),
        )
        cache.mark_fetched(conn, "listenbrainz", "artist", key, now_iso)


async def _resolve_and_insert(
    conn, access_token: str, artist: str, title: str,
    seed: str, source: str, weight: float, now_iso: str,
) -> bool:
    items = await spotify.search_track(access_token, artist, title)
    for item in items:
        if not item.get("artists"):
            continue
        got_artist = norm_name(item["artists"][0]["name"])
        if title:
            ok = norm_key(item["artists"][0]["name"], item["name"]) == norm_key(
                artist, title
            )
        else:
            ok = got_artist == norm_name(artist)
        if ok:
            _upsert_track(conn, item)
            cur = conn.execute(
                "INSERT OR IGNORE INTO candidates "
                "(track_id, seed, source, weight, added_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (item["id"], seed, source, weight, now_iso),
            )
            conn.commit()
            return cur.rowcount > 0
    logger.info("no spotify match for %s — %s; skipping", artist, title)
    return False


async def refresh_candidates(
    conn: sqlite3.Connection,
    settings: Settings,
    access_token: str,
    now: float,
    max_artist_seeds: int = 8,
    max_track_seeds: int = 8,
    per_seed: int = 10,
) -> int:
    now_iso = dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )
    top_artists, top_tracks, saved_artists = await _bootstrap(access_token)
    profile = build_profile(
        conn, now, top_artists=top_artists, saved_artists=saved_artists
    )

    # "more like this" feedback promotes that exact track to a seed (spec).
    mlt_rows = conn.execute(
        "SELECT DISTINCT t.artist_name, t.name FROM feedback f "
        "JOIN tracks t ON t.id = f.track_id "
        "WHERE f.verdict = 'more_like_this'"
    )
    top_tracks = [
        {"artist": r["artist_name"], "title": r["name"]} for r in mlt_rows
    ] + top_tracks

    display = {}  # norm key -> display name, for API calls
    rows = conn.execute("SELECT DISTINCT artist_name FROM tracks")
    for r in rows:
        display[norm_key(r["artist_name"])] = r["artist_name"]
    for name in top_artists + saved_artists:
        display.setdefault(norm_key(name), name)

    artist_seeds = sorted(
        profile.artist_weights.items(), key=lambda kv: -kv[1]
    )[:max_artist_seeds]

    for key, _w in artist_seeds:
        name = display.get(key)
        if name is None:
            continue
        await _enrich_artist_seed(conn, settings.lastfm_api_key, key, name, now_iso)

    for t in top_tracks[:max_track_seeds]:
        tkey = norm_key(t["artist"], t["title"])
        if not cache.was_fetched(conn, "lastfm", "track", tkey):
            cache.store_edges(
                conn, "lastfm", "track", tkey,
                await lastfm.get_similar_tracks(
                    settings.lastfm_api_key, t["artist"], t["title"]
                ),
            )
            cache.mark_fetched(conn, "lastfm", "track", tkey, now_iso)

    known = known_keys(conn)
    inserted = 0

    for key, _w in artist_seeds:
        for e in cache.get_edges(conn, "artist", key)[:per_seed]:
            if norm_key(e["to_name"]) in known:
                continue
            if await _resolve_and_insert(
                conn, access_token, e["to_name"], "",
                f"artist:{key}", e["source"], e["weight"], now_iso,
            ):
                known.add(norm_key(e["to_name"]))
                inserted += 1

    for t in top_tracks[:max_track_seeds]:
        tkey = norm_key(t["artist"], t["title"])
        for e in cache.get_edges(conn, "track", tkey)[:per_seed]:
            if norm_key(e["to_artist"], e["to_name"]) in known:
                continue
            if await _resolve_and_insert(
                conn, access_token, e["to_artist"], e["to_name"],
                f"track:{tkey}", e["source"], e["weight"], now_iso,
            ):
                known.add(norm_key(e["to_artist"], e["to_name"]))
                inserted += 1

    return inserted
```

- [ ] **Step 5: Run** — `.venv/bin/pytest tests/test_candidates.py tests/test_spotify.py -v` all PASS.
- [ ] **Step 6: Commit** — `git commit -m "feat: add candidate refresh orchestrator (seeds → edges → spotify resolution)"`

---

### Task 9: Heuristic ranker (golden-tested)

**Files:**
- Create: `app/taste/ranker.py`
- Test: `tests/test_ranker.py`

**Interfaces:**
- Consumes: `candidates`+`tracks`+`feedback` tables, `cache.get_tags`, `Profile`.
- Produces: `rank(conn, profile: Profile, now: float, limit: int = 50) -> list[dict]`, each dict:
  `{"track_id", "name", "artist", "score": float, "why": list[str], "seed", "source"}`, sorted by score desc.
- Score formula (golden-pinned):
  - `tag_overlap = sum(profile.tag_weights.get(tag, 0) * w for tag, w in candidate_artist_tags)` capped at 1.0
  - `proximity = candidates.weight` (already 0..1)
  - `novelty = 1.0` if candidate's artist key not in `profile.artist_weights` else `max(0.0, 1 - profile.artist_weights[key] / 5)`
  - `skip_penalty = 2.0` if the candidate's artist has any `down` feedback within the last 14 days of `now`, else `0`
  - `score = 2.0 * tag_overlap + 1.5 * proximity + 1.0 * novelty - skip_penalty`
- `why`: contributions sorted desc, rendered as (include a component only if > 0; penalty always included when applied):
  - tag_overlap → `"tags you love: <top 3 overlapping tags comma-joined>"`
  - proximity → `"similar to <seed without 'artist:'/'track:' prefix>"`
  - novelty → `"new artist for you"`
  - penalty → `"recently disliked this artist"`

- [ ] **Step 1: Write the failing golden tests**

```python
import datetime as dt

import pytest

from app.enrichment import cache
from app.taste.profile import Profile
from app.taste.ranker import rank

NOW = dt.datetime(2026, 7, 18, tzinfo=dt.timezone.utc).timestamp()


def seed(conn):
    conn.execute(
        "INSERT INTO tracks VALUES ('c1','Sprinter','a9','Dave','alb',200000)"
    )
    conn.execute(
        "INSERT INTO candidates VALUES "
        "('c1','artist:central cee','lastfm',0.9,'2026-07-18T00:00:00.000Z')"
    )
    conn.commit()


def test_scores_and_why(conn):
    seed(conn)
    cache.store_tags(conn, "lastfm", "artist", "dave",
                     [{"tag": "uk rap", "weight": 1.0}])
    profile = Profile(artist_weights={"central cee": 3.0},
                      tag_weights={"uk rap": 1.0})
    out = rank(conn, profile, NOW)
    assert len(out) == 1
    r = out[0]
    # tag_overlap=1.0 cap, proximity=0.9, novelty=1.0 (dave unknown), no penalty
    assert r["score"] == pytest.approx(2.0 * 1.0 + 1.5 * 0.9 + 1.0)
    assert r["why"][0] == "tags you love: uk rap"
    assert "similar to central cee" in r["why"]
    assert "new artist for you" in r["why"]


def test_known_artist_novelty_shrinks(conn):
    seed(conn)
    profile = Profile(artist_weights={"dave": 2.5}, tag_weights={})
    r = rank(conn, profile, NOW)[0]
    # novelty = 1 - 2.5/5 = 0.5 ; no tags → overlap 0
    assert r["score"] == pytest.approx(1.5 * 0.9 + 0.5)


def test_recent_down_feedback_penalizes(conn):
    seed(conn)
    conn.execute(
        "INSERT INTO feedback (track_id, verdict, created_at) "
        "VALUES ('c1','down','2026-07-17T00:00:00.000Z')"
    )
    conn.commit()
    profile = Profile(artist_weights={}, tag_weights={})
    r = rank(conn, profile, NOW)[0]
    assert r["score"] == pytest.approx(1.5 * 0.9 + 1.0 - 2.0)
    assert "recently disliked this artist" in r["why"]


def test_limit_and_order(conn):
    seed(conn)
    conn.execute(
        "INSERT INTO tracks VALUES ('c2','Low','a8','Aitch','alb',1)"
    )
    conn.execute(
        "INSERT INTO candidates VALUES "
        "('c2','artist:central cee','lastfm',0.2,'2026-07-18T00:00:00.000Z')"
    )
    conn.commit()
    profile = Profile(artist_weights={}, tag_weights={})
    out = rank(conn, profile, NOW, limit=1)
    assert [r["track_id"] for r in out] == ["c1"]
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement `app/taste/ranker.py`**

```python
import datetime as dt
import sqlite3

from ..enrichment import cache
from .normalize import norm_key
from .profile import Profile

SKIP_WINDOW_DAYS = 14


def _recent_down_artists(conn: sqlite3.Connection, now: float) -> set[str]:
    cutoff = dt.datetime.fromtimestamp(
        now - SKIP_WINDOW_DAYS * 86400, dt.timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%S")
    rows = conn.execute(
        "SELECT DISTINCT t.artist_name FROM feedback f "
        "JOIN tracks t ON t.id = f.track_id "
        "WHERE f.verdict = 'down' AND f.created_at >= ?",
        (cutoff,),
    )
    return {norm_key(r["artist_name"]) for r in rows}


def rank(
    conn: sqlite3.Connection, profile: Profile, now: float, limit: int = 50
) -> list[dict]:
    downed = _recent_down_artists(conn, now)
    out = []
    rows = conn.execute(
        "SELECT c.track_id, c.seed, c.source, c.weight, "
        "t.name, t.artist_name FROM candidates c "
        "JOIN tracks t ON t.id = c.track_id"
    )
    for r in rows:
        akey = norm_key(r["artist_name"])
        tags = cache.get_tags(conn, "artist", akey)
        overlap_tags = sorted(
            ((profile.tag_weights.get(tag, 0) * w, tag) for tag, w in tags.items()),
            reverse=True,
        )
        tag_overlap = min(sum(v for v, _ in overlap_tags), 1.0)
        proximity = r["weight"]
        if akey in profile.artist_weights:
            novelty = max(0.0, 1 - profile.artist_weights[akey] / 5)
        else:
            novelty = 1.0
        penalty = 2.0 if akey in downed else 0.0
        score = 2.0 * tag_overlap + 1.5 * proximity + 1.0 * novelty - penalty

        why = []
        parts = [
            (2.0 * tag_overlap,
             "tags you love: "
             + ", ".join(t for v, t in overlap_tags[:3] if v > 0)),
            (1.5 * proximity,
             "similar to " + r["seed"].split(":", 1)[1]),
            (1.0 * novelty, "new artist for you"),
        ]
        for value, text in sorted(parts, reverse=True):
            if value > 0:
                why.append(text)
        if penalty:
            why.append("recently disliked this artist")

        out.append({
            "track_id": r["track_id"], "name": r["name"],
            "artist": r["artist_name"], "score": score, "why": why,
            "seed": r["seed"], "source": r["source"],
        })
    out.sort(key=lambda x: -x["score"])
    return out[:limit]
```

- [ ] **Step 4: Run** — all PASS. **Step 5: Commit** — `git commit -m "feat: add explainable heuristic ranker (golden-tested)"`

---

### Task 10: API endpoints

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_api_discover.py` (new)

**Interfaces:**
- Consumes: Tasks 6-9, `auth.get_valid_access_token(conn, client_id)`, `auth.NotConnectedError`.
- Produces HTTP API (frontend contract):
  - `GET /discover?limit=20` → `{"items": [ranker dicts]}`. Builds profile with local data only (no Spotify calls — fast path).
  - `POST /discover/refresh` → `{"new": int}`. Runs `refresh_candidates` (slow; live network). 503 `{"detail": "not connected"}` if `NotConnectedError`.
  - `POST /feedback` body `{"track_id": str, "verdict": "up"|"down"|"more_like_this"}` → `{"ok": true}`; 422 on bad verdict (pydantic).
  - `POST /playlists/from-feed` body `{"track_ids": [str], "name": str | null}` → `{"url": str}`; default name `"Spotify DJ picks <YYYY-MM-DD>"`; 503 if not connected.
  - `POST /playback/queue` body `{"track_id": str}` → `{"ok": true}`; 503 if not connected; 404 from Spotify (no active device) passes through as 502 `{"detail": "no active device"}`.

- [ ] **Step 1: Write the failing tests** (uses existing `client` fixture; respx for Spotify)

```python
import datetime as dt

import respx
from httpx import Response

SPOTIFY = "https://api.spotify.com/v1"
TOKEN_URL = "https://accounts.spotify.com/api/token"


def seed_candidate(client):
    # reach into the app's live conn the way test_main.py does
    conn = client.app.state.conn
    conn.execute(
        "INSERT INTO tracks VALUES ('c1','Sprinter','a9','Dave','alb',200000)"
    )
    conn.execute(
        "INSERT INTO candidates VALUES "
        "('c1','artist:central cee','lastfm',0.9,'2026-07-18T00:00:00.000Z')"
    )
    conn.commit()


def connect(client):
    from app import auth
    auth.save_tokens(client.app.state.conn, "tok", "ref", 3600)


def test_discover_returns_ranked_items(client):
    seed_candidate(client)
    r = client.get("/discover?limit=5")
    assert r.status_code == 200
    items = r.json()["items"]
    assert items[0]["track_id"] == "c1"
    assert isinstance(items[0]["why"], list)


def test_feedback_roundtrip(client):
    seed_candidate(client)
    r = client.post("/feedback", json={"track_id": "c1", "verdict": "up"})
    assert r.status_code == 200
    row = client.app.state.conn.execute("SELECT * FROM feedback").fetchone()
    assert row["verdict"] == "up"
    assert client.post(
        "/feedback", json={"track_id": "c1", "verdict": "meh"}
    ).status_code == 422


def test_refresh_requires_connection(client):
    assert client.post("/discover/refresh").status_code == 503


@respx.mock
def test_playlist_from_feed(client):
    seed_candidate(client)
    connect(client)
    respx.post(f"{SPOTIFY}/me/playlists").mock(
        return_value=Response(201, json={
            "id": "pl1", "external_urls": {"spotify": "https://s/pl1"}})
    )
    respx.post(f"{SPOTIFY}/playlists/pl1/items").mock(
        return_value=Response(201, json={"snapshot_id": "s"})
    )
    r = client.post("/playlists/from-feed", json={"track_ids": ["c1"]})
    assert r.status_code == 200
    assert r.json()["url"] == "https://s/pl1"


@respx.mock
def test_queue_no_active_device_502(client):
    connect(client)
    respx.post(f"{SPOTIFY}/me/player/queue").mock(
        return_value=Response(404, json={"error": {"reason": "NO_ACTIVE_DEVICE"}})
    )
    r = client.post("/playback/queue", json={"track_id": "c1"})
    assert r.status_code == 502
```

Note: `connect()` stores a token expiring in 3600s, so `get_valid_access_token` returns it without hitting the token endpoint.

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement in `app/main.py`** — add imports and endpoints:

```python
import datetime as dt
import time
from typing import Literal

import httpx
from pydantic import BaseModel

from . import spotify
from .taste import candidates as taste_candidates
from .taste import ranker as taste_ranker
from .taste.profile import build_profile
```

```python
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
```

Add `HTTPException` to the fastapi import line.

- [ ] **Step 4: Run the whole suite** — `.venv/bin/pytest -v` → everything PASSES.
- [ ] **Step 5: Commit** — `git commit -m "feat: add discover, feedback, playlist, and queue endpoints"`

---

### Task 11: Frontend Discover page

**Files:**
- Create: `frontend/app/discover/page.tsx`, `frontend/app/discover/FeedbackButtons.tsx`, `frontend/app/discover/FeedbackButtons.test.tsx`, `frontend/vitest.config.mts`
- Modify: `frontend/app/page.tsx` (add nav link), `frontend/package.json` (test script + dev deps)

**Interfaces:**
- Consumes the Task 10 HTTP API exactly as specified there.
- Before writing code: read the routing and client-component guides in `frontend/node_modules/next/dist/docs/` (this Next.js differs from training data). Mirror `frontend/app/page.tsx` conventions.

- [ ] **Step 1: Install test tooling** — `cd ../frontend && npm i -D vitest @vitejs/plugin-react jsdom @testing-library/react @testing-library/user-event @testing-library/dom` and add `"test": "vitest run"` to package.json scripts. Create `frontend/vitest.config.mts`:

```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: { environment: "jsdom" },
});
```

- [ ] **Step 2: Write the failing component test** `frontend/app/discover/FeedbackButtons.test.tsx`

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import FeedbackButtons from "./FeedbackButtons";

describe("FeedbackButtons", () => {
  it("posts the verdict and disables after click", async () => {
    const onFeedback = vi.fn().mockResolvedValue(undefined);
    render(<FeedbackButtons trackId="t1" onFeedback={onFeedback} />);
    await userEvent.click(screen.getByRole("button", { name: "👍" }));
    expect(onFeedback).toHaveBeenCalledWith("t1", "up");
    expect(screen.getByRole("button", { name: "👍" })).toBeDisabled();
  });

  it("offers all three verdicts", () => {
    render(<FeedbackButtons trackId="t1" onFeedback={vi.fn()} />);
    for (const label of ["👍", "👎", "More like this"]) {
      expect(screen.getByRole("button", { name: label })).toBeTruthy();
    }
  });
});
```

Run: `npm test` → fails (module not found). Note: if `toBeDisabled` is unavailable without jest-dom, assert `(screen.getByRole(...) as HTMLButtonElement).disabled` is `true` instead — do not add jest-dom just for one matcher.

- [ ] **Step 3: Implement `frontend/app/discover/FeedbackButtons.tsx`**

```tsx
"use client";

import { useState } from "react";

type Verdict = "up" | "down" | "more_like_this";

export default function FeedbackButtons({
  trackId,
  onFeedback,
}: {
  trackId: string;
  onFeedback: (trackId: string, verdict: Verdict) => Promise<void>;
}) {
  const [sent, setSent] = useState<Verdict | null>(null);

  const send = (verdict: Verdict) => {
    setSent(verdict);
    onFeedback(trackId, verdict).catch(() => setSent(null));
  };

  const btn = "rounded border px-2 py-1 text-sm disabled:opacity-40";
  return (
    <span className="space-x-2">
      <button className={btn} disabled={sent !== null} onClick={() => send("up")}>
        👍
      </button>
      <button className={btn} disabled={sent !== null} onClick={() => send("down")}>
        👎
      </button>
      <button
        className={btn}
        disabled={sent !== null}
        onClick={() => send("more_like_this")}
      >
        More like this
      </button>
    </span>
  );
}
```

Run: `npm test` → PASS. Commit: `git commit -m "feat: add feedback buttons component with tests"`

- [ ] **Step 4: Implement `frontend/app/discover/page.tsx`**

```tsx
"use client";

import { useCallback, useEffect, useState } from "react";
import FeedbackButtons from "./FeedbackButtons";

const API = "http://127.0.0.1:8765";

type Item = {
  track_id: string;
  name: string;
  artist: string;
  score: number;
  why: string[];
};

export default function Discover() {
  const [items, setItems] = useState<Item[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    fetch(`${API}/discover?limit=30`)
      .then((r) => r.json())
      .then((d) => setItems(d.items))
      .catch(() => setNotice("Backend not reachable on :8765 — is it running?"));
  }, []);

  useEffect(load, [load]);

  const refresh = async () => {
    setBusy("Refreshing candidates — this hits Last.fm/ListenBrainz and can take a minute…");
    try {
      const r = await fetch(`${API}/discover/refresh`, { method: "POST" });
      if (!r.ok) throw new Error();
      const d = await r.json();
      setNotice(`${d.new} new candidates`);
      load();
    } catch {
      setNotice("Refresh failed — is Spotify connected?");
    } finally {
      setBusy(null);
    }
  };

  const sendFeedback = async (trackId: string, verdict: string) => {
    await fetch(`${API}/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ track_id: trackId, verdict }),
    });
  };

  const queue = async (trackId: string) => {
    const r = await fetch(`${API}/playback/queue`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ track_id: trackId }),
    });
    setNotice(r.ok ? "Queued." : "Queue failed — is Spotify playing on a device?");
  };

  const toggle = (id: string) => {
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const savePlaylist = async () => {
    const r = await fetch(`${API}/playlists/from-feed`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ track_ids: [...selected] }),
    });
    if (r.ok) {
      const d = await r.json();
      setNotice("Playlist created.");
      window.open(d.url, "_blank");
    } else {
      setNotice("Playlist failed — is Spotify connected?");
    }
  };

  return (
    <main className="mx-auto max-w-3xl p-8 space-y-6">
      <h1 className="text-2xl font-bold">Spotify DJ — Discover</h1>
      <p>
        <a href="/" className="text-sm underline">← Stats</a>
      </p>

      <div className="flex items-center gap-4">
        <button
          onClick={refresh}
          disabled={busy !== null}
          className="rounded bg-green-600 px-4 py-2 font-semibold text-white disabled:opacity-40"
        >
          Refresh candidates
        </button>
        {selected.size > 0 && (
          <button
            onClick={savePlaylist}
            className="rounded bg-blue-600 px-4 py-2 font-semibold text-white"
          >
            Save {selected.size} as playlist
          </button>
        )}
      </div>

      {busy && <p className="text-sm text-gray-500">{busy}</p>}
      {notice && <p className="text-sm">{notice}</p>}
      {items.length === 0 && !busy && (
        <p className="text-gray-500">
          No candidates yet — hit “Refresh candidates”.
        </p>
      )}

      <ul className="space-y-4">
        {items.map((it) => (
          <li key={it.track_id} className="rounded border p-3 space-y-1">
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={selected.has(it.track_id)}
                onChange={() => toggle(it.track_id)}
              />
              <span className="font-semibold">{it.name}</span>
              <span>— {it.artist}</span>
              <span className="text-xs text-gray-400">
                {it.score.toFixed(2)}
              </span>
            </div>
            <p className="text-sm text-gray-500">{it.why.join(" · ")}</p>
            <div className="flex items-center gap-3">
              <a
                className="text-sm underline"
                href={`https://open.spotify.com/track/${it.track_id}`}
                target="_blank"
              >
                Open in Spotify
              </a>
              <button className="text-sm underline" onClick={() => queue(it.track_id)}>
                Queue
              </button>
              <FeedbackButtons trackId={it.track_id} onFeedback={sendFeedback} />
            </div>
          </li>
        ))}
      </ul>
    </main>
  );
}
```

- [ ] **Step 5: Add nav link in `frontend/app/page.tsx`** — under the `<h1>`, add:

```tsx
      <p>
        <a href="/discover" className="text-sm underline">Discover →</a>
      </p>
```

- [ ] **Step 6: Verify** — `npm test` PASS; `npm run dev` and load http://localhost:3001/discover (empty-state message renders; full flow needs the backend).
- [ ] **Step 7: Commit** — `git commit -m "feat: add Discover page with refresh, feedback, queue, save-as-playlist"`

---

### Task 12: End-to-end verification (live)

**Files:** none (verification only).

- [ ] **Step 1:** Full backend suite green: `.venv/bin/pytest -v`. Frontend: `npm test`.
- [ ] **Step 2:** Restart the backend (`pkill -f "uvicorn app.main:app"`, then `.venv/bin/uvicorn app.main:app --port 8765`).
- [ ] **Step 3:** `curl -s -X POST http://127.0.0.1:8765/discover/refresh` — expect `{"new": N}` with N > 0 (ListenBrainz-only until the Last.fm key exists; MusicBrainz's 1 req/s makes this take ~10-30s). If N == 0, inspect `sqlite3 spotify_dj.sqlite3 "SELECT * FROM enrichment_fetches"` and the uvicorn log before touching code.
- [ ] **Step 4:** `curl -s "http://127.0.0.1:8765/discover?limit=5"` — items with non-empty `why`.
- [ ] **Step 5:** In the browser: Discover page shows the feed; 👍 writes a `feedback` row; Queue works while Spotify plays on some device; saving a playlist creates it in Spotify (user confirms).
- [ ] **Step 6:** If `/me/tracks` 404s in the uvicorn log (Spotify consolidated-library migration), change the path in `spotify.get_saved_tracks` to `/me/library` with `params={"type": "tracks", "limit": limit, "offset": offset}`, update `test_saved_tracks` to match, re-run tests, commit as `fix: use consolidated /me/library endpoint`.
