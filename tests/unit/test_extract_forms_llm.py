"""Unit tests for the LLM-boundary helpers in extract_forms.py.

These exercise the REAL ``_llm_extract`` and ``_text_for_doc`` helpers with a
faked Groq client (and a faked OCR/cache layer) — the OPPOSITE of
``test_extract_forms_node.py``, which monkeypatches these helpers away.

The production code obtains the client via ``get_client`` and invokes it through
``call_with_retry`` (which just calls the callable), so a fake client that
exposes ``.chat.completions.create`` flows straight through.
"""

from unittest.mock import patch

import wealthtax_agent.extract_forms as ef
from wealthtax_agent.extract_forms import _llm_extract, _text_for_doc
from wealthtax_agent.state import InputDocument


# --- Fake Groq client (proven pattern from test_parse_correction_prompt.py) ---

class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Comp:
    def __init__(self, content):
        self._content = content

    def create(self, **kwargs):
        return _Resp(self._content)


class _Chat:
    def __init__(self, content):
        self.completions = _Comp(content)


class _Client:
    def __init__(self, content):
        self.chat = _Chat(content)


def _client_returning(content):
    return lambda *_a, **_k: _Client(content)


# --- _llm_extract -----------------------------------------------------------

def test_numeric_coercion_strings_become_floats_nonnumeric_skipped():
    """String values are coerced to float; non-numeric values are dropped."""
    content = (
        '{"fields": {"wages": "5000", "tips": 200, "note": "not-a-number", '
        '"bonus": null}, "tax_year": 2024}'
    )
    with patch.object(ef, "get_client", _client_returning(content)):
        out = _llm_extract("some ocr text", "W-2")
    # "wages" string -> float, "tips" int -> float; "note"/"bonus" skipped.
    assert out["fields"] == {"wages": 5000.0, "tips": 200.0}
    assert out["tax_year"] == 2024


def test_non_int_tax_year_becomes_none():
    """tax_year that is not an int (e.g. a string) is coerced to None."""
    content = '{"fields": {"wages": 10}, "tax_year": "2024"}'
    with patch.object(ef, "get_client", _client_returning(content)):
        out = _llm_extract("text", "W-2")
    assert out["tax_year"] is None
    assert out["fields"] == {"wages": 10.0}


def test_client_build_failure_returns_empty_dict():
    """If get_client raises, _llm_extract swallows it and returns {}."""
    def _boom(*_a, **_k):
        raise RuntimeError("no client")

    with patch.object(ef, "get_client", _boom):
        out = _llm_extract("text", "W-2")
    assert out == {}


def test_call_or_parse_failure_returns_empty_dict():
    """If the response content is unparseable JSON, return {}."""
    with patch.object(ef, "get_client", _client_returning("this is not json")):
        out = _llm_extract("text", "W-2")
    assert out == {}


def test_empty_result_shape_when_no_fields_and_no_tax_year():
    """A bare {} payload yields the canonical empty shape."""
    with patch.object(ef, "get_client", _client_returning("{}")):
        out = _llm_extract("text", "W-2")
    assert out == {"fields": {}, "tax_year": None}


# --- _text_for_doc ----------------------------------------------------------

def test_text_for_doc_returns_cached_text_when_present():
    """When the doc-text cache has an entry, return it without OCR."""
    doc = InputDocument(content=b"docbytes", mime_type="application/pdf")
    with patch.object(ef, "get_cached_text_for", lambda content: "CACHED TEXT"):
        # ocr_bytes_to_text must NOT be reached; make it explode if it is.
        with patch.object(ef, "ocr_bytes_to_text", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("OCR should be skipped"))):
            out = _text_for_doc(doc)
    assert out == "CACHED TEXT"


def test_text_for_doc_returns_none_on_ocr_failure():
    """Cache miss + OCR raising -> None (the failure branch is swallowed)."""
    doc = InputDocument(content=b"docbytes", mime_type="application/pdf")

    def _ocr_boom(*_a, **_k):
        raise RuntimeError("ocr failed")

    with patch.object(ef, "get_cached_text_for", lambda content: None):
        with patch.object(ef, "ocr_bytes_to_text", _ocr_boom):
            out = _text_for_doc(doc)
    assert out is None


def test_text_for_doc_ocrs_and_sanitizes_on_cache_miss():
    """Cache miss + OCR success -> the OCR text is normalized & sanitized and
    returned (covers the line-78 return path)."""
    doc = InputDocument(content=b"docbytes", mime_type="application/pdf")
    with patch.object(ef, "get_cached_text_for", lambda content: None):
        with patch.object(ef, "ocr_bytes_to_text", lambda *_a, **_k: "  raw ocr  text  "):
            out = _text_for_doc(doc)
    # _normalize_ocr_text + _sanitize_text_for_llm run for real; just assert the
    # OCR content survived the round-trip (non-empty, contains the words).
    assert out is not None
    assert "raw ocr" in out and "text" in out
