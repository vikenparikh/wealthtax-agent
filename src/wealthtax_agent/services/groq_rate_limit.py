"""P2-AC7 — per-user Groq rate limit.

A simple in-memory rolling-window limiter. The default policy is **60 calls per
3600 seconds per ``user_id``** — the 61st call inside the window raises
``RateLimitExceeded``. The window slides: once a call's timestamp falls outside
``window_seconds``, it stops counting against the user's budget.

The limiter is process-local (no DB / no Redis). That's deliberate — this is a
guardrail against accidental tight loops, not a distributed quota system. For
multi-process throttling, swap the store with the existing
``RateLimitBucket`` row in ``db/repo.py``.

Time is injectable so tests can advance the clock without ``time.sleep``.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Callable, Deque, Dict


class RateLimitExceeded(Exception):
    """Raised when a ``user_id`` exhausts its Groq-call budget for the window."""

    def __init__(self, user_id: str, *, limit: int, window_seconds: int):
        self.user_id = user_id
        self.limit = limit
        self.window_seconds = window_seconds
        super().__init__(
            f"user_id={user_id!r} exceeded {limit} Groq calls within "
            f"{window_seconds} seconds"
        )


class GroqRateLimiter:
    """Sliding-window rate limiter keyed by ``user_id``.

    Examples
    --------
    >>> rl = GroqRateLimiter(limit=60, window_seconds=3600)
    >>> for _ in range(60): rl.record_call("u-1")
    >>> rl.record_call("u-1")  # 61st in the window
    Traceback (most recent call last):
        ...
    wealthtax_agent.services.groq_rate_limit.RateLimitExceeded: ...
    """

    def __init__(
        self,
        *,
        limit: int = 60,
        window_seconds: int = 3600,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        if limit <= 0:
            raise ValueError("limit must be > 0")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self.limit = limit
        self.window_seconds = window_seconds
        self._time_fn = time_fn
        self._calls: Dict[str, Deque[float]] = defaultdict(deque)

    def _evict_expired(self, calls: Deque[float], now: float) -> None:
        cutoff = now - self.window_seconds
        while calls and calls[0] <= cutoff:
            calls.popleft()

    def record_call(self, user_id: str) -> None:
        """Record one Groq call for ``user_id``. Raise if the budget is exhausted.

        The call is recorded **before** the limit check, so a user who is
        already at limit sees the 61st call rejected — matching P2-AC7.
        """
        now = self._time_fn()
        calls = self._calls[user_id]
        self._evict_expired(calls, now)
        if len(calls) >= self.limit:
            raise RateLimitExceeded(
                user_id, limit=self.limit, window_seconds=self.window_seconds
            )
        calls.append(now)

    def remaining(self, user_id: str) -> int:
        """How many more calls this user can make in the current window."""
        now = self._time_fn()
        calls = self._calls[user_id]
        self._evict_expired(calls, now)
        return max(0, self.limit - len(calls))

    def reset(self, user_id: str | None = None) -> None:
        """Clear state for one user, or for everyone when ``user_id`` is None."""
        if user_id is None:
            self._calls.clear()
        else:
            self._calls.pop(user_id, None)


# Module-level default — callers can ``from ... import default_limiter`` for
# the standard 60-per-hour policy without instantiating their own.
default_limiter = GroqRateLimiter()


__all__ = ["RateLimitExceeded", "GroqRateLimiter", "default_limiter"]
