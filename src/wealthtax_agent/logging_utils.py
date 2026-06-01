"""Structured (JSON) logging with PII scrubbing.

Every log record emitted via ``get_logger(...)`` is serialised as a single-line
JSON object and run through ``scrub_pii`` first. PII patterns we never want to
appear in logs:

* SSN-shaped ``\\b\\d{3}-\\d{2}-\\d{4}\\b``  (US Social Security Number)
* SIN-shaped ``\\b\\d{9}\\b``                (Canadian Social Insurance Number)
* PAN-shaped ``\\b[A-Z]{5}\\d{4}[A-Z]\\b``    (India Permanent Account Number)

P2-AC8 wires this into ``llm.py``, ``graph.py``, and ``build_return.py`` so the
broader pipeline observability is JSON-parseable and safe to ship to a log
aggregator.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from typing import Any, Dict, Iterable, Optional

# ---------------------------------------------------------------------------
# PII redaction
# ---------------------------------------------------------------------------
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_SIN_RE = re.compile(r"\b\d{9}\b")
_PAN_RE = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")

_REDACTED = "[REDACTED]"


def scrub_pii(value: Any) -> Any:
    """Recursively redact SSN / SIN / PAN-shaped substrings.

    Strings are mutated, containers (dict/list/tuple) are walked, everything
    else is returned unchanged. Booleans / numbers / None pass through.
    """
    if isinstance(value, str):
        out = _SSN_RE.sub(_REDACTED, value)
        out = _PAN_RE.sub(_REDACTED, out)
        # SIN regex runs last because it would otherwise eat the 9 digits in
        # the SSN before the dashes had a chance to anchor the SSN regex.
        out = _SIN_RE.sub(_REDACTED, out)
        return out
    if isinstance(value, dict):
        return {k: scrub_pii(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_pii(v) for v in value]
    if isinstance(value, tuple):
        return tuple(scrub_pii(v) for v in value)
    return value


# ---------------------------------------------------------------------------
# JSON formatter
# ---------------------------------------------------------------------------
# Standard LogRecord attributes — anything else attached via ``extra=...`` will
# show up on the record as well and we want to surface it in the JSON payload.
_STANDARD_ATTRS = frozenset({
    "args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName",
    "levelname", "levelno", "lineno", "message", "module", "msecs", "msg", "name",
    "pathname", "process", "processName", "relativeCreated", "stack_info",
    "thread", "threadName", "taskName",
})


class JSONFormatter(logging.Formatter):
    """Emit each log record as a single line of JSON with PII scrubbed."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401 — stdlib hook
        payload: Dict[str, Any] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Bubble any ``extra={...}`` kwargs onto the JSON payload.
        for key, value in record.__dict__.items():
            if key in _STANDARD_ATTRS or key.startswith("_"):
                continue
            payload[key] = value

        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)

        return json.dumps(scrub_pii(payload), default=str, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Logger factory
# ---------------------------------------------------------------------------
_CONFIGURED: set[str] = set()


def get_logger(name: str, *, level: int = logging.INFO, stream=None) -> logging.Logger:
    """Return a logger pre-configured with the JSON formatter.

    The handler is attached once per logger name (idempotent). ``stream``
    defaults to ``sys.stderr``; tests can pass an ``io.StringIO`` to capture.
    """
    logger = logging.getLogger(name)
    if name not in _CONFIGURED:
        handler = logging.StreamHandler(stream or sys.stderr)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(level)
        # Don't propagate to root — pytest captures root and would double-print.
        logger.propagate = False
        _CONFIGURED.add(name)
    return logger


def reset_loggers(names: Optional[Iterable[str]] = None) -> None:
    """Drop cached handlers so tests can attach their own streams.

    Without this the module-level cache would keep the first stream forever.
    """
    targets = list(names) if names is not None else list(_CONFIGURED)
    for name in targets:
        logger = logging.getLogger(name)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
        _CONFIGURED.discard(name)


__all__ = ["get_logger", "scrub_pii", "reset_loggers", "JSONFormatter"]
