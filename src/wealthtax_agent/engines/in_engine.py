"""Indian tax engine (Income Tax Act 1961, including Finance Act 2024 changes).

Pure functions. Tables loaded from ``config/tax_tables/in/<year>.yaml``.
Year argument is the *assessment year* (AY) — AY 2024-25 = FY 2023-24.

Scope:
- Income heads: Salary, House Property (Sec 24(b)), Capital Gains (LTCG/STCG
  pre/post Jul 23 2024 split), Business/Profession (PGBP), Other Sources.
- Deductions: 80C (cap 1.5L), 80CCD(1B) NPS (50k), 80D (premiums), 80E
  (uncapped), 80G, 80TTA/TTB, Section 24(b) home loan interest, HRA exemption,
  standard deduction (salary).
- 87A rebate, surcharge (10/15/25/37%), 4% Health & Education Cess.
- Regime selection: ``regime="old"|"new"|"auto"``. ``"auto"`` picks the lower
  tax-and-cess number and emits a comparison note.
- Residency-aware: NR / RNOR pay tax only on India-source income.

Out of scope: TDS reconciliation against 26AS, advance-tax / interest under
234A/B/C, MAT / AMT for individuals, foreign-asset disclosure penalties.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Tuple

from wealthtax_agent.config.tax_tables import (
    MissingTableError,
    compute_progressive_tax,
    load_tables,
)
from wealthtax_agent.state import DraftReturn, FormExtract


def _to_float(value, default: float = 0.0) -> float:
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
        if e.form_code == form_code and e.jurisdiction == "IN"
    ))


def _age(user_answers: Dict[str, str]) -> int:
    try:
        return max(0, int(user_answers.get("age", "0")))
    except (TypeError, ValueError):
        return 0


def _old_regime_brackets(age: int, tables: Dict[str, Any]) -> List[Dict[str, float]]:
    old = tables.get("old_regime", {})
    if age >= 80 and old.get("brackets_super_senior_80_plus"):
        return old["brackets_super_senior_80_plus"]
    if age >= 60 and old.get("brackets_senior_60_to_80"):
        return old["brackets_senior_60_to_80"]
    return old.get("brackets", [])


def _hra_exemption(
    hra_received: float,
    basic_salary: float,
    rent_paid: float,
    metro: bool,
    tables: Dict[str, Any],
) -> float:
    """Standard HRA exemption formula: min of three numbers."""
    if hra_received <= 0 or rent_paid <= 0 or basic_salary <= 0:
        return 0.0
    hra_cfg = tables.get("hra", {})
    pct = float(hra_cfg.get("metro_pct", 0.5) if metro else hra_cfg.get("non_metro_pct", 0.4))
    rent_minus_10 = max(0.0, rent_paid - 0.10 * basic_salary)
    salary_pct = basic_salary * pct
    return round(min(hra_received, rent_minus_10, salary_pct), 2)


def _surcharge(
    tax_before_surcharge: float,
    total_income: float,
    tables: Dict[str, Any],
    regime: str,
) -> float:
    """Tiered surcharge on income tax (not on income directly).

    For the new regime the highest tier (37%) is capped at 25%.
    """
    tiers = tables.get("surcharge", [])
    rate = 0.0
    for tier in tiers:
        if total_income > float(tier["income_above"]):
            rate = float(tier["rate"])
    if regime == "new":
        rate = min(rate, float(tables.get("surcharge_new_regime_cap", 0.25)))
    return round(tax_before_surcharge * rate, 2)


def _capital_gains_split(
    extracts: List[FormExtract],
    user_answers: Dict[str, str],
    tables: Dict[str, Any],
) -> Dict[str, float]:
    """Compute LTCG/STCG, with pre/post Jul 23 2024 split for AY 2025-26 tables.

    Looks at ``STOCK-GAIN`` extracts with fields:
      - ``stcg_equity_pre_change``, ``ltcg_equity_pre_change``
      - ``stcg_equity_post_change``, ``ltcg_equity_post_change``
      - ``stcg_other_pre_change``, ``ltcg_other_pre_change``
      - ``stcg_other_post_change``, ``ltcg_other_post_change``
    Falls back to single-rate fields (``stcg_equity``, ``ltcg_equity``,
    ``stcg_other``, ``ltcg_other``) for the AY 2024-25 table.
    """
    cg = tables.get("capital_gains", {})
    has_split = "regime_change_date" in cg
    pre = cg.get("pre_change", cg) if has_split else cg
    post = cg.get("post_change", cg) if has_split else cg

    def _sum(field: str) -> float:
        return _sum_field(extracts, "STOCK-GAIN", field)

    if has_split:
        stcg_eq_pre = _sum("stcg_equity_pre_change") or _sum("stcg_equity")
        ltcg_eq_pre = _sum("ltcg_equity_pre_change")
        stcg_eq_post = _sum("stcg_equity_post_change")
        ltcg_eq_post = _sum("ltcg_equity_post_change") or _sum("ltcg_equity")
        stcg_other_pre = _sum("stcg_other_pre_change") or _sum("stcg_other")
        ltcg_other_pre = _sum("ltcg_other_pre_change") or _sum("ltcg_other")
        stcg_other_post = _sum("stcg_other_post_change")
        ltcg_other_post = _sum("ltcg_other_post_change")
    else:
        stcg_eq_pre = _sum("stcg_equity")
        ltcg_eq_pre = _sum("ltcg_equity")
        stcg_eq_post = 0.0
        ltcg_eq_post = 0.0
        stcg_other_pre = _sum("stcg_other")
        ltcg_other_pre = _sum("ltcg_other")
        stcg_other_post = 0.0
        ltcg_other_post = 0.0

    # LTCG equity exemption applies per the year's threshold.
    pre_threshold = float(pre.get("ltcg_equity_threshold", 100000))
    post_threshold = float(post.get("ltcg_equity_threshold", pre_threshold))
    ltcg_eq_pre_taxable = max(0.0, ltcg_eq_pre - pre_threshold)
    ltcg_eq_post_taxable = max(0.0, ltcg_eq_post - post_threshold)

    tax_ltcg_eq = (
        ltcg_eq_pre_taxable * float(pre.get("ltcg_equity_rate", 0.10))
        + ltcg_eq_post_taxable * float(post.get("ltcg_equity_rate", 0.125))
    )
    tax_stcg_eq = (
        stcg_eq_pre * float(pre.get("stcg_equity_rate", 0.15))
        + stcg_eq_post * float(post.get("stcg_equity_rate", 0.20))
    )
    tax_ltcg_other = (
        ltcg_other_pre * float(pre.get("ltcg_other_rate", 0.20))
        + ltcg_other_post * float(post.get("ltcg_other_rate", 0.125))
    )

    return {
        "stcg_equity_total": stcg_eq_pre + stcg_eq_post,
        "ltcg_equity_total": ltcg_eq_pre + ltcg_eq_post,
        "ltcg_equity_taxable": ltcg_eq_pre_taxable + ltcg_eq_post_taxable,
        "ltcg_equity_exempt": (ltcg_eq_pre - ltcg_eq_pre_taxable) + (ltcg_eq_post - ltcg_eq_post_taxable),
        "stcg_other_total": stcg_other_pre + stcg_other_post,
        "ltcg_other_total": ltcg_other_pre + ltcg_other_post,
        "tax_ltcg_equity": round(tax_ltcg_eq, 2),
        "tax_stcg_equity": round(tax_stcg_eq, 2),
        "tax_ltcg_other": round(tax_ltcg_other, 2),
        "stcg_other_taxed_at_slab": stcg_other_pre + stcg_other_post,
    }


def _compute_one_regime(
    extracts: List[FormExtract],
    user_answers: Dict[str, str],
    tables: Dict[str, Any],
    regime: str,
    residency_status: str,
    year: int,
) -> Tuple[DraftReturn, Dict[str, float]]:
    """Compute the return under one regime. Returns (DraftReturn, line_items)."""
    notes: List[str] = []
    age = _age(user_answers)
    is_nr_or_rnor = residency_status in {"NR", "RNOR"}

    # ---- Salary head (Form 16) ----
    gross_salary = _sum_field(extracts, "FORM-16", "gross_salary")
    basic_salary = _sum_field(extracts, "FORM-16", "basic_salary")
    hra_received = _sum_field(extracts, "FORM-16", "hra_received")
    rent_paid = _to_float(user_answers.get("annual_rent_paid", 0))
    city = (user_answers.get("city_of_residence") or "").strip()
    metro = city.lower() in {c.lower() for c in tables.get("hra", {}).get("cities_metro", [])}
    tds_salary = _sum_field(extracts, "FORM-16", "tds_deducted")

    # NR/RNOR: only India-source salary is taxable. We treat all reported
    # Form-16 entries as India-source (since they're issued by Indian employers).
    # If the user marks salary as foreign-sourced via `salary_is_foreign=yes`,
    # NR/RNOR exclude it.
    if is_nr_or_rnor and (user_answers.get("salary_is_foreign", "").lower() in {"yes", "true", "1"}):
        gross_salary = 0.0
        tds_salary = 0.0
        notes.append(f"{residency_status}: foreign-source salary excluded from India tax.")

    cfg = tables.get(f"{regime}_regime", {})
    std_deduction_salary = float(cfg.get("standard_deduction_salary", 50000)) if gross_salary > 0 else 0.0

    # HRA exemption only under old regime.
    hra_exempt = 0.0
    if regime == "old":
        hra_exempt = _hra_exemption(hra_received, basic_salary, rent_paid, metro, tables)

    income_salary = max(0.0, gross_salary - std_deduction_salary - hra_exempt)

    # ---- House Property head (24(b) home-loan interest) ----
    rental_income = _to_float(user_answers.get("annual_rental_income", 0))
    municipal_tax = _to_float(user_answers.get("municipal_tax_paid", 0))
    home_loan_interest_self = _to_float(user_answers.get("home_loan_interest_self_occupied", 0))
    home_loan_interest_let_out = _to_float(user_answers.get("home_loan_interest_let_out", 0))

    let_out_net = rental_income - municipal_tax
    let_out_net -= let_out_net * 0.30  # 30% standard deduction on NAV
    let_out_net -= home_loan_interest_let_out

    sec_24b_cap = float(tables.get("deductions", {}).get("section_24b_home_loan_self_occupied", 200000))
    if regime == "new":
        # New regime disallows section 24(b) for self-occupied property only.
        sec_24b_self_allowed = 0.0
    else:
        sec_24b_self_allowed = min(home_loan_interest_self, sec_24b_cap)
    income_house_property = let_out_net - sec_24b_self_allowed

    # ---- Capital gains ----
    cg = _capital_gains_split(extracts, user_answers, tables)
    income_other_capital_gains = 0.0  # STCG other goes into slab income via cg dict below

    # ---- Business / Profession (PGBP) — kept simple ----
    business_income = _to_float(user_answers.get("business_income_pgbp", 0))

    # ---- Other Sources ----
    bank_interest = _sum_field(extracts, "FORM-16A", "interest_income") + _sum_field(extracts, "AIS", "interest_income")
    bank_interest += _to_float(user_answers.get("bank_savings_interest", 0))
    dividends = _sum_field(extracts, "FORM-16A", "dividend_income") + _sum_field(extracts, "AIS", "dividend_income")
    dividends += _to_float(user_answers.get("dividend_income", 0))
    rental_other = 0.0  # already captured under house property
    other_income = (
        bank_interest
        + dividends
        + _to_float(user_answers.get("other_income", 0))
    )
    tds_non_salary = (
        _sum_field(extracts, "FORM-16A", "tds_deducted")
        + _sum_field(extracts, "FORM-26AS", "total_tds")
    )

    if is_nr_or_rnor:
        # NR/RNOR pays tax only on India-source income. Form-16/16A are
        # Indian-source by nature; AIS captures Indian-source too. Anything
        # the user marks via `foreign_source_other_income=<amount>` is removed.
        foreign_other = _to_float(user_answers.get("foreign_source_other_income", 0))
        other_income = max(0.0, other_income - foreign_other)
        if foreign_other > 0:
            notes.append(f"{residency_status}: excluded ₹{foreign_other:,.0f} of foreign-source income.")

    # STCG-other is taxed at slab rates (per Sec 111A).
    slab_income = (
        income_salary
        + max(0.0, income_house_property)
        + business_income
        + other_income
        + cg["stcg_other_taxed_at_slab"]
    )

    # ---- Chapter VI-A deductions (old regime only, except 80CCD(2)) ----
    deductions = tables.get("deductions", {})
    sec_80c = 0.0
    sec_80ccd_1b = 0.0
    sec_80d = 0.0
    sec_80e = 0.0
    sec_80g = 0.0
    sec_80tta_ttb = 0.0

    if regime == "old":
        # 80C — PPF, ELSS, LIC, principal home loan, EPF
        sec_80c_raw = (
            _to_float(user_answers.get("section_80c_ppf", 0))
            + _to_float(user_answers.get("section_80c_elss", 0))
            + _to_float(user_answers.get("section_80c_lic", 0))
            + _to_float(user_answers.get("section_80c_epf", 0))
            + _to_float(user_answers.get("section_80c_home_loan_principal", 0))
            + _sum_field(extracts, "INVESTMENTS-80C", "amount")
            + _sum_field(extracts, "FORM-16", "section_80c_declared")
        )
        sec_80c = min(sec_80c_raw, float(deductions.get("section_80c_cap", 150000)))

        sec_80ccd_1b = min(
            _to_float(user_answers.get("section_80ccd_1b_nps", 0)),
            float(deductions.get("section_80ccd_1b_nps_cap", 50000)),
        )

        # 80D — health insurance (self + parents, senior bumps)
        self_senior = age >= 60
        self_cap = float(deductions.get(
            "section_80d_self_senior_60_plus" if self_senior else "section_80d_self_under_60",
            25000,
        ))
        parents_senior = (user_answers.get("parents_are_seniors", "").lower() in {"yes", "true", "1"})
        parents_cap = float(deductions.get(
            "section_80d_parents_senior_60_plus" if parents_senior else "section_80d_parents_under_60",
            25000,
        ))
        sec_80d_self = min(
            _to_float(user_answers.get("section_80d_self_premium", 0))
            + _sum_field(extracts, "MEDICAL-80D", "self_premium"),
            self_cap,
        )
        sec_80d_parents = min(
            _to_float(user_answers.get("section_80d_parents_premium", 0))
            + _sum_field(extracts, "MEDICAL-80D", "parents_premium"),
            parents_cap,
        )
        sec_80d = sec_80d_self + sec_80d_parents

        # 80E — student loan interest (uncapped, only for first 8 years).
        # Cross-border guardrail handles double-claim with US/CA.
        years_since_first = _to_float(user_answers.get("years_since_first_80e", 0))
        if years_since_first <= 8:
            sec_80e = _to_float(user_answers.get("student_loan_interest_in", 0))

        sec_80g = _to_float(user_answers.get("section_80g_donations", 0)) * float(
            deductions.get("section_80g_percent_default", 0.5)
        )

        if age >= 60:
            sec_80tta_ttb = min(
                bank_interest,
                float(deductions.get("section_80ttb_senior_interest_cap", 50000)),
            )
        else:
            sec_80tta_ttb = min(
                _to_float(user_answers.get("bank_savings_interest", 0)),
                float(deductions.get("section_80tta_savings_interest_cap", 10000)),
            )

    chapter_via_total = sec_80c + sec_80ccd_1b + sec_80d + sec_80e + sec_80g + sec_80tta_ttb

    gross_total_income = slab_income
    total_income = max(0.0, gross_total_income - chapter_via_total)

    # ---- Tax computation ----
    brackets = cfg.get("brackets", []) if regime == "new" else _old_regime_brackets(age, tables)
    slab_tax = compute_progressive_tax(total_income, brackets)
    cg_tax = cg["tax_ltcg_equity"] + cg["tax_stcg_equity"] + cg["tax_ltcg_other"]
    tax_before_rebate = slab_tax + cg_tax

    # 87A rebate (with new-regime marginal relief)
    rebate_cfg = cfg.get("rebate_87a", {})
    threshold = float(rebate_cfg.get("income_threshold", 0))
    max_credit = float(rebate_cfg.get("max_credit", 0))
    rebate = 0.0
    if total_income <= threshold:
        rebate = min(tax_before_rebate, max_credit)
    elif regime == "new" and threshold > 0:
        # Marginal relief: just above the threshold the normal tax (no rebate)
        # would exceed the income earned above the threshold — the cliff. Cap
        # the slab tax payable at that excess by rebating the difference.
        # Based on slab_tax only: §87A never rebates tax on capital gains taxed
        # at special rates. Self-limiting — relief reaches 0 once the slab tax
        # no longer exceeds the excess, so higher incomes are unaffected.
        excess = total_income - threshold
        rebate = max(0.0, slab_tax - excess)
    tax_after_rebate = max(0.0, tax_before_rebate - rebate)

    # Surcharge on income tax
    surcharge = _surcharge(tax_after_rebate, total_income, tables, regime)
    tax_with_surcharge = tax_after_rebate + surcharge

    # 4% Health & Education Cess
    cess_rate = float(tables.get("cess_rate", 0.04))
    cess = round(tax_with_surcharge * cess_rate, 2)
    total_tax = round(tax_with_surcharge + cess, 2)

    total_tds = tds_salary + tds_non_salary
    balance = round(total_tax - total_tds, 2)
    refund = round(max(0.0, -balance), 2)
    owing = round(max(0.0, balance), 2)

    line_items = {
        "gross_salary": gross_salary,
        "standard_deduction_salary": std_deduction_salary,
        "hra_exemption": hra_exempt,
        "income_salary": income_salary,
        "income_house_property": income_house_property,
        "rental_income": rental_income,
        "section_24b_self_occupied": sec_24b_self_allowed,
        "business_income": business_income,
        "bank_interest": bank_interest,
        "dividends": dividends,
        "other_income_total": other_income,
        "stcg_equity_total": cg["stcg_equity_total"],
        "ltcg_equity_total": cg["ltcg_equity_total"],
        "ltcg_equity_taxable": cg["ltcg_equity_taxable"],
        "ltcg_equity_exempt": cg["ltcg_equity_exempt"],
        "stcg_other_total": cg["stcg_other_total"],
        "ltcg_other_total": cg["ltcg_other_total"],
        "tax_ltcg_equity": cg["tax_ltcg_equity"],
        "tax_stcg_equity": cg["tax_stcg_equity"],
        "tax_ltcg_other": cg["tax_ltcg_other"],
        "section_80c": sec_80c,
        "section_80ccd_1b": sec_80ccd_1b,
        "section_80d": sec_80d,
        "section_80e": sec_80e,
        "section_80g": sec_80g,
        "section_80tta_or_80ttb": sec_80tta_ttb,
        "chapter_via_total": chapter_via_total,
        "gross_total_income": gross_total_income,
        "slab_tax": slab_tax,
        "capital_gains_tax": cg_tax,
        "rebate_87a": rebate,
        "surcharge": surcharge,
        "cess": cess,
        "total_tds": total_tds,
        "regime": 1.0 if regime == "new" else 0.0,
    }

    notes.append(f"Regime: {regime}. Total income ₹{total_income:,.0f}. Total tax ₹{total_tax:,.0f}.")
    if surcharge > 0:
        notes.append(f"Surcharge ₹{surcharge:,.0f} applied (income > ₹50 lakh tier).")
    if rebate > 0:
        notes.append(f"Section 87A rebate of ₹{rebate:,.0f} applied (income ≤ rebate threshold).")
    if cg["ltcg_equity_exempt"] > 0:
        notes.append(
            f"LTCG equity ₹{cg['ltcg_equity_exempt']:,.0f} exempt under Section 112A "
            "(within annual exemption limit)."
        )

    draft = DraftReturn(
        jurisdiction="IN",
        tax_year=year,
        total_income=round(slab_income + cg["stcg_equity_total"] + cg["ltcg_equity_total"] + cg["stcg_other_total"] + cg["ltcg_other_total"], 2),
        rrsp_deduction=0.0,
        taxable_income=total_income,
        estimated_tax=total_tax,
        estimated_refund=refund,
        line_items=line_items,
        totals={
            "total_income": round(slab_income + cg["stcg_equity_total"] + cg["ltcg_equity_total"] + cg["stcg_other_total"] + cg["ltcg_other_total"], 2),
            "taxable_income": total_income,
            "total_tax": total_tax,
            "balance_owing": owing,
            "refund": refund,
        },
        credits={
            "rebate_87a": rebate,
            "standard_deduction_salary": std_deduction_salary,
            "chapter_via_deductions": chapter_via_total,
        },
        notes=notes,
    )
    return draft, line_items


def compute_in_return(
    extracts: List[FormExtract],
    year: int,
    *,
    regime: str = "auto",
    user_answers: Optional[Dict[str, str]] = None,
    residency_status: str = "ROR",
) -> DraftReturn:
    user_answers = user_answers or {}
    try:
        tables = load_tables("in", year)
    except MissingTableError as exc:
        return DraftReturn(
            jurisdiction="IN",
            tax_year=year,
            notes=[f"India tax table missing for AY {year}: {exc}"],
        )

    if regime == "auto":
        new_draft, _ = _compute_one_regime(extracts, user_answers, tables, "new", residency_status, year)
        old_draft, _ = _compute_one_regime(extracts, user_answers, tables, "old", residency_status, year)
        if new_draft.estimated_tax <= old_draft.estimated_tax:
            chosen = new_draft
            chosen.notes.insert(0, (
                f"Auto-regime: new regime ₹{new_draft.estimated_tax:,.0f} ≤ "
                f"old regime ₹{old_draft.estimated_tax:,.0f}. New regime selected."
            ))
        else:
            chosen = old_draft
            chosen.notes.insert(0, (
                f"Auto-regime: old regime ₹{old_draft.estimated_tax:,.0f} < "
                f"new regime ₹{new_draft.estimated_tax:,.0f}. Old regime selected."
            ))
        chosen.line_items["alternate_regime_tax"] = (
            old_draft.estimated_tax if chosen is new_draft else new_draft.estimated_tax
        )
        return chosen

    draft, _ = _compute_one_regime(extracts, user_answers, tables, regime, residency_status, year)
    return draft
