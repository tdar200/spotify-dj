import datetime as dt

import pytest

from app.enrichment import cache
from app.taste.profile import Profile, build_profile

NOW = dt.datetime(2026, 7, 18, tzinfo=dt.timezone.utc).timestamp()


def iso(days_ago: float) -> str:
    d = dt.datetime.fromtimestamp(NOW, dt.timezone.utc) - dt.timedelta(days=days_ago)
    return d.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def seed(conn):
    conn.execute(
        "INSERT INTO tracks VALUES ('t1','CRG','a1','Central Cee','alb',180000)"
    )
    conn.execute(
        "INSERT INTO tracks VALUES ('t2','Meri Kahani','a2','Atif Aslam','alb',200000)"
    )
    conn.execute("INSERT INTO plays VALUES (?, 't1')", (iso(0),))
    conn.execute("INSERT INTO plays VALUES (?, 't1')", (iso(30),))
    conn.execute("INSERT INTO plays VALUES (?, 't2')", (iso(60),))
    conn.commit()


def test_play_weights_decay(conn):
    seed(conn)
    p = build_profile(conn, NOW)
    # central cee: 0.5**0 + 0.5**1 = 1.5 ; atif aslam: 0.5**2 = 0.25
    assert p.artist_weights["central cee"] == pytest.approx(1.5)
    assert p.artist_weights["atif aslam"] == pytest.approx(0.25)


def test_saved_and_top_bootstrap(conn):
    seed(conn)
    p = build_profile(
        conn, NOW,
        top_artists=["Atif Aslam", "Talha Anjum"],
        saved_artists=["Central Cee", "Central Cee"],
    )
    # atif: 0.25 + 3.0*(1-0/2)=3.25 ; talha: 3.0*(1-1/2)=1.5 ; cee: 1.5+2*0.5=2.5
    assert p.artist_weights["atif aslam"] == pytest.approx(3.25)
    assert p.artist_weights["talha anjum"] == pytest.approx(1.5)
    assert p.artist_weights["central cee"] == pytest.approx(2.5)


def test_feedback_adjusts(conn):
    seed(conn)
    conn.execute(
        "INSERT INTO feedback (track_id, verdict, created_at) "
        "VALUES ('t2','down',?)", (iso(1),)
    )
    conn.commit()
    p = build_profile(conn, NOW)
    assert p.artist_weights["atif aslam"] == pytest.approx(0.25 - 2.0)


def test_tag_vector_normalized(conn):
    seed(conn)
    cache.store_tags(conn, "lastfm", "artist", "central cee",
                     [{"tag": "uk rap", "weight": 1.0}])
    cache.store_tags(conn, "lastfm", "artist", "atif aslam",
                     [{"tag": "pop", "weight": 0.5}])
    p = build_profile(conn, NOW)
    # uk rap: 1.5*1.0=1.5 ; pop: 0.25*0.5=0.125 → /1.5
    assert p.tag_weights["uk rap"] == pytest.approx(1.0)
    assert p.tag_weights["pop"] == pytest.approx(0.125 / 1.5)


def test_empty_db_empty_profile(conn):
    p = build_profile(conn, NOW)
    assert p == Profile(artist_weights={}, tag_weights={})
