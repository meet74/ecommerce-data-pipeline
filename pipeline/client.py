"""HTTP client with retries. Honors Retry-After on 429 and backs off exponentially on 5xx."""
from __future__ import annotations

import random
import time
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from typing import Callable

import httpx

RETRY_STATUS = {500, 502, 503, 504}
MAX_SLEEP = 60.0


class ApiError(RuntimeError):
    pass


def retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
        return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


class ApiClient:
    def __init__(self, headers: dict[str, str] | None = None, max_retries: int = 6, backoff_base: float = 0.5,
                 sleep: Callable[[float], None] = time.sleep, transport: httpx.BaseTransport | None = None,
                 timeout: float = 30.0, jitter: float = 0.1):
        self.http = httpx.Client(headers=headers or {}, transport=transport, timeout=timeout)
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.sleep = sleep
        self.jitter = jitter
        self.stats = {"requests": 0, "retries": 0, "rate_limited": 0, "server_errors": 0, "slept_seconds": 0.0}

    def get(self, url: str, params: dict | None = None) -> httpx.Response:
        attempt = 0
        while True:
            self.stats["requests"] += 1
            wait = None
            reason = ""
            try:
                resp = self.http.get(url, params=params)
            except httpx.TransportError as exc:
                resp, reason = None, f"transport error: {exc.__class__.__name__}"
            if resp is not None:
                if resp.status_code == 429:
                    self.stats["rate_limited"] += 1
                    wait = retry_after_seconds(resp.headers.get("Retry-After"))
                    reason = "429"
                    if wait is None:
                        wait = self._backoff(attempt)
                elif resp.status_code in RETRY_STATUS:
                    self.stats["server_errors"] += 1
                    wait = self._backoff(attempt)
                    reason = str(resp.status_code)
                elif resp.status_code >= 400:
                    raise ApiError(f"GET {url} failed with {resp.status_code}: {resp.text[:200]}")
                else:
                    return resp
            else:
                wait = self._backoff(attempt)
            if attempt >= self.max_retries:
                raise ApiError(f"GET {url} gave up after {attempt + 1} attempts ({reason})")
            attempt += 1
            self.stats["retries"] += 1
            wait = min(wait, MAX_SLEEP)
            self.stats["slept_seconds"] += wait
            self.sleep(wait)

    def _backoff(self, attempt: int) -> float:
        return self.backoff_base * (2 ** attempt) + random.uniform(0, self.jitter)

    def close(self):
        self.http.close()
