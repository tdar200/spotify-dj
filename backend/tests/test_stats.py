import datetime as dt

from app import stats


def seed(conn, played_at: str, track_id: str, name: str, artist: str):
    conn.execute(
        "INSERT OR REPLACE INTO tracks (id, name, artist_id, artist_name) "
        "VALUES (?, ?, ?, ?)",
        (track_id, name, f"a-{artist}", artist),
    )
    conn.execute(
        "INSERT OR IGNORE INTO plays (played_at, track_id) VALUES (?, ?)",
        (played_at, track_id),
    )
    conn.commit()


def iso(days_ago: int, hour: int = 12) -> str:
    d = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)
    return d.replace(hour=hour, minute=0, second=0, microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


def test_recent_plays_newest_first(conn):
    seed(conn, iso(2), "t1", "Old Song", "A")
    seed(conn, iso(0), "t2", "New Song", "B")
    result = stats.recent_plays(conn)
    assert [r["track"] for r in result] == ["New Song", "Old Song"]
    assert result[0]["artist"] == "B"


def test_top_tracks_counts_and_cutoff(conn):
    seed(conn, iso(1, hour=10), "t1", "Hit", "A")
    seed(conn, iso(1, hour=11), "t1", "Hit", "A")
    seed(conn, iso(2), "t2", "Other", "B")
    seed(conn, iso(90), "t3", "Ancient", "C")  # outside 30-day window
    result = stats.top_tracks(conn, days=30)
    assert result[0] == {"name": "Hit", "artist": "A", "plays": 2}
    assert all(r["name"] != "Ancient" for r in result)


def test_top_artists_aggregates_across_tracks(conn):
    seed(conn, iso(1, hour=9), "t1", "Song1", "Radiohead")
    seed(conn, iso(1, hour=10), "t2", "Song2", "Radiohead")
    seed(conn, iso(1, hour=11), "t3", "Song3", "Bjork")
    result = stats.top_artists(conn, days=30)
    assert result[0] == {"name": "Radiohead", "plays": 2}


def test_stats_endpoints(client):
    conn = client.app.state.conn
    seed(conn, iso(1), "t1", "Hit", "A")
    r = client.get("/stats/recent")
    assert r.status_code == 200
    assert r.json()[0]["track"] == "Hit"
    r = client.get("/stats/top")
    assert r.status_code == 200
    body = r.json()
    assert body["tracks"][0]["plays"] == 1
    assert body["artists"][0]["name"] == "A"
