"""Dispatch tax reasoning to the correct engine for each selected jurisdiction.

If no jurisdiction was explicitly chosen we fall back to the legacy CA-only
path so older tests/UI flows keep working unchanged.
"""

from __future__ import annotations

from typing import List

from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import DraftReturn, FormExtract, GraphState, Slip


def _legacy_extracts_from_slips(slips: List[Slip]) -> List[FormExtract]:
    out: List[FormExtract] = []
    for slip in slips:
        out.append(FormExtract(
            form_code=slip.type.upper(),
            jurisdiction="CA",
            fields=slip.fields,
        ))
    return out


def _legacy_ca_flat_return(state: GraphState) -> DraftReturn:
    """Replicate the original prototype's flat-25% logic for old tests."""
    total_income = 0.0
    rrsp_contribs = 0.0
    for slip in state.slips:
        fields = slip.fields
        if slip.type.upper() == "T4":
            total_income += fields.get("employment_income", 0.0)
        elif slip.type.upper() == "T5":
            total_income += fields.get("interest_income", 0.0)
            total_income += fields.get("dividends", 0.0)
        elif slip.type.upper() == "RRSP":
            rrsp_contribs += fields.get("rrsp_contributions", 0.0)

    taxable = max(total_income - rrsp_contribs, 0.0)
    estimated_tax = taxable * 0.25
    return DraftReturn(
        jurisdiction="CA",
        total_income=total_income,
        rrsp_deduction=rrsp_contribs,
        taxable_income=taxable,
        estimated_tax=estimated_tax,
        estimated_refund=0.0,
    )


def reason_tax_node(state: GraphState) -> GraphState:
    jurisdictions = list(state.jurisdictions)
    extracts = list(state.extracts)
    year = state.filing_year or 2024

    # Legacy compatibility: if jurisdictions weren't set, reproduce the
    # original flat-rate CA behavior so existing unit tests keep passing.
    if not jurisdictions:
        if extracts:
            jurisdictions = sorted({e.jurisdiction for e in extracts})
        else:
            state.draft_return = _legacy_ca_flat_return(state)
            return state

    drafts = {}
    province = (state.user_answers.get("province_of_residence") or "ON").upper()
    state_code = (state.user_answers.get("state_of_residence") or "CA").upper()

    if "CA" in jurisdictions:
        ca_extracts = [e for e in extracts if e.jurisdiction == "CA"]
        if not ca_extracts and state.slips:
            ca_extracts = _legacy_extracts_from_slips(state.slips)
        drafts["CA"] = compute_ca_return(ca_extracts, year=year, province=province, user_answers=state.user_answers)

    if "US" in jurisdictions:
        us_extracts = [e for e in extracts if e.jurisdiction == "US"]
        drafts["US"] = compute_us_return(
            us_extracts,
            year=year,
            state=state_code,
            user_answers=state.user_answers,
        )

    # Cross-border warning
    if len(drafts) > 1 or state.user_answers.get("is_us_person", "").lower() in {"yes", "true", "1"}:
        state.warnings.append(
            "Cross-border situation detected (multiple jurisdictions or US-person status). "
            "Foreign tax credits and treaty positions are NOT modelled in v1."
        )

    state.draft_returns = drafts
    # Surface a single 'draft_return' for backwards compatibility with the UI.
    # Prefer CA when both exist (older UI was CA-only).
    state.draft_return = drafts.get("CA") or drafts.get("US")
    return state
