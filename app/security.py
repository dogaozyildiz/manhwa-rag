"""T6 (docs/THREAT_MODEL.md): access control and consumption limits for the API.

Before this module, anyone who could reach `/ask` could spend the Groq quota --
on the free tier that is ~65 calls a day before every user gets errors.

Three controls, all in-process (honest scope for a single-process service; a
multi-instance deployment needs a shared store such as Redis):

* `require_api_key` -- if API_KEY is set, /ask and /retrieve need X-API-Key.
* `rate_limited`    -- sliding window per client, RATE_LIMIT_PER_MINUTE.
* `llm_budget`      -- hard cap on generation calls per UTC day,
                       LLM_DAILY_BUDGET, so a quota cannot be drained by one
                       client rotating IPs.

The HTMX web UI cannot send a header, so it is switched off when an API key is
configured: a protected deployment exposes the API only.
"""

from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque
from collections.abc import Callable
from datetime import date, datetime, timezone

from fastapi import Header, HTTPException, Request

from app.config import get_settings


class SlidingWindow:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._clock = clock

    def allow(self, key: str, limit: int, window: float = 60.0) -> bool:
        now = self._clock()
        hits = self._hits[key]
        while hits and now - hits[0] >= window:
            hits.popleft()
        if len(hits) >= limit:
            return False
        hits.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


class DailyBudget:
    def __init__(self, today: Callable[[], date] = lambda: datetime.now(timezone.utc).date()) -> None:
        self._today = today
        self._day: date | None = None
        self.used = 0

    def take(self, limit: int) -> bool:
        day = self._today()
        if day != self._day:
            self._day, self.used = day, 0
        if self.used >= limit:
            return False
        self.used += 1
        return True

    def reset(self) -> None:
        self._day, self.used = None, 0


window = SlidingWindow()
budget = DailyBudget()


def _client_id(request: Request) -> str:
    # Direct peer address. Behind a reverse proxy this is the proxy; configure
    # uvicorn's --proxy-headers / forwarded-allow-ips there, never trust
    # X-Forwarded-For blindly.
    return request.client.host if request.client else "unknown"


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    expected = get_settings().api_key
    if not expected:
        return
    if not x_api_key or not hmac.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="invalid or missing API key")


async def rate_limited(request: Request) -> None:
    limit = get_settings().rate_limit_per_minute
    if limit > 0 and not window.allow(_client_id(request), limit):
        raise HTTPException(
            status_code=429, detail="rate limit exceeded", headers={"Retry-After": "60"}
        )


async def llm_budget() -> None:
    limit = get_settings().llm_daily_budget
    if limit > 0 and not budget.take(limit):
        raise HTTPException(status_code=429, detail="daily generation budget exhausted")


async def ui_enabled() -> None:
    if get_settings().api_key:
        raise HTTPException(status_code=404)
