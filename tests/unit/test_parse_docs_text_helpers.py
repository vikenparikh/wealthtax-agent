"""Tests for the pure OCR/LLM text helpers in parse_docs.py.

_sanitize_text_for_llm is the secret-redaction boundary before any LLM call;
_normalize_ocr_text cleans OCR text (incl. stripping thousands-separator commas
so downstream amount parsing sees clean numbers); _is_low_quality_ocr_text gates
unreadable scans; _build_minimal_llm_context trims context. None had direct tests.
"""

from wealthtax_agent.parse_docs import (
    _build_minimal_llm_context,
    _is_low_quality_ocr_text,
    _normalize_ocr_text,
    _sanitize_text_for_llm,
)


# --- _sanitize_text_for_llm (secret boundary) --------------------------------


def test_sanitize_redacts_groq_token():
    out = _sanitize_text_for_llm("leaked gsk_ABC123def456GHI end")
    assert "gsk_ABC123def456GHI" not in out
    assert "[REDACTED_TOKEN]" in out


def test_sanitize_redacts_openai_style_token():
    out = _sanitize_text_for_llm("token sk-abc123XYZ789 here")
    assert "sk-abc123XYZ789" not in out
    assert "[REDACTED_TOKEN]" in out


def test_sanitize_redacts_api_key_assignment_case_insensitive():
    assert "secretvalue" not in _sanitize_text_for_llm("API_KEY: secretvalue")
    out = _sanitize_text_for_llm("api_key=hunter2")
    assert "hunter2" not in out and "[REDACTED]" in out


def test_sanitize_leaves_ordinary_tax_text_untouched():
    text = "Employment income (Box 14): 84500.00"
    assert _sanitize_text_for_llm(text) == text


# --- _normalize_ocr_text -----------------------------------------------------


def test_normalize_converts_crlf_and_collapses_whitespace():
    assert _normalize_ocr_text("a\r\n  b   c\r\n") == "a\nb c"


def test_normalize_drops_empty_lines_and_strips():
    assert _normalize_ocr_text("\n\n  hello  \n\n  world \n") == "hello\nworld"


def test_normalize_strips_thousands_separators_in_numbers():
    assert _normalize_ocr_text("Total: 1,234.56") == "Total: 1234.56"
    assert _normalize_ocr_text("Amount 12,000") == "Amount 12000"


def test_normalize_replaces_non_printable_chars_with_space():
    assert _normalize_ocr_text("a\x00b") == "a b"


# --- _is_low_quality_ocr_text ------------------------------------------------


def test_low_quality_when_empty_or_too_short():
    assert _is_low_quality_ocr_text("") is True
    assert _is_low_quality_ocr_text("   ") is True
    assert _is_low_quality_ocr_text("ab cd") is True  # < 8 chars stripped


def test_low_quality_when_too_few_alphanumerics():
    assert _is_low_quality_ocr_text("....!!!! ----") is True  # long but < 6 alnum


def test_good_quality_text_is_accepted():
    assert _is_low_quality_ocr_text("Employment income 84500") is False


# --- _build_minimal_llm_context ----------------------------------------------


def test_build_context_returns_lines_under_the_limit():
    out = _build_minimal_llm_context("alpha\nbeta\ngamma", max_chars=4000)
    assert "alpha" in out and "gamma" in out


def test_build_context_truncates_to_max_chars():
    out = _build_minimal_llm_context("alpha\nbeta\ngamma\ndelta", max_chars=5)
    assert len(out) <= 5
