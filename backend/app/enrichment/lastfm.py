import asyncio

import httpx

API_ROOT = "https://ws.audioscrobbler.com/2.0/"


async def _call(api_key: str, params: dict) -> dict:
    params = {**params, "api_key": api_key, "format": "json"}
    async with httpx.AsyncClient() as client:
        for attempt in range(2):
            resp = await client.get(API_ROOT, params=params)
            if resp.status_code == 429 and attempt == 0:
                await asyncio.sleep(int(resp.headers.get("Retry-After", "1")))
                continue
            resp.raise_for_status()
            return resp.json()
    raise AssertionError("unreachable")


def _tags(payload: dict) -> list[dict]:
    tags = payload.get("toptags", {}).get("tag", [])
    return [
        {"tag": t["name"].lower(), "weight": min(float(t["count"]) / 100, 1.0)}
        for t in tags
        if t.get("count")
    ]


async def get_similar_artists(api_key: str, artist: str, limit: int = 50) -> list[dict]:
    if not api_key:
        return []
    data = await _call(
        api_key,
        {"method": "artist.getSimilar", "artist": artist, "limit": limit,
         "autocorrect": 1},
    )
    return [
        {"name": a["name"], "match": float(a["match"])}
        for a in data.get("similarartists", {}).get("artist", [])
    ]


async def get_artist_top_tags(api_key: str, artist: str) -> list[dict]:
    if not api_key:
        return []
    data = await _call(
        api_key,
        {"method": "artist.getTopTags", "artist": artist, "autocorrect": 1},
    )
    return _tags(data)


async def get_similar_tracks(
    api_key: str, artist: str, title: str, limit: int = 50
) -> list[dict]:
    if not api_key:
        return []
    data = await _call(
        api_key,
        {"method": "track.getSimilar", "artist": artist, "track": title,
         "limit": limit, "autocorrect": 1},
    )
    return [
        {"artist": t["artist"]["name"], "name": t["name"], "match": float(t["match"])}
        for t in data.get("similartracks", {}).get("track", [])
    ]


async def get_track_top_tags(api_key: str, artist: str, title: str) -> list[dict]:
    if not api_key:
        return []
    data = await _call(
        api_key,
        {"method": "track.getTopTags", "artist": artist, "track": title,
         "autocorrect": 1},
    )
    return _tags(data)
