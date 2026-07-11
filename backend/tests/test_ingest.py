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
