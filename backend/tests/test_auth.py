from urllib.parse import parse_qs, urlparse

from app import auth


def test_code_challenge_rfc7636_vector():
    # Appendix B of RFC 7636
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    assert auth.code_challenge(verifier) == "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def test_verifier_length_and_uniqueness():
    a, b = auth.make_code_verifier(), auth.make_code_verifier()
    assert 43 <= len(a) <= 128
    assert a != b


def test_build_authorize_url():
    url = auth.build_authorize_url(
        "cid", "http://127.0.0.1:8765/auth/callback", "some-verifier"
    )
    parsed = urlparse(url)
    q = parse_qs(parsed.query)
    assert url.startswith(auth.AUTHORIZE_URL + "?")
    assert q["client_id"] == ["cid"]
    assert q["response_type"] == ["code"]
    assert q["redirect_uri"] == ["http://127.0.0.1:8765/auth/callback"]
    assert q["code_challenge_method"] == ["S256"]
    assert q["code_challenge"] == [auth.code_challenge("some-verifier")]
    assert "user-read-recently-played" in q["scope"][0]


def test_save_and_load_tokens(conn):
    auth.save_tokens(conn, "acc", "ref", 3600, now=1000.0)
    row = auth.load_tokens(conn)
    assert row["access_token"] == "acc"
    assert row["refresh_token"] == "ref"
    assert row["expires_at"] == 4600.0


def test_save_tokens_overwrites_single_row(conn):
    auth.save_tokens(conn, "acc1", "ref1", 3600, now=0.0)
    auth.save_tokens(conn, "acc2", "ref2", 3600, now=0.0)
    assert auth.load_tokens(conn)["access_token"] == "acc2"
    assert conn.execute("SELECT COUNT(*) AS c FROM tokens").fetchone()["c"] == 1


def test_load_tokens_empty(conn):
    assert auth.load_tokens(conn) is None
