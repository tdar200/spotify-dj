import datetime as dt
import sqlite3

from ..enrichment import cache
from .normalize import norm_key
from .profile import Profile

SKIP_WINDOW_DAYS = 14


def _recent_down_artists(conn: sqlite3.Connection, now: float) -> set[str]:
    cutoff = dt.datetime.fromtimestamp(
        now - SKIP_WINDOW_DAYS * 86400, dt.timezone.utc
    ).strftime("%Y-%m-%dT%H:%M:%S")
    rows = conn.execute(
        "SELECT DISTINCT t.artist_name FROM feedback f "
        "JOIN tracks t ON t.id = f.track_id "
        "WHERE f.verdict = 'down' AND f.created_at >= ?",
        (cutoff,),
    )
    return {norm_key(r["artist_name"]) for r in rows}


def rank(
    conn: sqlite3.Connection, profile: Profile, now: float, limit: int = 50
) -> list[dict]:
    downed = _recent_down_artists(conn, now)
    out = []
    rows = conn.execute(
        "SELECT c.track_id, c.seed, c.source, c.weight, "
        "t.name, t.artist_name FROM candidates c "
        "JOIN tracks t ON t.id = c.track_id"
    )
    for r in rows:
        akey = norm_key(r["artist_name"])
        tags = cache.get_tags(conn, "artist", akey)
        overlap_tags = sorted(
            ((profile.tag_weights.get(tag, 0) * w, tag) for tag, w in tags.items()),
            reverse=True,
        )
        tag_overlap = min(sum(v for v, _ in overlap_tags), 1.0)
        proximity = r["weight"]
        if akey in profile.artist_weights:
            novelty = max(0.0, 1 - profile.artist_weights[akey] / 5)
        else:
            novelty = 1.0
        penalty = 2.0 if akey in downed else 0.0
        score = 2.0 * tag_overlap + 1.5 * proximity + 1.0 * novelty - penalty

        why = []
        parts = [
            (2.0 * tag_overlap,
             "tags you love: "
             + ", ".join(t for v, t in overlap_tags[:3] if v > 0)),
            (1.5 * proximity,
             "similar to " + r["seed"].split(":", 1)[1]),
            (1.0 * novelty, "new artist for you"),
        ]
        for value, text in sorted(parts, reverse=True):
            if value > 0:
                why.append(text)
        if penalty:
            why.append("recently disliked this artist")

        out.append({
            "track_id": r["track_id"], "name": r["name"],
            "artist": r["artist_name"], "score": score, "why": why,
            "seed": r["seed"], "source": r["source"],
        })
    out.sort(key=lambda x: -x["score"])
    return out[:limit]
