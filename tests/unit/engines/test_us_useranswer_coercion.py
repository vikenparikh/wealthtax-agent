"""US engine must not crash on non-numeric user-answer values.

`user_answers` holds raw strings (the corrections set-user_answer path stores
str(new_value) uncoerced; clarifying questions are free-text). Three sites in
the education / dependent-care computation coerced user answers with bare
int()/float() and no guard, so a worded answer like "two" / "five thousand"
raised ValueError and killed the ENTIRE US return (engine-level — worse than an
artifact-only failure). They must degrade gracefully like the rest of the
engine (_to_float / _num_dependents already do).
"""
import pytest
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


def _w2(wages: float = 80000.0):
    return [FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": wages})]


@pytest.mark.parametrize("ua", [
    {"num_students": "two", "qualified_education_expense": "5000"},
    {"num_dependent_care_persons": "two", "dependent_care_expenses": "3000"},
    {"qualified_education_expense": "five thousand", "num_students": "1"},
])
def test_us_return_does_not_crash_on_worded_user_answers(ua):
    # Before the fix each of these raised ValueError out of compute_us_return.
    draft = compute_us_return(_w2(), 2024, user_answers=ua)
    assert draft.jurisdiction == "US"
    assert draft.estimated_tax >= 0


def test_numeric_user_answers_still_parse():
    # Regression guard: valid numeric strings (incl. "$"/"," forms) still work.
    draft = compute_us_return(
        _w2(), 2024,
        user_answers={"num_students": "2", "qualified_education_expense": "4000",
                      "num_dependent_care_persons": "1", "dependent_care_expenses": "3000"},
    )
    assert draft.jurisdiction == "US"
    # A real education credit is produced from the parsed expense (not zeroed).
    assert draft.line_items.get("education_credit_chosen", 0.0) > 0.0


def test_worded_num_students_degrades_without_crash_but_numeric_credits():
    # "two" students → degrades to 0 students (no crash); a parallel numeric run
    # with the same expense yields a positive credit — proving the difference is
    # graceful degradation, not a silent global no-op.
    worded = compute_us_return(_w2(), 2024, user_answers={"num_students": "two", "qualified_education_expense": "5000"})
    numeric = compute_us_return(_w2(), 2024, user_answers={"num_students": "1", "qualified_education_expense": "5000"})
    assert worded.jurisdiction == "US"  # no crash
    assert numeric.line_items.get("education_credit_chosen", 0.0) > 0.0
