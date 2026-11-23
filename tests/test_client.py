import httpx
import pytest

from pipeline.client import ApiClient, ApiError


def scripted(responses):
    calls = iter(responses)

    def handler(request):
        return next(calls)
    return httpx.MockTransport(handler)


def make(responses, **kw):
    sleeps = []
    client = ApiClient(transport=scripted(responses), sleep=sleeps.append, jitter=0, backoff_base=0.5, **kw)
    return client, sleeps


def test_honors_retry_after_on_429():
    client, sleeps = make([httpx.Response(429, headers={"Retry-After": "2.5"}), httpx.Response(200, json={"ok": 1})])
    assert client.get("http://x/y").json() == {"ok": 1}
    assert sleeps == [2.5]
    assert client.stats["rate_limited"] == 1 and client.stats["retries"] == 1


def test_exponential_backoff_on_500():
    client, sleeps = make([httpx.Response(500), httpx.Response(502), httpx.Response(503), httpx.Response(200, json={})])
    client.get("http://x/y")
    assert sleeps == [0.5, 1.0, 2.0]
    assert client.stats["server_errors"] == 3


def test_429_without_header_falls_back_to_backoff():
    client, sleeps = make([httpx.Response(429), httpx.Response(200, json={})])
    client.get("http://x/y")
    assert sleeps == [0.5]


def test_gives_up_after_max_retries():
    client, sleeps = make([httpx.Response(500)] * 4, max_retries=3)
    with pytest.raises(ApiError, match="gave up"):
        client.get("http://x/y")
    assert len(sleeps) == 3


def test_client_errors_are_not_retried():
    client, sleeps = make([httpx.Response(404, text="nope")])
    with pytest.raises(ApiError, match="404"):
        client.get("http://x/y")
    assert sleeps == [] and client.stats["requests"] == 1


def test_retries_transport_errors():
    state = {"n": 0}

    def handler(request):
        state["n"] += 1
        if state["n"] == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, json={"ok": True})

    sleeps = []
    client = ApiClient(transport=httpx.MockTransport(handler), sleep=sleeps.append, jitter=0)
    assert client.get("http://x/y").json() == {"ok": True}
    assert len(sleeps) == 1
