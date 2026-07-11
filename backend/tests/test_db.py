from app import db


def test_tables_created(conn):
    names = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"tokens", "tracks", "plays"} <= names


def test_connect_is_idempotent(tmp_path):
    path = tmp_path / "x.sqlite3"
    db.connect(path).close()
    db.connect(path).close()  # second run must not fail


def test_duplicate_play_ignored(conn):
    conn.execute(
        "INSERT INTO tracks (id, name, artist_id, artist_name) "
        "VALUES ('t1', 'Song', 'a1', 'Artist')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO plays VALUES ('2026-07-12T10:00:00.000Z', 't1')"
    )
    conn.execute(
        "INSERT OR IGNORE INTO plays VALUES ('2026-07-12T10:00:00.000Z', 't1')"
    )
    assert conn.execute("SELECT COUNT(*) AS c FROM plays").fetchone()["c"] == 1


def test_tokens_single_row_constraint(conn):
    import sqlite3

    import pytest

    conn.execute("INSERT INTO tokens VALUES (1, 'a', 'r', 0)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO tokens VALUES (2, 'b', 'r', 0)")
