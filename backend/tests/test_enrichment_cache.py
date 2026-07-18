from app.enrichment import cache

NOW = "2026-07-18T12:00:00Z"


def test_fetched_roundtrip(conn):
    assert not cache.was_fetched(conn, "lastfm", "artist", "dave")
    cache.mark_fetched(conn, "lastfm", "artist", "dave", NOW)
    assert cache.was_fetched(conn, "lastfm", "artist", "dave")


def test_tags_merge_max_across_sources(conn):
    cache.store_tags(conn, "lastfm", "artist", "dave",
                     [{"tag": "uk rap", "weight": 0.9}])
    cache.store_tags(conn, "listenbrainz", "artist", "dave",
                     [{"tag": "uk rap", "weight": 0.4},
                      {"tag": "grime", "weight": 0.6}])
    assert cache.get_tags(conn, "artist", "dave") == {"uk rap": 0.9, "grime": 0.6}


def test_edges_roundtrip_ordered(conn):
    cache.store_edges(conn, "lastfm", "artist", "central cee",
                      [{"name": "Aitch", "match": 0.5},
                       {"name": "Dave", "match": 0.9}])
    cache.store_edges(conn, "lastfm", "track", "central cee|crg",
                      [{"artist": "Dave", "name": "Sprinter", "match": 0.8}])
    artist_edges = cache.get_edges(conn, "artist", "central cee")
    assert [e["to_name"] for e in artist_edges] == ["Dave", "Aitch"]
    assert artist_edges[0]["to_artist"] == ""
    track_edges = cache.get_edges(conn, "track", "central cee|crg")
    assert track_edges[0] == {
        "source": "lastfm", "to_name": "Sprinter",
        "to_artist": "Dave", "weight": 0.8,
    }


def test_store_edges_idempotent(conn):
    edges = [{"name": "Dave", "match": 0.9}]
    cache.store_edges(conn, "lastfm", "artist", "x", edges)
    cache.store_edges(conn, "lastfm", "artist", "x", edges)
    assert len(cache.get_edges(conn, "artist", "x")) == 1
