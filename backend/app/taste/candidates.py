import datetime as dt
import logging
import sqlite3

import httpx

from .. import spotify
from ..config import Settings
from ..enrichment import cache, lastfm, listenbrainz
from .normalize import norm_key, norm_name
from .profile import build_profile

logger = logging.getLogger(__name__)


def known_keys(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT t.artist_name, t.name FROM tracks t "
        "LEFT JOIN plays p ON p.track_id = t.id "
        "LEFT JOIN candidates c ON c.track_id = t.id "
        "WHERE p.track_id IS NOT NULL OR c.track_id IS NOT NULL"
    )
    out = set()
    for r in rows:
        out.add(norm_key(r["artist_name"], r["name"]))
        out.add(norm_key(r["artist_name"]))
    return out


def _upsert_track(conn: sqlite3.Connection, item: dict) -> None:
    artist = item["artists"][0]
    conn.execute(
        "INSERT OR REPLACE INTO tracks "
        "(id, name, artist_id, artist_name, album_name, duration_ms) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (item["id"], item["name"], artist["id"], artist["name"],
         item.get("album", {}).get("name"), item.get("duration_ms")),
    )


async def _bootstrap(access_token: str) -> tuple[list[str], list[dict], list[str]]:
    try:
        top_a = await spotify.get_top_artists(access_token)
        top_t = await spotify.get_top_tracks(access_token)
        saved = await spotify.get_saved_tracks(access_token)
    except httpx.HTTPStatusError:
        logger.info("spotify bootstrap unavailable; using local history only")
        return [], [], []
    return (
        [a["name"] for a in top_a.get("items", [])],
        [
            {"artist": t["artists"][0]["name"], "title": t["name"]}
            for t in top_t.get("items", [])
            if t.get("artists")
        ],
        [
            s["track"]["artists"][0]["name"]
            for s in saved.get("items", [])
            if s.get("track", {}).get("artists")
        ],
    )


async def _enrich_artist_seed(conn, api_key: str, key: str, name: str, now_iso: str):
    if not cache.was_fetched(conn, "lastfm", "artist", key):
        cache.store_edges(conn, "lastfm", "artist", key,
                          await lastfm.get_similar_artists(api_key, name))
        cache.store_tags(conn, "lastfm", "artist", key,
                         await lastfm.get_artist_top_tags(api_key, name))
        cache.mark_fetched(conn, "lastfm", "artist", key, now_iso)
    if not cache.was_fetched(conn, "listenbrainz", "artist", key):
        mbid = await listenbrainz.resolve_artist_mbid(name)
        if mbid:
            cache.store_edges(conn, "listenbrainz", "artist", key,
                              await listenbrainz.get_similar_artists(mbid))
        conn.execute(
            "INSERT OR REPLACE INTO artists (key, name, mbid) VALUES (?, ?, ?)",
            (key, name, mbid or ""),
        )
        cache.mark_fetched(conn, "listenbrainz", "artist", key, now_iso)


async def _resolve_and_insert(
    conn, access_token: str, artist: str, title: str,
    seed: str, source: str, weight: float, now_iso: str, api_key: str = "",
) -> bool:
    items = await spotify.search_track(access_token, artist, title)
    for item in items:
        if not item.get("artists"):
            continue
        got_artist = norm_name(item["artists"][0]["name"])
        if title:
            ok = norm_key(item["artists"][0]["name"], item["name"]) == norm_key(
                artist, title
            )
        else:
            ok = got_artist == norm_name(artist)
        if ok:
            _upsert_track(conn, item)
            cur = conn.execute(
                "INSERT OR IGNORE INTO candidates "
                "(track_id, seed, source, weight, added_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (item["id"], seed, source, weight, now_iso),
            )
            conn.commit()
            if cur.rowcount > 0 and api_key:
                cand_name = item["artists"][0]["name"]
                cand_key = norm_key(cand_name)
                if not cache.was_fetched(conn, "lastfm", "artist", cand_key):
                    cache.store_tags(
                        conn, "lastfm", "artist", cand_key,
                        await lastfm.get_artist_top_tags(api_key, cand_name),
                    )
                    cache.mark_fetched(conn, "lastfm", "artist", cand_key, now_iso)
            return cur.rowcount > 0
    logger.info("no spotify match for %s — %s; skipping", artist, title)
    return False


async def refresh_candidates(
    conn: sqlite3.Connection,
    settings: Settings,
    access_token: str,
    now: float,
    max_artist_seeds: int = 8,
    max_track_seeds: int = 8,
    per_seed: int = 10,
) -> int:
    now_iso = dt.datetime.fromtimestamp(now, dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )
    top_artists, top_tracks, saved_artists = await _bootstrap(access_token)
    profile = build_profile(
        conn, now, top_artists=top_artists, saved_artists=saved_artists
    )

    # "more like this" feedback promotes that exact track to a seed (spec).
    mlt_rows = conn.execute(
        "SELECT DISTINCT t.artist_name, t.name FROM feedback f "
        "JOIN tracks t ON t.id = f.track_id "
        "WHERE f.verdict = 'more_like_this'"
    )
    top_tracks = [
        {"artist": r["artist_name"], "title": r["name"]} for r in mlt_rows
    ] + top_tracks

    display = {}  # norm key -> display name, for API calls
    rows = conn.execute("SELECT DISTINCT artist_name FROM tracks")
    for r in rows:
        display[norm_key(r["artist_name"])] = r["artist_name"]
    for name in top_artists + saved_artists:
        display.setdefault(norm_key(name), name)

    artist_seeds = sorted(
        profile.artist_weights.items(), key=lambda kv: -kv[1]
    )[:max_artist_seeds]

    for key, _w in artist_seeds:
        name = display.get(key)
        if name is None:
            continue
        await _enrich_artist_seed(conn, settings.lastfm_api_key, key, name, now_iso)

    for t in top_tracks[:max_track_seeds]:
        tkey = norm_key(t["artist"], t["title"])
        if not cache.was_fetched(conn, "lastfm", "track", tkey):
            cache.store_edges(
                conn, "lastfm", "track", tkey,
                await lastfm.get_similar_tracks(
                    settings.lastfm_api_key, t["artist"], t["title"]
                ),
            )
            cache.mark_fetched(conn, "lastfm", "track", tkey, now_iso)

    known = known_keys(conn)
    inserted = 0

    for key, _w in artist_seeds:
        for e in cache.get_edges(conn, "artist", key)[:per_seed]:
            if norm_key(e["to_name"]) in known:
                continue
            if await _resolve_and_insert(
                conn, access_token, e["to_name"], "",
                f"artist:{key}", e["source"], e["weight"], now_iso,
                settings.lastfm_api_key,
            ):
                known.add(norm_key(e["to_name"]))
                inserted += 1

    for t in top_tracks[:max_track_seeds]:
        tkey = norm_key(t["artist"], t["title"])
        for e in cache.get_edges(conn, "track", tkey)[:per_seed]:
            if norm_key(e["to_artist"], e["to_name"]) in known:
                continue
            if await _resolve_and_insert(
                conn, access_token, e["to_artist"], e["to_name"],
                f"track:{tkey}", e["source"], e["weight"], now_iso,
                settings.lastfm_api_key,
            ):
                known.add(norm_key(e["to_artist"], e["to_name"]))
                inserted += 1

    return inserted
