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
