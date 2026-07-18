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
