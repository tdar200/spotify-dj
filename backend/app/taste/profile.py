import datetime as dt
import sqlite3
from collections import defaultdict
from dataclasses import dataclass

from ..enrichment import cache
from .normalize import norm_key

HALF_LIFE_DAYS = 30.0
SAVED_WEIGHT = 0.5
TOP_ARTIST_WEIGHT = 3.0
FEEDBACK_WEIGHTS = {"up": 2.0, "more_like_this": 3.0, "down": -2.0}


@dataclass(frozen=True)
class Profile:
    artist_weights: dict[str, float]
    tag_weights: dict[str, float]


def _age_days(played_at: str, now: float) -> float:
    t = dt.datetime.fromisoformat(played_at.replace("Z", "+00:00"))
    return max((now - t.timestamp()) / 86400, 0.0)


def build_profile(
    conn: sqlite3.Connection,
    now: float,
    top_artists: list[str] = (),
    saved_artists: list[str] = (),
) -> Profile:
    weights: dict[str, float] = defaultdict(float)

    rows = conn.execute(
        "SELECT p.played_at, t.artist_name FROM plays p "
        "JOIN tracks t ON t.id = p.track_id"
    )
    for r in rows:
        weights[norm_key(r["artist_name"])] += 0.5 ** (
            _age_days(r["played_at"], now) / HALF_LIFE_DAYS
        )

    for name in saved_artists:
        weights[norm_key(name)] += SAVED_WEIGHT

    n = len(top_artists)
    for rank, name in enumerate(top_artists):
        weights[norm_key(name)] += TOP_ARTIST_WEIGHT * (1 - rank / n)

    rows = conn.execute(
        "SELECT f.verdict, t.artist_name FROM feedback f "
        "JOIN tracks t ON t.id = f.track_id"
    )
    for r in rows:
        weights[norm_key(r["artist_name"])] += FEEDBACK_WEIGHTS[r["verdict"]]

    tag_weights: dict[str, float] = defaultdict(float)
    for key, w in weights.items():
        if w <= 0:
            continue
        for tag, tw in cache.get_tags(conn, "artist", key).items():
            tag_weights[tag] += w * tw
    if tag_weights:
        top = max(tag_weights.values())
        tag_weights = {t: v / top for t, v in tag_weights.items()}

    return Profile(artist_weights=dict(weights), tag_weights=dict(tag_weights))
