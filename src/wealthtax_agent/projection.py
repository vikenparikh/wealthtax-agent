"""Multi-year tax projection.

Given the current year's ``DraftReturn`` and (optionally) a growth rate, project
the next 5 years' tax owed. Uses the engines for each future year so the
projection respects real bracket creep / inflation tables.

This is illustrative — it assumes the same income mix repeats annually with
the supplied growth, and the same user_answers. Useful as a planning view.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

from wealthtax_agent.config.tax_tables import MissingTableError, load_tables
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract, GraphState


def _grow_extracts(extracts: List[FormExtract], growth: float) -> List[FormExtract]:
    grown: List[FormExtract] = []
    for e in extracts:
        bumped = deepcopy(e)
        bumped.fields = {k: round(v * (1 + growth), 2) for k, v in e.fields.items()}
        grown.append(bumped)
    return grown


def project_future_years(
    state: GraphState,
    growth: float = 0.03,
    horizon: int = 5,
) -> Dict[str, List[Dict[str, Any]]]:
    """Project income + tax for each jurisdiction.

    Returns ``{jurisdiction: [{year, total_income, taxable_income, total_tax, refund, balance_owing}]}``.
    """
    base_year = state.filing_year or 2024
    province = (state.user_answers.get("province_of_residence") or "ON").upper()
    state_code = (state.user_answers.get("state_of_residence") or "CA").upper()
    out: Dict[str, List[Dict[str, Any]]] = {}

    for jurisdiction in state.draft_returns:
        rows: List[Dict[str, Any]] = []
        extracts = [e for e in state.extracts if e.jurisdiction == jurisdiction]
        for step in range(1, horizon + 1):
            year = base_year + step
            grown = _grow_extracts(extracts, growth * step)
            try:
                if jurisdiction == "CA":
                    draft = compute_ca_return(grown, year=year, province=province, user_answers=state.user_answers)
                else:
                    draft = compute_us_return(grown, year=year, state=state_code, user_answers=state.user_answers)
            except MissingTableError:
                # No table for that year yet — reuse the most recent year by
                # falling back to current-year tables and noting it.
                if jurisdiction == "CA":
                    draft = compute_ca_return(grown, year=base_year, province=province, user_answers=state.user_answers)
                else:
                    draft = compute_us_return(grown, year=base_year, state=state_code, user_answers=state.user_answers)
            rows.append({
                "year": year,
                "growth_pct": round(growth * step * 100, 1),
                "total_income": draft.totals.get("total_income", 0.0),
                "taxable_income": draft.totals.get("taxable_income", 0.0),
                "total_tax": draft.totals.get("total_tax", 0.0),
                "refund": draft.totals.get("refund", 0.0),
                "balance_owing": draft.totals.get("balance_owing", 0.0),
            })
        out[jurisdiction] = rows
    return out


def fallback_table_years_available(jurisdiction: str) -> List[int]:
    """Probe the tax_tables directory and return the years we have data for."""
    from wealthtax_agent.config.tax_tables import available_years
    return available_years(jurisdiction)
