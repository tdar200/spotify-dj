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
