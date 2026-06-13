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


def _to_float(value, default: float = 0.0) -> float:
    """Parse a user-typed answer (string / int / float) into a float."""
    if value is None:
        return default
    try:
        return float(str(value).replace(",", "").strip() or default)
    except (TypeError, ValueError):
        return default


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


def _compute_amt(taxable_income: float, deduction_used: float, status: str, fed_tables: Dict[str, Any]) -> float:
    """Highly simplified AMT estimator (real Form 6251 has dozens of adjustments).

    Approach: AMTI = taxable_income + deduction_used (add back standard /
    itemized) - AMT exemption. Apply 26% / 28% bracket. The result is the
    tentative minimum tax; engine compares against regular tax.
    """
    # 2024 AMT exemption + phaseout thresholds
    exemption = 85700.0 if status != "married_filing_jointly" else 133300.0
    phaseout_start = 609350.0 if status != "married_filing_jointly" else 1218700.0
    amti = max(0.0, taxable_income + deduction_used)
    if amti > phaseout_start:
        exemption = max(0.0, exemption - 0.25 * (amti - phaseout_start))
    amt_base = max(0.0, amti - exemption)
    # 26% on first $232,600 (2024), 28% above
    threshold = 232600.0
    if amt_base <= threshold:
        return round(amt_base * 0.26, 2)
    return round(threshold * 0.26 + (amt_base - threshold) * 0.28, 2)


def _compute_ptc(annual_premiums: float, slcsp: float, aptc: float, agi: float, dependents: int, status: str) -> tuple[float, float]:
    """Simplified Premium Tax Credit calculation (Form 8962).

    Returns (refundable_credit, repayment_owed). Real PTC depends on FPL %,
    which we approximate using a single-number threshold.
    """
    if annual_premiums <= 0 or slcsp <= 0:
        return 0.0, 0.0
    # Affordable Care Act expected contribution: very simplified
    household_size = max(1, dependents + (2 if status == "married_filing_jointly" else 1))
    fpl_base = 14580 + 5140 * (household_size - 1)  # 2024 FPL
    fpl_pct = agi / fpl_base if fpl_base > 0 else 0
    if fpl_pct < 1.5:
        applicable_pct = 0.0
    elif fpl_pct < 2.0:
        applicable_pct = 0.02
    elif fpl_pct < 2.5:
        applicable_pct = 0.04
    elif fpl_pct < 3.0:
        applicable_pct = 0.06
    elif fpl_pct < 4.0:
        applicable_pct = 0.085
    else:
        applicable_pct = 0.085
    expected_contribution = agi * applicable_pct
    ptc = max(0.0, min(annual_premiums, slcsp) - expected_contribution)
    if aptc > ptc:
        return 0.0, round(aptc - ptc, 2)
    return round(ptc - aptc, 2), 0.0


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


def _taxable_social_security(ssa_net: float, other_income: float, status: str) -> float:
    """Taxable portion of Social Security benefits (IRS Pub 915 worksheet).

    ``other_income`` is modified AGI excluding Social Security (tax-exempt
    interest would also be added if tracked). Provisional income = that plus
    one-half of benefits. Result is 0%, up to 50%, or up to 85% of benefits.

    Thresholds are fixed in statute (not inflation-indexed):
      - single / HoH / MFS-apart : base1 25,000, base2 34,000
      - married filing jointly   : base1 32,000, base2 44,000
    """
    if ssa_net <= 0:
        return 0.0
    if status == "married_filing_jointly":
        base1, base2 = 32000.0, 44000.0
    else:
        base1, base2 = 25000.0, 34000.0

    provisional = other_income + 0.5 * ssa_net
    if provisional <= base1:
        return 0.0
    if provisional <= base2:
        # 50% tier only
        return round(min(0.5 * ssa_net, 0.5 * (provisional - base1)), 2)
    # Above base2: 85% tier stacked on the (capped) 50% tier.
    tier_50 = min(0.5 * ssa_net, 0.5 * (base2 - base1))
    taxable = 0.85 * (provisional - base2) + tier_50
    return round(min(taxable, 0.85 * ssa_net), 2)


def compute_us_return(
    extracts: List[FormExtract],
    year: int,
    state: Optional[str] = None,
    user_answers: Dict[str, str] | None = None,
    residency_status: str = "resident",
) -> DraftReturn:
    user_answers = user_answers or {}
    status = _resolve_filing_status(user_answers)
    num_deps = _num_dependents(user_answers)
    notes: List[str] = []
    if residency_status == "nonresident":
        notes.append(
            "US nonresident: file Form 1040-NR. Only US-source income is taxable; no standard deduction "
            "(except India tax-treaty Article 21 exception)."
        )
    elif residency_status == "dual_status":
        notes.append(
            "US dual-status year: file Form 1040 with a 1040-NR statement for the nonresident period."
        )

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
    fed_withheld = (
        _sum_field(extracts, "W-2", "federal_income_tax_withheld")
        + _sum_field(extracts, "1099-INT", "federal_income_tax_withheld")
        + _sum_field(extracts, "1099-DIV", "federal_income_tax_withheld")
        + _sum_field(extracts, "1099-MISC", "federal_income_tax_withheld")
        + _sum_field(extracts, "1099-R", "federal_income_tax_withheld")
        + _sum_field(extracts, "1099-NEC", "federal_income_tax_withheld")
        + _sum_field(extracts, "1099-K", "federal_income_tax_withheld")
        + _sum_field(extracts, "1099-G", "federal_income_tax_withheld")
        + _sum_field(extracts, "SSA-1099", "federal_income_tax_withheld")
    )
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

    # New form income sources
    k_payments = _sum_field(extracts, "1099-K", "gross_payments")
    unemployment = _sum_field(extracts, "1099-G", "unemployment_compensation")
    state_tax_refund = _sum_field(extracts, "1099-G", "state_local_tax_refund")
    taxable_grants = _sum_field(extracts, "1099-G", "taxable_grants")
    sch_e_supplemental = _sum_field(extracts, "SCH-E", "net_supplemental_income")
    gambling_winnings = _sum_field(extracts, "W-2G", "gambling_winnings")
    fed_withheld += _sum_field(extracts, "W-2G", "federal_income_tax_withheld")

    # 8949 capital asset detail flows into Sch D; if Sch D values are missing
    # we treat 8949 net gain/loss as long-term (most common case).
    sch_8949_gain = _sum_field(extracts, "8949", "gain_loss")

    short_gain, long_gain = _sch_d_short_long(extracts)
    if sch_8949_gain != 0.0 and short_gain == 0.0 and long_gain == 0.0:
        long_gain += sch_8949_gain

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

    # 1099-K gross payments are reported by payment networks; treat as
    # self-employment income unless explicitly assigned elsewhere by the user.
    self_employment_income = nec + sch_c_profit + k1_business + k_payments

    # 1098-E student loan interest deduction (capped at $2500)
    student_loan_interest = min(2500.0, _sum_field(extracts, "1098-E", "student_loan_interest"))

    # HSA deduction: prefer Form 8889 line, fall back to user answer
    hsa_deduction = _sum_field(extracts, "8889", "hsa_deduction")
    if hsa_deduction == 0.0:
        hsa_deduction = _to_float(user_answers.get("hsa_contributions", 0))

    # Traditional IRA contributions: prefer 5498 box 1, fall back to user answer
    ira_deduction = _sum_field(extracts, "5498", "ira_contributions")
    if ira_deduction == 0.0:
        ira_deduction = _to_float(user_answers.get("ira_401k_contributions", 0))

    # Form 2555 reports foreign-earned wages and the amount the taxpayer is
    # excluding. We add the foreign-earned amount to income then subtract the
    # exclusion so non-foreign income (W-2 etc.) is left untouched.
    feie_total = _sum_field(extracts, "2555", "foreign_earned_income")
    feie_excluded = _sum_field(extracts, "2555", "foreign_earned_income_excluded")

    # Prior-year capital-loss carryover (max $3k applied to ordinary income)
    prior_capital_losses = _to_float(user_answers.get("prior_capital_losses", 0))
    if prior_capital_losses > 0:
        if long_gain > 0:
            applied = min(prior_capital_losses, long_gain)
            long_gain -= applied
            prior_capital_losses -= applied
        if prior_capital_losses > 0 and short_gain > 0:
            applied = min(prior_capital_losses, short_gain)
            short_gain -= applied
            prior_capital_losses -= applied
        # Remaining loss reduces ordinary income up to $3,000.
        ordinary_offset = min(prior_capital_losses, 3000.0)
    else:
        ordinary_offset = 0.0

    # All income other than Social Security. The taxable portion of SS depends
    # on this (via provisional income), so it is summed first.
    other_income = round(
        wages
        + interest_income
        + ordinary_dividends
        + nec
        + sch_c_profit
        + misc_rents
        + misc_royalties
        + misc_other
        + sch_e_supplemental
        + pension_taxable
        + max(0.0, short_gain)
        + max(0.0, long_gain)
        + k1_business
        + k_payments
        + unemployment
        + state_tax_refund
        + taxable_grants
        + gambling_winnings
        + feie_total
        - ordinary_offset
        - feie_excluded,
        2,
    )

    above_line = student_loan_interest + hsa_deduction + ira_deduction

    # Social Security taxability — IRS provisional-income worksheet (Pub 915),
    # replacing the prior flat-85% inclusion which over-taxed low/middle-income
    # retirees (an SS-only retiree owes $0, not 85%). Provisional income is
    # modified AGI excluding SS plus one-half of benefits (tax-exempt interest,
    # which would also be added, is not tracked by this prototype).
    provisional_base = max(0.0, other_income - above_line)
    taxable_ssa = _taxable_social_security(ssa_net, provisional_base, status)

    total_income = round(other_income + taxable_ssa, 2)
    agi = max(0.0, total_income - above_line)
    std_deduction = float(fed_tables.get("standard_deduction", {}).get(status, 0))

    # Schedule A itemized deduction comparison. SALT bucket combines state +
    # local income/sales tax (SCH-A.state_local_taxes) with user-supplied
    # property tax (state_local_property_tax), capped together at $10,000.
    raw_property_tax_us = _to_float(user_answers.get("state_local_property_tax", 0))
    sch_a_state_local = _sum_field(extracts, "SCH-A", "state_local_taxes")
    salt_uncapped = sch_a_state_local + max(0.0, raw_property_tax_us)
    salt_deduction = min(10000.0, salt_uncapped)
    if salt_uncapped > 10000.0:
        notes.append(
            f"SALT cap applied: state/local + property tax ${salt_uncapped:,.0f} "
            f"capped at $10,000 (Schedule A)."
        )

    sch_a_total = (
        _sum_field(extracts, "SCH-A", "medical_expenses")
        + salt_deduction
        + _sum_field(extracts, "SCH-A", "mortgage_interest")
        + _sum_field(extracts, "SCH-A", "charitable_gifts")
    )
    used_itemized = sch_a_total > std_deduction
    effective_deduction = sch_a_total if used_itemized else std_deduction
    if used_itemized:
        notes.append(f"Itemized deduction (${sch_a_total:,.0f}) beats standard (${std_deduction:,.0f}).")
    taxable_income = max(0.0, agi - effective_deduction)

    # QBI deduction (Section 199A) — 20% of qualified business income from
    # Sch C / 1099-NEC / K-1, capped at 20% of taxable income (simplified).
    qbi_eligible = max(0.0, sch_c_profit + nec + k1_business)
    qbi_deduction = round(min(qbi_eligible, taxable_income) * 0.20, 2) if qbi_eligible > 0 else 0.0
    taxable_income = max(0.0, taxable_income - qbi_deduction)

    # Ordinary taxable income excludes qualified divs + LTCG
    preferential = qualified_dividends + max(0.0, long_gain)
    ordinary_taxable = max(0.0, taxable_income - preferential)

    brackets = fed_tables.get("brackets_by_status", {}).get(status, [])
    ordinary_tax = compute_progressive_tax(ordinary_taxable, brackets)
    preferential_tax = _qualified_dividend_tax(qualified_dividends, long_gain, ordinary_taxable, status, fed_tables)
    federal_tax_before_credits = ordinary_tax + preferential_tax

    ctc = _compute_ctc(num_deps, agi, status, fed_tables)

    # Premium Tax Credit reconciliation (1095-A)
    aptc = _sum_field(extracts, "1095-A", "advance_ptc")
    annual_premiums = _sum_field(extracts, "1095-A", "annual_premiums")
    slcsp = _sum_field(extracts, "1095-A", "annual_slcsp")
    ptc_credit, ptc_repayment = _compute_ptc(annual_premiums, slcsp, aptc, agi, num_deps, status)

    federal_tax = max(0.0, federal_tax_before_credits - ctc - ptc_credit) + ptc_repayment

    # Alternative Minimum Tax (simplified Form 6251)
    amt_tax = _compute_amt(taxable_income, effective_deduction, status, fed_tables)
    if amt_tax > federal_tax:
        notes.append(f"AMT applies: ${amt_tax:,.0f} > regular tax ${federal_tax:,.0f}. Form 6251 required.")
        federal_tax = amt_tax

    # Net Investment Income Tax (3.8%) for high earners (§1411).
    # Net investment income includes rents and royalties by default; only
    # income from a trade/business in which the taxpayer materially participates
    # (non-passive) is excluded — that active income (Schedule C, K-1 business)
    # is tracked separately above and correctly left out here.
    niit_threshold = 250000 if status == "married_filing_jointly" else 200000
    investment_income = (
        interest_income + ordinary_dividends
        + max(0.0, long_gain) + max(0.0, short_gain)
        + misc_royalties + misc_rents + sch_e_supplemental
    )
    niit = round(min(investment_income, max(0.0, agi - niit_threshold)) * 0.038, 2)
    federal_tax += niit

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
        "Simplified prototype: EITC, state-specific credits, and several adjustments not modelled.",
        "Social Security taxability uses the IRS provisional-income worksheet (0/50/85%); "
        "tax-exempt interest is not added to provisional income in this prototype.",
    ])
    if niit > 0:
        notes.append(f"NIIT applied: 3.8% on investment income above ${niit_threshold:,.0f} = ${niit:,.0f}.")
    if qbi_deduction > 0:
        notes.append(f"QBI (Section 199A) deduction of ${qbi_deduction:,.0f} (20% of pass-through income).")
    if ptc_repayment > 0:
        notes.append(f"Advance Premium Tax Credit exceeded eligible PTC; ${ptc_repayment:,.0f} repayment added.")
    if feie_excluded > 0:
        notes.append(f"Foreign Earned Income Exclusion (Form 2555) excluded ${feie_excluded:,.0f} from income.")

    line_items = {
        "wages": wages,
        "interest_income": interest_income,
        "ordinary_dividends": ordinary_dividends,
        "qualified_dividends": qualified_dividends,
        "short_term_capital_gain": short_gain,
        "long_term_capital_gain": long_gain,
        "capital_loss_ordinary_offset": ordinary_offset,
        "self_employment_income": self_employment_income,
        "1099_k_payments": k_payments,
        "rental_income": misc_rents,
        "royalty_income": misc_royalties,
        "other_misc_income": misc_other,
        "supplemental_income_sch_e": sch_e_supplemental,
        "taxable_pension": pension_taxable,
        "taxable_social_security": taxable_ssa,
        "unemployment_compensation": unemployment,
        "state_tax_refund_taxable": state_tax_refund,
        "taxable_grants": taxable_grants,
        "gambling_winnings": gambling_winnings,
        "feie_excluded": feie_excluded,
        "student_loan_interest_deduction": student_loan_interest,
        "hsa_deduction": hsa_deduction,
        "ira_401k_adjustment": ira_deduction,
        "standard_deduction": std_deduction,
        "itemized_deduction_sch_a": sch_a_total,
        "state_local_property_tax": raw_property_tax_us,
        "salt_deduction_capped": salt_deduction,
        "effective_deduction": effective_deduction,
        "qbi_deduction": qbi_deduction,
        "agi": agi,
        "ordinary_tax": ordinary_tax,
        "preferential_tax": preferential_tax,
        "amt_tax": amt_tax,
        "niit": niit,
        "child_tax_credit": ctc,
        "premium_tax_credit": ptc_credit,
        "premium_tax_credit_repayment": ptc_repayment,
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
        "premium_tax_credit": ptc_credit,
        "qbi_deduction": qbi_deduction,
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
