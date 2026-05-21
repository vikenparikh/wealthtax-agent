"""ClaudeCLILLM — subprocess wrapper around the ``claude`` CLI binary.

This is the canonical LLM client for wealthtax-agent.  It mirrors the
pattern from Trad-Platform's ``src/trad_platform/agents/llm_client.py``
exactly: no Anthropic SDK, no API key required — authenticates via the
existing Claude Code session.

Usage
-----
    from wealthtax_agent.services.claude_llm import ClaudeCLILLM, get_tax_llm

    llm = get_tax_llm()
    resp = llm.complete("Explain the wash-sale rule in one sentence.")
    print(resp.text)

    # Structured JSON output
    result = llm.complete_json(
        "Extract the tax year from: Tax Year 2024",
        schema_hint='{"tax_year": 0}',
    )
    # result == {"tax_year": 2024}
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

_CLAUDE_BIN_CANDIDATES = (
    "claude",
    str(Path.home() / ".claude" / "local" / "claude"),
    "/usr/local/bin/claude",
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

_CPA_SYSTEM_PREAMBLE = (
    "You are a knowledgeable tax research assistant. "
    "You help users understand tax concepts for the US and Canada, "
    "citing IRS publications, CRA guides, and relevant IRC / ITA sections. "
    "IMPORTANT DISCLAIMER: You are NOT a licensed CPA or tax professional. "
    "Nothing you say constitutes legal or professional tax advice. "
    "Always recommend the user consult a licensed CPA before taking action. "
    "Respond with accurate, well-cited information. "
    "If asked a structured-output question, reply ONLY with a valid JSON object "
    "matching the schema provided — no prose, no code fences.\n\n"
)


class LLMError(RuntimeError):
    """Raised when the Claude CLI call fails irrecoverably."""


@dataclass
class LLMResponse:
    text: str
    json: dict[str, Any] | None = None


def _resolve_binary(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit if Path(explicit).exists() or shutil.which(explicit) else None
    env = os.environ.get("CLAUDE_CLI_BIN")
    if env and (Path(env).exists() or shutil.which(env)):
        return env
    for cand in _CLAUDE_BIN_CANDIDATES:
        if shutil.which(cand) or Path(cand).exists():
            return cand
    return None


def _try_parse_json(text: str) -> dict[str, Any] | None:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    m = _JSON_RE.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


class StubLLM:
    """In-memory stub used by tests and offline runs (no ``claude`` binary needed)."""

    def __init__(self, responses: dict[str, dict[str, Any]] | None = None) -> None:
        self._responses = responses or {}
        self.calls: list[tuple[str, str | None]] = []
        self.available = True

    def complete(self, prompt: str, *, schema_hint: str | None = None) -> LLMResponse:
        self.calls.append((prompt, schema_hint))
        for needle, payload in self._responses.items():
            if needle in prompt:
                return LLMResponse(text=json.dumps(payload), json=payload)
        return LLMResponse(text="{}", json={})

    def complete_json(
        self,
        prompt: str,
        schema_hint: str,
        default: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.complete(prompt, schema_hint=schema_hint).json or dict(default or {})


class ClaudeCLILLM:
    """LLM client that shells out to the local ``claude`` CLI binary.

    Uses ``claude -p <prompt>`` for non-interactive single-turn completions.
    No API key or SDK dependency required.

    Parameters
    ----------
    binary:
        Explicit path. Falls back to ``$CLAUDE_CLI_BIN`` then ``claude`` on PATH.
    timeout:
        Hard cap per call (seconds). Default 90s — tax prompts can be verbose.
    model:
        Claude model slug. Overridable via ``$CLAUDE_MODEL`` env var.
    """

    def __init__(
        self,
        binary: str | None = None,
        timeout: float = 90.0,
        model: str | None = None,
    ) -> None:
        self.binary = _resolve_binary(binary)
        self.timeout = timeout
        self._model = model or os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-6")
        self.available: bool = False
        self.claude_version: str | None = None
        self._validate()

    def _validate(self) -> None:
        bin_path = self.binary or "claude"
        try:
            proc = subprocess.run(
                [bin_path, "--version"],
                capture_output=True,
                text=True,
                timeout=10.0,
                check=False,
            )
            self.claude_version = proc.stdout.strip() or proc.stderr.strip()
            self.available = True
        except FileNotFoundError as exc:
            raise RuntimeError(
                "claude binary not found on PATH. "
                "Install Claude Code CLI or set CLAUDE_CLI_BIN."
            ) from exc

    def complete(self, prompt: str, *, schema_hint: str | None = None) -> LLMResponse:
        if not self.available:
            raise LLMError("claude CLI binary not found")
        full_prompt = _CPA_SYSTEM_PREAMBLE + prompt
        if schema_hint:
            full_prompt += (
                "\n\nReply ONLY with a JSON object matching this shape "
                "(no prose, no code fences):\n" + schema_hint
            )
        bin_path = self.binary or "claude"
        cmd = [bin_path, "-p", full_prompt, "--model", self._model]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            raise LLMError(f"claude CLI invocation failed: {exc}") from exc
        if proc.returncode != 0:
            raise LLMError(
                f"claude exit={proc.returncode} stderr={proc.stderr.strip()[:300]}"
            )
        text = proc.stdout.strip()
        parsed: dict[str, Any] | None = None
        if schema_hint:
            parsed = _try_parse_json(text)
        return LLMResponse(text=text, json=parsed)

    def complete_json(
        self,
        prompt: str,
        schema_hint: str,
        default: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            resp = self.complete(prompt, schema_hint=schema_hint)
        except LLMError as exc:
            log.warning("ClaudeCLILLM.complete_json failed: %s", exc)
            return dict(default or {})
        if resp.json is not None:
            return resp.json
        log.warning("ClaudeCLILLM: JSON parse failed; returning default")
        return dict(default or {"raw": resp.text})


@lru_cache(maxsize=1)
def get_tax_llm() -> ClaudeCLILLM:
    """Return the singleton ClaudeCLILLM instance.

    Raises ``RuntimeError`` if the ``claude`` binary is not on PATH.
    Tests should monkeypatch this to return a ``StubLLM``.
    """
    return ClaudeCLILLM()
