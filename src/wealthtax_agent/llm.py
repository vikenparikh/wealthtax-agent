import os
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, TypeVar

from openai import OpenAI

from wealthtax_agent.logging_utils import get_logger

_log = get_logger("wealthtax_agent.llm")


T = TypeVar("T")
_DOTENV_LOADED_KEYS = set()
_DOTENV_CACHE = {"path": None, "mtime": None}


@dataclass(frozen=True)
class RuntimeConfig:
    provider: str
    base_url: str
    api_key: str
    ocr_model: str
    parse_model: str
    explain_model: str


def _load_dotenv_if_present() -> None:
    candidates = [Path.cwd() / ".env", Path(__file__).resolve().parents[2] / ".env"]
    env_path = None
    for env_path in candidates:
        if env_path.exists():
            break
    else:
        return

    mtime = env_path.stat().st_mtime
    if _DOTENV_CACHE["path"] == str(env_path) and _DOTENV_CACHE["mtime"] == mtime:
        return

    parsed = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            parsed[key] = value

    for key, value in parsed.items():
        os.environ[key] = value
        _DOTENV_LOADED_KEYS.add(key)

    _DOTENV_CACHE["path"] = str(env_path)
    _DOTENV_CACHE["mtime"] = mtime


def sanitize_runtime_error(message: str) -> str:
    lowered = message.lower()
    auth_markers = [
        "api_key",
        "gsk_",
        "sk-",
        "authentication",
        "unauthorized",
        "forbidden",
        "invalid key",
        "incorrect api key",
        "401",
        "403",
    ]
    if any(marker in lowered for marker in auth_markers):
        return "Model provider authentication failed. Verify GROQ_API_KEY and endpoint settings."

    missing_key_markers = ["groq_api_key is required", "missing groq_api_key"]
    if any(marker in lowered for marker in missing_key_markers):
        return "GROQ_API_KEY is missing. Set it in your environment or .env file."

    model_markers = ["model_decommissioned", "decommissioned and is no longer supported"]
    if any(marker in lowered for marker in model_markers):
        return "Configured model is no longer supported. Update OCR_MODEL/PARSE_MODEL/EXPLAIN_MODEL to an active Groq model."

    sanitized = re.sub(r"gsk_[A-Za-z0-9_\-]+", "[REDACTED_TOKEN]", message)
    sanitized = re.sub(r"sk-[A-Za-z0-9_\-]+", "[REDACTED_TOKEN]", sanitized)
    return sanitized


def _detect_provider() -> str:
    provider = os.getenv("LLM_PROVIDER", "groq").strip().lower()
    if provider and provider != "groq":
        raise ValueError("Only the 'groq' provider is supported")
    return "groq"


def load_runtime_config() -> RuntimeConfig:
    _load_dotenv_if_present()
    provider = _detect_provider()

    base_url = (
        os.getenv("GROQ_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or "https://api.groq.com/openai/v1"
    )
    api_key = os.getenv("GROQ_API_KEY", "").strip()

    if not api_key:
        raise ValueError("GROQ_API_KEY is required")
    if not (api_key.startswith("gsk_") or api_key.startswith("gsk-")):
        raise ValueError("GROQ_API_KEY appears invalid; expected it to start with 'gsk_' or 'gsk-'")

    default_ocr = "meta-llama/llama-4-scout-17b-16e-instruct"
    default_text = "llama-3.1-8b-instant"

    return RuntimeConfig(
        provider=provider,
        base_url=base_url,
        api_key=api_key,
        ocr_model=os.getenv("OCR_MODEL", default_ocr),
        parse_model=os.getenv("PARSE_MODEL", default_text),
        explain_model=os.getenv("EXPLAIN_MODEL", default_text),
    )


def get_client(config: Optional[RuntimeConfig] = None) -> OpenAI:
    runtime = config or load_runtime_config()
    return OpenAI(base_url=runtime.base_url, api_key=runtime.api_key)


def _is_retryable_error(exc: Exception) -> bool:
    message = str(exc).lower()

    non_retryable_markers = [
        "api_key",
        "authentication",
        "unauthorized",
        "forbidden",
        "invalid key",
        "401",
        "403",
    ]
    if any(marker in message for marker in non_retryable_markers):
        return False

    retryable_markers = [
        "rate limit",
        "timeout",
        "timed out",
        "temporarily unavailable",
        "connection",
        "429",
        "500",
        "502",
        "503",
        "504",
    ]
    return any(marker in message for marker in retryable_markers)


def call_with_retry(callable_fn: Callable[[], T], max_attempts: int = 3, base_delay_seconds: float = 0.5) -> T:
    last_error: Optional[Exception] = None
    for attempt in range(1, max_attempts + 1):
        try:
            return callable_fn()
        except Exception as exc:
            last_error = exc
            retryable = _is_retryable_error(exc)
            _log.warning(
                "llm_call_failed",
                extra={
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "retryable": retryable,
                    "error": sanitize_runtime_error(str(exc)),
                },
            )
            if not retryable:
                break
            if attempt == max_attempts:
                break
            jitter = random.uniform(0, 0.2)
            backoff = base_delay_seconds * (2 ** (attempt - 1))
            time.sleep(backoff + jitter)

    if last_error is None:
        raise RuntimeError("Retry helper failed without an exception")
    raise last_error


def get_provider_name() -> str:
    return load_runtime_config().provider


def get_base_url(provider: str) -> Optional[str]:
    _ = provider
    return load_runtime_config().base_url


def get_api_key(provider: str) -> Optional[str]:
    _ = provider
    return load_runtime_config().api_key


def get_model(kind: str) -> str:
    runtime = load_runtime_config()
    mapping = {
        "ocr": runtime.ocr_model,
        "parse": runtime.parse_model,
        "explain": runtime.explain_model,
    }
    if kind not in mapping:
        raise ValueError(f"Unsupported model kind: {kind}")
    return mapping[kind]


try:
    PROVIDER_NAME = get_provider_name()
    OCR_MODEL = get_model("ocr")
    PARSE_MODEL = get_model("parse")
    EXPLAIN_MODEL = get_model("explain")
except Exception:
    PROVIDER_NAME = "groq"
    OCR_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
    PARSE_MODEL = "llama-3.1-8b-instant"
    EXPLAIN_MODEL = "llama-3.1-8b-instant"

__all__ = [
    "RuntimeConfig",
    "load_runtime_config",
    "sanitize_runtime_error",
    "get_provider_name",
    "get_base_url",
    "get_api_key",
    "get_model",
    "get_client",
    "call_with_retry",
    "PROVIDER_NAME",
    "OCR_MODEL",
    "PARSE_MODEL",
    "EXPLAIN_MODEL",
]
