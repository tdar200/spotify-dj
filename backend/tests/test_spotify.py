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


@respx.mock
async def test_search_track_builds_field_query():
    route = respx.get("https://api.spotify.com/v1/search").mock(
        return_value=httpx.Response(200, json={"tracks": {"items": [{"id": "t1"}]}})
    )
    items = await spotify.search_track("tok", "Dave", "Sprinter")
    assert items == [{"id": "t1"}]
    q = route.calls[0].request.url.params["q"]
    assert q == 'artist:"Dave" track:"Sprinter"'


@respx.mock
async def test_top_artists_and_tracks_params():
    respx.get("https://api.spotify.com/v1/me/top/artists").mock(
        return_value=httpx.Response(200, json={"items": [{"name": "Atif Aslam"}]})
    )
    respx.get("https://api.spotify.com/v1/me/top/tracks").mock(
        return_value=httpx.Response(200, json={"items": []})
    )
    a = await spotify.get_top_artists("tok")
    t = await spotify.get_top_tracks("tok")
    assert a["items"][0]["name"] == "Atif Aslam"
    assert t["items"] == []


@respx.mock
async def test_saved_tracks():
    respx.get("https://api.spotify.com/v1/me/tracks").mock(
        return_value=httpx.Response(200, json={"items": [], "total": 0})
    )
    assert (await spotify.get_saved_tracks("tok"))["total"] == 0


@respx.mock
async def test_create_playlist_and_add_items():
    respx.post("https://api.spotify.com/v1/me/playlists").mock(
        return_value=httpx.Response(201, json={"id": "pl1",
                                               "external_urls": {"spotify": "u"}})
    )
    add = respx.post("https://api.spotify.com/v1/playlists/pl1/items").mock(
        return_value=httpx.Response(201, json={"snapshot_id": "s"})
    )
    pl = await spotify.create_playlist("tok", "DJ picks")
    await spotify.add_playlist_items("tok", pl["id"], ["spotify:track:t1"])
    assert add.called


@respx.mock
async def test_queue_track():
    route = respx.post("https://api.spotify.com/v1/me/player/queue").mock(
        return_value=httpx.Response(204)
    )
    await spotify.queue_track("tok", "spotify:track:t1")
    assert route.calls[0].request.url.params["uri"] == "spotify:track:t1"
