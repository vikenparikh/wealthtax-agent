"""Tests for build_return_node paths not covered by test_filing_artifacts.py.

That file exercises the CA/US PDF + structured artifacts. This adds the IN
artifacts, the always-on year-over-year planning artifact, amendment
worksheets (1040-X / T1-ADJ diff math), per-jurisdiction error isolation,
the CA quarterly instalment vouchers, and the transmissible=False invariant.
"""

import base64
import json

import wealthtax_agent.build_return as br
from wealthtax_agent.build_return import build_return_node
from wealthtax_agent.state import DraftReturn, GraphState


def _state(drafts, **kw):
    return GraphState(filing_year=2024, draft_returns=drafts, **kw)


def _decode(artifact) -> str:
    return base64.b64decode(artifact.content_b64).decode("utf-8")


def test_in_artifacts_include_itr_json_and_summary():
    draft = DraftReturn(
        jurisdiction="IN",
        line_items={"regime": 1.0},
        totals={"total_income": 1_000_000, "taxable_income": 950_000, "total_tax": 100_000},
    )
    arts = build_return_node(_state({"IN": draft})).filing_artifacts
    assert "in_itr_json" in arts and "in_itr_summary" in arts
    assert arts["in_itr_json"].mime_type == "application/json"
    assert json.loads(_decode(arts["in_itr_json"]))["transmissible"] is False
    assert "Regime: new" in _decode(arts["in_itr_summary"])  # regime=1.0 -> new


def test_yoy_planning_artifact_added_when_drafts_present():
    draft = DraftReturn(jurisdiction="CA", totals={"total_income": 80000, "taxable_income": 70000, "total_tax": 12000})
    arts = build_return_node(_state({"CA": draft})).filing_artifacts
    assert "yoy_planning" in arts
    assert "Planning Summary" in _decode(arts["yoy_planning"])


def test_amendment_artifacts_emitted_with_signed_diff():
    draft = DraftReturn(jurisdiction="US", totals={"total_tax": 11000, "total_income": 90000, "taxable_income": 70000})
    state = _state(
        {"US": draft},
        is_amendment=True,
        prior_filed_totals={"US": {"total_tax": 9000, "total_income": 90000, "taxable_income": 70000}},
    )
    arts = build_return_node(state).filing_artifacts
    assert "us_amendment" in arts
    text = _decode(arts["us_amendment"])
    assert "1040-X" in text
    assert "+2,000.00" in text  # amended 11000 - original 9000


def test_no_amendment_artifacts_when_not_an_amendment():
    draft = DraftReturn(jurisdiction="US", totals={"total_tax": 11000})
    arts = build_return_node(_state({"US": draft})).filing_artifacts
    assert not any(k.endswith("_amendment") for k in arts)


def test_jurisdiction_failure_is_isolated_and_warned(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("us serialize failed")

    monkeypatch.setattr(br, "_us_artifacts", _boom)
    drafts = {
        "CA": DraftReturn(jurisdiction="CA", totals={"total_income": 80000, "taxable_income": 70000}),
        "US": DraftReturn(jurisdiction="US", totals={"total_tax": 9000}),
    }
    out = build_return_node(_state(drafts))
    assert "ca_t1_pdf" in out.filing_artifacts          # CA still produced
    assert not any(k.startswith("us_") for k in out.filing_artifacts)
    assert any("Filing artifact generation failed for US" in w for w in out.warnings)


def test_ca_quarterly_instalment_vouchers_when_balance_is_material():
    draft = DraftReturn(jurisdiction="CA", totals={"balance_owing": 8000, "total_income": 100000, "taxable_income": 90000})
    arts = build_return_node(_state({"CA": draft})).filing_artifacts
    assert any(k.startswith("ca_instalment_q") for k in arts)


def test_all_generated_artifacts_are_non_transmissible():
    draft = DraftReturn(jurisdiction="CA", totals={"total_income": 80000, "taxable_income": 70000})
    arts = build_return_node(_state({"CA": draft})).filing_artifacts
    assert arts and all(a.transmissible is False for a in arts.values())


def test_ca_540_state_artifact_emitted_for_ca_resident():
    from wealthtax_agent.state import FormExtract
    draft = DraftReturn(
        jurisdiction="US",
        line_items={"state_tax": 3483.6, "agi": 80000.0,
                    "state_taxable_income": 74637.0, "state_standard_deduction": 5363.0},
        totals={"total_income": 80000, "taxable_income": 70000},
    )
    state = _state({"US": draft},
                   user_answers={"state_of_residence": "CA", "filing_status": "single"},
                   extracts=[FormExtract(form_code="W-2", jurisdiction="US",
                                         fields={"wages": 80000, "state_income_tax": 4000})])
    arts = build_return_node(state).filing_artifacts
    assert "ca_540_json" in arts
    ca = json.loads(_decode(arts["ca_540_json"]))
    assert ca["transmissible"] is False
    assert ca["CA540"]["state_tax"] == 3483.6
    assert ca["CA540"]["state_tax_withheld"] == 4000.0
    assert ca["CA540"]["refund"] == 516.4
    # The CA-540 also gets a human-readable PDF, like the federal 1040 and CA T1.
    assert "ca_540_pdf" in arts
    pdf = arts["ca_540_pdf"]
    assert pdf.mime_type == "application/pdf"
    assert pdf.transmissible is False
    assert base64.b64decode(pdf.content_b64)[:5] == b"%PDF-"


def test_no_ca_540_artifact_for_non_ca_resident():
    # NY resident: the gate is on residence == "CA" (not state_tax > 0), so a
    # state-taxed NY filer gets no Form 540.
    draft = DraftReturn(
        jurisdiction="US",
        line_items={"state_tax": 5000.0, "agi": 90000.0},
        totals={"total_income": 90000, "taxable_income": 80000},
    )
    arts = build_return_node(_state({"US": draft},
                                    user_answers={"state_of_residence": "NY"})).filing_artifacts
    assert "ca_540_json" not in arts
