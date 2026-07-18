import datetime as dt

import pytest

from app.enrichment import cache
from app.taste.profile import Profile
from app.taste.ranker import rank

NOW = dt.datetime(2026, 7, 18, tzinfo=dt.timezone.utc).timestamp()


def seed(conn):
    conn.execute(
        "INSERT INTO tracks VALUES ('c1','Sprinter','a9','Dave','alb',200000)"
    )
    conn.execute(
        "INSERT INTO candidates VALUES "
        "('c1','artist:central cee','lastfm',0.9,'2026-07-18T00:00:00.000Z')"
    )
    conn.commit()


def test_scores_and_why(conn):
    seed(conn)
    cache.store_tags(conn, "lastfm", "artist", "dave",
                     [{"tag": "uk rap", "weight": 1.0}])
    profile = Profile(artist_weights={"central cee": 3.0},
                      tag_weights={"uk rap": 1.0})
    out = rank(conn, profile, NOW)
    assert len(out) == 1
    r = out[0]
    # tag_overlap=1.0 cap, proximity=0.9, novelty=1.0 (dave unknown), no penalty
    assert r["score"] == pytest.approx(2.0 * 1.0 + 1.5 * 0.9 + 1.0)
    assert r["why"][0] == "tags you love: uk rap"
    assert "similar to central cee" in r["why"]
    assert "new artist for you" in r["why"]


def test_known_artist_novelty_shrinks(conn):
    seed(conn)
    profile = Profile(artist_weights={"dave": 2.5}, tag_weights={})
    r = rank(conn, profile, NOW)[0]
    # novelty = 1 - 2.5/5 = 0.5 ; no tags → overlap 0
    assert r["score"] == pytest.approx(1.5 * 0.9 + 0.5)


def test_recent_down_feedback_penalizes(conn):
    seed(conn)
    conn.execute(
        "INSERT INTO feedback (track_id, verdict, created_at) "
        "VALUES ('c1','down','2026-07-17T00:00:00.000Z')"
    )
    conn.commit()
    profile = Profile(artist_weights={}, tag_weights={})
    r = rank(conn, profile, NOW)[0]
    assert r["score"] == pytest.approx(1.5 * 0.9 + 1.0 - 2.0)
    assert "recently disliked this artist" in r["why"]


def test_limit_and_order(conn):
    seed(conn)
    conn.execute(
        "INSERT INTO tracks VALUES ('c2','Low','a8','Aitch','alb',1)"
    )
    conn.execute(
        "INSERT INTO candidates VALUES "
        "('c2','artist:central cee','lastfm',0.2,'2026-07-18T00:00:00.000Z')"
    )
    conn.commit()
    profile = Profile(artist_weights={}, tag_weights={})
    out = rank(conn, profile, NOW, limit=1)
    assert [r["track_id"] for r in out] == ["c1"]
