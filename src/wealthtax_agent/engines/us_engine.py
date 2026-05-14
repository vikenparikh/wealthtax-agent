"""US federal + state (CA) tax engine.

Pure functions; no LLM. Tables are loaded from
``config/tax_tables/us/<year>.yaml`` and
``config/tax_tables/us/states/<state>/<year>.yaml``.

Scope (v1):
- Federal progressive brackets per filing status (single, MFJ, HoH)
- Standard deduction
- Qualified dividends + long-term capital gains preferential rates
- Short-term capital gains taxed at ordinary rate
- Child Tax Credit (basic phase-out)
- FICA (Social Security + Medicare) on W-2 wages and Sch C / 1099-NEC SE income
- California state income tax (basic brackets + standard deduction)

Out of scope (notes): AMT, NIIT, EITC complex limits (referenced as suggestion),
QBI deduction, state-specific credits, multistate apportionment.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from wealthtax_agent.config.tax_tables import (
    MissingTableError,
    compute_progressive_tax,
    load_tables,
)
from wealthtax_agent.state import DraftReturn, FormExtract


VALID_FILING_STATUSES = {"single", "married_filing_jointly", "head_of_household"}


def _sum_field(extracts: Iterable[FormExtract], form_code: str, field: str) -> float:
    return float(sum(
        e.fields.get(field, 0.0)
        for e in extracts
        if e.form_code == form_code and e.jurisdiction == "US"
    ))


def _sch_d_short_long(extracts: Iterable[FormExtract]) -> tuple[float, float]:
    short = _sum_field(extracts, "SCH-D", "net_short_term_capital_gain")
    long_ = _sum_field(extracts, "SCH-D", "net_long_term_capital_gain")
    # Fallback to 1099-B if Sch D not provided
    if short == 0.0 and long_ == 0.0:
        for e in extracts:
            if e.form_code != "1099-B" or e.jurisdiction != "US":
                continue
            gain = float(e.fields.get("gain_loss", 0.0))
            term = e.fields.get("term", 0.0)
            if term and term >= 1.0:
                long_ += gain
            else:
                short += gain
    return short, long_


def _resolve_filing_status(user_answers: Dict[str, str]) -> str:
    raw = (user_answers.get("filing_status", "single") or "single").strip().lower().replace(" ", "_")
    if raw == "mfj":
        raw = "married_filing_jointly"
    if raw == "hoh":
        raw = "head_of_household"
    if raw not in VALID_FILING_STATUSES:
        raw = "single"
    return raw


def _num_dependents(user_answers: Dict[str, str]) -> int:
    try:
        return max(0, int(user_answers.get("num_dependents", "0")))
    except (TypeError, ValueError):
        return 0


def _qualified_dividend_tax(qualified_dividends: float, long_term_gain: float, ordinary_taxable_income: float,
                            status: str, fed_tables: Dict[str, Any]) -> float:
    """Tax preferential income (qualified divs + LTCG) using LTCG brackets,
    stacked on top of ordinary taxable income."""
    if qualified_dividends + long_term_gain <= 0:
        return 0.0
    ltcg_brackets = fed_tables.get("long_term_capital_gains", {}).get(status, [])
    if not ltcg_brackets:
        return 0.0
    preferential_income = qualified_dividends + max(0.0, long_term_gain)
    total_with_pref = ordinary_taxable_income + preferential_income
    tax_total = compute_progressive_tax(total_with_pref, ltcg_brackets)
    tax_ordinary_only = compute_progressive_tax(ordinary_taxable_income, ltcg_brackets)
    return round(max(0.0, tax_total - tax_ordinary_only), 2)


def _compute_ctc(num_dependents: int, agi: float, status: str, fed_tables: Dict[str, Any]) -> float:
    ctc = fed_tables.get("ctc", {})
    per_child = float(ctc.get("per_child", 2000))
    phaseout_start = float(
        ctc.get("phaseout_start_mfj", 400000) if status == "married_filing_jointly"
        else ctc.get("phaseout_start_single", 200000)
    )
    base = num_dependents * per_child
    if agi <= phaseout_start:
        return base
    excess = ((agi - phaseout_start) // 1000) * 50
    return max(0.0, base - float(excess))


def _compute_fica(w2_wages: float, se_net: float, status: str, fed_tables: Dict[str, Any]) -> float:
    fica = fed_tables.get("fica", {})
    ss_rate = float(fica.get("social_security_rate", 0.062))
    ss_base = float(fica.get("social_security_wage_base", 168600))
    medicare_rate = float(fica.get("medicare_rate", 0.0145))
    additional_rate = float(fica.get("additional_medicare_rate", 0.009))
    addl_threshold = float(
        fica.get("additional_medicare_threshold_mfj", 250000) if status == "married_filing_jointly"
        else fica.get("additional_medicare_threshold_single", 200000)
    )

    # Employee share already withheld via W-2; Self-employed pays both halves on
    # 92.35% of net SE earnings.
    se_earnings = se_net * 0.9235 if se_net > 0 else 0.0
    se_ss_tax = min(se_earnings, max(0.0, ss_base - w2_wages)) * (ss_rate * 2)
    se_medicare_tax = se_earnings * (medicare_rate * 2)
    total_wages = w2_wages + se_earnings
    additional_medicare = max(0.0, total_wages - addl_threshold) * additional_rate

    return round(se_ss_tax + se_medicare_tax + additional_medicare, 2)


def compute_us_return(
    extracts: List[FormExtract],
    year: int,
    state: Optional[str] = None,
    user_answers: Dict[str, str] | None = None,
) -> DraftReturn:
    user_answers = user_answers or {}
    status = _resolve_filing_status(user_answers)
    num_deps = _num_dependents(user_answers)
    notes: List[str] = []

    try:
        fed_tables = load_tables("us", year)
    except MissingTableError as exc:
        notes.append(f"Federal US table missing for {year}: {exc}")
        fed_tables = {"brackets_by_status": {status: []}, "standard_deduction": {status: 0}}

    state_tables = None
    if state:
        try:
            state_tables = load_tables("us", year, sub="states", region=state)
        except MissingTableError as exc:
            notes.append(f"State table missing for {state} {year}: {exc}")

    # ---- Income ----
    wages = _sum_field(extracts, "W-2", "wages")
    fed_withheld = _sum_field(extracts, "W-2", "federal_income_tax_withheld")
    interest_income = (
        _sum_field(extracts, "1099-INT", "interest_income")
        + _sum_field(extracts, "1099-INT", "us_treasury_interest")
    )
    ordinary_dividends = _sum_field(extracts, "1099-DIV", "ordinary_dividends")
    qualified_dividends = _sum_field(extracts, "1099-DIV", "qualified_dividends")
    nec = _sum_field(extracts, "1099-NEC", "nonemployee_compensation")
    sch_c_profit = _sum_field(extracts, "SCH-C", "net_profit")
    misc_rents = _sum_field(extracts, "1099-MISC", "rents")
    misc_royalties = _sum_field(extracts, "1099-MISC", "royalties")
    misc_other = _sum_field(extracts, "1099-MISC", "other_income")
    pension_taxable = _sum_field(extracts, "1099-R", "taxable_amount")
    ssa_net = _sum_field(extracts, "SSA-1099", "net_benefits")

    short_gain, long_gain = _sch_d_short_long(extracts)

    # K-1
    k1_business = _sum_field(extracts, "K-1", "ordinary_business_income")
    k1_interest = _sum_field(extracts, "K-1", "interest_income")
    k1_qdiv = _sum_field(extracts, "K-1", "qualified_dividends")
    k1_st_gain = _sum_field(extracts, "K-1", "net_short_term_capital_gain")
    k1_lt_gain = _sum_field(extracts, "K-1", "net_long_term_capital_gain")

    interest_income += k1_interest
    qualified_dividends += k1_qdiv
    short_gain += k1_st_gain
    long_gain += k1_lt_gain

    self_employment_income = nec + sch_c_profit + k1_business

    # 1098-E student loan interest deduction (capped at $2500)
    student_loan_interest = min(2500.0, _sum_field(extracts, "1098-E", "student_loan_interest"))

    # Social security partial inclusion (simplified: 85%)
    taxable_ssa = ssa_net * 0.85 if ssa_net > 0 else 0.0

    total_income = round(
        wages
        + interest_income
        + ordinary_dividends
        + nec
        + sch_c_profit
        + misc_rents
        + misc_royalties
        + misc_other
        + pension_taxable
        + taxable_ssa
        + max(0.0, short_gain)
        + max(0.0, long_gain)
        + k1_business,
        2,
    )

    agi = max(0.0, total_income - student_loan_interest)
    std_deduction = float(fed_tables.get("standard_deduction", {}).get(status, 0))
    taxable_income = max(0.0, agi - std_deduction)

    # Ordinary taxable income excludes qualified divs + LTCG
    preferential = qualified_dividends + max(0.0, long_gain)
    ordinary_taxable = max(0.0, taxable_income - preferential)

    brackets = fed_tables.get("brackets_by_status", {}).get(status, [])
    ordinary_tax = compute_progressive_tax(ordinary_taxable, brackets)
    preferential_tax = _qualified_dividend_tax(qualified_dividends, long_gain, ordinary_taxable, status, fed_tables)
    federal_tax_before_credits = ordinary_tax + preferential_tax

    ctc = _compute_ctc(num_deps, agi, status, fed_tables)
    federal_tax = max(0.0, federal_tax_before_credits - ctc)

    se_tax = _compute_fica(wages, self_employment_income, status, fed_tables)

    # State tax
    state_tax = 0.0
    state_breakdown = {}
    if state_tables:
        st_status = "married_filing_jointly" if status == "married_filing_jointly" else "single"
        st_brackets = state_tables.get("brackets_by_status", {}).get(st_status, [])
        st_std = float(state_tables.get("standard_deduction", {}).get(st_status, 0))
        st_taxable = max(0.0, agi - st_std)
        state_tax = compute_progressive_tax(st_taxable, st_brackets)
        state_breakdown = {
            "state_taxable_income": st_taxable,
            "state_standard_deduction": st_std,
            "state_tax": state_tax,
        }

    total_tax = round(federal_tax + state_tax + se_tax, 2)
    balance = round(total_tax - fed_withheld, 2)
    refund = round(max(0.0, -balance), 2)
    owing = round(max(0.0, balance), 2)

    notes.extend([
        "Simplified prototype: AMT, NIIT, QBI, EITC, and state-specific credits not modelled.",
        "Social Security inclusion uses a flat 85% approximation; real rule is income-tested.",
    ])
    if short_gain < 0 or long_gain < 0:
        notes.append("Capital losses present; cap on $3000 ordinary offset not modelled in v1.")

    line_items = {
        "wages": wages,
        "interest_income": interest_income,
        "ordinary_dividends": ordinary_dividends,
        "qualified_dividends": qualified_dividends,
        "short_term_capital_gain": short_gain,
        "long_term_capital_gain": long_gain,
        "self_employment_income": self_employment_income,
        "rental_income": misc_rents,
        "royalty_income": misc_royalties,
        "other_misc_income": misc_other,
        "taxable_pension": pension_taxable,
        "taxable_social_security": taxable_ssa,
        "student_loan_interest_deduction": student_loan_interest,
        "standard_deduction": std_deduction,
        "agi": agi,
        "ordinary_tax": ordinary_tax,
        "preferential_tax": preferential_tax,
        "child_tax_credit": ctc,
        "federal_tax": federal_tax,
        "self_employment_tax": se_tax,
        "tax_withheld": fed_withheld,
        **state_breakdown,
    }

    totals = {
        "total_income": total_income,
        "agi": agi,
        "taxable_income": taxable_income,
        "total_tax": total_tax,
        "balance_owing": owing,
        "refund": refund,
    }

    credits = {
        "child_tax_credit": ctc,
        "standard_deduction": std_deduction,
    }

    return DraftReturn(
        jurisdiction="US",
        tax_year=year,
        total_income=total_income,
        rrsp_deduction=0.0,
        taxable_income=taxable_income,
        estimated_tax=total_tax,
        estimated_refund=refund,
        line_items=line_items,
        totals=totals,
        credits=credits,
        notes=notes,
    )
