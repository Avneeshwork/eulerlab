"""Polite HTTP fetching: rate limited, backed off, and bounded.

Three rules this module exists to enforce.

**Never use HEAD.** NSE's legacy archive answers ``HEAD`` with 403/503 while
answering ``GET`` with 200 for the very same URL. The obvious optimisation —
HEAD to test existence before downloading — would report thousands of present
trading days as missing. There is no HEAD anywhere in this module, and that is
deliberate. See ``docs/RESEARCH/002-nse-eod-sources-and-schemas.md``.

**404 is an answer, not a failure.** A missing file usually means the market was
shut. It is returned as ``ABSENT`` and never retried; retrying it would multiply
our request count by the retry budget for every holiday in eleven years.

**Give up rather than hammer.** A bounded retry budget with exponential backoff
and jitter, and a minimum gap between every request. If the archive is
struggling, the correct behaviour is to stop and report, not to push harder.
"""

from __future__ import annotations

import random
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from http.cookiejar import CookieJar
from typing import Protocol

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
SESSION_URL = "https://www.nseindia.com/all-reports"
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class TransportError(Exception):
    """The request did not complete: DNS, connection, timeout, TLS."""


class Transport(Protocol):
    """Minimal HTTP surface, so the fetcher can be tested without a network."""

    def get(self, url: str, *, timeout: float) -> tuple[int, bytes]: ...


class Outcome(StrEnum):
    OK = "ok"
    ABSENT = "absent"
    """The server said 404. The file is not published for this date."""
    FAILED = "failed"
    """Retries exhausted. This is data loss, not a holiday."""


@dataclass(frozen=True)
class FetchResult:
    outcome: Outcome
    url: str
    payload: bytes | None = None
    status: int | None = None
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.outcome is Outcome.OK


class UrllibTransport:
    """stdlib HTTP. No third-party dependency for something this simple.

    Carries a cookie jar because NSE hands out a session cookie on first visit
    and its archive hosts may expect it. Whether it is strictly required was not
    isolated during research; establishing one costs a single request.
    """

    def __init__(self, user_agent: str = DEFAULT_USER_AGENT) -> None:
        self.user_agent = user_agent
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self.user_agent,
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": SESSION_URL,
        }

    def establish_session(self, timeout: float = 30.0) -> None:
        """Visit the reports page once so the archive sees a normal session."""
        try:
            self.get(SESSION_URL, timeout=timeout)
        except (TransportError, OSError):
            # Not fatal: the archive may not need it. The first real request
            # will tell us either way.
            return

    def get(self, url: str, *, timeout: float) -> tuple[int, bytes]:
        request = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with self._opener.open(request, timeout=timeout) as response:
                status: int = response.status
                return status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportError(str(exc)) from exc


@dataclass(frozen=True)
class FetchPolicy:
    """How hard we are willing to push. Defaults chosen to be unremarkable."""

    min_interval_s: float = 1.5
    """Minimum gap between requests."""

    max_attempts: int = 4
    backoff_base_s: float = 2.0
    backoff_cap_s: float = 60.0
    timeout_s: float = 45.0
    jitter_seed: int = 0
    """Seeded so a run is reproducible. Determinism is a project-wide rule."""


class Fetcher:
    """Wraps a Transport with rate limiting and bounded retries."""

    def __init__(
        self,
        transport: Transport,
        policy: FetchPolicy | None = None,
        *,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.transport = transport
        self.policy = policy or FetchPolicy()
        self._sleep = sleep
        self._clock = clock
        self._random = random.Random(self.policy.jitter_seed)
        self._last_request_at: float | None = None

    def _wait_for_slot(self) -> None:
        if self._last_request_at is None:
            return
        elapsed = self._clock() - self._last_request_at
        remaining = self.policy.min_interval_s - elapsed
        if remaining > 0:
            self._sleep(remaining)

    def _backoff(self, attempt: int) -> float:
        raw = self.policy.backoff_base_s * (2.0 ** (attempt - 1))
        capped = min(raw, self.policy.backoff_cap_s)
        jitter: float = self._random.random()
        return capped * (0.5 + jitter)

    def get(self, url: str) -> FetchResult:
        last_detail = ""
        last_status: int | None = None
        for attempt in range(1, self.policy.max_attempts + 1):
            self._wait_for_slot()
            try:
                status, payload = self.transport.get(url, timeout=self.policy.timeout_s)
            except TransportError as exc:
                self._last_request_at = self._clock()
                last_detail = f"transport error: {exc}"
            else:
                self._last_request_at = self._clock()
                if status == 404:
                    return FetchResult(Outcome.ABSENT, url, status=404)
                if 200 <= status < 300:
                    return FetchResult(Outcome.OK, url, payload=payload, status=status)
                last_detail = f"HTTP {status}"
                last_status = status
                if status not in RETRYABLE_STATUS:
                    return FetchResult(Outcome.FAILED, url, status=status, detail=last_detail)
            if attempt < self.policy.max_attempts:
                self._sleep(self._backoff(attempt))

        return FetchResult(
            Outcome.FAILED,
            url,
            status=last_status,
            detail=f"{last_detail} after {self.policy.max_attempts} attempts",
        )
