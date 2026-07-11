import base64
import hashlib
import secrets
import sqlite3
import time
from urllib.parse import urlencode

AUTHORIZE_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"
SCOPES = (
    "user-top-read user-read-recently-played user-library-read "
    "user-read-playback-state user-read-currently-playing "
    "user-modify-playback-state playlist-modify-private playlist-modify-public"
)


class NotConnectedError(Exception):
    """No Spotify tokens stored yet — user must visit /auth/login."""


def make_code_verifier() -> str:
    return secrets.token_urlsafe(64)[:128]


def code_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def build_authorize_url(client_id: str, redirect_uri: str, verifier: str) -> str:
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "code_challenge_method": "S256",
        "code_challenge": code_challenge(verifier),
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def save_tokens(
    conn: sqlite3.Connection,
    access_token: str,
    refresh_token: str,
    expires_in: float,
    now: float | None = None,
) -> None:
    expires_at = (time.time() if now is None else now) + expires_in
    conn.execute(
        "INSERT INTO tokens (id, access_token, refresh_token, expires_at) "
        "VALUES (1, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET access_token=excluded.access_token, "
        "refresh_token=excluded.refresh_token, expires_at=excluded.expires_at",
        (access_token, refresh_token, expires_at),
    )
    conn.commit()


def load_tokens(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM tokens WHERE id = 1").fetchone()
