import dataclasses
import datetime as dt

import respx
from httpx import Response

from app.config import Settings
from app.enrichment import cache
from app.taste import candidates
from app.taste.normalize import norm_key

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
    # resolved candidate artist's tags must also be enriched, or tag_overlap
    # in the ranker is dead for every candidate.
    assert cache.get_tags(conn, "artist", "dave")
    assert cache.was_fetched(conn, "lastfm", "artist", "dave")


@respx.mock
async def test_refresh_no_api_key_never_marks_candidate_fetched(conn, monkeypatch):
    async def no_sleep(s):
        pass
    import asyncio as aio
    monkeypatch.setattr(aio, "sleep", no_sleep)
    seed_history(conn)
    mock_spotify_bootstrap()
    empty_key_settings = dataclasses.replace(SETTINGS, lastfm_api_key="")
    # Pre-seed similar-artist edges (as if a prior run with a real key had
    # populated them) and mark the seed already fetched so the empty-key
    # run doesn't overwrite them via get_similar_artists() -> [].
    cache.store_edges(
        conn, "lastfm", "artist", "central cee",
        [{"name": "Dave", "match": 0.9}],
    )
    cache.mark_fetched(conn, "lastfm", "artist", "central cee", "2020-01-01T00:00:00.000Z")
    cache.mark_fetched(conn, "listenbrainz", "artist", "central cee", "2020-01-01T00:00:00.000Z")
    lastfm_route = respx.get("https://ws.audioscrobbler.com/2.0/").mock(
        return_value=Response(200, json={})
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
    n = await candidates.refresh_candidates(conn, empty_key_settings, "tok", NOW)
    assert n == 1
    assert lastfm_route.call_count == 0
    assert cache.was_fetched(conn, "lastfm", "artist", "dave") is False
    assert cache.get_tags(conn, "artist", "dave") == {}


@respx.mock
async def test_refresh_empty_key_does_not_poison_seed_cache(conn, monkeypatch):
    async def no_sleep(s):
        pass
    import asyncio as aio
    monkeypatch.setattr(aio, "sleep", no_sleep)
    seed_history(conn)
    empty_key_settings = dataclasses.replace(SETTINGS, lastfm_api_key="")
    respx.get(f"{SPOTIFY}/me/top/artists").mock(
        return_value=Response(200, json={"items": [{"name": "Central Cee"}]})
    )
    respx.get(f"{SPOTIFY}/me/top/tracks").mock(
        return_value=Response(200, json={"items": [{
            "name": "Sprinter",
            "artists": [{"name": "Central Cee"}],
        }]})
    )
    respx.get(f"{SPOTIFY}/me/tracks").mock(
        return_value=Response(200, json={"items": []})
    )
    lastfm_route = respx.get("https://ws.audioscrobbler.com/2.0/").mock(
        return_value=Response(200, json={})
    )
    respx.get("https://musicbrainz.org/ws/2/artist").mock(
        return_value=Response(200, json={"artists": []})
    )
    respx.get(f"{SPOTIFY}/search").mock(
        return_value=Response(200, json={"tracks": {"items": []}})
    )
    await candidates.refresh_candidates(conn, empty_key_settings, "tok", NOW)
    assert lastfm_route.call_count == 0
    assert cache.was_fetched(conn, "lastfm", "artist", "central cee") is False
    assert cache.was_fetched(
        conn, "lastfm", "track", norm_key("Central Cee", "Sprinter")
    ) is False
    assert cache.was_fetched(conn, "listenbrainz", "artist", "central cee") is True


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
