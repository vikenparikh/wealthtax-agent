"""Age-65+/blindness inputs are read by both engines but surfaced by no clarify
config, so they were dormant. Each clarify question's id IS the user_answers key,
so without a question the filer is never prompted.

US (us_engine.py): taxpayer_age_65_or_older, taxpayer_blind (+ spouse boxes for
MFJ) drive the additional standard deduction.
CA (ca_engine.py): taxpayer_age_65_or_older gates RRIF pension eligibility and
the federal age amount credit (line 30100).
"""
import pytest

from wealthtax_agent.clarify import ask_clarifications_node
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract, GraphState


def _f(code, juris, **fields):
    return FormExtract(form_code=code, jurisdiction=juris, fields=fields)


def _us_pending_ids(answers=None):
    state = GraphState(jurisdictions=["US"], user_answers=answers or {})
    return {q.id for q in ask_clarifications_node(state).clarifying_questions}


def _ca_pending_ids(answers=None):
    state = GraphState(jurisdictions=["CA"], user_answers=answers or {})
    return {q.id for q in ask_clarifications_node(state).clarifying_questions}


# --- clarify config surfacing ------------------------------------------------

@pytest.mark.parametrize("qid", [
    "taxpayer_age_65_or_older",
    "taxpayer_blind",
    "spouse_age_65_or_older",
    "spouse_blind",
])
def test_us_filer_is_asked_for_age_input(qid):
    assert qid in _us_pending_ids()


def test_answered_us_age_input_not_re_asked():
    assert "taxpayer_age_65_or_older" not in _us_pending_ids(
        {"taxpayer_age_65_or_older": "yes"}
    )


def test_ca_filer_is_asked_for_age_input():
    assert "taxpayer_age_65_or_older" in _ca_pending_ids()


def test_answered_ca_age_input_not_re_asked():
    assert "taxpayer_age_65_or_older" not in _ca_pending_ids(
        {"taxpayer_age_65_or_older": "yes"}
    )


# --- engine reachability guards (math already exists + tested) ---------------

def test_us_age_65_reduces_total_tax_by_234():
    base = compute_us_return(
        [_f("W-2", "US", wages=60000)], 2024,
        user_answers={"filing_status": "single"},
    )
    aged = compute_us_return(
        [_f("W-2", "US", wages=60000)], 2024,
        user_answers={"filing_status": "single", "taxpayer_age_65_or_older": "yes"},
    )
    assert round(base.totals["total_tax"] - aged.totals["total_tax"], 2) == 234.00


def test_ca_age_amount_reduces_total_tax_by_1303_31():
    base = compute_ca_return(
        [_f("T4", "CA", employment_income=45000)], 2024, province="ON",
        user_answers={},
    )
    aged = compute_ca_return(
        [_f("T4", "CA", employment_income=45000)], 2024, province="ON",
        user_answers={"taxpayer_age_65_or_older": "yes"},
    )
    assert round(base.totals["total_tax"] - aged.totals["total_tax"], 2) == 1303.31
