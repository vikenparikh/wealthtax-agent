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

import math
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
    # A qualifying surviving spouse (qualifying widow(er)) uses the MFJ rate
    # schedule and standard deduction (IRC §2(a)) — it is a computational clone of
    # MFJ, so alias it rather than falling through to single (which over-taxed it).
    # Every MFJ-specific table/branch keys on "married_filing_jointly", so the alias
    # inherits them all. (The EITC for a QSS technically uses the unmarried phase-out
    # start; using MFJ's is a minor, taxpayer-favorable approximation in a narrow band.)
    if raw in {"qss", "qualifying_surviving_spouse", "qualifying_widow(er)",
               "qualifying_widower", "qualifying_widow", "surviving_spouse"}:
        raw = "married_filing_jointly"
    if raw not in VALID_FILING_STATUSES:
        raw = "single"
    return raw


def _num_dependents(user_answers: Dict[str, str]) -> int:
    try:
        return max(0, int(user_answers.get("num_dependents", "0")))
    except (TypeError, ValueError):
        return 0


def _num_other_dependents(user_answers: Dict[str, str]) -> int:
    """Dependents who are NOT CTC qualifying children (17+, parents, relatives) —
    they get the $500 Credit for Other Dependents, not the $2,000 CTC. Defaults to
    0 so, with no input, all dependents are treated as qualifying children."""
    try:
        return max(0, int(user_answers.get("num_other_dependents", "0")))
    except (TypeError, ValueError):
        return 0


def _num_eitc_qualifying_children(user_answers: Dict[str, str], num_deps: int) -> int:
    """EITC qualifying children — under 19 (or under 24 if a full-time student, or
    any age if disabled), and NOT a parent/grandparent. This is a different test
    than the CTC's under-17, so it is an independent input from num_other_dependents
    (a 17-18yo is an EITC child but a CTC 'other dependent'). Defaults to num_deps
    so, with no input, every dependent is treated as an EITC qualifying child (the
    prior behaviour) → no regression; capped at the total dependent count."""
    raw = user_answers.get("num_eitc_qualifying_children")
    if raw is None or str(raw).strip() == "":
        return num_deps
    try:
        return max(0, min(int(raw), num_deps))
    except (TypeError, ValueError):
        return num_deps


def _compute_eitc(earned: float, agi: float, num_children: int, status: str, taxpayer_age: float,
                  investment_income: float, feie_claimed: bool, fed_tables: Dict[str, Any]) -> float:
    """Earned Income Tax Credit (refundable, Form 1040 line 27), federal v1.

    Phase-in/plateau/phase-out by number of qualifying children (0/1/2/3+), with
    the phase-out driven by the larger of earned income and AGI (§32(a)(2)). Hard
    disqualifiers: investment income over the year limit, a Form 2555 FEIE claim,
    and (conservatively) married-filing-separately. The childless (0-child) credit
    requires age 25-64. ``num_children`` is approximated by the dependent count, so
    this can over-credit dependents who are not EITC-qualifying children — flagged
    by the caller's note; a dedicated qualifying-children input is a follow-up.
    """
    eitc_tbl = fed_tables.get("eitc", {})
    if not eitc_tbl or feie_claimed or status == "married_filing_separately":
        return 0.0
    inv_limit = float(eitc_tbl.get("investment_income_limit", 0))
    if inv_limit and investment_income > inv_limit:
        return 0.0
    bucket = str(min(max(0, num_children), 3))
    b = eitc_tbl.get("brackets", {}).get(bucket)
    if not b:
        return 0.0
    if num_children == 0 and not (25 <= taxpayer_age <= 64):
        # Childless EITC is age-gated; without a confirmable age, credit nothing.
        return 0.0
    rate = float(b["credit_rate"])
    max_credit = float(b["max_credit"])
    start = float(b["phaseout_start_mfj"] if status == "married_filing_jointly" else b["phaseout_start"])
    credit = min(earned * rate, max_credit)
    reduction = max(0.0, max(earned, agi) - start) * float(b["phaseout_rate"])
    return round(max(0.0, credit - reduction), 2)


def _truthy(val: Any) -> bool:
    return str(val).strip().lower() in {"1", "true", "yes", "y", "t"}


def _additional_std_boxes(user_answers: Dict[str, str], status: str) -> int:
    """Count Form 1040 age-65/blind boxes: taxpayer 65+, taxpayer blind, and —
    for MFJ only — spouse 65+ and spouse blind. Each box adds one unit of the
    year/status additional standard deduction."""
    boxes = 0
    if _truthy(user_answers.get("taxpayer_age_65_or_older", False)):
        boxes += 1
    if _truthy(user_answers.get("taxpayer_blind", False)):
        boxes += 1
    if status == "married_filing_jointly":
        if _truthy(user_answers.get("spouse_age_65_or_older", False)):
            boxes += 1
        if _truthy(user_answers.get("spouse_blind", False)):
            boxes += 1
    return boxes


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


def _compute_ctc(num_children: int, num_other_deps: int, agi: float, status: str,
                 fed_tables: Dict[str, Any]) -> tuple[float, float]:
    """Return (CTC for qualifying children, ODC for other dependents) after the
    shared §24(h) phase-out. Only children under 17 get the $2,000 CTC; other
    dependents get the $500 Credit for Other Dependents (non-refundable)."""
    ctc = fed_tables.get("ctc", {})
    per_child = float(ctc.get("per_child", 2000))
    odc_per = float(ctc.get("odc_per_dependent", 500))
    phaseout_start = float(
        ctc.get("phaseout_start_mfj", 400000) if status == "married_filing_jointly"
        else ctc.get("phaseout_start_single", 200000)
    )
    base_ctc = num_children * per_child
    base_odc = num_other_deps * odc_per
    if agi <= phaseout_start:
        return base_ctc, base_odc
    # §24(b)(2): one combined phase-out — reduce by $50 per $1,000 (or fraction
    # thereof) of AGI over the threshold. Apply the reduction to the (lower-value,
    # non-refundable) ODC first, preserving the more valuable refundable CTC last
    # (Schedule 8812-consistent / taxpayer-favorable; the exact statutory ordering
    # only shifts the CTC/ODC split inside the phase-out band).
    excess = math.ceil((agi - phaseout_start) / 1000.0) * 50
    odc = max(0.0, base_odc - float(excess))
    remaining = max(0.0, float(excess) - base_odc)
    ctc_children = max(0.0, base_ctc - remaining)
    return ctc_children, odc


def _compute_amt(taxable_income: float, deduction_used: float, status: str, fed_tables: Dict[str, Any]) -> float:
    """Highly simplified AMT estimator (real Form 6251 has dozens of adjustments).

    Approach: AMTI = taxable_income + deduction_used (add back standard /
    itemized) - AMT exemption. Apply 26% / 28% bracket. The result is the
    tentative minimum tax; engine compares against regular tax.
    """
    # AMT exemption, phaseout, and rate breakpoint are indexed annually, so they
    # come from the year table. The hardcoded fallbacks are the 2024 values, used
    # only if the table omits the block (no regression for already-loaded years).
    amt_tbl = fed_tables.get("amt", {})
    _default_non_mfj = status != "married_filing_jointly"
    exemption_tbl = amt_tbl.get("exemption", {})
    exemption = float(exemption_tbl.get(status, 85700.0 if _default_non_mfj else 133300.0))
    phaseout_tbl = amt_tbl.get("phaseout_start", {})
    phaseout_start = float(phaseout_tbl.get(status, 609350.0 if _default_non_mfj else 1218700.0))
    amti = max(0.0, taxable_income + deduction_used)
    if amti > phaseout_start:
        exemption = max(0.0, exemption - 0.25 * (amti - phaseout_start))
    amt_base = max(0.0, amti - exemption)
    # 26% on the first <breakpoint> of AMT base, 28% above.
    threshold = float(amt_tbl.get("rate_breakpoint", 232600.0))
    if amt_base <= threshold:
        return round(amt_base * 0.26, 2)
    return round(threshold * 0.26 + (amt_base - threshold) * 0.28, 2)


def _ptc_applicable_figure(fpl_pct: float, anchors: list, cap: float) -> float:
    """Linearly interpolate the Form 8962 applicable figure between (fpl_ratio,
    applicable_pct) anchors. Below the first anchor → 0; at/above the last → cap."""
    pts = sorted((float(r), float(p)) for r, p in anchors)
    if fpl_pct < pts[0][0]:
        return 0.0
    if fpl_pct >= pts[-1][0]:
        return float(cap)
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= fpl_pct < x1:
            return y0 + (fpl_pct - x0) / (x1 - x0) * (y1 - y0)
    return float(cap)


def _compute_ptc(annual_premiums: float, slcsp: float, aptc: float, agi: float, dependents: int,
                 status: str, fed_tables: Dict[str, Any]) -> tuple[float, float]:
    """Simplified Premium Tax Credit calculation (Form 8962).

    Returns (refundable_credit, repayment_owed). Real PTC depends on FPL %,
    which we approximate using a single-number threshold.

    The federal poverty line is indexed annually and a coverage year uses the
    prior calendar year's HHS guidelines, so the base/increment come from the
    year table; the hardcoded fallbacks are the figures for the 2024 tax year.
    (The applicable-percentage step table below is still approximate, not
    year-accurate — only the FPL base is made year-specific here.)
    """
    if annual_premiums <= 0 or slcsp <= 0:
        return 0.0, 0.0
    # Affordable Care Act expected contribution: very simplified
    household_size = max(1, dependents + (2 if status == "married_filing_jointly" else 1))
    fpl_tbl = fed_tables.get("fpl", {})
    fpl_base = float(fpl_tbl.get("one_person", 14580)) + float(fpl_tbl.get("additional_person", 5140)) * (household_size - 1)
    fpl_pct = agi / fpl_base if fpl_base > 0 else 0
    # Form 8962 applicable figure: a piecewise-LINEAR ramp between Table 2 anchors,
    # not a step function. The old 5-bucket step used each bucket's upper value
    # (e.g. a flat 8.5% from 300-400%), materially over-charging mid-range filers.
    # Anchors/cap come from the year table; the fallback is the ARPA/IRA enhanced
    # schedule (2021-2025). Post-2025 the cliff returns — a future year's table
    # would re-introduce a 400% cutoff, so this stays table-driven.
    ptc_tbl = fed_tables.get("ptc", {})
    anchors = ptc_tbl.get("applicable_figure") or [
        [1.5, 0.0], [2.0, 0.02], [2.5, 0.04], [3.0, 0.06], [4.0, 0.085],
    ]
    cap = float(ptc_tbl.get("cap_applicable_pct", 0.085))
    applicable_pct = _ptc_applicable_figure(fpl_pct, anchors, cap)
    expected_contribution = agi * applicable_pct
    ptc = max(0.0, min(annual_premiums, slcsp) - expected_contribution)
    if aptc > ptc:
        return 0.0, round(aptc - ptc, 2)
    return round(ptc - aptc, 2), 0.0


def _compute_fica(w2_wages: float, se_net: float, status: str, fed_tables: Dict[str, Any]) -> tuple[float, float]:
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

    total_se_tax = round(se_ss_tax + se_medicare_tax + additional_medicare, 2)
    # One-half of SE tax is an above-the-line deduction (§164(f)). Only the SS +
    # Medicare components count — the 0.9% additional Medicare is not SE tax and
    # is not deductible.
    half_deduction = round(0.5 * (se_ss_tax + se_medicare_tax), 2)
    return total_se_tax, half_deduction


def _net_capital_gains(net_short: float, net_long: float, prior_carryover: float,
                       status: str) -> tuple[float, float, float, float]:
    """Schedule D netting (§1222) + current-year capital-loss limitation (§1211).

    ``net_short`` / ``net_long`` may be negative (current-year losses);
    ``prior_carryover`` is a positive prior-year loss amount. Returns
    ``(short_for_ordinary, long_for_preferential, ordinary_loss_deduction,
    loss_carryover_to_next_year)``, all >= 0.

    - Short- and long-term are netted against each other; a loss in one
      character offsets a gain in the other.
    - A net capital loss reduces ordinary income up to $3,000, with the excess
      carried to next year. (The $1,500 married-filing-separately limit is not
      modelled — this engine does not support that status.)
    """
    prior = max(0.0, prior_carryover)
    combined = net_short + net_long - prior

    if combined > 0:
        s, l, p = net_short, net_long, prior
        # Prior-year loss reduces gains, long first then short (mirrors the
        # engine's prior behaviour).
        if l > 0:
            a = min(p, l); l -= a; p -= a
        if p > 0 and s > 0:
            a = min(p, s); s -= a; p -= a
        # §1222: net the two characters against each other.
        if s < 0:
            l += s; s = 0.0
        if l < 0:
            s += l; l = 0.0
        return round(max(0.0, s), 2), round(max(0.0, l), 2), 0.0, 0.0

    # Net capital loss → §1211 ordinary deduction (capped), remainder carries over.
    loss = -combined
    deduction = min(loss, 3000.0)
    return 0.0, 0.0, round(deduction, 2), round(loss - deduction, 2)


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
    # W-2 box 8 (allocated tips) is NOT included in box 1; the IRS requires it
    # reported as income (Form 1040 line 1c) unless the employee has records of
    # lesser tips. Box 7 (Social Security tips) is already inside box 1, so only
    # box 8 is added here. (The §3121(q)/Form 4137 SS+Medicare tax on these tips
    # is a separate computation the engine does not model — noted below.)
    allocated_tips = _sum_field(extracts, "W-2", "allocated_tips")
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
    # 1099-DIV box 2a: total capital gain distributions from mutual funds / ETFs
    # are long-term capital gains and were previously dropped (captured by the
    # extractor but never read), under-reporting income for fund holders.
    long_gain += _sum_field(extracts, "1099-DIV", "capital_gain_distributions")

    # 1099-K gross payments are reported by payment networks; treat as
    # self-employment income unless explicitly assigned elsewhere by the user.
    self_employment_income = nec + sch_c_profit + k1_business + k_payments

    # 1098-E student loan interest deduction (capped at $2500)
    student_loan_interest = min(2500.0, _sum_field(extracts, "1098-E", "student_loan_interest"))

    taxpayer_age = _to_float(user_answers.get("taxpayer_age", 0))

    # HSA deduction: prefer Form 8889 line, fall back to user answer, then cap at the
    # year's contribution limit (self vs family coverage, +$1,000 catch-up at 55+).
    hsa_deduction = _sum_field(extracts, "8889", "hsa_deduction")
    if hsa_deduction == 0.0:
        hsa_deduction = _to_float(user_answers.get("hsa_contributions", 0))
    _hsa_tbl = fed_tables.get("hsa", {})
    if _hsa_tbl:
        _hsa_coverage = str(user_answers.get("hsa_coverage", "family")).strip().lower()
        _hsa_base = float(_hsa_tbl.get("self_limit", 4150)) if _hsa_coverage == "self" else float(_hsa_tbl.get("family_limit", 8300))
        _hsa_cap = _hsa_base + (float(_hsa_tbl.get("catchup_55_plus", 1000)) if taxpayer_age >= 55 else 0.0)
        if hsa_deduction > _hsa_cap:
            notes.append(f"HSA deduction capped at ${_hsa_cap:,.0f} ({_hsa_coverage} coverage limit); "
                         f"${hsa_deduction - _hsa_cap:,.0f} over the limit is not deductible.")
            hsa_deduction = _hsa_cap

    # Traditional IRA contributions: prefer 5498 box 1, fall back to user answer, then
    # cap at the contribution limit (+$1,000 catch-up at 50+). The MAGI deduction
    # phase-out for employer-plan participants is not modeled (and this key conflates
    # IRA with 401(k), whose elective deferrals are already pre-tax — left as-is).
    ira_deduction = _sum_field(extracts, "5498", "ira_contributions")
    if ira_deduction == 0.0:
        ira_deduction = _to_float(user_answers.get("ira_401k_contributions", 0))
    _ira_tbl = fed_tables.get("ira", {})
    if _ira_tbl:
        _ira_cap = float(_ira_tbl.get("contribution_limit", 7000)) + (
            float(_ira_tbl.get("catchup_50_plus", 1000)) if taxpayer_age >= 50 else 0.0)
        if ira_deduction > _ira_cap:
            notes.append(f"IRA deduction capped at ${_ira_cap:,.0f} (contribution limit); "
                         f"${ira_deduction - _ira_cap:,.0f} over the limit is not deductible. "
                         f"MAGI phase-out for employer-plan participants is not modeled.")
            ira_deduction = _ira_cap

    # Form 2555 reports foreign-earned wages and the amount the taxpayer is
    # excluding. We add the foreign-earned amount to income then subtract the
    # exclusion so non-foreign income (W-2 etc.) is left untouched.
    feie_total = _sum_field(extracts, "2555", "foreign_earned_income")
    feie_excluded = _sum_field(extracts, "2555", "foreign_earned_income_excluded")

    # Schedule D netting (§1222) of current-year short/long, the current-year
    # net-loss deduction limit (§1211, max $3,000 against ordinary income), and
    # any prior-year carryover the user supplied — handled together.
    prior_capital_losses = _to_float(user_answers.get("prior_capital_losses", 0))
    short_gain, long_gain, ordinary_offset, capital_loss_carryover = _net_capital_gains(
        short_gain, long_gain, prior_capital_losses, status
    )
    if capital_loss_carryover > 0:
        total_net_loss = ordinary_offset + capital_loss_carryover
        notes.append(
            f"Net capital loss of ${total_net_loss:,.0f} exceeds the $3,000 annual limit; "
            f"${ordinary_offset:,.0f} deducted this year, ${capital_loss_carryover:,.0f} carries forward."
        )

    # All income other than Social Security. The taxable portion of SS depends
    # on this (via provisional income), so it is summed first.
    other_income = round(
        wages
        + allocated_tips
        + interest_income
        + ordinary_dividends
        + nec
        + sch_c_profit
        + misc_rents
        + misc_royalties
        + misc_other
        + sch_e_supplemental
        + pension_taxable
        + short_gain
        + long_gain
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
    if allocated_tips > 0:
        notes.append(
            f"Allocated tips of ${allocated_tips:,.2f} (W-2 box 8) added to income; the "
            f"Social Security and Medicare tax owed on unreported tips (Form 4137) is not modeled."
        )

    # Self-employment tax and its one-half above-the-line deduction (§164(f)),
    # computed here so the deduction reduces AGI (and everything keyed off it).
    se_tax, se_tax_deduction = _compute_fica(wages, self_employment_income, status, fed_tables)

    # 1099-INT box 2: penalty on early withdrawal of savings is an above-the-line
    # deduction (Schedule 1, line 18). It was captured but never deducted.
    early_withdrawal_penalty = _sum_field(extracts, "1099-INT", "early_withdrawal_penalty")

    above_line = (
        student_loan_interest + hsa_deduction + ira_deduction + se_tax_deduction
        + early_withdrawal_penalty
    )

    # Social Security taxability — IRS provisional-income worksheet (Pub 915),
    # replacing the prior flat-85% inclusion which over-taxed low/middle-income
    # retirees (an SS-only retiree owes $0, not 85%). Provisional income is
    # modified AGI excluding SS, plus tax-exempt interest (1099-INT box 8, added
    # back under §86), plus one-half of benefits (added inside the worksheet).
    tax_exempt_interest = _sum_field(extracts, "1099-INT", "tax_exempt_interest")
    provisional_base = max(0.0, other_income - above_line) + tax_exempt_interest
    taxable_ssa = _taxable_social_security(ssa_net, provisional_base, status)

    total_income = round(other_income + taxable_ssa, 2)
    agi = max(0.0, total_income - above_line)
    std_deduction = float(fed_tables.get("standard_deduction", {}).get(status, 0))
    # Additional standard deduction for age 65+ / blindness (Form 1040). One unit
    # per checked box; the per-box amount is higher for unmarried filers. Applies
    # only to the standard deduction, so it is folded in before the itemized
    # comparison below (an itemizer who beats the boosted standard is unaffected).
    add_std_boxes = _additional_std_boxes(user_answers, status)
    add_std_per_box = float(fed_tables.get("additional_standard_deduction", {}).get(status, 0))
    additional_std = add_std_boxes * add_std_per_box
    if additional_std > 0:
        std_deduction += additional_std
        notes.append(
            f"Additional standard deduction of ${additional_std:,.0f} for age 65+/blindness "
            f"({add_std_boxes} box(es) x ${add_std_per_box:,.0f})."
        )

    # Schedule A itemized deduction comparison. SALT bucket combines state +
    # local income/sales tax (SCH-A.state_local_taxes) with user-supplied
    # property tax (state_local_property_tax), capped together at $10,000.
    raw_property_tax_us = _to_float(user_answers.get("state_local_property_tax", 0))
    sch_a_state_local = _sum_field(extracts, "SCH-A", "state_local_taxes")
    # State income tax for SALT: prefer the Schedule A total when the user
    # supplied it, otherwise fall back to W-2 box 17 withholding (the primary
    # source most filers have). Only the Sch A field was read before, so an
    # itemizer who uploaded a W-2 but no Sch A entry lost their state income tax
    # — usually the largest SALT component — from the deduction.
    state_income_tax_salt = sch_a_state_local if sch_a_state_local > 0 else _sum_field(extracts, "W-2", "state_income_tax")
    salt_uncapped = state_income_tax_salt + max(0.0, raw_property_tax_us)
    salt_deduction = min(10000.0, salt_uncapped)
    if salt_uncapped > 10000.0:
        notes.append(
            f"SALT cap applied: state/local + property tax ${salt_uncapped:,.0f} "
            f"capped at $10,000 (Schedule A)."
        )

    # §213: medical/dental expenses are deductible only to the extent they exceed
    # 7.5% of AGI (a permanent floor since 2021). The engine added them at face
    # value, over-deducting. The floor uses the post-above-line AGI (line 615).
    medical_raw = _sum_field(extracts, "SCH-A", "medical_expenses")
    _medical_floor_rate = float(fed_tables.get("schedule_a", {}).get("medical_agi_floor_rate", 0.075))
    medical_deductible = round(max(0.0, medical_raw - _medical_floor_rate * agi), 2)
    if medical_raw > 0:
        notes.append(
            f"Medical expenses ${medical_raw:,.0f} reduced by the {_medical_floor_rate:.1%}-of-AGI floor "
            f"(${_medical_floor_rate * agi:,.0f}) → ${medical_deductible:,.0f} deductible (§213)."
        )
    # Mortgage interest: prefer a Schedule A entry, otherwise fall back to Form
    # 1098 box 1 (the lender slip most homeowners actually have) — it was captured
    # but never read, so a filer who uploaded a 1098 without a Sch A entry lost the
    # entire (usually largest) itemized deduction. (The $750k acquisition-debt limit
    # is not modelled here, matching the existing Sch A treatment.)
    sch_a_mortgage = _sum_field(extracts, "SCH-A", "mortgage_interest")
    mortgage_interest = sch_a_mortgage if sch_a_mortgage > 0 else _sum_field(extracts, "1098", "mortgage_interest_received")
    sch_a_total = (
        medical_deductible
        + salt_deduction
        + mortgage_interest
        + _sum_field(extracts, "SCH-A", "charitable_gifts")
    )
    used_itemized = sch_a_total > std_deduction
    effective_deduction = sch_a_total if used_itemized else std_deduction
    if used_itemized:
        notes.append(f"Itemized deduction (${sch_a_total:,.0f}) beats standard (${std_deduction:,.0f}).")
    taxable_income = max(0.0, agi - effective_deduction)

    # QBI deduction (Section 199A) — 20% of qualified business income from
    # Sch C / 1099-NEC / K-1. The overall limitation caps it at 20% of
    # (taxable income before QBI MINUS net capital gain), where net capital gain
    # = net long-term capital gain + qualified dividends. Omitting that
    # subtraction overstates the deduction for taxpayers with preferential
    # income. (Wage/UBIA limits and the SSTB phase-out are not modelled.)
    qbi_eligible = max(0.0, sch_c_profit + nec + k1_business)
    net_capital_gain = max(0.0, long_gain) + qualified_dividends
    qbi_income_limit = max(0.0, taxable_income - net_capital_gain)
    qbi_deduction = round(min(qbi_eligible, qbi_income_limit) * 0.20, 2) if qbi_eligible > 0 else 0.0
    taxable_income = max(0.0, taxable_income - qbi_deduction)

    # Ordinary taxable income excludes qualified divs + LTCG
    preferential = qualified_dividends + max(0.0, long_gain)
    ordinary_taxable = max(0.0, taxable_income - preferential)

    brackets = fed_tables.get("brackets_by_status", {}).get(status, [])
    ordinary_tax = compute_progressive_tax(ordinary_taxable, brackets)
    preferential_tax = _qualified_dividend_tax(qualified_dividends, long_gain, ordinary_taxable, status, fed_tables)
    federal_tax_before_credits = ordinary_tax + preferential_tax

    # Split dependents: children under 17 get the CTC, the rest get the ODC.
    num_other_deps = _num_other_dependents(user_answers)
    num_qualifying_kids = max(0, num_deps - num_other_deps)
    ctc, odc = _compute_ctc(num_qualifying_kids, num_other_deps, agi, status, fed_tables)
    if odc > 0:
        notes.append(
            f"Credit for Other Dependents of ${odc:,.2f} ({num_other_deps} non-child "
            "dependent(s) at $500 each, non-refundable)."
        )

    # Premium Tax Credit reconciliation (1095-A)
    aptc = _sum_field(extracts, "1095-A", "advance_ptc")
    annual_premiums = _sum_field(extracts, "1095-A", "annual_premiums")
    slcsp = _sum_field(extracts, "1095-A", "annual_slcsp")
    ptc_credit, ptc_repayment = _compute_ptc(annual_premiums, slcsp, aptc, agi, num_deps, status, fed_tables)

    federal_tax = max(0.0, federal_tax_before_credits - ctc - odc - ptc_credit) + ptc_repayment

    # Additional Child Tax Credit (refundable portion of the CTC, Form 8812).
    # When a family's tax liability is too low to absorb the full non-refundable
    # CTC, the unused portion is refundable up to $1,700/child (2024) but no more
    # than 15% of earned income over $2,500. Without this, low-income families
    # with children wrongly receive $0 benefit from the CTC.
    _ctc_tbl = fed_tables.get("ctc", {})
    actc_per_child = float(_ctc_tbl.get("refundable_per_child", 1700))
    actc_floor = float(_ctc_tbl.get("earned_income_floor", 2500))
    actc_rate = float(_ctc_tbl.get("refundable_rate", 0.15))
    # Only the CTC (qualifying children) is refundable — the ODC never is. The ODC,
    # being non-refundable, absorbs tax first so more of the refundable CTC survives.
    ctc_absorbed = min(ctc, max(0.0, federal_tax_before_credits - ptc_credit - odc))
    unused_ctc = ctc - ctc_absorbed
    actc = 0.0
    if unused_ctc > 0 and num_qualifying_kids > 0:
        actc_earned = wages + max(0.0, self_employment_income)
        earned_limit = max(0.0, (actc_earned - actc_floor) * actc_rate)
        actc = round(min(unused_ctc, num_qualifying_kids * actc_per_child, earned_limit), 2)
    if actc > 0:
        notes.append(
            f"Additional Child Tax Credit of ${actc:,.2f} (refundable portion of the "
            "Child Tax Credit, Form 8812) credited as a payment."
        )

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
    # NIIT is keyed off MAGI, which adds the foreign earned income exclusion back
    # to AGI (§1411(d)(1)). Using AGI alone would let FEIE filers (Form 2555)
    # wrongly slip under the threshold even when their worldwide income is over
    # it — a real case for this cross-border tool.
    niit_magi = agi + feie_excluded
    niit = round(min(investment_income, max(0.0, niit_magi - niit_threshold)) * 0.038, 2)
    federal_tax += niit

    # se_tax + se_tax_deduction already computed above (the deduction feeds AGI).

    # State tax
    state_tax = 0.0
    state_breakdown = {}
    if state_tables:
        # Use the filer's own status for the state schedule, falling back to single
        # when a state table lacks that status' brackets/deduction. This lets a
        # state add a head_of_household schedule (e.g. CA's higher HoH standard
        # deduction) without forcing every state to define one — states without it
        # keep the single treatment, byte-for-byte (no regression).
        _bbs = state_tables.get("brackets_by_status", {})
        _std = state_tables.get("standard_deduction", {})
        st_status = status if status in {"single", "married_filing_jointly", "head_of_household"} else "single"
        st_brackets = _bbs.get(st_status) or _bbs.get("single", [])
        st_std = float(_std.get(st_status, _std.get("single", 0)))
        st_taxable = max(0.0, agi - st_std)
        state_tax = compute_progressive_tax(st_taxable, st_brackets)
        # CA Mental Health Services Tax (R&TC §17043): a flat 1% on taxable income
        # over $1M (same threshold for all statuses), separate from the brackets
        # (which stop at 12.3%). Table-driven and self-gating — only CA's state
        # table carries the key, so other states get 0.
        _mhs_cfg = state_tables.get("mental_health_surcharge", {})
        state_mhs = round(float(_mhs_cfg.get("rate", 0.0)) * max(0.0, st_taxable - float(_mhs_cfg.get("threshold", 0.0))), 2)
        state_tax = round(state_tax + state_mhs, 2)
        state_breakdown = {
            "state_taxable_income": st_taxable,
            "state_standard_deduction": st_std,
            "state_mental_health_surcharge": state_mhs,
            "state_tax": state_tax,
        }

    total_tax = round(federal_tax + state_tax + se_tax, 2)

    # Excess Social Security tax: a filer with 2+ employers whose combined SS
    # wages exceed the wage base over-withholds SS tax; the excess is a
    # refundable credit (treated as an additional payment). Single-employer
    # over-withholding is the employer's to correct, so this requires 2+ W-2s.
    _fica = fed_tables.get("fica", {})
    _max_ss_tax = float(_fica.get("social_security_rate", 0.062)) * float(_fica.get("social_security_wage_base", 168600))
    ss_tax_withheld = _sum_field(extracts, "W-2", "social_security_tax_withheld")
    w2_count = sum(1 for e in extracts if e.form_code == "W-2" and e.jurisdiction == "US")
    excess_ss_tax = round(max(0.0, ss_tax_withheld - _max_ss_tax), 2) if w2_count >= 2 else 0.0
    if excess_ss_tax > 0:
        notes.append(
            f"Excess Social Security tax of ${excess_ss_tax:,.2f} from multiple employers "
            "is credited as an additional payment (Schedule 3, line 11)."
        )

    # Additional Medicare tax withheld (Form 8959 Part IV): the employer withholds
    # the 0.9% surtax above $200,000 into W-2 box 6 (on top of the regular 1.45%).
    # The engine adds the 0.9% to the liability via _compute_fica, so the box-6
    # over-withholding must be credited as a payment or the filer is double-charged.
    _medicare_rate = float(_fica.get("medicare_rate", 0.0145))
    medicare_wages = _sum_field(extracts, "W-2", "medicare_wages")
    medicare_tax_withheld = _sum_field(extracts, "W-2", "medicare_tax_withheld")
    addl_medicare_withheld = round(max(0.0, medicare_tax_withheld - _medicare_rate * medicare_wages), 2)
    if addl_medicare_withheld > 0:
        notes.append(
            f"Additional Medicare tax withheld of ${addl_medicare_withheld:,.2f} (W-2 box 6 above "
            "1.45%) is credited as a payment (Form 8959 Part IV)."
        )

    # Earned Income Tax Credit (refundable, Form 1040 line 27). The §32(i)
    # investment-income cliff adds tax-exempt interest to the NIIT investment total
    # (which omits it). EITC qualifying children (under 19, not a parent/relative)
    # use a different age test than the CTC, so they have their own input that
    # defaults to the full dependent count.
    eitc_children = _num_eitc_qualifying_children(user_answers, num_deps)
    eitc_earned = wages + max(0.0, self_employment_income)
    eitc = _compute_eitc(eitc_earned, agi, eitc_children, status, taxpayer_age,
                         investment_income + tax_exempt_interest, feie_excluded > 0, fed_tables)
    if eitc > 0:
        notes.append(
            f"Earned Income Tax Credit of ${eitc:,.2f} (refundable, Form 1040 line 27) credited as "
            f"a payment, based on {eitc_children} EITC-qualifying child(ren)."
        )

    balance = round(total_tax - fed_withheld - excess_ss_tax - addl_medicare_withheld - actc - eitc, 2)
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
        "allocated_tips": allocated_tips,
        "interest_income": interest_income,
        "ordinary_dividends": ordinary_dividends,
        "qualified_dividends": qualified_dividends,
        "short_term_capital_gain": short_gain,
        "long_term_capital_gain": long_gain,
        "capital_loss_ordinary_offset": ordinary_offset,
        "capital_loss_carryover": capital_loss_carryover,
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
        "se_tax_deduction": se_tax_deduction,
        "early_withdrawal_penalty": early_withdrawal_penalty,
        "standard_deduction": std_deduction,
        "medical_expense_deductible": medical_deductible,
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
        "credit_for_other_dependents": odc,
        "additional_child_tax_credit": actc,
        "earned_income_credit": eitc,
        "premium_tax_credit": ptc_credit,
        "premium_tax_credit_repayment": ptc_repayment,
        "federal_tax": federal_tax,
        "self_employment_tax": se_tax,
        "tax_withheld": fed_withheld,
        "excess_social_security_tax": excess_ss_tax,
        "additional_medicare_tax_withheld": addl_medicare_withheld,
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
        "credit_for_other_dependents": odc,
        "additional_child_tax_credit": actc,
        "earned_income_credit": eitc,
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
