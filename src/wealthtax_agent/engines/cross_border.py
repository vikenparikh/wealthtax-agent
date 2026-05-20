"""Cross-border guardrails: detect and resolve income claimed in two countries.

Two situations matter for v1:

1. **Student-loan interest** (US 1098-E, CA line 31900, IN Section 80E). The
   same loan can only be claimed in one jurisdiction. ``enforce_single_student_loan``
   picks the jurisdiction with the highest marginal rate, zeros out the
   other(s), and emits a warning.

2. **Same wages reported in multiple jurisdictions** (W-2 income that also
   appears on a Canadian T1 because the taxpayer was a Canadian resident).
   ``foreign_tax_credit_hint`` computes an FTC suggestion (NOT a binding
   number) so the user knows roughly how much double-tax relief to expect.

3. **Equity comp sourcing**: ``rsu_sourcing_split`` allocates an RSU vest's
   income between the grant and vest jurisdictions based on workdays.

Pure functions, no LLM, no I/O. The engines call these helpers via the
graph wiring in ``reason_tax.py``.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from wealthtax_agent.state import DraftReturn, GraphState


def _highest_marginal_jurisdiction(
    drafts: Dict[str, DraftReturn],
    user_answers: Dict[str, str],
) -> str:
    """Pick the jurisdiction whose marginal rate on the next $1 is highest.

    Approximation: use ``total_tax / taxable_income`` as a proxy when no
    explicit marginal field is available. Falls back to a fixed preference
    order if neither has computed tax.
    """
    preference = ["US", "CA", "IN"]
    best = (-1.0, "US")
    for jurisdiction in preference:
        draft = drafts.get(jurisdiction)
        if not draft:
            continue
        taxable = float(draft.totals.get("taxable_income", 0.0) or 0.0)
        total_tax = float(draft.totals.get("total_tax", 0.0) or 0.0)
        if taxable <= 0:
            continue
        rate = total_tax / taxable
        if rate > best[0]:
            best = (rate, jurisdiction)
    if best[0] < 0:
        for jurisdiction in preference:
            if jurisdiction in drafts:
                return jurisdiction
    return best[1]


def enforce_single_student_loan(state: GraphState) -> List[str]:
    """If student-loan interest was claimed in >1 jurisdiction, keep the best.

    Returns a list of warnings appended to the state.
    """
    drafts = state.draft_returns or {}
    claimed: Dict[str, float] = {}
    for jurisdiction, draft in drafts.items():
        amt = 0.0
        if jurisdiction == "US":
            amt = float(draft.line_items.get("student_loan_interest_deduction", 0.0) or 0.0)
        elif jurisdiction == "CA":
            amt = float(draft.line_items.get("student_loan_interest_ca", 0.0) or 0.0)
        elif jurisdiction == "IN":
            amt = float(draft.line_items.get("section_80e", 0.0) or 0.0)
        if amt > 0:
            claimed[jurisdiction] = amt

    if len(claimed) <= 1:
        return []

    keep = _highest_marginal_jurisdiction(
        {j: drafts[j] for j in claimed}, state.user_answers
    )
    warnings: List[str] = []
    for jurisdiction in claimed:
        if jurisdiction == keep:
            continue
        draft = drafts[jurisdiction]
        if jurisdiction == "US":
            zeroed = float(draft.line_items.get("student_loan_interest_deduction", 0.0))
            draft.line_items["student_loan_interest_deduction"] = 0.0
        elif jurisdiction == "CA":
            zeroed = float(draft.line_items.get("student_loan_interest_ca", 0.0))
            draft.line_items["student_loan_interest_ca"] = 0.0
        elif jurisdiction == "IN":
            zeroed = float(draft.line_items.get("section_80e", 0.0))
            draft.line_items["section_80e"] = 0.0
        else:
            zeroed = 0.0
        warnings.append(
            f"Cross-border: student-loan interest of ${zeroed:,.2f} cannot be claimed in "
            f"both {jurisdiction} and {keep}. Removed from {jurisdiction} (lower marginal). "
            "Re-run the engine to recompute that draft if you want the tax recomputed."
        )
    return warnings


def foreign_tax_credit_hint(state: GraphState) -> List[str]:
    """Add an informational FTC hint when same income is taxed in two places."""
    drafts = state.draft_returns or {}
    if len(drafts) < 2:
        return []

    notes: List[str] = []
    # Pairwise FTC hints — order: resident country credits the source-country tax.
    for resident in drafts:
        for source in drafts:
            if resident == source:
                continue
            # If resident is "resident" and source is "nonresident", credit flows.
            resident_status = state.residency_status.get(resident, "")
            source_status = state.residency_status.get(source, "")
            if resident_status in {"resident", "part_year_resident", "ROR", "RNOR"} and source_status in {
                "nonresident", "non_resident", "NR", "dual_status",
            }:
                source_tax = float(drafts[source].totals.get("total_tax", 0.0) or 0.0)
                if source_tax > 0:
                    notes.append(
                        f"Foreign tax credit hint: {resident} resident may credit up to "
                        f"${source_tax:,.2f} of {source} tax paid (Form 1116 / T2209 / "
                        "Schedule TR equivalent). Engine does not currently apply FTC "
                        "automatically — adjust manually before filing."
                    )
    return notes


def rsu_sourcing_split(
    total_vest_value: float,
    workdays_us: int,
    workdays_ca: int,
    workdays_in: int = 0,
) -> Dict[str, float]:
    """Allocate one RSU vest's income across countries by workdays.

    Mirrors IRS Rev. Proc. 2008-23 and CRA Income Tax Folio S5-F2-C1 sourcing.
    """
    total_days = workdays_us + workdays_ca + workdays_in
    if total_days <= 0 or total_vest_value <= 0:
        return {"US": 0.0, "CA": 0.0, "IN": 0.0}
    return {
        "US": round(total_vest_value * workdays_us / total_days, 2),
        "CA": round(total_vest_value * workdays_ca / total_days, 2),
        "IN": round(total_vest_value * workdays_in / total_days, 2),
    }


def cross_border_node(state: GraphState) -> GraphState:
    """Graph node: apply cross-border guardrails after all engines have run."""
    if not state.draft_returns:
        return state
    for warning in enforce_single_student_loan(state):
        if warning not in state.warnings:
            state.warnings.append(warning)
    for note in foreign_tax_credit_hint(state):
        if note not in state.warnings:
            state.warnings.append(note)
    return state
