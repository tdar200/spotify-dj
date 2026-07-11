import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "api.sqlite3"))
    monkeypatch.setenv("SPOTIFY_CLIENT_ID", "test-client-id")
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as tc:
        yield tc


@pytest.fixture
def conn(tmp_path):
    from app import db

    c = db.connect(tmp_path / "test.sqlite3")
    yield c
    c.close()
