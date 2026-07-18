import asyncio

import httpx

API_BASE = "https://api.spotify.com/v1"


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


async def get_recently_played(
    access_token: str, after_ms: int | None = None, limit: int = 50
) -> dict:
    params: dict = {"limit": limit}
    if after_ms is not None:
        params["after"] = after_ms
    resp = await _request("GET", "/me/player/recently-played",
                          access_token, params=params)
    return resp.json()


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
