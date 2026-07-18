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
