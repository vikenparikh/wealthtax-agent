"""Amendment ``form_code`` must be correct per jurisdiction.

Pre-registered bug (rung-3): ``_amendment_artifacts`` mapped everything
non-US to Canada's T1-ADJ, so an India amendment was wrongly labelled
``form_code="T1-ADJ"`` (a Canadian form). India's revised return under
§139(5) is ITR-Revised.
"""

import base64

from wealthtax_agent.build_return import _amendment_artifacts
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.engines.in_engine import compute_in_return
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract, GraphState


def _decode(artifact):
    return base64.b64decode(artifact.content_b64).decode("utf-8")


def test_in_amendment_form_code_is_itr_revised():
    extracts = [FormExtract(form_code="FORM16", jurisdiction="IN",
                            fields={"gross_salary": 1200000.0, "tds": 100000.0})]
    draft = compute_in_return(extracts, year=2024)
    state = GraphState(
        filing_year=2024,
        jurisdictions=["IN"],
        extracts=extracts,
        draft_returns={"IN": draft},
        is_amendment=True,
        prior_filed_totals={"IN": {"total_income": 1100000.0, "taxable_income": 1100000.0,
                                   "total_tax": 120000.0, "refund": 0.0, "balance_owing": 0.0}},
    )
    out = _amendment_artifacts(state)
    assert "in_amendment" in out
    art = out["in_amendment"]
    assert art.form_code == "ITR-Revised"
    text = _decode(art)
    assert "ITR-Revised" in text
    assert "T1-ADJ" not in text


def test_us_amendment_form_code_unchanged():
    extracts = [FormExtract(form_code="W-2", jurisdiction="US",
                            fields={"wages": 95000.0, "federal_income_tax_withheld": 12000.0})]
    draft = compute_us_return(extracts, year=2024, user_answers={"filing_status": "single"})
    state = GraphState(
        filing_year=2024,
        jurisdictions=["US"],
        user_answers={"filing_status": "single"},
        extracts=extracts,
        draft_returns={"US": draft},
        is_amendment=True,
        prior_filed_totals={"US": {"total_income": 90000.0, "taxable_income": 75400.0,
                                   "total_tax": 12000.0, "refund": 0.0, "balance_owing": 0.0}},
    )
    out = _amendment_artifacts(state)
    assert out["us_amendment"].form_code == "1040-X"
    assert "1040-X" in _decode(out["us_amendment"])


def test_ca_amendment_form_code_unchanged():
    extracts = [FormExtract(form_code="T4", jurisdiction="CA",
                            fields={"employment_income": 90000.0, "income_tax_deducted": 16000.0})]
    draft = compute_ca_return(extracts, year=2024, province="ON")
    state = GraphState(
        filing_year=2024,
        jurisdictions=["CA"],
        user_answers={"province_of_residence": "ON"},
        extracts=extracts,
        draft_returns={"CA": draft},
        is_amendment=True,
        prior_filed_totals={"CA": {"total_income": 85000.0, "taxable_income": 85000.0,
                                   "total_tax": 18000.0, "refund": 0.0, "balance_owing": 2000.0}},
    )
    out = _amendment_artifacts(state)
    assert out["ca_amendment"].form_code == "T1-ADJ"
    assert "T1-ADJ" in _decode(out["ca_amendment"])
