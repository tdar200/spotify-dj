import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tracks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    artist_id TEXT NOT NULL,
    artist_name TEXT NOT NULL,
    album_name TEXT,
    duration_ms INTEGER
);
CREATE TABLE IF NOT EXISTS plays (
    played_at TEXT PRIMARY KEY,
    track_id TEXT NOT NULL REFERENCES tracks(id)
);
CREATE TABLE IF NOT EXISTS artists (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    spotify_id TEXT,
    mbid TEXT
);
CREATE TABLE IF NOT EXISTS tags (
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    tag TEXT NOT NULL,
    weight REAL NOT NULL,
    PRIMARY KEY (source, kind, key, tag)
);
CREATE TABLE IF NOT EXISTS similar_edges (
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    from_key TEXT NOT NULL,
    to_name TEXT NOT NULL,
    to_artist TEXT NOT NULL DEFAULT '',
    weight REAL NOT NULL,
    PRIMARY KEY (source, kind, from_key, to_name, to_artist)
);
CREATE TABLE IF NOT EXISTS enrichment_fetches (
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (source, kind, key)
);
CREATE TABLE IF NOT EXISTS candidates (
    track_id TEXT PRIMARY KEY REFERENCES tracks(id),
    seed TEXT NOT NULL,
    source TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 0,
    added_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id TEXT NOT NULL,
    verdict TEXT NOT NULL CHECK (verdict IN ('up','down','more_like_this')),
    created_at TEXT NOT NULL
);
"""


def connect(db_path: Path | str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    return conn
