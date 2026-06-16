"""Serialize the US/CA draft into a California Form 540 state-tax JSON envelope.

Planning artifact only — stamped ``transmissible=False``. NOT FTB e-file
certified and never transmitted. This completes the federal-only 1040 refactor
(the federal 1040 deliberately excludes state income tax; the state tax belongs
on this artifact).

Scope: California only (the only state with a non-trivial income tax among the
engine's state tables). The engine computes ``state_tax`` /
``state_taxable_income`` / ``state_standard_deduction`` from AGI; state tax
withheld is summed here from W-2 box 17 (``state_income_tax``), and the state
balance owing / refund is ``state_tax − state_withheld``.
"""

from __future__ import annotations

from typing import Any, Dict, List

from wealthtax_agent.state import DraftReturn, FormExtract

SCHEMA_VERSION = "ca540-0.1-draft"


def _sum_w2_state_tax(extracts: List[FormExtract]) -> float:
    """Sum W-2 box 17 (state income tax withheld) across US W-2 slips."""
    return round(
        sum(
            float(e.fields.get("state_income_tax", 0.0) or 0.0)
            for e in extracts
            if e.form_code == "W-2" and e.jurisdiction == "US"
        ),
        2,
    )


def serialize_ca540(draft: DraftReturn, extracts: List[FormExtract], year: int,
                    user_answers: Dict[str, str] | None = None) -> Dict[str, Any]:
    user_answers = user_answers or {}
    li = draft.line_items or {}

    def _f(key: str) -> float:
        return float(li.get(key, 0.0) or 0.0)

    state_tax = _f("state_tax")
    state_withheld = _sum_w2_state_tax(extracts)
    balance = round(state_tax - state_withheld, 2)

    return {
        "transmissible": False,
        "schema_version": SCHEMA_VERSION,
        "note": "Prototype DRAFT only. NOT FTB e-file certified. Not transmitted to the California FTB.",
        "ReturnHeader": {
            "TaxYear": year,
            "FilingStatus": user_answers.get("filing_status", "single"),
            "StateOfResidence": user_answers.get("state_of_residence", ""),
        },
        "CA540": {
            "agi_from_federal": _f("agi"),
            "state_standard_deduction": _f("state_standard_deduction"),
            "state_taxable_income": _f("state_taxable_income"),
            "state_tax": state_tax,
            "state_tax_withheld": state_withheld,
            "total_tax": state_tax,
            "amount_you_owe": round(max(0.0, balance), 2),
            "refund": round(max(0.0, -balance), 2),
        },
        "Slips": [
            {
                "form_code": e.form_code,
                "source": e.source_filename,
                "state_income_tax": float(e.fields.get("state_income_tax", 0.0) or 0.0),
            }
            for e in extracts
            if e.jurisdiction == "US"
        ],
    }
