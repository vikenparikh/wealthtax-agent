"""CA Medical Expense Tax Credit (METC, line 33099) is read by the engine but
surfaced by no clarify config, so it was dormant. Medical expenses are receipt-
only (never slip-sourced), so without a clarifying question a CA filer is never
prompted and the credit never applies.

ca_engine.py reads user_answers["medical_expenses"], computes a credit on the
amount exceeding the lesser of 3% of net income or the fixed floor (~$2,759 for
2024) at the lowest federal rate, and rolls it into federal non-refundable
credits (surfaces as line_item "medical_credit").
"""
from wealthtax_agent.clarify import ask_clarifications_node
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.state import FormExtract, GraphState


def _f(code, juris, **fields):
    return FormExtract(form_code=code, jurisdiction=juris, fields=fields)


def _ca_pending_ids(answers=None):
    state = GraphState(jurisdictions=["CA"], user_answers=answers or {})
    return {q.id for q in ask_clarifications_node(state).clarifying_questions}


# --- clarify config surfacing ------------------------------------------------

def test_ca_filer_is_asked_for_medical_expenses():
    assert "medical_expenses" in _ca_pending_ids()


def test_answered_medical_expenses_not_re_asked():
    assert "medical_expenses" not in _ca_pending_ids({"medical_expenses": "8000"})


# --- engine reachability guard (math already exists + tested) ----------------

def test_ca_medical_expenses_reduce_total_tax():
    without = compute_ca_return(
        [_f("T4", "CA", employment_income=70000)], 2024, province="ON",
        user_answers={},
    )
    with_med = compute_ca_return(
        [_f("T4", "CA", employment_income=70000)], 2024, province="ON",
        user_answers={"medical_expenses": "8000"},
    )
    assert with_med.totals["total_tax"] < without.totals["total_tax"]
    assert with_med.line_items["medical_credit"] > 0
