"""Single async seam for GitHub I/O: GraphQL + a thin REST bridge, request-level retry.

The only thing in the codebase that touches GitHub. Retry happens per request, so a
throttle deep in a paginated fetch redoes one page, not the whole task. The token
lives only inside the httpx client's default headers — never stored as an attribute
that a repr/log could leak.
"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

import httpx

from dse_oss_reports.retry import (
    DEFAULT_MAX_RETRIES,
    RateLimitExhausted,
    is_rate_limited,
    retry_delay,
)

logger = logging.getLogger(__name__)

_API_BASE = "https://api.github.com"


def search_item_repo(item: dict) -> tuple[str, str]:
    """Extract ``(owner, name)`` from a REST search item's ``repository_url``."""
    url = item.get("repository_url", "")
    _head, sep, tail = url.partition("/repos/")
    if not sep:
        return "", ""
    owner, _, name = tail.partition("/")
    return owner, name


class AsyncGitHubClient:
    def __init__(
        self,
        token: str | None,
        *,
        concurrency: int = 10,
        max_retries: int = DEFAULT_MAX_RETRIES,
        search_concurrency: int = 1,
        search_min_interval: float = 2.0,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        now: Callable[[], float] = time.time,
    ) -> None:
        headers = {"Accept": "application/vnd.github+json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"  # token lives only here
        self._http = httpx.AsyncClient(
            base_url=_API_BASE, headers=headers, transport=transport, timeout=30.0
        )
        self._sem = asyncio.Semaphore(concurrency)
        self._max_retries = max_retries
        # GitHub's Search API has a separate, low limit (~30 req/min). Serialize search
        # and space requests so a backoff actually lets the limit clear, instead of 10
        # concurrent searches sustaining a secondary 403 until retries exhaust.
        self._search_sem = asyncio.Semaphore(search_concurrency)
        self._search_min_interval = search_min_interval
        self._last_search_at = 0.0
        self._sleep = sleep
        self._now = now

    async def __aenter__(self) -> "AsyncGitHubClient":
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        attempt = 0
        while True:
            async with self._sem:
                response = await self._http.request(method, url, **kwargs)
            if response.status_code < 400:
                return response
            body = response.text
            if is_rate_limited(response.status_code, body):
                # Throttle exhaustion is a typed error so run_outcome fails the run loud
                # by class (a sustained throttle won't clear by degrading one unit).
                if attempt >= self._max_retries:
                    raise RateLimitExhausted(
                        f"GitHub {method} {url} rate limited; retries exhausted "
                        f"({response.status_code})"
                    )
                delay = retry_delay(dict(response.headers), attempt, now=self._now)
                if delay is None:
                    raise RateLimitExhausted(
                        f"GitHub {method} {url} rate limited; reset too far to wait"
                    )
                logger.warning(
                    f"GitHub throttled {method} {url}; "
                    f"retry {attempt + 1}/{self._max_retries} in {delay:.0f}s"
                )
                await self._sleep(delay)
                attempt += 1
                continue
            raise RuntimeError(f"GitHub {method} {url} -> {response.status_code}: {body[:500]}")

    async def graphql(self, query: str, variables: dict) -> dict:
        attempt = 0
        while True:
            response = await self._request(
                "POST", "/graphql", json={"query": query, "variables": variables}
            )
            data = response.json()
            errors = data.get("errors")
            if errors:
                rate_limited = any((e or {}).get("type") == "RATE_LIMITED" for e in errors)
                if rate_limited:
                    delay = retry_delay(dict(response.headers), attempt, now=self._now)
                    if attempt >= self._max_retries or delay is None:
                        raise RateLimitExhausted("GraphQL rate limited; retries exhausted")
                    logger.warning(
                        f"GitHub GraphQL throttled; "
                        f"retry {attempt + 1}/{self._max_retries} in {delay:.0f}s"
                    )
                    await self._sleep(delay)
                    attempt += 1
                    continue
                raise RuntimeError(f"GraphQL errors: {errors}")
            return data["data"]

    async def rest(self, method: str, path: str, **kwargs) -> httpx.Response:
        return await self._request(method, path, **kwargs)

    async def search_issues(
        self, query: str, *, per_page: int = 100, max_pages: int = 10
    ) -> list[dict]:
        """Paginate GitHub's REST issue/PR search, returning raw item dicts.

        Search caps at 1000 results (10 pages of 100); ``max_pages`` enforces that. A
        stable ``created asc`` sort is requested so multi-page results don't skip or
        duplicate items (the default "best match" relevance order is non-deterministic
        across page requests). Each item is a REST search result (``repository_url``,
        ``user``, ``pull_request``…).
        """
        items: list[dict] = []
        page = 1
        while page <= max_pages:
            response = await self._search_request(
                params={
                    "q": query,
                    "per_page": per_page,
                    "page": page,
                    "sort": "created",
                    "order": "asc",
                }
            )
            data = response.json()
            if data.get("incomplete_results"):
                logger.warning("GitHub search timed out (incomplete_results) for: %s", query)
            batch = data.get("items", [])
            items.extend(batch)
            if len(batch) < per_page:
                break
            page += 1
        return items

    async def _search_request(self, *, params: dict) -> httpx.Response:
        """One paced, serialized /search/issues request.

        Holding ``_search_sem`` across the request (and any internal backoff) keeps
        concurrent searches at ``search_concurrency`` so a throttle backoff isn't
        undone by other in-flight searches; ``_search_min_interval`` spaces requests
        to stay under the Search API's ~30/min budget.
        """
        async with self._search_sem:
            wait = self._search_min_interval - (self._now() - self._last_search_at)
            if wait > 0:
                await self._sleep(wait)
            try:
                return await self._request("GET", "/search/issues", params=params)
            finally:
                self._last_search_at = self._now()
