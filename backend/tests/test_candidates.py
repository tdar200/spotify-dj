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
