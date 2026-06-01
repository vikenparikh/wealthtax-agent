"""P2-AC7 — per-user Groq rate limit.

Pins:

* A burst of **61 Groq calls within one hour for the same ``user_id``** raises
  ``RateLimitExceeded`` on the 61st call.
* The counter **resets after a mocked 3600-second window** — the user can make
  another 60 calls.
* The LLM is mocked at module level so **no actual Groq network call is made**.
* Different ``user_id`` values do not share the same budget.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from wealthtax_agent.services.groq_rate_limit import (
    GroqRateLimiter,
    RateLimitExceeded,
    default_limiter,
)


class _Clock:
    """Cheap monotonic-clock substitute for tests."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


# ---------------------------------------------------------------------------
# Core sliding-window behavior.
# ---------------------------------------------------------------------------
def test_61_calls_in_window_raises_rate_limit_exceeded() -> None:
    """The PRD pin: 61st call within one hour for the same user_id raises."""
    clock = _Clock()
    rl = GroqRateLimiter(limit=60, window_seconds=3600, time_fn=clock)

    for _ in range(60):
        rl.record_call("user-A")

    with pytest.raises(RateLimitExceeded) as excinfo:
        rl.record_call("user-A")

    assert excinfo.value.user_id == "user-A"
    assert excinfo.value.limit == 60
    assert excinfo.value.window_seconds == 3600


def test_counter_resets_after_3600_second_window() -> None:
    """Once the mocked clock advances past the window, the user can call again."""
    clock = _Clock()
    rl = GroqRateLimiter(limit=60, window_seconds=3600, time_fn=clock)

    for _ in range(60):
        rl.record_call("user-A")

    # Still at the cap — next call would raise.
    assert rl.remaining("user-A") == 0
    with pytest.raises(RateLimitExceeded):
        rl.record_call("user-A")

    # Advance past the window. All prior calls fall out.
    clock.advance(3601)
    assert rl.remaining("user-A") == 60

    # Full 60-call budget is available again.
    for _ in range(60):
        rl.record_call("user-A")
    with pytest.raises(RateLimitExceeded):
        rl.record_call("user-A")


def test_partial_window_eviction() -> None:
    """As individual calls age past the window, room opens up incrementally."""
    clock = _Clock()
    rl = GroqRateLimiter(limit=3, window_seconds=10, time_fn=clock)

    rl.record_call("user-A")  # t=0
    clock.advance(4)
    rl.record_call("user-A")  # t=4
    clock.advance(4)
    rl.record_call("user-A")  # t=8

    with pytest.raises(RateLimitExceeded):
        rl.record_call("user-A")

    # t=11 — first call (at t=0) drops out of the 10s window.
    clock.advance(3)
    rl.record_call("user-A")  # succeeds

    # Two more should still be blocked (calls at t=4, t=8, t=11).
    with pytest.raises(RateLimitExceeded):
        rl.record_call("user-A")


def test_different_users_do_not_share_budget() -> None:
    """Per-user isolation: exhausting user-A leaves user-B's budget intact."""
    clock = _Clock()
    rl = GroqRateLimiter(limit=60, window_seconds=3600, time_fn=clock)

    for _ in range(60):
        rl.record_call("user-A")
    with pytest.raises(RateLimitExceeded):
        rl.record_call("user-A")

    # user-B is untouched.
    assert rl.remaining("user-B") == 60
    for _ in range(60):
        rl.record_call("user-B")
    with pytest.raises(RateLimitExceeded):
        rl.record_call("user-B")


def test_remaining_reports_correct_count() -> None:
    clock = _Clock()
    rl = GroqRateLimiter(limit=60, window_seconds=3600, time_fn=clock)

    assert rl.remaining("user-A") == 60
    rl.record_call("user-A")
    assert rl.remaining("user-A") == 59
    for _ in range(59):
        rl.record_call("user-A")
    assert rl.remaining("user-A") == 0


def test_reset_clears_user_state() -> None:
    clock = _Clock()
    rl = GroqRateLimiter(limit=60, window_seconds=3600, time_fn=clock)

    for _ in range(60):
        rl.record_call("user-A")
    rl.reset("user-A")
    assert rl.remaining("user-A") == 60
    rl.record_call("user-A")  # would have raised without reset


def test_reset_all_clears_every_user() -> None:
    clock = _Clock()
    rl = GroqRateLimiter(limit=60, window_seconds=3600, time_fn=clock)

    for _ in range(60):
        rl.record_call("user-A")
    for _ in range(60):
        rl.record_call("user-B")
    rl.reset()  # no arg → clear all
    assert rl.remaining("user-A") == 60
    assert rl.remaining("user-B") == 60


def test_invalid_construction_args_rejected() -> None:
    with pytest.raises(ValueError):
        GroqRateLimiter(limit=0)
    with pytest.raises(ValueError):
        GroqRateLimiter(window_seconds=0)


def test_default_limiter_uses_60_per_hour() -> None:
    """The module-level singleton is the 60/3600 policy the PRD calls out."""
    assert default_limiter.limit == 60
    assert default_limiter.window_seconds == 3600


# ---------------------------------------------------------------------------
# LLM-mocked-at-module-level guarantee.
# ---------------------------------------------------------------------------
def test_no_groq_network_call_made_when_limiter_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even in a burst, no Groq network call fires.

    We patch ``OpenAI`` (the Groq-compatible client) at the ``llm`` module
    level. The limiter is independent of the client — exercising it must never
    touch the network.
    """
    import wealthtax_agent.llm as llm_module

    sentinel = object()

    class _NoNetworkClient:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError(
                "OpenAI client constructed during rate-limit test — "
                "network path must be mocked"
            )

    monkeypatch.setattr(llm_module, "OpenAI", _NoNetworkClient)

    clock = _Clock()
    rl = GroqRateLimiter(limit=60, window_seconds=3600, time_fn=clock)

    for _ in range(60):
        rl.record_call("user-A")
    with pytest.raises(RateLimitExceeded):
        rl.record_call("user-A")

    # No instantiation happened — the assertion inside _NoNetworkClient never fired.
    assert sentinel is sentinel  # sanity check that the test ran end-to-end


def test_pure_python_no_env_var_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """The limiter must work without GROQ_API_KEY / ANTHROPIC_API_KEY set."""
    for key in ("GROQ_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    rl = GroqRateLimiter(limit=2, window_seconds=10, time_fn=_Clock())
    rl.record_call("u-1")
    rl.record_call("u-1")
    with pytest.raises(RateLimitExceeded):
        rl.record_call("u-1")
