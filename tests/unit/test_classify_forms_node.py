"""Unit tests for classify_forms_node + heuristic confidence (classify_forms.py).

test_classify_forms.py covers _heuristic_classify matches only. This adds the
confidence thresholds and drives the node itself (OCR mocked at the module
boundary): successful classify + text caching, unsupported MIME, low-quality
OCR, unrecognised form, and the sanitized per-document failure warning.
"""

import pytest

import wealthtax_agent.classify_forms as cf
import wealthtax_agent.forms  # noqa: F401 - populate the extractor registry
from wealthtax_agent.classify_forms import _heuristic_classify, classify_forms_node, get_cached_text_for
from wealthtax_agent.state import GraphState, InputDocument


@pytest.fixture(autouse=True)
def _isolate_doc_text_cache():
    snap = dict(cf._DOC_TEXT_CACHE)
    yield
    cf._DOC_TEXT_CACHE.clear()
    cf._DOC_TEXT_CACHE.update(snap)


def _doc(content=b"d", filename="f.pdf", mime="application/pdf"):
    return InputDocument(content=content, filename=filename, mime_type=mime)


# --- _heuristic_classify confidence ------------------------------------------


def test_heuristic_high_confidence_for_long_pattern_match():
    c = _heuristic_classify("T4 Statement of Remuneration Paid — 2024 employment income")
    assert c is not None
    assert c.form_code == "T4" and c.jurisdiction == "CA"
    assert c.confidence == "high"  # matched pattern >= 12 chars


def test_heuristic_medium_confidence_for_short_pattern_match():
    c = _heuristic_classify("this document is a Form 16 issued to the employee")
    assert c is not None
    assert c.form_code == "FORM-16"
    assert c.confidence == "medium"  # only the short "Form 16" pattern matched


def test_heuristic_returns_none_for_unrecognized_text():
    assert _heuristic_classify("random unrelated text about gardening") is None


# --- classify_forms_node -----------------------------------------------------


def test_node_classifies_supported_doc_and_caches_text(monkeypatch):
    monkeypatch.setattr(cf, "ocr_bytes_to_text", lambda content, mime: "T4 Statement of Remuneration Paid")
    monkeypatch.setattr(cf, "_is_low_quality_ocr_text", lambda t: False)
    out = classify_forms_node(GraphState(raw_docs=[_doc(content=b"t4bytes")]))
    assert len(out.classifications) == 1
    c = out.classifications[0]
    assert c.form_code == "T4" and c.filename == "f.pdf"
    # text is cached for the downstream extract step
    assert get_cached_text_for(b"t4bytes") == "T4 Statement of Remuneration Paid"


def test_node_flags_unsupported_mime_type():
    # mime is derived from the filename extension, so use a genuinely unsupported one.
    out = classify_forms_node(GraphState(raw_docs=[_doc(filename="archive.zip", mime="application/zip")]))
    assert out.classifications == []
    assert any("not supported" in u.reason for u in out.unsupported_forms)


def test_node_flags_low_quality_ocr(monkeypatch):
    monkeypatch.setattr(cf, "ocr_bytes_to_text", lambda content, mime: "blurry noise")
    monkeypatch.setattr(cf, "_is_low_quality_ocr_text", lambda t: True)
    out = classify_forms_node(GraphState(raw_docs=[_doc()]))
    assert out.classifications == []
    assert any("OCR confidence too low" in u.reason for u in out.unsupported_forms)


def test_node_flags_unrecognized_form(monkeypatch):
    monkeypatch.setattr(cf, "ocr_bytes_to_text", lambda content, mime: "totally unrelated content")
    monkeypatch.setattr(cf, "_is_low_quality_ocr_text", lambda t: False)
    monkeypatch.setattr(cf, "_llm_classify", lambda t: None)  # no LLM rescue
    out = classify_forms_node(GraphState(raw_docs=[_doc()]))
    assert out.classifications == []
    assert any("not recognised" in u.reason for u in out.unsupported_forms)


def test_node_exception_appends_sanitized_warning(monkeypatch):
    def _boom(content, mime):
        raise RuntimeError("ocr blew up gsk_leak")

    monkeypatch.setattr(cf, "ocr_bytes_to_text", _boom)
    out = classify_forms_node(GraphState(raw_docs=[_doc()]))
    assert any("classification failed" in w for w in out.warnings)
    assert not any("gsk_leak" in w for w in out.warnings)  # secret scrubbed
