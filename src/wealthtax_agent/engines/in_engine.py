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
    slab_tax_after_rebate: float,
    cg_tax: float,
    total_income: float,
    tables: Dict[str, Any],
    regime: str,
) -> float:
    """Tiered surcharge on income tax (not on income directly).

    The tier rate is set by total income, but two caps apply:
    - new regime: the top tier (37%) is capped at 25%;
    - on the income-tax attributable to capital gains taxed at special rates
      (§111A / §112 / §112A), the surcharge rate is capped at 15% regardless of the
      total-income tier (a proviso in Part I of the Finance Act). So a >₹2cr / >₹5cr
      filer pays the full tier rate on slab tax but only 15% surcharge on CG tax.

    Note: surcharge marginal relief at the tier thresholds is not modelled (a
    pre-existing simplification); the 15% cap on dividend surcharge is also not
    modelled because dividends flow through the slab and are not separable here.
    """
    tiers = tables.get("surcharge", [])
    rate = 0.0
    for tier in tiers:
        if total_income > float(tier["income_above"]):
            rate = float(tier["rate"])
    if regime == "new":
        rate = min(rate, float(tables.get("surcharge_new_regime_cap", 0.25)))
    cg_rate = min(rate, float(tables.get("surcharge_capital_gains_cap", 0.15)))
    return round(slab_tax_after_rebate * rate + cg_tax * cg_rate, 2)


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
    # §112A LTCG-equity exemption is an ANNUAL amount, not one per pre/post-change
    # period. Applying it per period double-exempted taxpayers with gains both
    # sides of Jul 23 2024 (and under-exempted pre-only filers). Use a single
    # annual exemption (the year's higher amount) applied to the higher-rate
    # post-change gains first, then pre-change (taxpayer-favourable).
    annual_exemption = max(pre_threshold, post_threshold)
    exempt_post = min(ltcg_eq_post, annual_exemption)
    exempt_pre = min(ltcg_eq_pre, annual_exemption - exempt_post)
    ltcg_eq_pre_taxable = max(0.0, ltcg_eq_pre - exempt_pre)
    ltcg_eq_post_taxable = max(0.0, ltcg_eq_post - exempt_post)

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

    # HRA exemption and professional tax are only allowed under the old regime.
    hra_exempt = 0.0
    professional_tax = 0.0
    if regime == "old":
        hra_exempt = _hra_exemption(hra_received, basic_salary, rent_paid, metro, tables)
        # Professional tax actually paid is deductible from salary under §16(iii)
        # (disallowed in the new regime). Capped at ₹2,500 — the constitutional
        # ceiling (Art. 276) on the state levy itself. Prefer the amount reported
        # on Form 16, fall back to a manual user answer (the form is the primary
        # path; reading only the manual key dropped form-uploaded amounts).
        professional_tax = _sum_field(extracts, "FORM-16", "professional_tax")
        if professional_tax == 0.0:
            professional_tax = _to_float(user_answers.get("professional_tax_paid", 0))
        professional_tax = min(professional_tax, 2500.0)

    income_salary = max(0.0, gross_salary - std_deduction_salary - hra_exempt - professional_tax)

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

    # Family pension (pension to the legal heir of a deceased employee) is taxed
    # under Income from Other Sources, but §57(iia) grants a standard deduction of
    # the lower of 1/3 of the pension or a statutory cap (₹15,000 old regime;
    # ₹25,000 new regime from AY 2025-26). Crucially this is one of the few
    # deductions §115BAC does NOT disallow, so it applies under BOTH regimes —
    # only the cap value is regime-specific. Without it, family pension funnelled
    # through `other_income` is taxed in full, over-taxing widows/dependants.
    family_pension = _to_float(user_answers.get("family_pension_income", 0))
    _fp_cap = float(tables.get("deductions", {}).get(
        "section_57_family_pension_new" if regime == "new"
        else "section_57_family_pension_old",
        25000 if regime == "new" else 15000))
    family_pension_deduction = min(family_pension / 3.0, _fp_cap) if family_pension > 0 else 0.0
    family_pension_taxable = max(0.0, family_pension - family_pension_deduction)
    if family_pension_deduction > 0:
        notes.append(
            f"§57(iia) standard deduction of ₹{family_pension_deduction:,.0f} on family "
            f"pension (lower of 1/3 or ₹{_fp_cap:,.0f})."
        )

    other_income = (
        bank_interest
        + dividends
        + family_pension_taxable
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

    # A net loss from house property (commonly the self-occupied home-loan
    # interest under §24(b)) can be set off against other income only up to
    # ₹2,00,000 (§71(3A)), and only under the OLD regime — the new regime allows
    # no inter-head set-off of a house-property loss (carry-forward only, which
    # this prototype does not model). Previously max(0, ...) discarded the loss
    # entirely, dropping the very common ₹2L home-loan-interest deduction.
    house_property_loss_setoff_cap = 200000.0
    if regime == "old":
        house_property_for_slab = max(-house_property_loss_setoff_cap, income_house_property)
        if income_house_property < -house_property_loss_setoff_cap:
            notes.append(
                f"House-property loss ₹{-income_house_property:,.0f} exceeds the ₹2,00,000 "
                "inter-head set-off limit; ₹"
                f"{(-income_house_property - house_property_loss_setoff_cap):,.0f} carries forward."
            )
    else:
        house_property_for_slab = max(0.0, income_house_property)

    # STCG-other is taxed at slab rates (per Sec 111A).
    slab_income = (
        income_salary
        + house_property_for_slab
        + business_income
        + other_income
        # Short-term capital gains on non-equity assets are taxed at slab rates,
        # but a net loss there is a capital loss and must not offset salary/other
        # income (floor at zero; the loss carries forward, not modelled).
        + max(0.0, cg["stcg_other_taxed_at_slab"])
    )

    # ---- Chapter VI-A deductions (old regime only, except 80CCD(2)) ----
    deductions = tables.get("deductions", {})
    sec_80c = 0.0
    sec_80ccd_1b = 0.0
    sec_80d = 0.0
    sec_80e = 0.0
    sec_80g = 0.0
    sec_80ggc = 0.0
    sec_80tta_ttb = 0.0
    sec_80gg = 0.0
    sec_80u = 0.0
    sec_80dd = 0.0
    sec_80ddb = 0.0
    sec_80eeb = 0.0

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
        # A single declared 80D total (Form 16 / wizard) is used when no granular
        # self/parents breakdown is given. It was captured but never read — only
        # the granular keys were — so a declared health-insurance deduction was
        # dropped. Cap the combined 80D at the self+parents ceiling (mirrors the
        # 80C declared handling).
        sec_80d_declared = (
            _sum_field(extracts, "FORM-16", "section_80d_declared")
            + _to_float(user_answers.get("section_80d_declared", 0))
        )
        sec_80d = min(sec_80d_self + sec_80d_parents + sec_80d_declared, self_cap + parents_cap)

        # 80E — student loan interest (uncapped, only for first 8 years).
        # Prefer the Form-16-declared amount (captured but previously unread, so a
        # Form-16 upload silently lost the deduction), else the manual entry. This
        # also restores the cross-border single-claim guardrail, which keys on
        # line_items["section_80e"].
        years_since_first = _to_float(user_answers.get("years_since_first_80e", 0))
        if years_since_first <= 8:
            _form_80e = _sum_field(extracts, "FORM-16", "section_80e_declared")
            sec_80e = _form_80e if _form_80e > 0 else _to_float(user_answers.get("student_loan_interest_in", 0))

        sec_80g = _to_float(user_answers.get("section_80g_donations", 0)) * float(
            deductions.get("section_80g_percent_default", 0.5)
        )

        # §80GGC — donations to a registered political party / electoral trust:
        # 100% deductible, no cap, no sunset. Non-cash mode only (the engine, like
        # §80EEB's sanction window, does not verify payment mode). Unlike the
        # disability sections this is NOT resident-gated — it is available to
        # non-residents too, so it sits here (no `residency_status != "NR"` guard).
        sec_80ggc = _to_float(user_answers.get("section_80ggc_political_donation", 0)) * float(
            deductions.get("section_80ggc_percent", 1.0)
        )
        if sec_80ggc > 0:
            notes.append(
                f"§80GGC deduction of ₹{sec_80ggc:,.0f} for a non-cash donation to a "
                "registered political party / electoral trust (100%, old regime)."
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

        # 80U (own disability) / 80DD (maintenance of a disabled dependent): FLAT
        # deductions of ₹75,000 (disability ≥40%) or ₹1,25,000 (severe ≥80%),
        # independent of actual expense. Resident-only — a non-resident (NR) is
        # barred; RNOR is a resident under the Act and keeps them (gate on the literal
        # "NR", mirroring §87A). §80U and §80DD are distinct sections (self vs
        # dependent) and both claimable in the same year. Computed BEFORE §80GG so
        # they reduce its adjusted-total-income base.
        _disab = deductions.get("section_80u_80dd", {}) or {}
        _disab_normal = float(_disab.get("normal", 75000))
        _disab_severe = float(_disab.get("severe", 125000))

        def _disability_amount(flag: str) -> float:
            f = (flag or "").strip().lower()
            if f == "severe":
                return _disab_severe
            if f == "normal":
                return _disab_normal
            return 0.0

        if residency_status != "NR":
            sec_80u = _disability_amount(user_answers.get("taxpayer_disability", "none"))
            sec_80dd = _disability_amount(user_answers.get("dependent_disability", "none"))
            if sec_80u > 0:
                notes.append(f"§80U disability deduction of ₹{sec_80u:,.0f} (flat, resident taxpayer).")
            if sec_80dd > 0:
                notes.append(f"§80DD dependent-disability deduction of ₹{sec_80dd:,.0f} (flat).")
        elif (str(user_answers.get("taxpayer_disability", "none")).strip().lower() not in ("none", "")
              or str(user_answers.get("dependent_disability", "none")).strip().lower() not in ("none", "")):
            notes.append("§80U/§80DD not available to a non-resident (NR); set to ₹0.")

        # 80DDB — medical treatment of specified diseases (cancer, chronic kidney
        # failure, neurological disorders, etc.). Deduction = actual expense (net of
        # any insurance/employer reimbursement — the user enters the net) capped at
        # ₹40,000, or ₹1,00,000 when the patient is a senior citizen (60+). Old regime
        # only and resident-only (NR barred; RNOR keeps). The cap keys off the
        # taxpayer's age, mirroring the §80D self-premium cap handling.
        if residency_status != "NR":
            _ddb_cfg = deductions.get("section_80ddb", {})
            _ddb_cap = float(_ddb_cfg.get(
                "senior_60_plus" if age >= 60 else "under_60",
                100000 if age >= 60 else 40000))
            sec_80ddb = min(_to_float(user_answers.get("section_80ddb_medical", 0)), _ddb_cap)
            if sec_80ddb > 0:
                notes.append(
                    f"§80DDB deduction of ₹{sec_80ddb:,.0f} for treatment of a specified "
                    f"disease (capped at ₹{_ddb_cap:,.0f})."
                )

        # 80EEB — interest on a loan to buy an electric vehicle, capped at
        # ₹1,50,000/year. Old regime only and resident-only. (Statutorily limited to
        # loans sanctioned 1 Apr 2019 – 31 Mar 2023; that eligibility window is the
        # filer's responsibility, like other date-bounded inputs the engine doesn't
        # capture.) The deduction reduces taxable income.
        if residency_status != "NR":
            _eeb_cap = float(deductions.get("section_80eeb", {}).get("cap", 150000))
            sec_80eeb = min(_to_float(user_answers.get("section_80eeb_ev_loan_interest", 0)), _eeb_cap)
            if sec_80eeb > 0:
                notes.append(
                    f"§80EEB deduction of ₹{sec_80eeb:,.0f} for electric-vehicle loan "
                    f"interest (capped at ₹{_eeb_cap:,.0f})."
                )

        # 80GG — rent paid by a filer who receives NO HRA (self-employed, gig
        # workers, employees whose package has no HRA line). Old regime only
        # (§115BAC disallows it) and mutually exclusive with the §10(13A) HRA
        # exemption, so it is gated on hra_received == 0. Deduction = least of:
        #   (a) ₹5,000/month = ₹60,000/year,
        #   (b) 25% of adjusted total income,
        #   (c) rent paid − 10% of adjusted total income.
        # "Adjusted total income" for §80GG excludes the §80GG deduction itself and
        # special-rate capital gains; slab_income already excludes the latter (they
        # live in the `cg` dict), so slab_income net of the other Chapter VI-A
        # deductions is the correct, conservative base.
        if hra_received == 0 and rent_paid > 0:
            gg = deductions.get("section_80gg", {}) or {}
            gg_annual_cap = float(gg.get("monthly_cap", 5000)) * 12
            gg_income_pct = float(gg.get("income_pct", 0.25))
            gg_excess_pct = float(gg.get("rent_excess_pct", 0.10))
            other_via = (sec_80c + sec_80ccd_1b + sec_80d + sec_80e + sec_80g
                         + sec_80tta_ttb + sec_80u + sec_80dd + sec_80ddb + sec_80eeb)
            adj_total_income = max(0.0, slab_income - other_via)
            sec_80gg = max(0.0, min(
                gg_annual_cap,
                gg_income_pct * adj_total_income,
                rent_paid - gg_excess_pct * adj_total_income,
            ))
            if sec_80gg > 0:
                notes.append(
                    f"§80GG deduction of ₹{sec_80gg:,.0f} for rent paid with no HRA "
                    "(least of ₹60,000, 25% of income, or rent − 10% of income)."
                )

    chapter_via_total = (sec_80c + sec_80ccd_1b + sec_80d + sec_80e + sec_80g + sec_80ggc
                         + sec_80tta_ttb + sec_80gg + sec_80u + sec_80dd + sec_80ddb + sec_80eeb)

    # 80CCD(2): the employer's NPS contribution is deductible under BOTH regimes
    # (the one Chapter VI-A item not disallowed in the new regime), up to 10% of
    # salary (basic + DA; modelled as a configurable percentage of basic salary,
    # falling back to gross). Previously never implemented despite being flagged
    # as the exception, so new-regime (default) filers with employer NPS lost it.
    employer_nps = _to_float(user_answers.get("section_80ccd_2_employer_nps", 0))
    ccd2_pct = float(deductions.get("section_80ccd_2_salary_pct", 0.10))
    salary_base_for_ccd2 = basic_salary if basic_salary > 0 else gross_salary
    sec_80ccd_2 = min(employer_nps, ccd2_pct * salary_base_for_ccd2) if employer_nps > 0 else 0.0

    gross_total_income = slab_income
    total_income = max(0.0, gross_total_income - chapter_via_total - sec_80ccd_2)

    # ---- Tax computation ----
    brackets = cfg.get("brackets", []) if regime == "new" else _old_regime_brackets(age, tables)
    slab_tax = compute_progressive_tax(total_income, brackets)
    # Net the special-rate capital-gains tax across categories (a loss in one
    # offsets a gain in another), but floor the TOTAL at zero: a net capital
    # loss carries forward (not modelled) and must NOT reduce tax on salary or
    # other income (§70/§71 bar capital losses from offsetting non-capital
    # income). Without the floor a negative cg_tax illegally cut total tax.
    cg_tax = max(0.0, cg["tax_ltcg_equity"] + cg["tax_stcg_equity"] + cg["tax_ltcg_other"])
    tax_before_rebate = slab_tax + cg_tax

    # 87A rebate (with new-regime marginal relief)
    rebate_cfg = cfg.get("rebate_87a", {})
    threshold = float(rebate_cfg.get("income_threshold", 0))
    max_credit = float(rebate_cfg.get("max_credit", 0))
    rebate = 0.0
    # §87A is a resident-only relief: a non-resident (NR) is statutorily barred.
    # RNOR is a *resident* under the Act (only its foreign income is exempt), so it
    # keeps the rebate — gate on the literal "NR", NOT is_nr_or_rnor.
    is_resident_for_87a = residency_status != "NR"
    if is_resident_for_87a and total_income <= threshold:
        # §87A rebates tax on normal income only — it never offsets tax on
        # capital gains taxed at special rates (e.g. equity LTCG u/s 112A). Base
        # it on slab_tax, consistent with the marginal-relief branch below; using
        # tax_before_rebate let the rebate wrongly zero out LTCG tax for
        # low-income filers with capital gains.
        rebate = min(slab_tax, max_credit)
    elif is_resident_for_87a and regime == "new" and threshold > 0:
        # Marginal relief: just above the threshold the normal tax (no rebate)
        # would exceed the income earned above the threshold — the cliff. Cap
        # the slab tax payable at that excess by rebating the difference.
        # Based on slab_tax only: §87A never rebates tax on capital gains taxed
        # at special rates. Self-limiting — relief reaches 0 once the slab tax
        # no longer exceeds the excess, so higher incomes are unaffected.
        excess = total_income - threshold
        rebate = max(0.0, slab_tax - excess)
    if not is_resident_for_87a and total_income <= threshold:
        notes.append(
            "Section 87A rebate not available to a non-resident (NR); rebate set to ₹0."
        )
    tax_after_rebate = max(0.0, tax_before_rebate - rebate)

    # Surcharge on income tax
    # Split the surcharge base: §87A rebate only ever reduces slab tax (never CG
    # tax), so the post-rebate slab portion is slab_tax - rebate; the CG-tax portion
    # is surcharged at the capped rate inside _surcharge.
    surcharge = _surcharge(max(0.0, slab_tax - rebate), cg_tax, total_income, tables, regime)
    tax_with_surcharge = tax_after_rebate + surcharge

    # 4% Health & Education Cess
    cess_rate = float(tables.get("cess_rate", 0.04))
    cess = round(tax_with_surcharge * cess_rate, 2)
    total_tax = round(tax_with_surcharge + cess, 2)

    # Prepaid taxes (ITR Part B-TTI): TDS is joined by advance tax, self-assessment
    # tax and TCS — all credits against the liability. Crediting TDS alone made the
    # full liability show as owing for the large population (business / capital-gains
    # / professional) that pays advance tax. §234B/§234C interest on any advance-tax
    # shortfall is a separate liability-side computation and is not modelled here.
    # Advance tax: prefer the amount reported on an uploaded Form 26AS (captured but
    # previously unread, so a 26AS upload left advance tax uncredited and overstated
    # the balance owing), else the manual entry. Fallback, not a sum — no double-count.
    _form_advance = _sum_field(extracts, "FORM-26AS", "advance_tax_paid")
    advance_tax = _form_advance if _form_advance > 0 else _to_float(user_answers.get("advance_tax_paid", 0))
    self_assessment_tax = _to_float(user_answers.get("self_assessment_tax_paid", 0))
    tcs = _to_float(user_answers.get("tcs_collected", 0))
    total_tds = tds_salary + tds_non_salary
    total_taxes_paid = round(total_tds + advance_tax + self_assessment_tax + tcs, 2)
    balance = round(total_tax - total_taxes_paid, 2)
    refund = round(max(0.0, -balance), 2)
    owing = round(max(0.0, balance), 2)
    if advance_tax + self_assessment_tax > 0:
        notes.append(
            f"Credited prepaid taxes ₹{total_taxes_paid:,.0f} (TDS ₹{total_tds:,.0f} + advance "
            f"₹{advance_tax:,.0f} + self-assessment ₹{self_assessment_tax:,.0f} + TCS ₹{tcs:,.0f}); "
            f"§234B/§234C interest on any shortfall is not computed."
        )

    line_items = {
        "gross_salary": gross_salary,
        "standard_deduction_salary": std_deduction_salary,
        "hra_exemption": hra_exempt,
        "professional_tax_deduction": professional_tax,
        "income_salary": income_salary,
        "income_house_property": income_house_property,
        "rental_income": rental_income,
        "section_24b_self_occupied": sec_24b_self_allowed,
        "business_income": business_income,
        "bank_interest": bank_interest,
        "dividends": dividends,
        "family_pension": family_pension,
        "family_pension_deduction": family_pension_deduction,
        "family_pension_taxable": family_pension_taxable,
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
        "section_80ccd_2_employer_nps": sec_80ccd_2,
        "section_80d": sec_80d,
        "section_80e": sec_80e,
        "section_80g": sec_80g,
        "section_80ggc": sec_80ggc,
        "section_80tta_or_80ttb": sec_80tta_ttb,
        "section_80gg": sec_80gg,
        "section_80u": sec_80u,
        "section_80dd": sec_80dd,
        "section_80ddb": sec_80ddb,
        "section_80eeb": sec_80eeb,
        "chapter_via_total": chapter_via_total,
        "gross_total_income": gross_total_income,
        "slab_tax": slab_tax,
        "capital_gains_tax": cg_tax,
        "rebate_87a": rebate,
        "surcharge": surcharge,
        "cess": cess,
        "total_tds": total_tds,
        "advance_tax": advance_tax,
        "self_assessment_tax": self_assessment_tax,
        "tcs": tcs,
        "total_taxes_paid": total_taxes_paid,
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
            "total_taxes_paid": total_taxes_paid,
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
