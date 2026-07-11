import asyncio
import datetime as dt
import logging
import sqlite3

from . import auth, spotify

logger = logging.getLogger(__name__)


def latest_played_at_ms(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT MAX(played_at) AS m FROM plays").fetchone()
    if row["m"] is None:
        return None
    t = dt.datetime.fromisoformat(row["m"].replace("Z", "+00:00"))
    return int(t.timestamp() * 1000)


def store_items(conn: sqlite3.Connection, items: list[dict]) -> int:
    new = 0
    for item in items:
        track = item["track"]
        artist = track["artists"][0]
        conn.execute(
            "INSERT OR REPLACE INTO tracks "
            "(id, name, artist_id, artist_name, album_name, duration_ms) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                track["id"],
                track["name"],
                artist["id"],
                artist["name"],
                track.get("album", {}).get("name"),
                track.get("duration_ms"),
            ),
        )
        cur = conn.execute(
            "INSERT OR IGNORE INTO plays (played_at, track_id) VALUES (?, ?)",
            (item["played_at"], track["id"]),
        )
        new += cur.rowcount
    conn.commit()
    return new


async def ingest_once(conn: sqlite3.Connection, client_id: str) -> int:
    token = await auth.get_valid_access_token(conn, client_id)
    data = await spotify.get_recently_played(
        token, after_ms=latest_played_at_ms(conn)
    )
    return store_items(conn, data.get("items", []))


async def run_worker(
    conn: sqlite3.Connection, client_id: str, interval_s: float = 120
) -> None:
    while True:
        try:
            new = await ingest_once(conn, client_id)
            if new:
                logger.info("ingested %d new plays", new)
        except auth.NotConnectedError:
            pass  # user hasn't connected Spotify yet
        except Exception:
            logger.exception("ingest failed; will retry next cycle")
        await asyncio.sleep(interval_s)
