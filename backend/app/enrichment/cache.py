import sqlite3


def was_fetched(conn: sqlite3.Connection, source: str, kind: str, key: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM enrichment_fetches WHERE source=? AND kind=? AND key=?",
        (source, kind, key),
    ).fetchone()
    return row is not None


def mark_fetched(
    conn: sqlite3.Connection, source: str, kind: str, key: str, now_iso: str
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO enrichment_fetches (source, kind, key, fetched_at) "
        "VALUES (?, ?, ?, ?)",
        (source, kind, key, now_iso),
    )
    conn.commit()


def store_tags(
    conn: sqlite3.Connection, source: str, kind: str, key: str, tags: list[dict]
) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO tags (source, kind, key, tag, weight) "
        "VALUES (?, ?, ?, ?, ?)",
        [(source, kind, key, t["tag"], t["weight"]) for t in tags],
    )
    conn.commit()


def get_tags(conn: sqlite3.Connection, kind: str, key: str) -> dict[str, float]:
    rows = conn.execute(
        "SELECT tag, MAX(weight) AS weight FROM tags "
        "WHERE kind=? AND key=? GROUP BY tag",
        (kind, key),
    )
    return {r["tag"]: r["weight"] for r in rows}


def store_edges(
    conn: sqlite3.Connection, source: str, kind: str, from_key: str,
    edges: list[dict],
) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO similar_edges "
        "(source, kind, from_key, to_name, to_artist, weight) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (source, kind, from_key, e["name"], e.get("artist", ""), e["match"])
            for e in edges
        ],
    )
    conn.commit()


def get_edges(conn: sqlite3.Connection, kind: str, from_key: str) -> list[dict]:
    rows = conn.execute(
        "SELECT source, to_name, to_artist, weight FROM similar_edges "
        "WHERE kind=? AND from_key=? ORDER BY weight DESC",
        (kind, from_key),
    )
    return [dict(r) for r in rows]
