from pathlib import Path

from app.config import get_settings


def test_defaults(monkeypatch):
    monkeypatch.delenv("SPOTIFY_CLIENT_ID", raising=False)
    monkeypatch.delenv("REDIRECT_URI", raising=False)
    s = get_settings()
    assert s.redirect_uri == "http://127.0.0.1:8765/auth/callback"
    assert s.frontend_origin == "http://localhost:3001"
    assert s.db_path == Path("spotify_dj.sqlite3")


def test_env_overrides(monkeypatch):
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "abc123")
    monkeypatch.setenv("DB_PATH", "/tmp/x.sqlite3")
    s = get_settings()
    assert s.spotify_client_id == "abc123"
    assert s.db_path == Path("/tmp/x.sqlite3")
