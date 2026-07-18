import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    spotify_client_id: str
    redirect_uri: str
    db_path: Path
    frontend_origin: str
    lastfm_api_key: str


def get_settings() -> Settings:
    return Settings(
        spotify_client_id=os.environ.get("SPOTIFY_CLIENT_ID", ""),
        redirect_uri=os.environ.get(
            "REDIRECT_URI", "http://127.0.0.1:8765/auth/callback"
        ),
        db_path=Path(os.environ.get("DB_PATH", "spotify_dj.sqlite3")),
        frontend_origin=os.environ.get("FRONTEND_ORIGIN", "http://localhost:3001"),
        lastfm_api_key=os.environ.get("LASTFM_API_KEY", ""),
    )
