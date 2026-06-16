"""Canadian federal + provincial (Ontario) tax engine.

Pure functions; no LLM. Tables are loaded from
``config/tax_tables/ca/<year>.yaml`` and
``config/tax_tables/ca/provinces/<province>/<year>.yaml``.

Scope (v1):
- Federal progressive brackets
- Basic Personal Amount (BPA) credit
- CPP / EI withholding totals (informational; not added to tax)
- Eligible / non-eligible dividend gross-up + tax credit
- RRSP deduction
- Capital gains 50% inclusion
- Ontario provincial brackets + BPA
- Simplified Canada Employment Amount credit

Out of scope (flagged as ``notes``): OAS clawback, AMT, donations credit math,
medical expense credit, tuition transfer (raised as suggestion only), Québec
dual filing, multi-province allocation.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from wealthtax_agent.config.tax_tables import (
    MissingTableError,
    compute_progressive_tax,
    load_tables,
)
from wealthtax_agent.state import DraftReturn, FormExtract


def _to_float(value, default: float = 0.0) -> float:
    """Parse a user-typed answer (string / int / float) into a float."""
    if value is None:
        return default
    try:
        return float(str(value).replace(",", "").strip() or default)
    except (TypeError, ValueError):
        return default


def _is_65_or_older(user_answers: Dict[str, str]) -> bool:
    """True when the taxpayer is 65+ at year-end, via a truthy flag or an age."""
    if str(user_answers.get("taxpayer_age_65_or_older", "")).strip().lower() in {"1", "true", "yes", "y", "t"}:
        return True
    try:
        return float(user_answers.get("taxpayer_age", 0) or 0) >= 65
    except (TypeError, ValueError):
        return False


def _sum_field(extracts: Iterable[FormExtract], form_code: str, field: str) -> float:
    return float(sum(
        e.fields.get(field, 0.0)
        for e in extracts
        if e.form_code == form_code and e.jurisdiction == "CA"
    ))


def _t5008_capital_gains(extracts: Iterable[FormExtract]) -> float:
    return float(sum(
        e.fields.get("capital_gain", 0.0)
        for e in extracts
        if e.form_code == "T5008" and e.jurisdiction == "CA"
    ))


def _gross_up_dividends(taxable_eligible: float, actual_non_eligible: float, fed_tables: Dict[str, Any]) -> Dict[str, float]:
    div = fed_tables.get("dividend", {})
    eligible_grossup = div.get("eligible", {}).get("gross_up", 0.38)
    non_eligible_grossup = div.get("non_eligible", {}).get("gross_up", 0.15)
    grossed_non_eligible = actual_non_eligible * (1 + non_eligible_grossup)
    return {
        "taxable_eligible_dividends": taxable_eligible,
        "taxable_non_eligible_dividends": grossed_non_eligible,
    }


def _federal_dtc(taxable_eligible: float, taxable_non_eligible: float, fed_tables: Dict[str, Any]) -> float:
    div = fed_tables.get("dividend", {})
    eligible_rate = div.get("eligible", {}).get("federal_credit_rate", 0.150198)
    non_eligible_rate = div.get("non_eligible", {}).get("federal_credit_rate", 0.090301)
    return round(taxable_eligible * eligible_rate + taxable_non_eligible * non_eligible_rate, 2)


def _province_dtc(taxable_eligible: float, taxable_non_eligible: float, prov_tables: Dict[str, Any]) -> float:
    div = prov_tables.get("dividend", {})
    eligible_rate = float(div.get("eligible", 0.10))
    non_eligible_rate = float(div.get("non_eligible", 0.0299))
    return round(taxable_eligible * eligible_rate + taxable_non_eligible * non_eligible_rate, 2)


def compute_ca_return(
    extracts: List[FormExtract],
    year: int,
    province: str = "ON",
    user_answers: Dict[str, str] | None = None,
    residency_status: str = "resident",
) -> DraftReturn:
    user_answers = user_answers or {}
    notes: List[str] = []
    if residency_status == "non_resident":
        notes.append("Canadian non-resident: only Canada-source income is taxed in Canada.")
    elif residency_status == "part_year_resident":
        notes.append(
            "Canadian part-year resident: world income while resident, Canadian-source only while non-resident."
        )

    try:
        fed_tables = load_tables("ca", year)
    except MissingTableError as exc:
        notes.append(f"Federal CA table missing for {year}: {exc}")
        fed_tables = {"brackets": [], "basic_personal_amount": 0, "capital_gains_inclusion_rate": 0.5}

    try:
        prov_tables = load_tables("ca", year, sub="provinces", region=province)
    except MissingTableError as exc:
        notes.append(f"Provincial table missing for {province} {year}: {exc}")
        prov_tables = {"brackets": [], "basic_personal_amount": 0}

    # ---- Income aggregation ----
    employment_income = _sum_field(extracts, "T4", "employment_income")
    cpp_contributions = _sum_field(extracts, "T4", "cpp_contributions")
    ei_premiums = _sum_field(extracts, "T4", "ei_premiums")
    fed_tax_withheld = _sum_field(extracts, "T4", "income_tax_deducted")
    # Registered Pension Plan contributions (T4 box 20, line 20700) and union /
    # professional dues (T4 box 44, line 21200) are deductions from total income.
    rpp_contributions = _sum_field(extracts, "T4", "rpp_contributions")
    union_dues = _sum_field(extracts, "T4", "union_dues")

    interest_income = _sum_field(extracts, "T5", "interest_income")
    eligible_div_taxable = _sum_field(extracts, "T5", "taxable_eligible_dividends")
    non_eligible_div_actual = _sum_field(extracts, "T5", "actual_non_eligible_dividends")

    # T3 trust income
    t3_capital_gains = _sum_field(extracts, "T3", "capital_gains")
    t3_dividends_eligible = _sum_field(extracts, "T3", "taxable_eligible_dividends")
    t3_other_income = _sum_field(extracts, "T3", "other_income")
    # T3 box 25: foreign non-business income (foreign interest/dividends flowed
    # through a Canadian trust/fund — common on diversified ETF/mutual-fund T3s) is
    # fully taxable other income (T1 line 12100). Captured by the extractor (box 25)
    # but previously never read; distinct from box 26 (other_income) above.
    t3_foreign_income = _sum_field(extracts, "T3", "foreign_non_business_income")

    # T5008 capital gains (book vs proceeds difference)
    t5008_gains = _t5008_capital_gains(extracts)

    # Rental + self-employment
    net_rental = _sum_field(extracts, "T776", "net_rental_income")
    net_business = _sum_field(extracts, "T2125", "net_business_income")

    # T4A pension / fees
    pension_income = _sum_field(extracts, "T4A", "pension_or_superannuation")
    self_emp_t4a = _sum_field(extracts, "T4A", "fees_for_services") + _sum_field(extracts, "T4A", "self_employed_commissions")
    # T4A box 018: lump-sum payments (e.g. retiring allowance, DPSP/RPP commutation)
    # are taxable other income (line 13000). Captured but previously unread, so they
    # were dropped from income. They are NOT eligible for the pension income amount,
    # so they go into total_income but not pension_income.
    lump_sum_income = _sum_field(extracts, "T4A", "lump_sum_payments")

    # T4RSP / T4RIF (RRSP & RRIF withdrawals; HBP / LLP excluded from income)
    rrsp_withdrawals = (
        _sum_field(extracts, "T4RSP", "annuity_payments")
        + _sum_field(extracts, "T4RSP", "refund_of_premiums")
        + _sum_field(extracts, "T4RSP", "withdrawal_and_commutation")
        + _sum_field(extracts, "T4RSP", "other_income")
        - _sum_field(extracts, "T4RSP", "hbp_withdrawal")
        - _sum_field(extracts, "T4RSP", "llp_withdrawal")
    )
    rrsp_withdrawals = max(0.0, rrsp_withdrawals)
    rrif_income = _sum_field(extracts, "T4RIF", "taxable_amount")
    fed_tax_withheld += _sum_field(extracts, "T4RSP", "tax_deducted")
    fed_tax_withheld += _sum_field(extracts, "T4RIF", "tax_deducted")
    fed_tax_withheld += _sum_field(extracts, "T4A", "tax_deducted")

    # T5013 partnership income
    t5013_business = (
        _sum_field(extracts, "T5013", "business_income_loss")
        + _sum_field(extracts, "T5013", "professional_income_loss")
    )
    t5013_rental = _sum_field(extracts, "T5013", "rental_income")
    t5013_interest = _sum_field(extracts, "T5013", "interest_income")
    t5013_dividends_eligible = _sum_field(extracts, "T5013", "taxable_eligible_dividends")
    t5013_capital_gains = _sum_field(extracts, "T5013", "capital_gains")

    interest_income += t5013_interest

    # T2200 employment expenses (reduce employment income for tax purposes)
    employment_expenses = _sum_field(extracts, "T2200", "employment_expenses")

    # RRSP deduction (contributions slip + optional answer override)
    rrsp_deduction = _sum_field(extracts, "RRSP", "rrsp_contributions")

    # Dividend gross-ups
    div_taxable = _gross_up_dividends(
        eligible_div_taxable + t3_dividends_eligible + t5013_dividends_eligible,
        non_eligible_div_actual,
        fed_tables,
    )
    taxable_eligible = div_taxable["taxable_eligible_dividends"]
    taxable_non_eligible = div_taxable["taxable_non_eligible_dividends"]

    # Capital gains inclusion (apply user-supplied prior-year capital-loss
    # carryforward before the inclusion rate).
    prior_capital_losses = _to_float(user_answers.get("prior_capital_losses", 0))
    inclusion_rate = float(fed_tables.get("capital_gains_inclusion_rate", 0.5))
    raw_capital_gains = t3_capital_gains + t5008_gains + t5013_capital_gains
    net_capital_gains = max(0.0, raw_capital_gains - prior_capital_losses)
    taxable_capital_gains = net_capital_gains * inclusion_rate
    if prior_capital_losses > 0:
        notes.append(
            f"Applied ${prior_capital_losses:,.0f} of prior-year capital losses; "
            f"net taxable capital gains ${net_capital_gains:,.0f} × {inclusion_rate:.0%} inclusion."
        )

    employment_income_after_t2200 = max(0.0, employment_income - employment_expenses)
    if employment_expenses > 0:
        notes.append(
            f"Deducted ${employment_expenses:,.0f} of T2200-certified employment expenses (line 22900)."
        )

    # T1135 awareness — emit an explicit reminder if the user has foreign property over $100k.
    t1135_cost = _sum_field(extracts, "T1135", "total_foreign_property_cost")
    if t1135_cost == 0.0:
        t1135_cost = _to_float(user_answers.get("t1135_foreign_property_value", 0))
    foreign_property_income = _sum_field(extracts, "T1135", "foreign_property_income")
    if t1135_cost >= 100000:
        notes.append(
            f"T1135 required: foreign property cost ${t1135_cost:,.0f} ≥ $100,000 CAD. "
            "File separately from your T1."
        )

    # T2222 Northern Residents Deduction (line 25500)
    nrd = (
        _sum_field(extracts, "T2222", "residency_deduction")
        + _sum_field(extracts, "T2222", "travel_deduction")
    )

    # Student loan interest (line 31900). 15% federal credit on the interest
    # paid on Canada Student Loans. Cross-border guardrail can zero this out.
    student_loan_interest_ca = _to_float(user_answers.get("student_loan_interest_ca", 0))
    # Federal tuition amount (line 32300): a lowest-rate non-refundable credit on the
    # student's OWN eligible tuition fees (T2202), captured but previously never read.
    # The student must claim it against their own tax first; transfer (up to $5,000) or
    # carry-forward of the UNUSED portion is a separate optimization (see optimize.py),
    # not the own-year claim modelled here. Only the federal credit is added (the
    # provincial tuition credit is left out to keep this minimal).
    tuition_fees = _sum_field(extracts, "T2202", "eligible_tuition_fees")

    # Old Age Security benefits (T4A(OAS) box 18, supplied via user_answers) are fully
    # taxable income (T1 line 11300). The engine previously read the OAS amount only to
    # cap the recovery-tax clawback (#136); it is now also included in total income so
    # an OAS recipient is taxed on it (and so net income — which drives the clawback
    # threshold — reflects it).
    oas_benefits = _to_float(user_answers.get("oas_benefits", 0))
    total_income = round(
        employment_income_after_t2200
        + interest_income
        + taxable_eligible
        + taxable_non_eligible
        + taxable_capital_gains
        + net_rental
        + net_business
        + pension_income
        + self_emp_t4a
        + t3_other_income
        + t3_foreign_income
        + rrsp_withdrawals
        + rrif_income
        + t5013_business
        + t5013_rental
        + foreign_property_income
        + lump_sum_income
        + oas_benefits,
        2,
    )

    # Northern Residents Deduction reduces net income (line 25500). RPP
    # contributions (20700) and union/professional dues (21200) likewise reduce
    # income on the way to net income.
    net_income = max(0.0, total_income - rrsp_deduction - rpp_contributions - union_dues - nrd)
    if nrd > 0:
        notes.append(f"Applied ${nrd:,.0f} Northern Residents Deduction (T2222 / line 25500).")
    taxable_income = net_income

    # ---- Tax + credits ----
    federal_tax_before_credits = compute_progressive_tax(taxable_income, fed_tables.get("brackets", []))
    bpa = float(fed_tables.get("basic_personal_amount", 0))
    # Federal BPA is reduced for high earners, phasing linearly from the full
    # amount to a floor as net income rises from the bottom of the 29% bracket to
    # the bottom of the top (33%) bracket (CRA rule since 2020). Only applied when
    # the table supplies the floor (basic_personal_amount_min); otherwise the flat
    # BPA is used (no regression for years without the value).
    bpa_min = float(fed_tables.get("basic_personal_amount_min", 0))
    _fed_brackets = fed_tables.get("brackets", [])
    if bpa_min and bpa_min < bpa and len(_fed_brackets) >= 3:
        phase_start = float(_fed_brackets[-3].get("up_to") or 0)
        phase_end = float(_fed_brackets[-2].get("up_to") or 0)
        if phase_end > phase_start:
            if net_income >= phase_end:
                bpa = bpa_min
            elif net_income > phase_start:
                bpa -= (bpa - bpa_min) * (net_income - phase_start) / (phase_end - phase_start)
    employment_amount = float(fed_tables.get("canada_employment_amount", 0)) if employment_income > 0 else 0.0
    lowest_rate = (fed_tables.get("brackets") or [{"rate": 0.15}])[0].get("rate", 0.15)

    # Donations + medical expense credits (federal)
    # T4 box 46 captures employer-facilitated (payroll) charitable giving. Take the
    # larger of the slip amount and the manual entry rather than summing: a single
    # donation reported on the slip and also typed by the user is the same dollar, so
    # summing would double the credit. Manual entry thus acts as an override (e.g. the
    # user adds a separate cash-donation receipt by typing a larger total). Mirrors the
    # slip-or-manual precedent used for T1135 foreign property above.
    slip_donations = _sum_field(extracts, "T4", "charitable_donations")
    manual_donations = _to_float(user_answers.get("charitable_donations", 0))
    donations = max(slip_donations, manual_donations)
    medical_expenses = _to_float(user_answers.get("medical_expenses", 0))
    # First $200 of donations gets 15%; excess gets 29% (federal). Simplified.
    if donations > 0:
        donations_credit = donations * float(lowest_rate) if donations <= 200 else (
            200 * float(lowest_rate) + (donations - 200) * 0.29
        )
    else:
        donations_credit = 0.0
    # Medical: credit on amount exceeding lesser of 3% of net income or fixed threshold ($2,759 for 2024)
    medical_threshold = min(net_income * 0.03, 2759.0)
    medical_creditable = max(0.0, medical_expenses - medical_threshold)
    medical_credit = medical_creditable * float(lowest_rate)

    student_loan_credit = student_loan_interest_ca * float(lowest_rate) if student_loan_interest_ca > 0 else 0.0

    # Property tax credit (line 61120 / Ontario Trillium Benefit umbrella).
    # Eligible expense capped at $12,000 per the wizard tooltip; credit applied
    # at the lowest federal rate to mirror the tuition/student-loan credit shape.
    raw_property_tax = _to_float(user_answers.get("property_tax_paid", 0))
    property_tax_eligible = min(max(0.0, raw_property_tax), 12000.0)
    property_tax_credit = property_tax_eligible * float(lowest_rate)
    if raw_property_tax > 12000.0:
        notes.append(
            f"Property tax paid ${raw_property_tax:,.0f} exceeds $12,000 cap; "
            "credit computed on the first $12,000."
        )

    # Excess CPP/EI from multiple employers (T1 lines 44800/45000): each employer
    # withholds CPP and EI independently, so a job-switcher's combined contributions
    # routinely exceed the annual employee maximum. That excess is a REFUNDABLE
    # overpayment, not a 15% credit (the CA analog of the US excess-Social-Security
    # rule). It requires 2+ T4s — single-employer over-withholding is the employer's
    # to correct. (QC's QPP has its own maximum; this uses the federal CPP/EI maxima
    # and so under-models a QC-only QPP overpayment, which is acceptable here.)
    cpp_max = float(fed_tables.get("cpp", {}).get("max_contribution", 0) or 0)
    ei_max = float(fed_tables.get("ei", {}).get("max_contribution", 0) or 0)
    t4_count = sum(1 for e in extracts if e.form_code == "T4" and e.jurisdiction == "CA")
    cpp_overpayment = round(max(0.0, cpp_contributions - cpp_max), 2) if (t4_count >= 2 and cpp_max > 0) else 0.0
    ei_overpayment = round(max(0.0, ei_premiums - ei_max), 2) if (t4_count >= 2 and ei_max > 0) else 0.0
    cpp_ei_overpayment = round(cpp_overpayment + ei_overpayment, 2)
    # The refunded excess must not also earn the non-refundable credit, so the
    # creditable base is contributions net of the overpayment (full amount when
    # there is no overpayment, so single-employer filers are unaffected).
    creditable_cpp = cpp_contributions - cpp_overpayment
    creditable_ei = ei_premiums - ei_overpayment

    # CPP/QPP and EI contributions (T4 boxes 16/18) are non-refundable credits
    # at the lowest rate (federal lines 30800 / 31200). The enhanced-CPP portion
    # is technically a deduction rather than a credit; crediting the full amount
    # here is a simplification that is conservative for taxpayers above the
    # lowest bracket.
    cpp_ei_credit = (creditable_cpp + creditable_ei) * float(lowest_rate)

    # Pension income amount (federal line 31400): a lowest-rate credit on the
    # first $2,000 of eligible pension income. T4A superannuation/pension annuity
    # qualifies at any age; RRIF income (T4RIF) is eligible pension income only
    # once the taxpayer is 65+, so it is added to the base under the age gate.
    eligible_pension = pension_income
    if _is_65_or_older(user_answers):
        eligible_pension += rrif_income
    pension_income_amount = min(eligible_pension, 2000.0)
    pension_income_credit = pension_income_amount * float(lowest_rate)

    # Age amount (federal line 30100): a lowest-rate credit for taxpayers 65+ at
    # year-end, reduced by 15% of net income over the year's threshold and fully
    # phased out above it. Federal only — the provincial age amount is not modelled
    # (mirrors how the pension income amount is handled). Requires an age input.
    age_tbl = fed_tables.get("age_amount", {})
    age_amount_credit = 0.0
    if age_tbl and _is_65_or_older(user_answers):
        age_max = float(age_tbl.get("maximum", 0))
        age_threshold = float(age_tbl.get("net_income_threshold", 0))
        age_reduction = float(age_tbl.get("reduction_rate", 0.15))
        age_amount = max(0.0, age_max - age_reduction * max(0.0, net_income - age_threshold))
        age_amount_credit = round(age_amount * float(lowest_rate), 2)

    tuition_credit = tuition_fees * float(lowest_rate)
    fed_non_refundable = (
        (bpa + employment_amount) * float(lowest_rate)
        + cpp_ei_credit
        + pension_income_credit
        + age_amount_credit
        + donations_credit
        + medical_credit
        + student_loan_credit
        + property_tax_credit
        + tuition_credit
    )
    federal_dtc = _federal_dtc(taxable_eligible, taxable_non_eligible, fed_tables)
    federal_tax = max(0.0, federal_tax_before_credits - fed_non_refundable - federal_dtc)

    # OAS clawback (recovery tax) — 15% of net income above the year's threshold.
    # The threshold is indexed annually (2023 $86,912; 2024 $90,997; 2025 $93,454),
    # so it must come from the year table — a single hardcoded value mis-taxed every
    # non-2024 return near the boundary. Falls back to the 2024 value if absent.
    oas_threshold = float(fed_tables.get("oas_recovery_threshold", 90997.0))
    # The recovery tax (§180.2 ITA) claws back the LESSER of the OAS actually
    # received and 15% of net income over the threshold. The OAS amount (T4A(OAS)
    # box 18) must be supplied — previously the engine used pension + RRIF income as
    # a proxy, which (a) spuriously clawed back from seniors with pension/RRIF income
    # but no OAS, and (b) capped at the full pension rather than the OAS received. A
    # filer with no OAS owes no recovery tax. (oas_benefits is read above and is
    # included in total/net income; net income is what crosses the threshold here.)
    if oas_benefits > 0 and net_income > oas_threshold:
        clawback = round(min(oas_benefits, (net_income - oas_threshold) * 0.15), 2)
        federal_tax += clawback
        notes.append(f"OAS recovery tax (clawback): net income > ${oas_threshold:,.0f}; added ${clawback:,.0f}.")
    else:
        clawback = 0.0

    provincial_tax_before_credits = compute_progressive_tax(taxable_income, prov_tables.get("brackets", []))
    prov_bpa = float(prov_tables.get("basic_personal_amount", 0))
    prov_lowest_rate = (prov_tables.get("brackets") or [{"rate": 0.0505}])[0].get("rate", 0.0505)
    # CPP/EI contributions are also credited provincially, at the province's
    # lowest rate (the federal credit was added separately). Without this every
    # employed Canadian's provincial tax was overstated.
    cpp_ei_credit_prov = (creditable_cpp + creditable_ei) * float(prov_lowest_rate)
    # The medical-expense credit is a lowest-rate credit in both jurisdictions,
    # so the provincial credit is the creditable amount at the PROVINCIAL lowest
    # rate — not the federal-rate amount, which over-credited provincially.
    medical_credit_prov = medical_creditable * float(prov_lowest_rate)
    # Provincial tuition credit: the lowest-rate non-refundable credit on the same
    # T2202 eligible tuition fees claimed federally (#128). Most provinces grant it at
    # their own lowest rate (ON 5.05%); a few have eliminated it, but the table-driven
    # prov_lowest_rate keeps this a province-agnostic estimate. Mirrors the provincial
    # CPP/EI and medical credits above; the federal half is computed earlier.
    tuition_credit_prov = tuition_fees * float(prov_lowest_rate)
    # Provincial donation credit at provincial rates when the table supplies the
    # excess rate (first $200 at the lowest rate, excess at donation_credit_high_rate).
    # Provinces without that rate fall back to the federal-rate amount (legacy
    # behaviour) rather than approximating an unknown provincial rate.
    prov_donation_high = prov_tables.get("donation_credit_high_rate")
    if prov_donation_high is not None and donations > 0:
        donations_credit_prov = (
            donations * float(prov_lowest_rate) if donations <= 200
            else 200 * float(prov_lowest_rate) + (donations - 200) * float(prov_donation_high)
        )
    else:
        donations_credit_prov = donations_credit
    prov_non_refundable = (
        prov_bpa * float(prov_lowest_rate)
        + cpp_ei_credit_prov
        + donations_credit_prov
        + medical_credit_prov
        + tuition_credit_prov
    )
    prov_dtc = _province_dtc(taxable_eligible, taxable_non_eligible, prov_tables)
    provincial_tax = max(0.0, provincial_tax_before_credits - prov_non_refundable - prov_dtc)

    # Pension income splitting with spouse (line 21000 / 11600 reciprocal)
    pension_split_pct = _to_float(user_answers.get("pension_split_pct", 0))
    if pension_split_pct > 0 and pensionable > 0:
        # Up to 50% of eligible pension income can be split.
        pension_split_pct = min(pension_split_pct, 50.0)
        notes.append(
            f"Pension income splitting at {pension_split_pct:.0f}% of ${pensionable:,.0f} "
            "may further reduce tax (not modelled in this estimate)."
        )

    # Canada Workers Benefit (Schedule 6): a REFUNDABLE credit for low-income
    # workers, so it is credited as a payment (reduces balance / increases refund),
    # mirroring the US ACTC. Federal basic amount only — the disability supplement,
    # provincial AB/QC/NU reconfigurations, and true family AFNI (spousal income is
    # not modelled) are out of scope and flagged. Years without a cwb table (e.g.
    # 2025 pending CRA figures) yield $0 → no regression.
    cwb = 0.0
    cwb_tbl = fed_tables.get("cwb", {})
    if cwb_tbl and residency_status == "resident":
        working_income = employment_income_after_t2200 + max(0.0, net_business + t5013_business + self_emp_t4a)
        age = _to_float(user_answers.get("taxpayer_age", 19))
        is_student = str(user_answers.get("full_time_student", "")).strip().lower() in {"1", "true", "yes", "y", "t"}
        has_family = str(user_answers.get("has_spouse_or_dependant", "")).strip().lower() in {"1", "true", "yes", "y", "t"}
        floor = float(cwb_tbl.get("working_income_floor", 3000))
        if working_income > floor and age >= 19 and not is_student:
            max_basic = float(cwb_tbl.get("max_family" if has_family else "max_single", 0))
            threshold = float(cwb_tbl.get("phaseout_threshold_family" if has_family else "phaseout_threshold_single", 0))
            basic = min(max_basic, float(cwb_tbl.get("phase_in_rate", 0.27)) * (working_income - floor))
            cwb = round(max(0.0, basic - float(cwb_tbl.get("phaseout_rate", 0.15)) * max(0.0, net_income - threshold)), 2)
            if cwb > 0:
                notes.append(f"Canada Workers Benefit (refundable, Schedule 6) of ${cwb:,.2f} credited as a payment.")
                if has_family:
                    notes.append("CWB family amount uses the filer's net income only; spousal income is not modelled.")
                if province.upper() in {"AB", "QC", "NU"}:
                    notes.append(f"{province.upper()} uses a CWB reconfiguration; the federal estimate may differ.")

    total_tax = round(federal_tax + provincial_tax, 2)
    if cpp_ei_overpayment > 0:
        notes.append(
            f"Excess CPP/EI of ${cpp_ei_overpayment:,.2f} from multiple employers "
            "is refunded as an overpayment (T1 lines 44800 / 45000)."
        )
    balance = round(total_tax - fed_tax_withheld - cwb - cpp_ei_overpayment, 2)
    refund = round(max(0.0, -balance), 2)
    owing = round(max(0.0, balance), 2)

    notes.extend([
        "Simplified prototype: foreign tax credit and a few minor credits not modelled.",
        "CPP / EI shown for context but not added back; T4 already nets them.",
    ])
    if province.upper() == "QC":
        notes.append(
            "Quebec residents file a separate Quebec TP-1 return with Revenu Québec; "
            "the provincial estimate above is informational only."
        )

    line_items = {
        "employment_income": employment_income,
        "employment_expenses_t2200": employment_expenses,
        "employment_income_net": employment_income_after_t2200,
        "canada_workers_benefit": cwb,
        "student_loan_interest_ca": student_loan_interest_ca,
        "student_loan_credit": student_loan_credit,
        "property_tax_paid": raw_property_tax,
        "property_tax_eligible": property_tax_eligible,
        "property_tax_credit": property_tax_credit,
        "eligible_tuition_fees": tuition_fees,
        "tuition_credit": tuition_credit,
        "interest_income": interest_income,
        "trust_foreign_non_business_income": t3_foreign_income,
        "taxable_eligible_dividends": taxable_eligible,
        "taxable_non_eligible_dividends": taxable_non_eligible,
        "raw_capital_gains": raw_capital_gains,
        "prior_capital_losses_applied": prior_capital_losses,
        "net_capital_gains": net_capital_gains,
        "taxable_capital_gains": taxable_capital_gains,
        "net_rental_income": net_rental + t5013_rental,
        "net_business_income": net_business + t5013_business,
        "rrsp_withdrawals": rrsp_withdrawals,
        "rrif_income": rrif_income,
        "pension_income": pension_income,
        "oas_income": oas_benefits,
        "pension_income_credit": pension_income_credit,
        "age_amount_credit": age_amount_credit,
        "other_self_employment": self_emp_t4a,
        "lump_sum_income": lump_sum_income,
        "trust_other_income": t3_other_income,
        "rrsp_deduction": rrsp_deduction,
        "rpp_deduction": rpp_contributions,
        "union_dues_deduction": union_dues,
        "northern_residents_deduction": nrd,
        "foreign_property_income": foreign_property_income,
        "t1135_foreign_property_cost": t1135_cost,
        "donations_credit": donations_credit,
        "charitable_donations": donations,
        "charitable_donations_slip": slip_donations,
        "medical_credit": medical_credit,
        "oas_clawback": clawback,
        "federal_tax_before_credits": federal_tax_before_credits,
        "federal_non_refundable_credits": fed_non_refundable,
        "federal_dividend_tax_credit": federal_dtc,
        "federal_tax": federal_tax,
        "provincial_tax_before_credits": provincial_tax_before_credits,
        "provincial_non_refundable_credits": prov_non_refundable,
        "provincial_cpp_ei_credit": cpp_ei_credit_prov,
        "provincial_tuition_credit": tuition_credit_prov,
        "provincial_medical_credit": medical_credit_prov,
        "provincial_donations_credit": donations_credit_prov,
        "provincial_dividend_tax_credit": prov_dtc,
        "provincial_tax": provincial_tax,
        "tax_withheld": fed_tax_withheld,
        "cpp_contributions": cpp_contributions,
        "ei_premiums": ei_premiums,
        "cpp_ei_credit": cpp_ei_credit,
        "cpp_overpayment": cpp_overpayment,
        "ei_overpayment": ei_overpayment,
        "cpp_ei_overpayment": cpp_ei_overpayment,
    }

    totals = {
        "total_income": total_income,
        "net_income": net_income,
        "taxable_income": taxable_income,
        "total_tax": total_tax,
        "balance_owing": owing,
        "refund": refund,
    }

    credits = {
        "basic_personal_amount": bpa,
        "canada_employment_amount": employment_amount,
        "provincial_basic_personal_amount": prov_bpa,
    }

    return DraftReturn(
        jurisdiction="CA",
        tax_year=year,
        total_income=total_income,
        rrsp_deduction=rrsp_deduction,
        taxable_income=taxable_income,
        estimated_tax=total_tax,
        estimated_refund=refund,
        line_items=line_items,
        totals=totals,
        credits=credits,
        notes=notes,
    )
