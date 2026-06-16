"""CA pension income-splitting input must not crash the return.

The informational pension-splitting block referenced an undefined name
(`pensionable`), so any filer supplying `user_answers["pension_split_pct"] > 0`
raised NameError and the ENTIRE draft return died — instead of computing and
appending the advisory split note. The variable was meant to be the eligible
pension income (`eligible_pension`).
"""
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.state import FormExtract


def _retiree_extracts():
    return [
        FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": 30000.0}),
        FormExtract(form_code="T4A", jurisdiction="CA", fields={"pension_or_superannuation": 40000.0}),
    ]


def test_pension_split_does_not_crash_and_emits_note():
    # Before the fix this raised NameError: name 'pensionable' is not defined.
    draft = compute_ca_return(
        _retiree_extracts(), year=2024, province="ON",
        user_answers={"pension_split_pct": "40", "taxpayer_age": "67"},
    )
    assert draft.jurisdiction == "CA"
    assert draft.estimated_tax > 0
    # The advisory note is surfaced with the eligible pension amount and capped pct.
    assert any("Pension income splitting at 40%" in n for n in draft.notes)


def test_pension_split_pct_capped_at_50_in_note():
    draft = compute_ca_return(
        _retiree_extracts(), year=2024, province="ON",
        user_answers={"pension_split_pct": "80", "taxpayer_age": "67"},
    )
    # Up to 50% is splittable; an 80% request is capped to 50% in the note.
    assert any("Pension income splitting at 50%" in n for n in draft.notes)


def test_no_pension_split_pct_no_note_no_crash():
    draft = compute_ca_return(
        _retiree_extracts(), year=2024, province="ON",
        user_answers={"taxpayer_age": "67"},
    )
    assert not any("Pension income splitting" in n for n in draft.notes)


def test_pension_split_pct_with_zero_eligible_pension_emits_no_note():
    # Short-circuit must also be safe when there is no eligible pension income.
    extracts = [FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": 50000.0})]
    draft = compute_ca_return(
        extracts, year=2024, province="ON",
        user_answers={"pension_split_pct": "40"},
    )
    assert draft.jurisdiction == "CA"  # no crash
    assert not any("Pension income splitting" in n for n in draft.notes)
