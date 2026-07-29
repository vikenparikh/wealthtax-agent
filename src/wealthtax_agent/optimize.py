"""Produce ranked legal tax-optimization suggestions.

Deterministic rules first; the LLM is only used to rewrite each rationale
into plain English when it's available. Each rule reads the parsed extracts
and the draft return, computes an estimated saving using the engine's marginal
rate, and emits an ``OptimizationSuggestion``.
"""

from __future__ import annotations

import json
from typing import Dict, List

from wealthtax_agent.config.tax_tables import MissingTableError, load_tables
from wealthtax_agent.llm import call_with_retry, get_client, load_runtime_config
from wealthtax_agent.state import DraftReturn, FormExtract, GraphState, OptimizationSuggestion


def _marginal_rate(taxable_income: float, brackets: List[Dict]) -> float:
    lower = 0.0
    for bracket in brackets:
        ceiling = bracket.get("up_to")
        rate = float(bracket.get("rate", 0.0))
        if ceiling is None or taxable_income < float(ceiling):
            return rate
        lower = float(ceiling)
    return float(brackets[-1].get("rate", 0.0)) if brackets else 0.0


def _ca_marginal_rate(year: int, taxable_income: float, province: str = "ON") -> float:
    try:
        fed = load_tables("ca", year)
    except MissingTableError:
        fed = {"brackets": []}
    try:
        prov = load_tables("ca", year, sub="provinces", region=province)
    except MissingTableError:
        prov = {"brackets": []}
    return _marginal_rate(taxable_income, fed.get("brackets", [])) + _marginal_rate(taxable_income, prov.get("brackets", []))


def _us_marginal_rate(year: int, taxable_income: float, status: str = "single") -> float:
    try:
        fed = load_tables("us", year)
    except MissingTableError:
        fed = {"brackets_by_status": {status: []}}
    brackets = fed.get("brackets_by_status", {}).get(status, [])
    return _marginal_rate(taxable_income, brackets)


def _in_marginal_rate(year: int, taxable_income: float, regime: str, age: int = 0) -> float:
    """Top applicable slab rate for the taxable income, India.

    Mirrors the CA/US rough-estimate spirit: return the marginal slab rate the
    next rupee of taxable income would be taxed at (no surcharge/cess loading —
    a conservative floor, so est_savings is not overstated). Uses the same
    regime the return was computed under so the estimate matches the filer's
    actual bracket. Old-regime senior/super-senior brackets are honoured.
    """
    try:
        tables = load_tables("in", year)
    except MissingTableError:
        return 0.30  # fall back to the well-known top slab
    if regime == "new":
        brackets = tables.get("new_regime", {}).get("brackets", [])
    else:
        old = tables.get("old_regime", {})
        if age >= 80 and old.get("brackets_super_senior_80_plus"):
            brackets = old["brackets_super_senior_80_plus"]
        elif age >= 60 and old.get("brackets_senior_60_to_80"):
            brackets = old["brackets_senior_60_to_80"]
        else:
            brackets = old.get("brackets", [])
    return _marginal_rate(taxable_income, brackets)


def _in_regime_used(draft: DraftReturn, user_answers: Dict[str, str]) -> str | None:
    """Determine which regime the IN draft was computed under.

    Returns "old", "new", or None (cannot tell reliably).

    Primary signal: the engine stamps ``line_items["regime"]`` = 1.0 for the new
    regime and 0.0 for the old regime (see ``in_engine._compute_one_regime``).
    That is emitted on every IN draft, including the ``regime="auto"`` path
    (auto stamps the CHOSEN regime), so it is the most reliable signal. We fall
    back to ``chapter_via_total > 0`` (only the old regime accrues Chapter VI-A
    deductions) and then to the raw ``in_regime`` user answer only when it is an
    explicit "old"/"new" (never "auto", which doesn't tell us what was picked).
    """
    regime_flag = draft.line_items.get("regime")
    if regime_flag is not None:
        return "new" if float(regime_flag) >= 0.5 else "old"
    if float(draft.line_items.get("chapter_via_total", 0.0) or 0.0) > 0:
        return "old"
    answer = (user_answers.get("in_regime") or "").strip().lower()
    if answer in {"old", "new"}:
        return answer
    return None


def _suggest_in(extracts: List[FormExtract], draft: DraftReturn, year: int, user_answers: Dict[str, str]) -> List[OptimizationSuggestion]:
    """India tax-optimization suggestions, correctly gated by regime.

    Chapter VI-A deductions (80C, 80CCD(1B), 80D) reduce tax ONLY in the OLD
    regime, so those top-up suggestions are emitted ONLY when the return used the
    old regime. 80CCD(2) (employer NPS) is deductible in BOTH regimes and is
    regime-agnostic. If the regime cannot be reliably determined, ONLY the
    regime-agnostic (80CCD(2)) suggestion is emitted, plus a safe "compare the
    old regime" nudge — never a deduction that wouldn't help the filer.
    Caps are read from the engine's tax tables (``config/tax_tables/in/<year>``).
    """
    out: List[OptimizationSuggestion] = []
    li = draft.line_items
    try:
        age = max(0, int(user_answers.get("age", "0")))
    except (TypeError, ValueError):
        age = 0

    regime = _in_regime_used(draft, user_answers)
    marginal = _in_marginal_rate(year, draft.taxable_income, regime or "new", age)

    try:
        tables = load_tables("in", year)
    except MissingTableError:
        tables = {}
    caps = tables.get("deductions", {})
    cap_80c = float(caps.get("section_80c_cap", 150000))          # ₹1,50,000 (2024)
    cap_80ccd_1b = float(caps.get("section_80ccd_1b_nps_cap", 50000))  # ₹50,000
    cap_80d_self = float(caps.get(
        "section_80d_self_senior_60_plus" if age >= 60 else "section_80d_self_under_60",
        50000 if age >= 60 else 25000,
    ))
    ccd2_pct = float(caps.get("section_80ccd_2_salary_pct", 0.10))

    # ---- OLD-regime-only Chapter VI-A top-ups ----
    if regime == "old":
        # 80C: used figure (already capped by the engine) vs the ₹1.5L cap.
        used_80c = float(li.get("section_80c", 0.0) or 0.0)
        gap_80c = cap_80c - used_80c
        if gap_80c > 1000:
            out.append(OptimizationSuggestion(
                id="in_80c_topup",
                jurisdiction="IN",
                title=f"Invest ₹{gap_80c:,.0f} more under Section 80C (ELSS/PPF/EPF/LIC)",
                rationale=(
                    f"You've used ₹{used_80c:,.0f} of the ₹{cap_80c:,.0f} Section 80C limit. "
                    f"At your marginal rate of {marginal:.0%}, investing the remaining "
                    f"₹{gap_80c:,.0f} in ELSS, PPF, EPF or LIC would reduce your tax."
                ),
                est_savings=round(gap_80c * marginal, 2),
                horizon="now",
                action_steps=[
                    "Invest before 31 March to claim against this financial year.",
                    "ELSS has the shortest (3-year) lock-in; PPF/EPF are safer, longer-term.",
                    "Section 80C is available only in the OLD regime you filed under.",
                ],
            ))

        # 80CCD(1B): additional ₹50,000 NPS, over and above 80C.
        used_80ccd_1b = float(li.get("section_80ccd_1b", 0.0) or 0.0)
        gap_80ccd_1b = cap_80ccd_1b - used_80ccd_1b
        if gap_80ccd_1b > 1000:
            out.append(OptimizationSuggestion(
                id="in_80ccd1b_nps",
                jurisdiction="IN",
                title=f"Contribute ₹{gap_80ccd_1b:,.0f} to NPS under Section 80CCD(1B)",
                rationale=(
                    f"Section 80CCD(1B) gives an extra ₹{cap_80ccd_1b:,.0f} NPS deduction "
                    f"over and above 80C. At your marginal rate of {marginal:.0%}, the unused "
                    f"₹{gap_80ccd_1b:,.0f} would further cut your tax (old regime only)."
                ),
                est_savings=round(gap_80ccd_1b * marginal, 2),
                horizon="now",
                action_steps=[
                    "Open or top up a Tier-I NPS account before 31 March.",
                    "This ₹50,000 is separate from — and stacks on top of — your 80C limit.",
                ],
            ))

        # 80D: health insurance premium vs the self cap (senior bump applied).
        used_80d = float(li.get("section_80d", 0.0) or 0.0)
        gap_80d = cap_80d_self - used_80d
        if gap_80d > 1000:
            out.append(OptimizationSuggestion(
                id="in_80d_health",
                jurisdiction="IN",
                title=f"Buy/top up health insurance for ₹{gap_80d:,.0f} more under Section 80D",
                rationale=(
                    f"You've claimed ₹{used_80d:,.0f} of the ₹{cap_80d_self:,.0f} Section 80D "
                    f"health-insurance limit. At {marginal:.0%}, insuring for the remaining "
                    f"₹{gap_80d:,.0f} in premium would reduce your tax (old regime only)."
                ),
                est_savings=round(gap_80d * marginal, 2),
                horizon="now",
                action_steps=[
                    "A separate ₹25,000–₹50,000 limit applies for parents' premiums.",
                    "Pay by a traceable mode (not cash) to keep the deduction valid.",
                ],
            ))

    # ---- Regime-agnostic: 80CCD(2) employer NPS (deductible in BOTH regimes) ----
    used_80ccd_2 = float(li.get("section_80ccd_2_employer_nps", 0.0) or 0.0)
    gross_salary = float(li.get("gross_salary", 0.0) or 0.0)
    if gross_salary > 0 and used_80ccd_2 <= 0:
        # Up to 10% of salary (basic+DA); the engine models the base as basic
        # salary, falling back to gross. line_items exposes only gross_salary, so
        # estimate the headroom conservatively off gross.
        ccd2_headroom = round(ccd2_pct * gross_salary, 2)
        out.append(OptimizationSuggestion(
            id="in_80ccd2_employer_nps",
            jurisdiction="IN",
            title="Ask your employer to route part of your CTC into NPS (Section 80CCD(2))",
            rationale=(
                f"Employer NPS contributions of up to {ccd2_pct:.0%} of salary are deductible "
                "in BOTH the old and new regimes — the one Chapter VI-A benefit the new regime "
                f"keeps. At {marginal:.0%}, up to ₹{ccd2_headroom:,.0f} of contribution is untaxed."
            ),
            est_savings=round(ccd2_headroom * marginal, 2),
            horizon="future",
            action_steps=[
                "Ask HR for a corporate-NPS (80CCD(2)) salary-restructuring option.",
                "This is over and above your own 80C / 80CCD(1B) limits.",
            ],
        ))

    # ---- Safe, always-correct nudge when the return used the NEW regime but
    #      significant deductions were declared: compare the old regime. ----
    if regime == "new":
        declared = sum(float(li.get(k, 0.0) or 0.0) for k in (
            "section_80c", "section_80ccd_1b", "section_80d", "hra_exemption",
        ))
        # In the new regime these engine figures are 0 (disallowed), so look at
        # the raw declared inputs the filer supplied instead.
        raw_declared = (
            _sum_field_in(extracts, "INVESTMENTS-80C", "amount")
            + _sum_field_in(extracts, "FORM-16", "section_80c_declared")
            + _sum_field_in(extracts, "FORM-16", "section_80d_declared")
            + _to_float_in(user_answers.get("section_80c_ppf"))
            + _to_float_in(user_answers.get("section_80c_elss"))
            + _to_float_in(user_answers.get("section_80d_self_premium"))
            + _to_float_in(user_answers.get("annual_rent_paid"))
        )
        manual = (user_answers.get("in_regime") or "").strip().lower()
        if (declared > 0 or raw_declared > 50000) and manual == "new":
            out.append(OptimizationSuggestion(
                id="in_compare_old_regime",
                jurisdiction="IN",
                title="Compare the OLD regime — your declared deductions may make it cheaper",
                rationale=(
                    "You filed under the new regime but reported significant deductions "
                    "(80C / 80D / HRA). Those reduce tax only in the old regime, which may "
                    "produce a lower bill. Let the engine pick automatically (regime=auto)."
                ),
                est_savings=0.0,
                horizon="now",
                action_steps=[
                    "Re-run with in_regime='auto' to let the engine choose the lower-tax regime.",
                    "The old regime is only worth it if your total deductions are large enough.",
                ],
            ))

    return out


def _to_float_in(value) -> float:
    if value is None:
        return 0.0
    try:
        return float(str(value).replace(",", "").strip() or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _sum_field_in(extracts: List[FormExtract], form_code: str, field: str) -> float:
    return float(sum(
        e.fields.get(field, 0.0)
        for e in extracts
        if e.form_code == form_code and e.jurisdiction == "IN"
    ))


def _suggest_ca(extracts: List[FormExtract], draft: DraftReturn, year: int, user_answers: Dict[str, str]) -> List[OptimizationSuggestion]:
    out: List[OptimizationSuggestion] = []
    marginal = _ca_marginal_rate(year, draft.taxable_income)

    rrsp_contributed = sum(e.fields.get("rrsp_contributions", 0.0) for e in extracts if e.form_code == "RRSP")
    employment_income = draft.line_items.get("employment_income", 0.0)
    rrsp_room = 0.0
    try:
        rrsp_room = float(user_answers.get("rrsp_room_remaining", "0") or 0)
    except ValueError:
        rrsp_room = 0.0
    if rrsp_room <= 0 and employment_income > 0:
        # Estimate using 18% of prior-year earned income as a rough cap
        rrsp_room = max(0.0, employment_income * 0.18 - rrsp_contributed)
    if rrsp_room > 1000:
        # `rrsp_room` is the user's TOTAL deduction limit — a CRA Notice-of-
        # Assessment figure already rolls in all prior years' unused room plus the
        # current 18% accrual, and it is fully deductible this year (room carries
        # forward indefinitely). Do NOT re-cap it at one year's 18% accrual; the
        # 18% cap is applied only on the estimate branch above when no NOA room is
        # supplied. (Re-capping told a filer with $50k of real room to contribute
        # only $18k.)
        contribution = rrsp_room
        out.append(OptimizationSuggestion(
            id="rrsp_topup",
            jurisdiction="CA",
            title=f"Contribute up to ${contribution:,.0f} more to your RRSP",
            rationale=(
                f"You have unused RRSP room. At your marginal rate of {marginal:.0%}, a ${contribution:,.0f} "
                "contribution would defer roughly the amount shown in estimated savings."
            ),
            est_savings=round(contribution * marginal, 2),
            horizon="now",
            action_steps=[
                "Verify exact room on your latest CRA Notice of Assessment.",
                "Contribute before the March 1st deadline to claim against this tax year.",
                "Keep the official contribution receipt for filing.",
            ],
        ))

    # Capital loss harvesting from T5008
    losing_dispositions = [
        e for e in extracts
        if e.form_code == "T5008" and e.fields.get("capital_gain", 0.0) < 0
    ]
    if losing_dispositions:
        loss = sum(-e.fields.get("capital_gain", 0.0) for e in losing_dispositions)
        out.append(OptimizationSuggestion(
            id="capital_loss_harvest_ca",
            jurisdiction="CA",
            title=f"Use ${loss:,.0f} of realized capital losses",
            rationale="Net capital losses can offset taxable capital gains in the current year, prior 3 years, or carry forward indefinitely.",
            est_savings=round(loss * 0.5 * marginal, 2),  # inclusion rate 0.5
            horizon="now",
            action_steps=[
                "Aggregate gains and losses on Schedule 3.",
                "Consider carrying back to one of the prior 3 years if it produced higher taxes.",
            ],
        ))

    # FHSA eligibility hint (if young first-time home buyer signal absent)
    if user_answers.get("home_buyer_first", "").lower() not in {"yes", "true", "1"}:
        out.append(OptimizationSuggestion(
            id="fhsa",
            jurisdiction="CA",
            title="Open and contribute to a First Home Savings Account (FHSA)",
            rationale="FHSA contributions are deductible like an RRSP and withdrawals for a first home are tax-free like a TFSA. $8,000/yr, $40,000 lifetime.",
            est_savings=round(8000 * marginal, 2),
            horizon="future",
            action_steps=[
                "Open an FHSA at any qualifying institution before year-end to start the room clock.",
                "Contribute up to $8,000 this year and deduct it.",
            ],
        ))

    # T2202 tuition transfer
    tuition = sum(e.fields.get("eligible_tuition_fees", 0.0) for e in extracts if e.form_code == "T2202")
    if tuition > 0:
        out.append(OptimizationSuggestion(
            id="tuition_transfer",
            jurisdiction="CA",
            title=f"Consider transferring up to ${min(tuition, 5000):,.0f} of tuition credit to a supporting relative",
            rationale="If you don't need the full tuition credit, up to $5,000 can be transferred to a parent, grandparent, or spouse this year. The rest carries forward.",
            est_savings=round(min(tuition, 5000) * 0.15, 2),
            horizon="now",
            action_steps=[
                "Coordinate with the supporting relative to ensure they sign the transfer back of the T2202.",
                "Keep the original T2202 in case CRA asks.",
            ],
        ))

    return out


def _suggest_us(extracts: List[FormExtract], draft: DraftReturn, year: int, user_answers: Dict[str, str]) -> List[OptimizationSuggestion]:
    out: List[OptimizationSuggestion] = []
    status = user_answers.get("filing_status", "single").lower().replace(" ", "_")
    if status == "mfj":
        status = "married_filing_jointly"
    marginal = _us_marginal_rate(year, draft.taxable_income, status)

    try:
        fed = load_tables("us", year)
    except MissingTableError:
        fed = {}
    ira_limit = float(fed.get("ira", {}).get("contribution_limit", 7000))
    plan_401k_limit = float(fed.get("plan_401k", {}).get("contribution_limit", 23000))

    wages = draft.line_items.get("wages", 0.0)
    if wages > 0:
        out.append(OptimizationSuggestion(
            id="max_401k",
            jurisdiction="US",
            title=f"Maximize 401(k) up to ${plan_401k_limit:,.0f}",
            rationale=f"At your marginal rate of {marginal:.0%}, every dollar contributed to a traditional 401(k) reduces federal tax by that rate this year.",
            est_savings=round(plan_401k_limit * marginal, 2),
            horizon="now",
            action_steps=[
                "Increase elective deferrals via payroll.",
                "If self-employed, consider a Solo 401(k) before year-end.",
            ],
        ))

    if draft.totals.get("agi", 0.0) < 150000:
        out.append(OptimizationSuggestion(
            id="ira_or_roth",
            jurisdiction="US",
            title=f"Contribute up to ${ira_limit:,.0f} to a Traditional or Roth IRA",
            rationale="Traditional IRA reduces current AGI; Roth IRA grows tax-free. Below the phase-out you can pick either.",
            est_savings=round(ira_limit * marginal, 2),
            horizon="now",
            action_steps=[
                "Contribute by the April filing deadline to count for this tax year.",
                "Choose Roth if you expect higher brackets in retirement; Traditional otherwise.",
            ],
        ))

    # HSA prompt
    if user_answers.get("hsa_eligible", "").lower() in {"yes", "true", "1"}:
        out.append(OptimizationSuggestion(
            id="hsa_max",
            jurisdiction="US",
            title="Max out your HSA",
            rationale="HSA contributions are triple-tax-advantaged: deductible now, grow tax-free, and tax-free if used for qualified medical expenses.",
            est_savings=round(4150 * marginal, 2),
            horizon="now",
            action_steps=[
                "Confirm 2024 HSA limits ($4,150 self / $8,300 family) and contribute before the filing deadline.",
            ],
        ))

    # Capital loss harvesting
    short = draft.line_items.get("short_term_capital_gain", 0.0)
    long_ = draft.line_items.get("long_term_capital_gain", 0.0)
    if short + long_ > 0:
        out.append(OptimizationSuggestion(
            id="capital_loss_harvest_us",
            jurisdiction="US",
            title="Look for losing positions to harvest against your gains",
            rationale="Realized losses offset realized gains dollar-for-dollar; excess up to $3,000 offsets ordinary income and the rest carries forward.",
            est_savings=round(min(short + long_, 3000) * marginal, 2),
            horizon="now",
            action_steps=[
                "Review brokerage holdings for unrealized losses before year-end.",
                "Mind the 30-day wash-sale rule on substantially identical securities.",
            ],
        ))

    # Student loan interest reminder
    sl = draft.line_items.get("student_loan_interest_deduction", 0.0)
    if sl > 0:
        out.append(OptimizationSuggestion(
            id="student_loan_interest_claimed",
            jurisdiction="US",
            title="Confirm you can claim the full student loan interest deduction",
            rationale="Up to $2,500 of student loan interest is above-the-line deductible, subject to MAGI phase-outs ($80k single, $165k MFJ for 2024).",
            est_savings=round(min(sl, 2500) * marginal, 2),
            horizon="now",
            action_steps=[
                "Confirm your MAGI is below the phase-out threshold for your filing status.",
            ],
        ))

    return out


def _llm_rerank(suggestions: List[OptimizationSuggestion]) -> List[OptimizationSuggestion]:
    if not suggestions:
        return suggestions
    try:
        runtime = load_runtime_config()
        client = get_client(runtime)
    except Exception:
        return suggestions

    payload = [s.model_dump() for s in suggestions]
    prompt = (
        "Rewrite each tax-optimization rationale into clear, friendly English under 35 words. "
        "Preserve the JSON shape. Reply with JSON: {\"suggestions\": [...same fields...]}."
    )

    def _call():
        return client.chat.completions.create(
            model=runtime.explain_model,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": json.dumps({"suggestions": payload})},
            ],
            response_format={"type": "json_object"},
        )

    try:
        response = call_with_retry(_call)
        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        items = data.get("suggestions", [])
        rewritten: List[OptimizationSuggestion] = []
        by_id = {s.id: s for s in suggestions}
        for item in items:
            sid = str(item.get("id", ""))
            base = by_id.get(sid)
            if base is None:
                continue
            base = base.model_copy(update={"rationale": str(item.get("rationale", base.rationale))})
            rewritten.append(base)
        if rewritten:
            return rewritten
    except Exception:
        pass
    return suggestions


def optimize_node(state: GraphState) -> GraphState:
    suggestions: List[OptimizationSuggestion] = []
    year = state.filing_year or 2024
    answers = state.user_answers or {}

    for jurisdiction, draft in state.draft_returns.items():
        jurisdiction_extracts = [e for e in state.extracts if e.jurisdiction == jurisdiction]
        if jurisdiction == "CA":
            suggestions.extend(_suggest_ca(jurisdiction_extracts, draft, year, answers))
        elif jurisdiction == "US":
            suggestions.extend(_suggest_us(jurisdiction_extracts, draft, year, answers))
        elif jurisdiction == "IN":
            suggestions.extend(_suggest_in(jurisdiction_extracts, draft, year, answers))

    suggestions.sort(key=lambda s: s.est_savings, reverse=True)
    state.optimization_suggestions = _llm_rerank(suggestions)
    return state
