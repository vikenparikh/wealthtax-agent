"""Batched contract: every remaining un-surfaced calc input must be asked.

Each clarifying-question ``id`` IS the ``user_answers`` key char-for-char, so the
id surfaced here must EXACTLY match the engine key the engine already reads.

This file is the contract that the 26 ids below are (a) surfaced by
``ask_clarifications_node`` and (b) suppressed once answered. It also includes
a handful of reachability-delta guards that drive the REAL engines end-to-end to
prove the surfaced id actually wires to a calc.
"""
import pytest

from wealthtax_agent.clarify import ask_clarifications_node
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.engines.in_engine import compute_in_return
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract, GraphState


# --- The contract: (jurisdiction, id). Each id == engine user_answers key. ---
US_IDS = [
    "num_other_dependents",
    "num_eitc_qualifying_children",
    "taxpayer_age",
    "hsa_coverage",
    "self_employed_health_insurance",
    "qualified_education_expense",
    "num_students",
    "aotc_eligible",
    "spouse_earned_income",
    "state_local_property_tax",
]
CA_IDS = [
    "student_loan_interest_ca",
    "charitable_donations",
    "property_tax_paid",
    "taxpayer_age",
    "full_time_student",
    "has_spouse_or_dependant",
]
IN_IDS = [
    "section_80c_lic",
    "section_80c_epf",
    "section_80c_home_loan_principal",
    "section_80c_elss",
    "section_80d_declared",
    "years_since_first_80e",
    "professional_tax_paid",
    "municipal_tax_paid",
    "home_loan_interest_let_out",
    "section_80ccd_2_employer_nps",
    "salary_is_foreign",
]

CONTRACT = (
    [("US", i) for i in US_IDS]
    + [("CA", i) for i in CA_IDS]
    + [("IN", i) for i in IN_IDS]
)


def _pending(jurisdiction, answers=None):
    state = GraphState(jurisdictions=[jurisdiction], user_answers=answers or {})
    return {q.id for q in ask_clarifications_node(state).clarifying_questions}


# --- char-for-char surfacing guard: id present when unanswered ---------------
@pytest.mark.parametrize("jurisdiction,qid", CONTRACT)
def test_id_is_surfaced_when_unanswered(jurisdiction, qid):
    assert qid in _pending(jurisdiction)


# --- id is suppressed once answered ------------------------------------------
@pytest.mark.parametrize("jurisdiction,qid", CONTRACT)
def test_id_not_re_asked_once_answered(jurisdiction, qid):
    assert qid not in _pending(jurisdiction, {qid: "1"})


# --- answer_type sanity ------------------------------------------------------
def _question(jurisdiction, qid):
    state = GraphState(jurisdictions=[jurisdiction], user_answers={})
    for q in ask_clarifications_node(state).clarifying_questions:
        if q.id == qid:
            return q
    raise AssertionError(f"{qid} not surfaced for {jurisdiction}")


@pytest.mark.parametrize("jurisdiction,qid", [
    ("US", "aotc_eligible"),
    ("CA", "full_time_student"),
    ("CA", "has_spouse_or_dependant"),
    ("IN", "salary_is_foreign"),
])
def test_yes_no_questions(jurisdiction, qid):
    assert _question(jurisdiction, qid).answer_type == "yes_no"


def test_hsa_coverage_is_choice_self_family():
    q = _question("US", "hsa_coverage")
    assert q.answer_type == "choice"
    assert q.options == ["self", "family"]


def test_salary_is_foreign_is_low_priority():
    # low priority so it never flips awaiting_clarification.
    assert _question("IN", "salary_is_foreign").priority == "low"


# --- reachability-delta guards via the REAL engines --------------------------
def _form16_gross(salary):
    return [FormExtract(
        form_code="FORM-16",
        jurisdiction="IN",
        fields={"gross_salary": float(salary)},
    )]


def test_in_section_80c_lic_lowers_total_tax():
    base = compute_in_return(
        _form16_gross(1_200_000), 2024,
        regime="old", residency_status="ROR", user_answers={},
    )
    claimed = compute_in_return(
        _form16_gross(1_200_000), 2024,
        regime="old", residency_status="ROR",
        user_answers={"section_80c_lic": "150000"},
    )
    assert claimed.totals["total_tax"] < base.totals["total_tax"]


def _w2_wages(wages):
    return [FormExtract(
        form_code="W-2",
        jurisdiction="US",
        fields={"wages": float(wages), "federal_income_tax_withheld": 0.0},
    )]


def test_us_num_other_dependents_lowers_total_tax():
    base = compute_us_return(
        _w2_wages(80000), 2024, user_answers={"filing_status": "single"},
    )
    claimed = compute_us_return(
        _w2_wages(80000), 2024,
        user_answers={"filing_status": "single", "num_other_dependents": "2"},
    )
    assert claimed.totals["total_tax"] < base.totals["total_tax"]


def _t4_income(income):
    return [FormExtract(
        form_code="T4",
        jurisdiction="CA",
        fields={"employment_income": float(income)},
    )]


def test_ca_property_tax_paid_lowers_total_tax():
    base = compute_ca_return(_t4_income(70000), 2024, "ON", user_answers={})
    claimed = compute_ca_return(
        _t4_income(70000), 2024, "ON",
        user_answers={"property_tax_paid": "8000"},
    )
    assert claimed.totals["total_tax"] < base.totals["total_tax"]


def test_in_section_80c_elss_lowers_total_tax():
    # ELSS alone, no other 80C key set — otherwise the ₹1.5L cap is already hit
    # and ELSS would add nothing (delta would be 0). Full ₹1.5L ELSS at the
    # old-regime top slab (30% + 4% cess) saves ~₹46,800.
    base = compute_in_return(
        _form16_gross(1_200_000), 2024,
        regime="old", residency_status="ROR", user_answers={},
    )
    claimed = compute_in_return(
        _form16_gross(1_200_000), 2024,
        regime="old", residency_status="ROR",
        user_answers={"section_80c_elss": "150000"},
    )
    assert claimed.totals["total_tax"] < base.totals["total_tax"]


def _w2_with_sch_a_mortgage(wages, mortgage_interest):
    return [
        FormExtract(
            form_code="W-2",
            jurisdiction="US",
            fields={"wages": float(wages), "federal_income_tax_withheld": 0.0},
        ),
        FormExtract(
            form_code="SCH-A",
            jurisdiction="US",
            fields={"mortgage_interest": float(mortgage_interest)},
        ),
    ]


def test_us_state_local_property_tax_lowers_total_tax():
    # An itemizing filer (mortgage interest already beats the standard deduction)
    # so the added property tax lifts the Schedule A SALT bucket and lowers tax.
    extracts = _w2_with_sch_a_mortgage(150000, 25000)
    base = compute_us_return(
        extracts, 2024, user_answers={"filing_status": "single"},
    )
    claimed = compute_us_return(
        extracts, 2024,
        user_answers={"filing_status": "single", "state_local_property_tax": "8000"},
    )
    assert claimed.totals["total_tax"] < base.totals["total_tax"]
