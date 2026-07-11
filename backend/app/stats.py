import datetime as dt
import sqlite3


def _cutoff(days: int) -> str:
    d = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    return d.strftime("%Y-%m-%dT%H:%M:%S")


def recent_plays(conn: sqlite3.Connection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT p.played_at, t.name AS track, t.artist_name AS artist "
        "FROM plays p JOIN tracks t ON t.id = p.track_id "
        "ORDER BY p.played_at DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


def top_tracks(conn: sqlite3.Connection, days: int = 30, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT t.name AS name, t.artist_name AS artist, COUNT(*) AS plays "
        "FROM plays p JOIN tracks t ON t.id = p.track_id "
        "WHERE p.played_at >= ? "
        "GROUP BY t.id ORDER BY plays DESC, name LIMIT ?",
        (_cutoff(days), limit),
    )
    return [dict(r) for r in rows]


def top_artists(conn: sqlite3.Connection, days: int = 30, limit: int = 20) -> list[dict]:
    rows = conn.execute(
        "SELECT t.artist_name AS name, COUNT(*) AS plays "
        "FROM plays p JOIN tracks t ON t.id = p.track_id "
        "WHERE p.played_at >= ? "
        "GROUP BY t.artist_id ORDER BY plays DESC, name LIMIT ?",
        (_cutoff(days), limit),
    )
    return [dict(r) for r in rows]
