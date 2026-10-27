import httpx
import pytest
import respx

from ozon_sync.config import Settings
from ozon_sync.ozon.client import OzonClient, OzonError

BASE = "https://ozon.test"


def make_client(env="prod", **overrides):
    settings = Settings(
        _env_file=None,
        ozon_env=env,
        ozon_client_id="cid",
        ozon_api_key="key",
        ozon_sandbox_client_id="scid",
        ozon_sandbox_client_secret="ssecret",
        **overrides,
    )
    sleeps = []
    client = OzonClient(settings, http=httpx.Client(base_url=BASE), sleep=sleeps.append)
    return client, sleeps


@respx.mock
def test_prod_auth_headers():
    route = respx.post(f"{BASE}/v1/warehouse/list").respond(json={"result": []})
    client, _ = make_client()
    client.post("/v1/warehouse/list")
    headers = route.calls.last.request.headers
    assert headers["Client-Id"] == "cid"
    assert headers["Api-Key"] == "key"


@respx.mock
def test_429_waits_retry_after():
    respx.post(f"{BASE}/x").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(429),
            httpx.Response(200, json={"ok": 1}),
        ]
    )
    client, sleeps = make_client()
    assert client.post("/x") == {"ok": 1}
    assert sleeps == [7.0, 1.0]


@respx.mock
def test_429_gives_up_eventually():
    respx.post(f"{BASE}/x").respond(429, headers={"Retry-After": "0"})
    client, _ = make_client(ozon_max_429_retries=2)
    with pytest.raises(OzonError, match="429"):
        client.post("/x")


@respx.mock
def test_5xx_retries_with_backoff_then_fails():
    route = respx.post(f"{BASE}/x").respond(502)
    client, sleeps = make_client()
    with pytest.raises(OzonError, match="502"):
        client.post("/x")
    assert route.call_count == 4
    assert sleeps == [1, 2, 4]


@respx.mock
def test_network_error_recovers():
    respx.post(f"{BASE}/x").mock(side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json={})])
    client, sleeps = make_client()
    assert client.post("/x") == {}
    assert sleeps == [1]


@respx.mock
def test_4xx_fails_without_retry():
    route = respx.post(f"{BASE}/x").respond(404, text="not found")
    client, _ = make_client()
    with pytest.raises(OzonError, match="404"):
        client.post("/x")
    assert route.call_count == 1


@respx.mock
def test_ratelimit_remaining_zero_waits_reset():
    respx.post(f"{BASE}/x").respond(200, json={}, headers={"Ratelimit-Remaining": "0", "Ratelimit-Reset": "3"})
    client, sleeps = make_client()
    client.post("/x")
    assert sleeps == [3.0]


@respx.mock
def test_sandbox_oauth_token_cached():
    token = respx.post(f"{BASE}/oauth/token").respond(json={"access_token": "tok", "expires_in": 3600})
    api = respx.post(f"{BASE}/x").respond(json={})
    client, _ = make_client(env="sandbox")
    client.post("/x")
    client.post("/x")
    assert token.call_count == 1
    assert api.calls.last.request.headers["Authorization"] == "Bearer tok"
    assert b"client_secret=ssecret" in token.calls.last.request.content


@respx.mock
def test_sandbox_401_refreshes_token():
    token = respx.post(f"{BASE}/oauth/token").respond(json={"access_token": "tok", "expires_in": 3600})
    respx.post(f"{BASE}/x").mock(side_effect=[httpx.Response(401), httpx.Response(200, json={"ok": 1})])
    client, _ = make_client(env="sandbox")
    assert client.post("/x") == {"ok": 1}
    assert token.call_count == 2


@respx.mock
def test_paginate_last_id_until_empty_page():
    route = respx.post(f"{BASE}/p").mock(
        side_effect=[
            httpx.Response(200, json={"items": [1, 2], "last_id": "a"}),
            httpx.Response(200, json={"items": [3], "last_id": "b"}),
            httpx.Response(200, json={"items": [], "last_id": ""}),
        ]
    )
    client, _ = make_client()
    assert list(client.paginate_last_id("/p", {"limit": 2}, lambda r: r["items"])) == [1, 2, 3]
    assert [c.request.content for c in route.calls][1] == b'{"limit":2,"last_id":"a"}'


@respx.mock
def test_paginate_offset():
    respx.post(f"{BASE}/p").mock(
        side_effect=[
            httpx.Response(200, json={"r": [1, 2]}),
            httpx.Response(200, json={"r": [3]}),
            httpx.Response(200, json={"r": []}),
        ]
    )
    client, _ = make_client()
    assert list(client.paginate_offset("/p", {}, lambda r: r["r"], limit=2)) == [1, 2, 3]
