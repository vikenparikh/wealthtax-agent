"""Unit tests for extract_forms_node (extract_forms.py).

Drives the node's branches without OCR or a live LLM by monkeypatching the
two boundary helpers (_text_for_doc, _llm_extract): manual-extract pass-
through, rule-extractor dispatch, LLM fallback when the rule record is
empty, skips (unknown form code / no text / None form_code), and the
sanitized failure + no-forms warnings.
"""

import wealthtax_agent.extract_forms as ef
import wealthtax_agent.forms  # noqa: F401 - populate the extractor registry
from wealthtax_agent.extract_forms import extract_forms_node
from wealthtax_agent.state import FormClassification, FormExtract, GraphState

FORM16_TEXT = "\n".join(
    [
        "FORM NO. 16",
        "Tax year: 2024",
        "Gross salary: 1800000.00",
        "Tax deducted at source TDS deducted: 184000.00",
    ]
)


def _cls(form_code, jurisdiction="IN", filename="f.pdf"):
    return FormClassification(form_code=form_code, jurisdiction=jurisdiction, filename=filename)


def _no_llm(*_a, **_k):
    raise AssertionError("LLM fallback should not be called")


def test_manual_extracts_without_classification_pass_through():
    manual = FormExtract(form_code="MANUAL", jurisdiction="CA", fields={"x": 1.0})
    out = extract_forms_node(GraphState(extracts=[manual], classifications=[]))
    assert any(e.form_code == "MANUAL" for e in out.extracts)
    assert any(s.type == "MANUAL" for s in out.slips)


def test_classified_doc_extracted_by_rule_extractor(monkeypatch):
    monkeypatch.setattr(ef, "_text_for_doc", lambda doc: FORM16_TEXT)
    monkeypatch.setattr(ef, "_llm_extract", _no_llm)  # rule succeeds -> no fallback
    out = extract_forms_node(GraphState(classifications=[_cls("FORM-16")], raw_docs=[b"doc0"]))
    e = next(e for e in out.extracts if e.form_code == "FORM-16")
    assert e.fields["gross_salary"] == 1800000.0
    assert e.extractor == "rule"


def test_llm_fallback_used_when_rule_record_is_empty(monkeypatch):
    monkeypatch.setattr(ef, "_text_for_doc", lambda doc: "unparseable text, no known labels")
    monkeypatch.setattr(ef, "_llm_extract", lambda text, code: {"fields": {"wages": 5000.0}, "tax_year": 2024})
    out = extract_forms_node(GraphState(classifications=[_cls("FORM-16")], raw_docs=[b"doc0"]))
    e = next(e for e in out.extracts if e.form_code == "FORM-16")
    assert e.fields == {"wages": 5000.0}
    assert e.extractor == "llm"
    assert e.confidence == "medium"
    assert e.tax_year == 2024


def test_unknown_form_code_is_skipped(monkeypatch):
    monkeypatch.setattr(ef, "_text_for_doc", lambda doc: "anything")
    out = extract_forms_node(GraphState(classifications=[_cls("NOPE-FORM", "CA")], raw_docs=[b"d"]))
    assert out.extracts == []


def test_doc_without_text_is_skipped(monkeypatch):
    monkeypatch.setattr(ef, "_text_for_doc", lambda doc: None)
    out = extract_forms_node(GraphState(classifications=[_cls("FORM-16")], raw_docs=[b"d"]))
    assert out.extracts == []


def test_classification_with_none_form_code_is_skipped():
    state = GraphState(classifications=[FormClassification(form_code=None, jurisdiction="CA")], raw_docs=[b"d"])
    assert extract_forms_node(state).extracts == []


def test_extraction_exception_appends_sanitized_warning(monkeypatch):
    def _boom(doc):
        raise RuntimeError("kaboom gsk_supersecret")

    monkeypatch.setattr(ef, "_text_for_doc", _boom)
    out = extract_forms_node(GraphState(classifications=[_cls("FORM-16")], raw_docs=[b"d"]))
    assert any("extraction failed" in w for w in out.warnings)
    assert not any("gsk_supersecret" in w for w in out.warnings)  # secret scrubbed


def test_warns_when_no_forms_extracted(monkeypatch):
    monkeypatch.setattr(ef, "_text_for_doc", lambda doc: None)
    out = extract_forms_node(GraphState(classifications=[_cls("FORM-16")], raw_docs=[b"d"]))
    assert any("No tax forms were successfully extracted" in w for w in out.warnings)
