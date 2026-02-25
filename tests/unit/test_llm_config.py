import wealthtax_agent.llm as llm
from pathlib import Path


def test_load_runtime_config_detects_groq(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")

    runtime = llm.load_runtime_config()

    assert runtime.provider == "groq"
    assert runtime.parse_model == "llama-3.1-8b-instant"


def test_load_runtime_config_requires_groq_key(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    try:
        llm.load_runtime_config()
    except ValueError as exc:
        assert "GROQ_API_KEY is required" in str(exc)
    else:
        raise AssertionError("Expected ValueError when GROQ_API_KEY is missing")


def test_load_runtime_config_rejects_invalid_groq_key_shape(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "not-a-groq-key")

    try:
        llm.load_runtime_config()
    except ValueError as exc:
        assert "expected it to start with 'gsk_' or 'gsk-'" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid GROQ_API_KEY shape")


def test_get_client_uses_runtime_base_url(monkeypatch):
    calls = {}

    class DummyOpenAI:
        def __init__(self, **kwargs):
            calls.update(kwargs)

    monkeypatch.setattr(llm, "OpenAI", DummyOpenAI)

    runtime = llm.RuntimeConfig(
        provider="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key="gsk-x",
        ocr_model="m1",
        parse_model="m2",
        explain_model="m3",
    )

    llm.get_client(runtime)

    assert calls["base_url"] == "https://api.groq.com/openai/v1"
    assert calls["api_key"] == "gsk-x"


def test_call_with_retry_succeeds_after_retry():
    attempts = {"count": 0}

    def flaky():
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise RuntimeError("rate limit")
        return "ok"

    result = llm.call_with_retry(flaky, max_attempts=3, base_delay_seconds=0)

    assert result == "ok"
    assert attempts["count"] == 2


def test_call_with_retry_does_not_retry_auth_errors():
    attempts = {"count": 0}

    def auth_error():
        attempts["count"] += 1
        raise RuntimeError("invalid api_key")

    try:
        llm.call_with_retry(auth_error, max_attempts=3, base_delay_seconds=0)
    except RuntimeError as exc:
        assert "api_key" in str(exc)
    else:
        raise AssertionError("Expected RuntimeError for auth failure")

    assert attempts["count"] == 1


def test_sanitize_runtime_error_for_auth_message():
    sanitized = llm.sanitize_runtime_error("Incorrect API key provided: gsk_secret")

    assert sanitized == "Model provider authentication failed. Verify GROQ_API_KEY and endpoint settings."


def test_load_runtime_config_reloads_updated_dotenv(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(llm, "_DOTENV_LOADED_KEYS", set())
    monkeypatch.setattr(llm, "_DOTENV_CACHE", {"path": None, "mtime": None})

    env_file = Path(tmp_path) / ".env"
    env_file.write_text("LLM_PROVIDER=groq\nGROQ_API_KEY=gsk_first\n", encoding="utf-8")
    first = llm.load_runtime_config()
    assert first.api_key == "gsk_first"

    env_file.write_text("LLM_PROVIDER=groq\nGROQ_API_KEY=gsk_second\n", encoding="utf-8")
    second = llm.load_runtime_config()
    assert second.api_key == "gsk_second"


def test_load_runtime_config_dotenv_overrides_existing_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_stale")
    monkeypatch.setattr(llm, "_DOTENV_LOADED_KEYS", set())
    monkeypatch.setattr(llm, "_DOTENV_CACHE", {"path": None, "mtime": None})

    env_file = Path(tmp_path) / ".env"
    env_file.write_text("LLM_PROVIDER=groq\nGROQ_API_KEY=gsk_from_dotenv\n", encoding="utf-8")

    runtime = llm.load_runtime_config()

    assert runtime.api_key == "gsk_from_dotenv"
