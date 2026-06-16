"""Serialize the IN draft into an ITR-shaped JSON envelope.

This is a planning artifact only — stamped ``transmissible=false``. The
shape mirrors the top-level sections of the official ITR schema so users
can hand-fill the official form or feed it into third-party software.
"""

from __future__ import annotations

from typing import Any, Dict, List

from wealthtax_agent.state import DraftReturn, FormExtract


def serialize_itr(
    draft: DraftReturn,
    extracts: List[FormExtract],
    year: int,
    regime: str = "auto",
) -> Dict[str, Any]:
    li = draft.line_items or {}
    totals = draft.totals or {}

    def _f(key: str) -> float:
        return float(li.get(key, 0.0) or 0.0)

    payload: Dict[str, Any] = {
        "ITR": {
            "ITR1_or_2": "ITR-2",  # Picked when capital gains / multi-source
            "PartA_GEN": {
                "AssessmentYear": year,
                "Regime": "New" if li.get("regime", 0) == 1.0 else "Old",
                "FilingType": "Original",
            },
            "ScheduleS_Salary": {
                "GrossSalary": _f("gross_salary"),
                "StandardDeduction": _f("standard_deduction_salary"),
                "HRA_Exemption": _f("hra_exemption"),
                "IncomeFromSalary": _f("income_salary"),
            },
            "ScheduleHP_HouseProperty": {
                "RentalIncome": _f("rental_income"),
                "Section24bSelfOccupied": _f("section_24b_self_occupied"),
                "NetIncome": _f("income_house_property"),
            },
            # Profits & Gains of Business or Profession (PGBP). The engine folds
            # business_income into slab_income (and thus taxable_income), but the ITR
            # had no Business schedule — so the income was invisible in the artifact
            # even though it was taxed. Placed between House Property and Capital Gains
            # to match the ITR head ordering.
            "ScheduleBP_Business": {
                "NetIncome": _f("business_income"),
            },
            "ScheduleCG_CapitalGains": {
                "STCGEquityTotal": _f("stcg_equity_total"),
                "LTCGEquityTotal": _f("ltcg_equity_total"),
                "LTCGEquityTaxable": _f("ltcg_equity_taxable"),
                "LTCGEquityExempt": _f("ltcg_equity_exempt"),
                "STCGOtherTotal": _f("stcg_other_total"),
                "LTCGOtherTotal": _f("ltcg_other_total"),
                "TaxLTCGEquity": _f("tax_ltcg_equity"),
                "TaxSTCGEquity": _f("tax_stcg_equity"),
                "TaxLTCGOther": _f("tax_ltcg_other"),
            },
            "ScheduleOS_OtherSources": {
                "BankInterest": _f("bank_interest"),
                "Dividends": _f("dividends"),
                "OtherIncomeTotal": _f("other_income_total"),
            },
            "ScheduleVIA_Deductions": {
                "Section80C": _f("section_80c"),
                "Section80CCD1B": _f("section_80ccd_1b"),
                # §80CCD(2) employer-NPS is the one Chapter VI-A item allowed in the
                # NEW regime; the engine computes it and nets it from total income
                # (in_engine: total_income = gross - chapter_via_total - sec_80ccd_2),
                # but it was excluded from chapter_via_total. Surface it and fold it
                # into TotalChapterVIA so GrossTotalIncome - TotalChapterVIA
                # reconciles with TotalIncome (otherwise the artifact under-reports
                # the deduction the engine already applied).
                "Section80CCD2_EmployerNPS": _f("section_80ccd_2_employer_nps"),
                "Section80D": _f("section_80d"),
                "Section80E": _f("section_80e"),
                "Section80G": _f("section_80g"),
                "Section80TTAor80TTB": _f("section_80tta_or_80ttb"),
                # §80U (self disability), §80DD (dependant disability), §80DDB
                # (specified-disease treatment), §80EEB (EV-loan interest) and
                # §80GG (no-HRA rent) are computed by the engine and ALREADY folded
                # into chapter_via_total, but were never serialized — so the draft
                # ITR's ScheduleVIA hid the per-section attribution a hand-filer
                # needs. Surface them as display rows only; do NOT add them to
                # TotalChapterVIA (the total already counts them — adding here would
                # double-count, unlike §80CCD(2) which was excluded from the total).
                "Section80U": _f("section_80u"),
                "Section80DD": _f("section_80dd"),
                "Section80DDB": _f("section_80ddb"),
                "Section80EEB": _f("section_80eeb"),
                "Section80GG": _f("section_80gg"),
                # §80GGC (political-party donation) is already in chapter_via_total,
                # so surface it as a display row only — do NOT add it to
                # TotalChapterVIA (would double-count, same rule as §80GG/§80U above).
                "Section80GGC": _f("section_80ggc"),
                "TotalChapterVIA": _f("chapter_via_total") + _f("section_80ccd_2_employer_nps"),
            },
            "PartB_TI": {
                "GrossTotalIncome": _f("gross_total_income"),
                "TotalIncome": float(totals.get("taxable_income", 0.0)),
            },
            "PartB_TTI": {
                "SlabTax": _f("slab_tax"),
                "CapitalGainsTax": _f("capital_gains_tax"),
                "Rebate87A": _f("rebate_87a"),
                "Surcharge": _f("surcharge"),
                "Cess": _f("cess"),
                "TotalTax": float(totals.get("total_tax", 0.0)),
                "TotalTDS": _f("total_tds"),
                "TCS": _f("tcs"),
                "AdvanceTax": _f("advance_tax"),
                "SelfAssessmentTax": _f("self_assessment_tax"),
                "TotalTaxesPaid": _f("total_taxes_paid"),
                "Refund": float(totals.get("refund", 0.0)),
                "BalanceOwing": float(totals.get("balance_owing", 0.0)),
            },
            "AttachedSources": [
                {"form_code": e.form_code, "source_filename": e.source_filename}
                for e in extracts
                if e.jurisdiction == "IN"
            ],
        },
        "transmissible": False,
        "note": "Draft ITR envelope. Not submitted to incometax.gov.in.",
        "schema_version": "in-itr-0.1",
    }
    return payload
