import asyncio

import httpx

MB_ARTIST_URL = "https://musicbrainz.org/ws/2/artist"
LABS_SIMILAR_URL = "https://labs.api.listenbrainz.org/similar-artists/json"
USER_AGENT = "spotify-dj/0.1 (personal use)"
ALGORITHM = (
    "session_based_days_7500_session_300_contribution_5_"
    "threshold_10_limit_100_filter_True_skip_30"
)


async def _get(url: str, params: dict) -> httpx.Response:
    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient() as client:
        for attempt in range(2):
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code == 429 and attempt == 0:
                await asyncio.sleep(int(resp.headers.get("Retry-After", "1")))
                continue
            resp.raise_for_status()
            return resp
    raise AssertionError("unreachable")


async def resolve_artist_mbid(name: str) -> str | None:
    await asyncio.sleep(1)  # MusicBrainz rate limit: 1 req/s
    resp = await _get(
        MB_ARTIST_URL,
        {"query": f'artist:"{name}"', "fmt": "json", "limit": 1},
    )
    artists = resp.json().get("artists", [])
    if artists and artists[0].get("score", 0) >= 90:
        return artists[0]["id"]
    return None


async def get_similar_artists(mbid: str, limit: int = 50) -> list[dict]:
    resp = await _get(
        LABS_SIMILAR_URL, {"artist_mbids": mbid, "algorithm": ALGORITHM}
    )
    rows = resp.json()[:limit]
    if not rows:
        return []
    top = max(r["score"] for r in rows) or 1
    return [{"name": r["artist_name"], "match": r["score"] / top} for r in rows]
