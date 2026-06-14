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

    # T5008 capital gains (book vs proceeds difference)
    t5008_gains = _t5008_capital_gains(extracts)

    # Rental + self-employment
    net_rental = _sum_field(extracts, "T776", "net_rental_income")
    net_business = _sum_field(extracts, "T2125", "net_business_income")

    # T4A pension / fees
    pension_income = _sum_field(extracts, "T4A", "pension_or_superannuation")
    self_emp_t4a = _sum_field(extracts, "T4A", "fees_for_services") + _sum_field(extracts, "T4A", "self_employed_commissions")

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
        + rrsp_withdrawals
        + rrif_income
        + t5013_business
        + t5013_rental
        + foreign_property_income,
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
    donations = _to_float(user_answers.get("charitable_donations", 0))
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

    # CPP/QPP and EI contributions (T4 boxes 16/18) are non-refundable credits
    # at the lowest rate (federal lines 30800 / 31200). The enhanced-CPP portion
    # is technically a deduction rather than a credit; crediting the full amount
    # here is a simplification that is conservative for taxpayers above the
    # lowest bracket. Excess over the annual maxima (multiple employers) would be
    # refunded rather than credited — not modelled.
    cpp_ei_credit = (cpp_contributions + ei_premiums) * float(lowest_rate)

    # Pension income amount (federal line 31400): a lowest-rate credit on the
    # first $2,000 of eligible pension income. T4A superannuation/pension annuity
    # qualifies at any age, so no age gate is needed. (RRIF income, which only
    # qualifies at 65+, is conservatively excluded here.)
    pension_income_amount = min(pension_income, 2000.0)
    pension_income_credit = pension_income_amount * float(lowest_rate)

    fed_non_refundable = (
        (bpa + employment_amount) * float(lowest_rate)
        + cpp_ei_credit
        + pension_income_credit
        + donations_credit
        + medical_credit
        + student_loan_credit
        + property_tax_credit
    )
    federal_dtc = _federal_dtc(taxable_eligible, taxable_non_eligible, fed_tables)
    federal_tax = max(0.0, federal_tax_before_credits - fed_non_refundable - federal_dtc)

    # OAS clawback (recovery tax) — 15% of net income above the threshold
    # ($90,997 for 2024). Adds to federal tax. Skip if no pension/RRIF income.
    oas_threshold = 90997.0
    pensionable = pension_income + rrif_income
    if pensionable > 0 and net_income > oas_threshold:
        clawback = min(pensionable, (net_income - oas_threshold) * 0.15)
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
    cpp_ei_credit_prov = (cpp_contributions + ei_premiums) * float(prov_lowest_rate)
    # The medical-expense credit is a lowest-rate credit in both jurisdictions,
    # so the provincial credit is the creditable amount at the PROVINCIAL lowest
    # rate — not the federal-rate amount, which over-credited provincially.
    medical_credit_prov = medical_creditable * float(prov_lowest_rate)
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

    total_tax = round(federal_tax + provincial_tax, 2)
    balance = round(total_tax - fed_tax_withheld, 2)
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
        "student_loan_interest_ca": student_loan_interest_ca,
        "student_loan_credit": student_loan_credit,
        "property_tax_paid": raw_property_tax,
        "property_tax_eligible": property_tax_eligible,
        "property_tax_credit": property_tax_credit,
        "interest_income": interest_income,
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
        "pension_income_credit": pension_income_credit,
        "other_self_employment": self_emp_t4a,
        "trust_other_income": t3_other_income,
        "rrsp_deduction": rrsp_deduction,
        "rpp_deduction": rpp_contributions,
        "union_dues_deduction": union_dues,
        "northern_residents_deduction": nrd,
        "foreign_property_income": foreign_property_income,
        "t1135_foreign_property_cost": t1135_cost,
        "donations_credit": donations_credit,
        "medical_credit": medical_credit,
        "oas_clawback": clawback,
        "federal_tax_before_credits": federal_tax_before_credits,
        "federal_non_refundable_credits": fed_non_refundable,
        "federal_dividend_tax_credit": federal_dtc,
        "federal_tax": federal_tax,
        "provincial_tax_before_credits": provincial_tax_before_credits,
        "provincial_non_refundable_credits": prov_non_refundable,
        "provincial_cpp_ei_credit": cpp_ei_credit_prov,
        "provincial_medical_credit": medical_credit_prov,
        "provincial_donations_credit": donations_credit_prov,
        "provincial_dividend_tax_credit": prov_dtc,
        "provincial_tax": provincial_tax,
        "tax_withheld": fed_tax_withheld,
        "cpp_contributions": cpp_contributions,
        "ei_premiums": ei_premiums,
        "cpp_ei_credit": cpp_ei_credit,
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
