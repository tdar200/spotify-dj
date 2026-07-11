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
