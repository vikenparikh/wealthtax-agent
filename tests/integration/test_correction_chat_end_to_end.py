"""Run the new graph node end-to-end with a sequence of corrections.

The pipeline goes: ingest fixtures -> apply_corrections -> reason_tax ->
build_return. We confirm draft totals change in the expected direction
and the artifacts still parse.
"""

from __future__ import annotations

import base64
import json
from unittest.mock import patch

import wealthtax_agent.classify_forms as classify_forms
import wealthtax_agent.explain_return as explain_return
import wealthtax_agent.extract_forms as extract_forms
import wealthtax_agent.optimize as optimize
import wealthtax_agent.parse_docs as parse_docs
from wealthtax_agent.corrections import compute_correction_diff
from wealthtax_agent.graph import build_graph
from wealthtax_agent.state import Correction, FieldChange, GraphState, InputDocument


class _StubMsg:
    def __init__(self, c): self.content = c
class _StubChoice:
    def __init__(self, c): self.message = _StubMsg(c)
class _StubResp:
    def __init__(self, c): self.choices = [_StubChoice(c)]
class _StubComp:
    def create(self, **kwargs):
        return _StubResp('{"lines":{"total_income":"x","estimated_tax":"y"}}')
class _StubChat:
    def __init__(self): self.completions = _StubComp()
class _StubClient:
    def __init__(self): self.chat = _StubChat()


def _setup_stubs(monkeypatch):
    txt = "T4 Statement of Remuneration Paid\nTax year: 2024\nBox 14 Employment income: 80000.00\nBox 22 Income tax deducted: 14500.00"
    monkeypatch.setattr(parse_docs, "ocr_bytes_to_text", lambda d, m: txt)
    monkeypatch.setattr(classify_forms, "ocr_bytes_to_text", lambda d, m: txt)
    monkeypatch.setattr(extract_forms, "ocr_bytes_to_text", lambda d, m: txt)
    stub = _StubClient()
    monkeypatch.setattr(explain_return, "_get_client", lambda: stub)
    monkeypatch.setattr(explain_return, "client", stub)
    monkeypatch.setattr(classify_forms, "_llm_classify", lambda t: None)
    monkeypatch.setattr(extract_forms, "_llm_extract", lambda t, c: {})
    monkeypatch.setattr(optimize, "_llm_rerank", lambda x: x)


def _invoke(state):
    return GraphState.model_validate(build_graph().invoke(state))


def test_correction_changes_draft_total_and_records_revision(monkeypatch):
    _setup_stubs(monkeypatch)
    base = GraphState(
        raw_docs=[InputDocument(content=b"FAKE-T4", filename="t4.pdf", mime_type="application/pdf")],
        filing_year=2024,
        jurisdictions=["CA"],
        user_answers={"province_of_residence": "ON", "marital_status": "single", "foreign_property_over_100k": "no"},
    )

    first = _invoke(base)
    before_total = first.draft_returns["CA"].totals["total_income"]
    assert first.revision_number == 0  # no corrections applied yet

    # Stage a correction: bump T4 box 14 by $20,000
    first.corrections = [Correction(kind="chat", user_prompt="Set T4 box 14 to 100,000", changes=[
        FieldChange(op="set", target="extract", form_code="T4", field="employment_income", new_value=100000.0),
    ])]
    second = _invoke(first)
    after_total = second.draft_returns["CA"].totals["total_income"]
    assert after_total == before_total + 20000.0
    assert second.revision_number == 1
    assert len(second.applied_corrections) == 1

    # Filing artifacts regenerated for the new totals
    assert "ca_t1_pdf" in second.filing_artifacts
    pdf = base64.b64decode(second.filing_artifacts["ca_t1_pdf"].content_b64)
    assert pdf.startswith(b"%PDF")

    # Diff helper reports the expected delta
    diff = compute_correction_diff(first.draft_returns, second.draft_returns)
    assert diff["CA"]["total_income"] == 20000.0


def test_correction_adds_new_1099_int_and_bumps_us_income(monkeypatch):
    _setup_stubs(monkeypatch)
    # Use US W-2 OCR text instead
    monkeypatch.setattr(parse_docs, "ocr_bytes_to_text",
                        lambda d, m: "Form W-2 Wage and Tax Statement\nTax year: 2024\nBox 1 Wages, tips, other compensation: 80000.00")
    monkeypatch.setattr(classify_forms, "ocr_bytes_to_text",
                        lambda d, m: "Form W-2 Wage and Tax Statement\nTax year: 2024\nBox 1 Wages, tips, other compensation: 80000.00")
    monkeypatch.setattr(extract_forms, "ocr_bytes_to_text",
                        lambda d, m: "Form W-2 Wage and Tax Statement\nTax year: 2024\nBox 1 Wages, tips, other compensation: 80000.00")

    base = GraphState(
        raw_docs=[InputDocument(content=b"FAKE-W2", filename="w2.pdf", mime_type="application/pdf")],
        filing_year=2024,
        jurisdictions=["US"],
        user_answers={"filing_status": "single", "num_dependents": "0", "state_of_residence": "CA", "foreign_accounts_over_10k": "no"},
    )
    first = _invoke(base)
    before = first.draft_returns["US"].totals["total_income"]

    first.corrections = [Correction(kind="chat", user_prompt="Add a 1099-INT for $400 from Chase", changes=[
        FieldChange(op="add", target="form", form_code="1099-INT",
                    jurisdiction="US", field="interest_income", new_value=400.0),
    ])]
    second = _invoke(first)
    after = second.draft_returns["US"].totals["total_income"]
    assert after == before + 400.0


def test_negative_correction_skipped_and_warned(monkeypatch):
    _setup_stubs(monkeypatch)
    base = GraphState(
        raw_docs=[InputDocument(content=b"FAKE-T4", filename="t4.pdf", mime_type="application/pdf")],
        filing_year=2024,
        jurisdictions=["CA"],
        user_answers={"province_of_residence": "ON", "marital_status": "single", "foreign_property_over_100k": "no"},
    )
    first = _invoke(base)
    before_total = first.draft_returns["CA"].totals["total_income"]

    first.corrections = [Correction(kind="inline_edit", changes=[
        FieldChange(op="set", target="extract", form_code="T4",
                    field="employment_income", new_value=-1000.0),
    ])]
    second = _invoke(first)
    assert second.draft_returns["CA"].totals["total_income"] == before_total
    assert any("cannot be negative" in w for w in second.warnings)
