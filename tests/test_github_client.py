"""Tests for AsyncGitHubClient, driven entirely through httpx.MockTransport.

Coroutines are exercised by ``asyncio.run`` inside plain sync tests so no
pytest-asyncio plugin is needed.
"""

import httpx
import pytest

from tests.utils import mock_client, run


def test_graphql_returns_data():
    def handler(request):
        return httpx.Response(200, json={"data": {"ok": 1}})

    async def go():
        async with mock_client(handler) as c:
            return await c.graphql("q", {})

    assert run(go()) == {"ok": 1}


def test_request_retries_on_429_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, json={"message": "secondary rate limit"})
        return httpx.Response(200, json={"data": {"ok": 1}})

    async def go():
        async with mock_client(handler) as c:
            return await c.graphql("q", {})

    assert run(go()) == {"ok": 1}
    assert calls["n"] == 2


def test_graphql_rate_limited_errors_are_retried():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                200, json={"errors": [{"type": "RATE_LIMITED", "message": "slow"}]}
            )
        return httpx.Response(200, json={"data": {"ok": 2}})

    async def go():
        async with mock_client(handler) as c:
            return await c.graphql("q", {})

    assert run(go()) == {"ok": 2}
    assert calls["n"] == 2


def test_non_rate_limit_error_raises_with_body_not_headers():
    def handler(request):
        return httpx.Response(
            404, json={"message": "Not Found"}, headers={"authorization": "secret"}
        )

    async def go():
        async with mock_client(handler) as c:
            return await c.rest("GET", "/repos/x/y")

    with pytest.raises(RuntimeError) as exc:
        run(go())
    assert "404" in str(exc.value)
    assert "secret" not in str(exc.value)  # headers never surfaced


def test_retries_exhausted_raises_rate_limited_message():
    # A sustained 429 must surface "rate limited" so run_outcome fails the run loud.
    def handler(request):
        return httpx.Response(429, json={"message": "throttled"})

    async def go():
        async with mock_client(handler, max_retries=2) as c:
            return await c.graphql("q", {})

    with pytest.raises(RuntimeError) as exc:
        run(go())
    assert "rate limited" in str(exc.value).lower()


def test_graphql_rate_limited_errors_exhausted_raise_rate_limited_message():
    # A sustained GraphQL RATE_LIMITED (200 + errors) must also say "rate limited".
    def handler(request):
        return httpx.Response(200, json={"errors": [{"type": "RATE_LIMITED", "message": "slow"}]})

    async def go():
        async with mock_client(handler, max_retries=1) as c:
            return await c.graphql("q", {})

    with pytest.raises(RuntimeError) as exc:
        run(go())
    assert "rate limited" in str(exc.value).lower()
