"""tests/unit/services/test_cpa_chat_safety.py — coverage for the offline
degradation path and the TaxYearContext prompt-context formatting.

These pin two REAL deployed behaviors not exercised by ``test_cpa_chat.py``:

1. **Offline degradation (cpa_chat lines 135-141).** When ``llm=None`` and
   ``get_tax_llm()`` raises ``RuntimeError`` (the Claude CLI is not installed),
   ``ask()`` must STILL return an ``Answer`` carrying the mandatory
   ``_DISCLAIMER`` (a prior security audit requires the disclaimer to always be
   present), with ``confidence == "low"`` and an answer that tells the user to
   consult a licensed CPA. This is the safety regression-pin.

2. **Context formatting (cpa_chat lines 71-75).** ``draft_totals`` are rendered
   as ``$x,xxx.xx`` (comma + 2-decimal) under a "Draft return totals:" header,
   and ``notes`` are joined under "Additional context:". This is what anchors
   the LLM prompt; display/advisory only — non-money.
"""

from __future__ import annotations

import pytest

import wealthtax_agent.services.cpa_chat as cpa_chat
from wealthtax_agent.services.cpa_chat import (
    Answer,
    TaxYearContext,
    _DISCLAIMER,
    ask,
)


# ---------------------------------------------------------------------------
# Offline degradation: get_tax_llm() raises RuntimeError (cpa_chat 135-141)
# ---------------------------------------------------------------------------

class TestOfflineDegradation:
    def test_ask_returns_answer_when_claude_cli_unavailable(self, monkeypatch):
        """When llm is None and get_tax_llm() raises RuntimeError, ask() must
        degrade gracefully into a low-confidence Answer rather than propagating."""

        def _raise() -> None:
            raise RuntimeError("claude CLI not found")

        monkeypatch.setattr(
            "wealthtax_agent.services.claude_llm.get_tax_llm", _raise
        )

        ans = ask("What is the standard deduction?", TaxYearContext(tax_year=2024), llm=None)

        assert isinstance(ans, Answer)
        # SAFETY: the mandatory disclaimer is present even when the LLM is down.
        assert ans.disclaimer == _DISCLAIMER
        assert ans.confidence == "low"

    def test_offline_answer_directs_user_to_a_cpa(self, monkeypatch):
        def _raise() -> None:
            raise RuntimeError("claude CLI not found")

        monkeypatch.setattr(
            "wealthtax_agent.services.claude_llm.get_tax_llm", _raise
        )

        ans = ask("Any tax question?", TaxYearContext(tax_year=2023), llm=None)

        lowered = ans.answer_text.lower()
        assert "unavailable" in lowered
        assert "consult a licensed cpa" in lowered

    def test_offline_answer_preserves_the_question(self, monkeypatch):
        def _raise() -> None:
            raise RuntimeError("claude CLI not found")

        monkeypatch.setattr(
            "wealthtax_agent.services.claude_llm.get_tax_llm", _raise
        )

        question = "How much is the RRSP limit?"
        ans = ask(question, TaxYearContext(tax_year=2024), llm=None)
        assert ans.question == question


# ---------------------------------------------------------------------------
# Context formatting: draft_totals + notes (cpa_chat 71-75)
# ---------------------------------------------------------------------------

class TestContextStringFormatting:
    def test_draft_totals_rendered_with_header_and_money_format(self):
        ctx = TaxYearContext(
            tax_year=2024,
            jurisdictions=["US"],
            draft_totals={"US federal tax": 12345.67, "US refund": 980.5},
        )
        out = ctx.to_context_string()
        assert "Draft return totals:" in out
        # comma + 2-decimal formatting
        assert "US federal tax: $12,345.67" in out
        assert "US refund: $980.50" in out

    def test_notes_joined_under_additional_context(self):
        ctx = TaxYearContext(
            tax_year=2024,
            notes=["has wash sales", "QQQ day trader"],
        )
        out = ctx.to_context_string()
        assert "Additional context: has wash sales; QQQ day trader" in out

    def test_empty_draft_totals_and_notes_omit_those_sections(self):
        ctx = TaxYearContext(tax_year=2024, jurisdictions=["CA"])
        out = ctx.to_context_string()
        assert "Draft return totals:" not in out
        assert "Additional context:" not in out

    def test_draft_totals_threaded_into_ask_prompt(self):
        """End-to-end: the formatted draft_totals string reaches the LLM prompt."""

        captured: dict = {}

        class _CapturingLLM:
            _model = "stub"

            def complete(self, prompt, *, schema_hint=None):
                captured["prompt"] = prompt
                from wealthtax_agent.services.claude_llm import LLMResponse

                return LLMResponse(text="Answer.", json=None)

        ctx = TaxYearContext(
            tax_year=2024,
            draft_totals={"US federal tax": 12345.67},
            notes=["has wash sales"],
        )
        ask("Explain my return.", ctx, llm=_CapturingLLM())
        assert "US federal tax: $12,345.67" in captured["prompt"]
        assert "Additional context: has wash sales" in captured["prompt"]
