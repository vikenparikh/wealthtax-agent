"""India tax-optimization suggestions — regime-gated correctness.

The critical guard: Chapter VI-A top-ups (80C/80D/80CCD(1B)) reduce tax ONLY in
the old regime, so a new-regime filer must NEVER receive them. 80CCD(2) is
regime-agnostic. Fixtures are built through the real India engine so the
regime-detection signal (line_items["regime"]) is exercised end-to-end.
"""

from unittest.mock import patch

from wealthtax_agent.engines.in_engine import compute_in_return
from wealthtax_agent.optimize import _suggest_in, optimize_node
from wealthtax_agent.state import DraftReturn, FormExtract, GraphState


def _no_rerank():
    return patch("wealthtax_agent.optimize._llm_rerank", side_effect=lambda x: x)


def _form16(**fields) -> FormExtract:
    return FormExtract(form_code="FORM-16", jurisdiction="IN", fields=fields)


def _old_regime_draft(**answers) -> DraftReturn:
    # Salary high enough to be in the 20%+ old-regime slab, with unused 80C/80D.
    extracts = [_form16(gross_salary=1200000.0, basic_salary=600000.0, tds_deducted=100000.0)]
    return compute_in_return(extracts, 2024, regime="old", user_answers=answers)


def _new_regime_draft(**answers) -> DraftReturn:
    extracts = [_form16(gross_salary=1200000.0, basic_salary=600000.0, tds_deducted=100000.0)]
    return compute_in_return(extracts, 2024, regime="new", user_answers=answers)


def test_old_regime_filer_gets_80c_80d_topups_with_positive_savings():
    draft = _old_regime_draft(section_80c_ppf=50000, section_80d_self_premium=5000)
    suggestions = _suggest_in([], draft, 2024, {"in_regime": "old"})
    ids = {s.id for s in suggestions}
    assert "in_80c_topup" in ids
    assert "in_80d_health" in ids
    assert "in_80ccd1b_nps" in ids  # unused NPS 80CCD(1B)
    for s in suggestions:
        if s.id in {"in_80c_topup", "in_80d_health", "in_80ccd1b_nps"}:
            assert s.est_savings > 0, f"{s.id} should have positive est_savings"
            assert s.jurisdiction == "IN"


def test_new_regime_filer_gets_no_invalid_deduction_advice():
    # THE correctness guard: no 80C/80D/80CCD(1B) top-up under the new regime.
    draft = _new_regime_draft(section_80c_ppf=50000, section_80d_self_premium=5000)
    suggestions = _suggest_in([], draft, 2024, {"in_regime": "new"})
    ids = {s.id for s in suggestions}
    assert "in_80c_topup" not in ids
    assert "in_80d_health" not in ids
    assert "in_80ccd1b_nps" not in ids
    # Regime-agnostic 80CCD(2) is still allowed (employer NPS unused here).
    assert "in_80ccd2_employer_nps" in ids


def test_80ccd2_is_regime_agnostic_and_suggested_in_both_regimes():
    old = _suggest_in([], _old_regime_draft(), 2024, {"in_regime": "old"})
    new = _suggest_in([], _new_regime_draft(), 2024, {"in_regime": "new"})
    assert any(s.id == "in_80ccd2_employer_nps" for s in old)
    assert any(s.id == "in_80ccd2_employer_nps" for s in new)


def test_80ccd2_not_suggested_when_already_used():
    draft = _old_regime_draft(section_80ccd_2_employer_nps=60000)
    suggestions = _suggest_in([], draft, 2024, {"in_regime": "old"})
    assert not any(s.id == "in_80ccd2_employer_nps" for s in suggestions)


def test_new_regime_with_big_declared_deductions_gets_compare_nudge():
    draft = _new_regime_draft()
    # Filer manually chose new regime but declared large 80C investments.
    extracts = [
        FormExtract(form_code="INVESTMENTS-80C", jurisdiction="IN", fields={"amount": 150000.0}),
    ]
    suggestions = _suggest_in(extracts, draft, 2024, {"in_regime": "new"})
    ids = {s.id for s in suggestions}
    assert "in_compare_old_regime" in ids
    # And still no invalid deduction top-ups.
    assert "in_80c_topup" not in ids


def test_regime_unknown_defaults_to_agnostic_only():
    # No regime flag, no chapter-VI-A total, no explicit in_regime answer.
    draft = DraftReturn(
        jurisdiction="IN",
        tax_year=2024,
        taxable_income=1200000.0,
        estimated_tax=150000.0,
        line_items={"gross_salary": 1200000.0},  # no "regime" key
    )
    suggestions = _suggest_in([], draft, 2024, {})
    ids = {s.id for s in suggestions}
    # No regime-specific advice may be emitted.
    assert "in_80c_topup" not in ids
    assert "in_80d_health" not in ids
    assert "in_80ccd1b_nps" not in ids
    assert "in_compare_old_regime" not in ids
    # Only the regime-agnostic 80CCD(2) is safe.
    assert ids <= {"in_80ccd2_employer_nps"}


def test_dispatch_produces_at_least_one_suggestion_for_in_draft():
    draft = _old_regime_draft(section_80c_ppf=30000)
    state = GraphState(
        filing_year=2024,
        jurisdictions=["IN"],
        user_answers={"in_regime": "old"},
        extracts=[_form16(gross_salary=1200000.0, basic_salary=600000.0)],
        draft_returns={"IN": draft},
    )
    with _no_rerank():
        result = optimize_node(state)
    assert len(result.optimization_suggestions) >= 1
    assert all(s.jurisdiction == "IN" for s in result.optimization_suggestions)


def test_auto_regime_draft_regime_detected_from_line_items_flag():
    # regime="auto" stamps the CHOSEN regime's flag; detection must follow it.
    draft = _old_regime_draft(section_80c_ppf=50000)
    assert draft.line_items["regime"] == 0.0  # old chosen
    suggestions = _suggest_in([], draft, 2024, {"in_regime": "auto"})
    assert any(s.id == "in_80c_topup" for s in suggestions)
