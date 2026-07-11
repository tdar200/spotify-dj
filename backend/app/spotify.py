import asyncio

import httpx

API_BASE = "https://api.spotify.com/v1"


async def get_recently_played(
    access_token: str, after_ms: int | None = None, limit: int = 50
) -> dict:
    params: dict = {"limit": limit}
    if after_ms is not None:
        params["after"] = after_ms
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient() as client:
        for attempt in range(2):
            resp = await client.get(
                f"{API_BASE}/me/player/recently-played",
                params=params,
                headers=headers,
            )
            if resp.status_code == 429 and attempt == 0:
                await asyncio.sleep(int(resp.headers.get("Retry-After", "1")))
                continue
            resp.raise_for_status()
            return resp.json()
    raise AssertionError("unreachable")
