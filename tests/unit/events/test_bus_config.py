"""Config-plumbing tests for events/bus.py.

The existing ``test_bus.py`` exercises publish/subscribe routing and idle
tolerance, but never touches the environment-variable parsing helpers
(``_opt_float`` / ``_opt_int``) or the ``socket_timeout`` branch of
``_client_kwargs``. Those helpers decide how the Redis client is tuned, so a
silent regression (e.g. a negative timeout leaking through) would degrade the
consumer's idle resilience without any test catching it.

Each helper is a pure function of ``os.environ``: empty/missing -> fallback,
unparseable -> fallback, non-positive -> fallback, valid positive -> the value.
These tests pin every one of those branches against real outputs.
"""

from __future__ import annotations

import wealthtax_agent.events.bus as bus


# --- _opt_float --------------------------------------------------------------


def test_opt_float_missing_env_returns_none(monkeypatch):
    monkeypatch.delenv("WT_TEST_OPT_FLOAT", raising=False)
    assert bus._opt_float("WT_TEST_OPT_FLOAT") is None


def test_opt_float_empty_string_returns_none(monkeypatch):
    monkeypatch.setenv("WT_TEST_OPT_FLOAT", "")
    assert bus._opt_float("WT_TEST_OPT_FLOAT") is None


def test_opt_float_unparseable_returns_none(monkeypatch):
    monkeypatch.setenv("WT_TEST_OPT_FLOAT", "not-a-number")
    assert bus._opt_float("WT_TEST_OPT_FLOAT") is None


def test_opt_float_zero_returns_none(monkeypatch):
    # value <= 0 is rejected: a zero/negative timeout is meaningless here.
    monkeypatch.setenv("WT_TEST_OPT_FLOAT", "0")
    assert bus._opt_float("WT_TEST_OPT_FLOAT") is None


def test_opt_float_negative_returns_none(monkeypatch):
    monkeypatch.setenv("WT_TEST_OPT_FLOAT", "-2.5")
    assert bus._opt_float("WT_TEST_OPT_FLOAT") is None


def test_opt_float_valid_positive_is_parsed(monkeypatch):
    monkeypatch.setenv("WT_TEST_OPT_FLOAT", "3.5")
    assert bus._opt_float("WT_TEST_OPT_FLOAT") == 3.5


# --- _opt_int ----------------------------------------------------------------


def test_opt_int_missing_env_returns_default(monkeypatch):
    monkeypatch.delenv("WT_TEST_OPT_INT", raising=False)
    assert bus._opt_int("WT_TEST_OPT_INT", 30) == 30


def test_opt_int_empty_string_returns_default(monkeypatch):
    monkeypatch.setenv("WT_TEST_OPT_INT", "")
    assert bus._opt_int("WT_TEST_OPT_INT", 30) == 30


def test_opt_int_unparseable_returns_default(monkeypatch):
    monkeypatch.setenv("WT_TEST_OPT_INT", "12.5")  # not an int literal
    assert bus._opt_int("WT_TEST_OPT_INT", 30) == 30


def test_opt_int_zero_returns_default(monkeypatch):
    # value <= 0 falls back to the supplied default rather than disabling.
    monkeypatch.setenv("WT_TEST_OPT_INT", "0")
    assert bus._opt_int("WT_TEST_OPT_INT", 30) == 30


def test_opt_int_negative_returns_default(monkeypatch):
    monkeypatch.setenv("WT_TEST_OPT_INT", "-5")
    assert bus._opt_int("WT_TEST_OPT_INT", 30) == 30


def test_opt_int_valid_positive_is_parsed(monkeypatch):
    monkeypatch.setenv("WT_TEST_OPT_INT", "42")
    assert bus._opt_int("WT_TEST_OPT_INT", 30) == 42


# --- _client_kwargs socket_timeout branch ------------------------------------


def test_client_kwargs_omits_socket_timeout_when_unset(monkeypatch):
    """With no socket timeout configured, the key is absent so an idle read
    never times out as fatal — the crash-loop-avoidance default."""
    monkeypatch.setattr(bus, "_SOCKET_TIMEOUT", None)
    kwargs = bus._client_kwargs()
    assert "socket_timeout" not in kwargs
    assert kwargs["socket_keepalive"] is True
    assert kwargs["decode_responses"] is True


def test_client_kwargs_includes_socket_timeout_when_set(monkeypatch):
    """A positive socket timeout is threaded into the client kwargs verbatim."""
    monkeypatch.setattr(bus, "_SOCKET_TIMEOUT", 5.0)
    kwargs = bus._client_kwargs()
    assert kwargs["socket_timeout"] == 5.0


def test_client_kwargs_threads_health_check_interval(monkeypatch):
    """The module-level health-check interval flows into every client build."""
    monkeypatch.setattr(bus, "_HEALTH_CHECK_INTERVAL", 17)
    kwargs = bus._client_kwargs()
    assert kwargs["health_check_interval"] == 17
