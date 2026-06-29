"""Shared test helpers: run coroutines, build a MockTransport-backed client, fake search.

Imported by the async fetcher/client tests so the boilerplate lives in one place.
"""

import asyncio

import httpx

from dse_oss_reports.github_client import AsyncGitHubClient


def run(coro):
    """Drive a coroutine to completion (so plain sync tests can exercise async code)."""
    return asyncio.run(coro)


async def noop_sleep(_seconds):
    """An ``asyncio.sleep`` stand-in that returns immediately (no real backoff in tests)."""
    return None


def mock_client(handler, **kw) -> AsyncGitHubClient:
    """An ``AsyncGitHubClient`` whose HTTP is served by ``handler`` (no network, no real sleep)."""
    return AsyncGitHubClient(
        "t", transport=httpx.MockTransport(handler), sleep=noop_sleep, now=lambda: 0.0, **kw
    )


def search_item(number, org, repo, *, is_pr=False, login="alice", state="closed") -> dict:
    """A REST issue/PR search result item (``repository_url``, ``user``, ``pull_request``…)."""
    item = {
        "number": number,
        "title": f"t{number}",
        "state": state,
        "user": {"login": login},
        "html_url": f"https://github.com/{org}/{repo}/issues/{number}",
        "created_at": "2026-02-01T00:00:00Z",
        "updated_at": "2026-03-01T00:00:00Z",
        "repository_url": f"https://api.github.com/repos/{org}/{repo}",
    }
    if is_pr:
        item["pull_request"] = {"url": "https://example/pull"}
    return item


def search_handler(issue_items, pr_items):
    """A MockTransport handler routing /search/issues by the is:issue / is:pr qualifier."""

    def handler(request):
        q = request.url.params.get("q", "")
        items = issue_items if "is:issue" in q else pr_items if "is:pr" in q else []
        return httpx.Response(200, json={"items": items, "total_count": len(items)})

    return handler
