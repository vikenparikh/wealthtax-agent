"""RRSP top-up advice must respect the user's full accumulated NOA room.

RRSP "room" on a CRA Notice of Assessment is the TOTAL deduction limit — it
already rolls in all prior years' unused room plus the current year's 18%
accrual, and it is fully deductible this year (room carries forward
indefinitely). The optimizer wrongly re-capped the user's explicit room at one
year's 18%-of-income accrual, telling a filer with $50k of real room to
contribute only $18k — understating the deductible amount and the tax deferral.
"""
from wealthtax_agent.optimize import _suggest_ca, _ca_marginal_rate
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.state import FormExtract


def _draft(income=100000.0):
    t4 = [FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": income})]
    return t4, compute_ca_return(t4, 2024, "ON", user_answers={})


def _rrsp(suggestions):
    return next((s for s in suggestions if s.id == "rrsp_topup"), None)


def test_explicit_noa_room_is_fully_deductible():
    t4, draft = _draft(100000.0)
    s = _rrsp(_suggest_ca(t4, draft, 2024, {"rrsp_room_remaining": "50000"}))
    assert s is not None
    # Full $50,000 NOA room, NOT re-capped at 18% of income ($18,000).
    marginal = _ca_marginal_rate(2024, draft.taxable_income)
    assert s.est_savings == round(50000.0 * marginal, 2)
    assert "50,000" in s.title


def test_estimate_path_uses_18pct_accrual_unchanged():
    # No explicit room -> estimate 18% of income minus what's already contributed.
    t4 = [FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": 100000.0}),
          FormExtract(form_code="RRSP", jurisdiction="CA", fields={"rrsp_contributions": 5000.0})]
    draft = compute_ca_return(t4, 2024, "ON", user_answers={})
    s = _rrsp(_suggest_ca(t4, draft, 2024, {}))
    assert s is not None
    marginal = _ca_marginal_rate(2024, draft.taxable_income)
    # 18% x 100,000 - 5,000 already contributed = 13,000.
    assert s.est_savings == round(13000.0 * marginal, 2)


def test_room_below_threshold_no_suggestion():
    t4, draft = _draft(100000.0)
    s = _rrsp(_suggest_ca(t4, draft, 2024, {"rrsp_room_remaining": "500"}))
    assert s is None
