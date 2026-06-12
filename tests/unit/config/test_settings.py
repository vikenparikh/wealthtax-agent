"""Config hardening: get_settings must not crash on malformed env vars."""

from wealthtax_agent.config.settings import get_settings, reset_settings_cache

_INT_VARS = ["SESSION_TTL_MINUTES", "CORRECTION_RATE_PER_MINUTE"]
_ALL = _INT_VARS + ["WEALTHTAX_MODE", "DATABASE_URL", "LOG_LEVEL"]


def _fresh(monkeypatch, **env):
    for k in _ALL:
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    reset_settings_cache()
    settings = get_settings()
    reset_settings_cache()
    return settings


def test_defaults_when_unset(monkeypatch):
    s = _fresh(monkeypatch)
    assert s.session_ttl_minutes == 1440
    assert s.correction_rate_per_minute == 20
    assert s.mode == "self_hosted"
    assert s.database_url == "sqlite:///./wealthtax.db"


def test_valid_int_overrides_apply(monkeypatch):
    s = _fresh(monkeypatch, SESSION_TTL_MINUTES="60", CORRECTION_RATE_PER_MINUTE="5")
    assert s.session_ttl_minutes == 60
    assert s.correction_rate_per_minute == 5


def test_malformed_int_falls_back_to_default(monkeypatch):
    s = _fresh(monkeypatch, SESSION_TTL_MINUTES="30m", CORRECTION_RATE_PER_MINUTE="abc")
    assert s.session_ttl_minutes == 1440
    assert s.correction_rate_per_minute == 20


def test_non_positive_int_falls_back_to_default(monkeypatch):
    s = _fresh(monkeypatch, SESSION_TTL_MINUTES="0", CORRECTION_RATE_PER_MINUTE="-5")
    assert s.session_ttl_minutes == 1440
    assert s.correction_rate_per_minute == 20


def test_blank_int_falls_back_to_default(monkeypatch):
    s = _fresh(monkeypatch, SESSION_TTL_MINUTES="   ")
    assert s.session_ttl_minutes == 1440


def test_mode_is_normalised_lowercase(monkeypatch):
    assert _fresh(monkeypatch, WEALTHTAX_MODE="SaaS").mode == "saas"
    assert _fresh(monkeypatch, WEALTHTAX_MODE="Self_Hosted").mode == "self_hosted"


def test_unknown_mode_falls_back_to_self_hosted(monkeypatch):
    assert _fresh(monkeypatch, WEALTHTAX_MODE="production").mode == "self_hosted"


def test_log_level_uppercased(monkeypatch):
    assert _fresh(monkeypatch, LOG_LEVEL="debug").log_level == "DEBUG"


def test_reset_settings_cache_picks_up_change(monkeypatch):
    monkeypatch.delenv("SESSION_TTL_MINUTES", raising=False)
    reset_settings_cache()
    assert get_settings().session_ttl_minutes == 1440
    monkeypatch.setenv("SESSION_TTL_MINUTES", "99")
    reset_settings_cache()
    assert get_settings().session_ttl_minutes == 99
    reset_settings_cache()
