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
) -> DraftReturn:
    user_answers = user_answers or {}
    notes: List[str] = []

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

    # RRSP deduction
    rrsp_deduction = _sum_field(extracts, "RRSP", "rrsp_contributions")

    # Dividend gross-ups
    div_taxable = _gross_up_dividends(eligible_div_taxable + t3_dividends_eligible, non_eligible_div_actual, fed_tables)
    taxable_eligible = div_taxable["taxable_eligible_dividends"]
    taxable_non_eligible = div_taxable["taxable_non_eligible_dividends"]

    # Capital gains inclusion
    inclusion_rate = float(fed_tables.get("capital_gains_inclusion_rate", 0.5))
    total_capital_gains = t3_capital_gains + t5008_gains
    taxable_capital_gains = max(0.0, total_capital_gains) * inclusion_rate

    total_income = round(
        employment_income
        + interest_income
        + taxable_eligible
        + taxable_non_eligible
        + taxable_capital_gains
        + net_rental
        + net_business
        + pension_income
        + self_emp_t4a
        + t3_other_income,
        2,
    )

    net_income = max(0.0, total_income - rrsp_deduction)
    taxable_income = net_income

    # ---- Tax + credits ----
    federal_tax_before_credits = compute_progressive_tax(taxable_income, fed_tables.get("brackets", []))
    bpa = float(fed_tables.get("basic_personal_amount", 0))
    employment_amount = float(fed_tables.get("canada_employment_amount", 0)) if employment_income > 0 else 0.0
    lowest_rate = (fed_tables.get("brackets") or [{"rate": 0.15}])[0].get("rate", 0.15)
    fed_non_refundable = (bpa + employment_amount) * float(lowest_rate)
    federal_dtc = _federal_dtc(taxable_eligible, taxable_non_eligible, fed_tables)
    federal_tax = max(0.0, federal_tax_before_credits - fed_non_refundable - federal_dtc)

    provincial_tax_before_credits = compute_progressive_tax(taxable_income, prov_tables.get("brackets", []))
    prov_bpa = float(prov_tables.get("basic_personal_amount", 0))
    prov_lowest_rate = (prov_tables.get("brackets") or [{"rate": 0.0505}])[0].get("rate", 0.0505)
    prov_non_refundable = prov_bpa * float(prov_lowest_rate)
    prov_dtc = _province_dtc(taxable_eligible, taxable_non_eligible, prov_tables)
    provincial_tax = max(0.0, provincial_tax_before_credits - prov_non_refundable - prov_dtc)

    total_tax = round(federal_tax + provincial_tax, 2)
    balance = round(total_tax - fed_tax_withheld, 2)
    refund = round(max(0.0, -balance), 2)
    owing = round(max(0.0, balance), 2)

    notes.extend([
        "Simplified prototype: AMT, OAS clawback, foreign tax credit, and donations credit not modelled.",
        "CPP / EI shown for context but not added back; T4 already nets them.",
    ])

    line_items = {
        "employment_income": employment_income,
        "interest_income": interest_income,
        "taxable_eligible_dividends": taxable_eligible,
        "taxable_non_eligible_dividends": taxable_non_eligible,
        "taxable_capital_gains": taxable_capital_gains,
        "net_rental_income": net_rental,
        "net_business_income": net_business,
        "pension_income": pension_income,
        "other_self_employment": self_emp_t4a,
        "trust_other_income": t3_other_income,
        "rrsp_deduction": rrsp_deduction,
        "federal_tax_before_credits": federal_tax_before_credits,
        "federal_non_refundable_credits": fed_non_refundable,
        "federal_dividend_tax_credit": federal_dtc,
        "federal_tax": federal_tax,
        "provincial_tax_before_credits": provincial_tax_before_credits,
        "provincial_non_refundable_credits": prov_non_refundable,
        "provincial_dividend_tax_credit": prov_dtc,
        "provincial_tax": provincial_tax,
        "tax_withheld": fed_tax_withheld,
        "cpp_contributions": cpp_contributions,
        "ei_premiums": ei_premiums,
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
