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
        contribution = min(rrsp_room, employment_income * 0.18)
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

    suggestions.sort(key=lambda s: s.est_savings, reverse=True)
    state.optimization_suggestions = _llm_rerank(suggestions)
    return state
