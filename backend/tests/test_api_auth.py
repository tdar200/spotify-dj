import httpx
import respx

from app import auth


def test_login_redirects_to_spotify(client):
    r = client.get("/auth/login", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"].startswith(auth.AUTHORIZE_URL + "?")
    assert "client_id=test-client-id" in r.headers["location"]


def test_status_disconnected(client):
    assert client.get("/auth/status").json() == {"connected": False}


@respx.mock
def test_callback_exchanges_and_connects(client):
    respx.route(host="testserver").pass_through()  # let TestClient through
    client.get("/auth/login", follow_redirects=False)  # sets the verifier
    respx.post(auth.TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={"access_token": "a", "refresh_token": "r", "expires_in": 3600},
        )
    )
    r = client.get("/auth/callback", params={"code": "abc"}, follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "http://localhost:3001"
    assert client.get("/auth/status").json() == {"connected": True}
