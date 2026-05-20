"""Residency-test engine. Pure functions, no LLM, no I/O.

Each function returns the residency classification one tax authority would
assign based on physical-presence inputs alone. ``recommend_residency`` ties
them together and surfaces treaty tie-breaker notes when more than one
jurisdiction would call the taxpayer a resident.

Inputs are integer days; outputs are short strings the engines understand:

  - US:    "resident" | "nonresident" | "dual_status"
  - CA:    "resident" | "part_year_resident" | "non_resident"
  - IN:    "ROR" | "RNOR" | "NR"
"""

from __future__ import annotations

from typing import Dict, List, Optional


# ---------- United States ----------

def us_substantial_presence(
    days_current: int,
    days_prior_1: int = 0,
    days_prior_2: int = 0,
) -> bool:
    """IRS Substantial Presence Test.

    Test passes when: at least 31 days in current year AND
    (current + 1/3 * prior_1 + 1/6 * prior_2) >= 183.
    """
    if days_current < 31:
        return False
    weighted = days_current + (days_prior_1 / 3.0) + (days_prior_2 / 6.0)
    return weighted >= 183


def us_residency(
    days_current: int,
    days_prior_1: int = 0,
    days_prior_2: int = 0,
    *,
    is_us_citizen: bool = False,
    is_green_card: bool = False,
    moved_in_or_out: bool = False,
) -> str:
    """Decide whether the taxpayer is a US resident for the year."""
    if is_us_citizen or is_green_card:
        return "resident"
    spt = us_substantial_presence(days_current, days_prior_1, days_prior_2)
    if spt and moved_in_or_out:
        return "dual_status"
    return "resident" if spt else "nonresident"


# ---------- Canada ----------

def ca_residency(
    days_current: int,
    *,
    has_primary_ties: bool = False,
    moved_in_or_out: bool = False,
) -> str:
    """Simplified Canadian residency test.

    Primary residential ties (home in Canada, spouse, dependants) make you a
    factual resident regardless of day count. Otherwise the 183-day rule
    triggers deemed residency. A taxpayer who moves part-way through the year
    is a part-year resident.
    """
    if has_primary_ties:
        return "part_year_resident" if moved_in_or_out else "resident"
    if days_current >= 183:
        return "resident"
    return "non_resident"


# ---------- India ----------

def india_residency(
    days_current: int,
    days_prior_4_total: int = 0,
    *,
    days_prior_7_resident_years: int = 0,
    indian_income_above_15l: bool = False,
    is_indian_citizen: bool = False,
) -> str:
    """India Section 6 residency.

    Resident if (a) >= 182 days in India in the current year, OR
    (b) >= 60 days current + >= 365 days across the last 4 years.
    The 60-day threshold is relaxed to 182 days for Indian citizens leaving
    for employment or NRIs visiting India when Indian income <= 15 lakh.
    A resident is also "Resident Ordinarily Resident" (ROR) if she has been
    resident in at least 2 of the last 10 years AND present >= 730 days in
    the last 7 years. Otherwise she is RNOR (Resident but Not Ordinarily Resident).
    """
    threshold_60 = 60
    # NRI visiting India with Indian income <= 15L gets a relaxed 182-day rule.
    if is_indian_citizen and not indian_income_above_15l:
        threshold_60 = 182

    is_resident = days_current >= 182 or (
        days_current >= threshold_60 and days_prior_4_total >= 365
    )
    if not is_resident:
        # Deemed residency for Indian citizens earning > ₹15L with no other-country tax
        if is_indian_citizen and indian_income_above_15l and days_current < 182:
            return "RNOR"  # Section 6(1A) deemed residency is always RNOR
        return "NR"

    # Ordinary vs not ordinary
    is_ror = days_prior_7_resident_years >= 730
    return "ROR" if is_ror else "RNOR"


# ---------- Orchestrator ----------

_TREATY_HINTS = {
    ("US", "CA"): (
        "US-Canada tax treaty Article IV tie-breaker: where both countries "
        "claim residency, treaty defines residency by (1) permanent home, "
        "(2) center of vital interests, (3) habitual abode, (4) citizenship."
    ),
    ("US", "IN"): (
        "US-India tax treaty Article 4 tie-breaker: where both countries "
        "claim residency, treaty defines residency by (1) permanent home, "
        "(2) center of vital interests, (3) habitual abode, (4) nationality."
    ),
    ("CA", "IN"): (
        "Canada-India tax treaty Article 4 tie-breaker: where both countries "
        "claim residency, treaty defines residency by (1) permanent home, "
        "(2) center of vital interests, (3) habitual abode, (4) nationality."
    ),
}


def _is_resident_like(status: str) -> bool:
    return status in {"resident", "part_year_resident", "dual_status", "ROR", "RNOR"}


def recommend_residency(
    days_by_country: Dict[str, int],
    *,
    prior_year_days: Optional[Dict[str, Dict[str, int]]] = None,
    user_answers: Optional[Dict[str, str]] = None,
) -> Dict[str, object]:
    """Compute per-jurisdiction residency status and treaty tie-breaker hints.

    Args:
      days_by_country: e.g. ``{"US": 150, "CA": 200, "IN": 15}``.
      prior_year_days: optional ``{"US": {"prior_1": 100, "prior_2": 80}, ...}``.
      user_answers: clarifying answers (used to read flags like
        ``is_us_citizen``, ``has_primary_ties_ca``, ``is_indian_citizen``,
        ``moved_country_during_year``).

    Returns ``{"status": {country: status}, "notes": [str, ...]}``.
    """
    prior = prior_year_days or {}
    ua = {k: str(v).strip().lower() for k, v in (user_answers or {}).items()}

    def _yes(key: str) -> bool:
        return ua.get(key, "") in {"yes", "true", "1", "y"}

    statuses: Dict[str, str] = {}
    notes: List[str] = []

    if "US" in days_by_country:
        days = int(days_by_country.get("US", 0))
        prior_us = prior.get("US", {})
        statuses["US"] = us_residency(
            days,
            int(prior_us.get("prior_1", 0)),
            int(prior_us.get("prior_2", 0)),
            is_us_citizen=_yes("is_us_citizen"),
            is_green_card=_yes("is_green_card_holder"),
            moved_in_or_out=_yes("moved_country_during_year"),
        )
        weighted = days + int(prior_us.get("prior_1", 0)) / 3.0 + int(prior_us.get("prior_2", 0)) / 6.0
        if 170 <= weighted < 190:
            notes.append(
                f"US Substantial Presence weighted days {weighted:.1f} is within ±10 of the 183 threshold; "
                "verify with a tax professional before taking a position."
            )

    if "CA" in days_by_country:
        statuses["CA"] = ca_residency(
            int(days_by_country.get("CA", 0)),
            has_primary_ties=_yes("has_primary_ties_ca"),
            moved_in_or_out=_yes("moved_country_during_year"),
        )

    if "IN" in days_by_country:
        days = int(days_by_country.get("IN", 0))
        prior_in = prior.get("IN", {})
        statuses["IN"] = india_residency(
            days,
            int(prior_in.get("prior_4_total", 0)),
            days_prior_7_resident_years=int(prior_in.get("prior_7_days", 0)),
            indian_income_above_15l=_yes("indian_income_above_15l"),
            is_indian_citizen=_yes("is_indian_citizen"),
        )
        if 55 <= days <= 65 or 175 <= days <= 189:
            notes.append(
                f"India residency: {days} days is close to a Section 6 threshold; "
                "verify the day count with travel records."
            )

    resident_jurisdictions = [j for j, s in statuses.items() if _is_resident_like(s)]
    if len(resident_jurisdictions) >= 2:
        for i in range(len(resident_jurisdictions)):
            for j in range(i + 1, len(resident_jurisdictions)):
                pair = tuple(sorted([resident_jurisdictions[i], resident_jurisdictions[j]]))
                hint = _TREATY_HINTS.get(pair) or _TREATY_HINTS.get(pair[::-1])
                if hint:
                    notes.append(hint)

    return {"status": statuses, "notes": notes}


def residency_test_node(state):
    """Graph node: read ``state.residency_days``, write ``state.residency_status``."""
    if not state.residency_days:
        return state

    prior: Dict[str, Dict[str, int]] = {}
    for country in ("US", "CA", "IN"):
        per_country: Dict[str, int] = {}
        for k, v in state.user_answers.items():
            prefix = f"prior_year_days_{country.lower()}_"
            if k.startswith(prefix):
                suffix = k[len(prefix):]
                try:
                    per_country[suffix] = int(str(v).replace(",", "").strip() or 0)
                except ValueError:
                    continue
        if per_country:
            prior[country] = per_country

    result = recommend_residency(
        state.residency_days,
        prior_year_days=prior,
        user_answers=state.user_answers,
    )
    state.residency_status = result["status"]  # type: ignore[assignment]
    state.residency_notes = result["notes"]  # type: ignore[assignment]
    for note in result["notes"]:  # type: ignore[union-attr]
        if note not in state.warnings:
            state.warnings.append(note)
    return state
