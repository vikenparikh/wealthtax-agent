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
                "Section80D": _f("section_80d"),
                "Section80E": _f("section_80e"),
                "Section80G": _f("section_80g"),
                "Section80TTAor80TTB": _f("section_80tta_or_80ttb"),
                "TotalChapterVIA": _f("chapter_via_total"),
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
