"""tests/unit/test_cpa_chat.py — unit tests for the LLM CPA chat service.

Covers:
- Disclaimer is always present in the Answer object (HIGH: legal requirement)
- IRS Pub citations are parsed from responses that contain them (MED)
- No "filed with CRA/IRS" or "I will file" language in system prompt (HIGH)
- Graceful degradation when ClaudeCLILLM is unavailable
- ask() handles LLM errors without crashing
"""
from __future__ import annotations

import pytest

from wealthtax_agent.services.claude_llm import StubLLM
from wealthtax_agent.services.cpa_chat import Answer, TaxYearContext, _DISCLAIMER, _SYSTEM_CONTEXT, ask


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx(**kwargs) -> TaxYearContext:
    defaults = dict(tax_year=2024, jurisdictions=["US"], draft_totals={}, form_types_present=[])
    defaults.update(kwargs)
    return TaxYearContext(**defaults)


def _stub(response_text: str) -> StubLLM:
    """Return a StubLLM that returns response_text for any prompt."""
    class _FixedStub(StubLLM):
        def complete(self, prompt, *, schema_hint=None):
            from wealthtax_agent.services.claude_llm import LLMResponse
            return LLMResponse(text=response_text, json=None)
    return _FixedStub()


# ---------------------------------------------------------------------------
# Disclaimer enforcement
# ---------------------------------------------------------------------------

class TestDisclaimerAlwaysPresent:
    def test_answer_has_disclaimer_field(self):
        stub = _stub("Consult IRS Publication 550 for investment income details.")
        ans = ask("What is a wash sale?", _ctx(), llm=stub)
        assert ans.disclaimer, "disclaimer field must be non-empty"

    def test_disclaimer_text_contains_not_professional_advice(self):
        stub = _stub("Answer here.")
        ans = ask("Explain the W-2.", _ctx(), llm=stub)
        assert "not" in ans.disclaimer.lower() and "advice" in ans.disclaimer.lower(), (
            f"Disclaimer does not contain expected language: {ans.disclaimer!r}"
        )

    def test_disclaimer_appended_when_llm_omits_it(self):
        stub = _stub("Here is info about IRC §1091.")
        ans = ask("Explain wash sales.", _ctx(), llm=stub)
        assert _DISCLAIMER.lower()[:40] in ans.answer_text.lower() or \
               "not a licensed" in ans.answer_text.lower() or \
               "not professional" in ans.answer_text.lower(), (
            "When LLM omits disclaimer, ask() must append it to answer_text"
        )

    def test_disclaimer_field_equals_constant(self):
        stub = _stub("Tax info.")
        ans = ask("Any question.", _ctx(), llm=stub)
        assert ans.disclaimer == _DISCLAIMER


# ---------------------------------------------------------------------------
# No over-promising (no claim to file returns)
# ---------------------------------------------------------------------------

class TestNoOverPromiseClaims:
    def test_system_prompt_does_not_claim_to_file(self):
        prohibited = [
            "will file",
            "filed with cra",
            "filed with irs",
            "i will submit",
            "transmit your return",
        ]
        prompt_lower = _SYSTEM_CONTEXT.lower()
        for phrase in prohibited:
            assert phrase not in prompt_lower, (
                f"System prompt contains prohibited over-promise phrase: {phrase!r}"
            )

    def test_system_prompt_contains_not_licensed_disclaimer(self):
        assert "not a licensed" in _SYSTEM_CONTEXT.lower(), (
            "System prompt must state the assistant is not a licensed professional"
        )


# ---------------------------------------------------------------------------
# Citation extraction
# ---------------------------------------------------------------------------

class TestCitationParsing:
    def test_irs_pub_citation_extracted(self):
        stub = _stub(
            "See IRS Publication 550 for details on investment income. "
            "IRC §1091 governs wash sales."
        )
        ans = ask("Explain wash sales.", _ctx(), llm=stub)
        assert any("550" in c or "Pub" in c for c in ans.citations), (
            f"IRS Pub 550 should be in citations; got {ans.citations}"
        )

    def test_irc_section_citation_extracted(self):
        stub = _stub("Under IRC §1091, wash sale losses are disallowed.")
        ans = ask("What is IRC 1091?", _ctx(), llm=stub)
        assert any("1091" in c for c in ans.citations), (
            f"IRC §1091 should appear in citations; got {ans.citations}"
        )

    def test_no_citations_returns_empty_list(self):
        stub = _stub("No references in this answer.")
        ans = ask("Random question.", _ctx(), llm=stub)
        assert isinstance(ans.citations, list)


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    def test_llm_error_returns_answer_not_exception(self):
        class _ErrorStub(StubLLM):
            def complete(self, prompt, *, schema_hint=None):
                raise RuntimeError("LLM unavailable")

        ans = ask("Any question.", _ctx(), llm=_ErrorStub())
        assert isinstance(ans, Answer)
        assert ans.confidence == "low"
        assert ans.disclaimer  # disclaimer still present even on error

    def test_answer_question_field_preserved(self):
        stub = _stub("Some answer.")
        question = "What is the RRSP contribution limit?"
        ans = ask(question, _ctx(jurisdictions=["CA"]), llm=stub)
        assert ans.question == question

    def test_llm_error_message_pii_is_scrubbed(self):
        """rung-3 security: when the LLM raises, the exception message can echo
        the user's question (which may carry PII). Neither ``answer_text`` nor
        ``raw_response`` may surface a raw SSN/SIN/PAN shape; both must redact to
        ``[REDACTED]`` while keeping the friendly 'Unable to process' prefix.
        """
        class _PIIErrorStub(StubLLM):
            def complete(self, prompt, *, schema_hint=None):
                raise RuntimeError("failed on input 123-45-6789 from user")

        ans = ask("my SSN is 123-45-6789", _ctx(), llm=_PIIErrorStub())
        assert isinstance(ans, Answer)
        assert ans.confidence == "low"
        assert "123-45-6789" not in ans.answer_text, ans.answer_text
        assert "123-45-6789" not in (ans.raw_response or ""), ans.raw_response
        assert "[REDACTED]" in ans.answer_text, ans.answer_text
        assert "[REDACTED]" in (ans.raw_response or ""), ans.raw_response
        # Friendly prefix preserved.
        assert "Unable to process your question" in ans.answer_text
