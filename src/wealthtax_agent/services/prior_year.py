"""P2-AC4 — multi-year carry-forward defaults.

When a user opens a new tax return, step 3 of the wizard (income sources)
pre-fills three carry-forward fields from the previous year's saved return:

  - ``rrsp_room``                — Canadian RRSP contribution room remaining
  - ``capital_loss_carryforward``— net capital losses carried forward
  - ``foreign_tax_credits``      — unused foreign tax credit balance

The pre-fill is *non-destructive*: any field the user has already typed in the
current wizard wins over the prior-year default.

Contract enforced by ``tests/unit/test_multi_year_carry_forward.py``::

    defaults = load_prior_year_defaults(user_id, year - 1)
    # defaults["rrsp_room"], defaults["capital_loss_carryforward"],
    # defaults["foreign_tax_credits"] all present (0.0 when missing)
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..db import get_session
from ..db.models import TaxReturn


# Canonical fields P2-AC4 requires to be present in the returned dict.
CARRY_FORWARD_KEYS: tuple[str, ...] = (
    "rrsp_room",
    "capital_loss_carryforward",
    "foreign_tax_credits",
)


def _coerce_float(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _extract_from_fields(fields: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """Pull the three carry-forward values out of a TaxReturn.fields dict.

    The dict may store them at the top level *or* nested under
    ``wizard_data`` / ``user_answers`` — we check all known locations and
    take the first non-empty hit per key.
    """
    out: Dict[str, float] = {key: 0.0 for key in CARRY_FORWARD_KEYS}
    if not fields:
        return out

    search_scopes: list[Dict[str, Any]] = [fields]
    wizard_data = fields.get("wizard_data") if isinstance(fields, dict) else None
    if isinstance(wizard_data, dict):
        search_scopes.append(wizard_data)
    user_answers = fields.get("user_answers") if isinstance(fields, dict) else None
    if isinstance(user_answers, dict):
        search_scopes.append(user_answers)

    # Map of canonical key → alternate spellings we accept from older data.
    aliases: Dict[str, tuple[str, ...]] = {
        "rrsp_room": ("rrsp_room", "rrsp_room_remaining", "rrsp_contribution_room"),
        "capital_loss_carryforward": (
            "capital_loss_carryforward",
            "capital_loss_carry_forward",
            "net_capital_loss_carryforward",
        ),
        "foreign_tax_credits": (
            "foreign_tax_credits",
            "foreign_tax_credit",
            "ftc_carryforward",
            "ftc_balance",
        ),
    }

    for canonical, names in aliases.items():
        for scope in search_scopes:
            for name in names:
                if name in scope and scope[name] not in (None, ""):
                    out[canonical] = _coerce_float(scope[name])
                    break
            if out[canonical]:
                break
    return out


def load_prior_year_defaults(user_id: str, year: int) -> Dict[str, float]:
    """Return the carry-forward defaults pulled from the user's tax return
    for ``year`` (callers pass ``year - 1`` to fetch *prior* year data).

    Always returns a dict with all three :data:`CARRY_FORWARD_KEYS` populated.
    Missing values default to ``0.0`` so callers can blindly merge.
    """
    with get_session() as session:
        prior = (
            session.query(TaxReturn)
            .filter(TaxReturn.user_id == user_id, TaxReturn.filing_year == year)
            .order_by(TaxReturn.updated_at.desc())
            .first()
        )
        if prior is None:
            return {key: 0.0 for key in CARRY_FORWARD_KEYS}
        return _extract_from_fields(prior.fields)


def prefill_wizard_data(
    *,
    current_wizard_data: Dict[str, Any],
    user_id: str,
    filing_year: int,
) -> Dict[str, Any]:
    """Merge prior-year carry-forward defaults into the current wizard data
    without overwriting any field the user has already typed.

    Returns a *new* dict; the input is not mutated.
    """
    defaults = load_prior_year_defaults(user_id, filing_year - 1)
    merged: Dict[str, Any] = dict(current_wizard_data)
    for key, value in defaults.items():
        existing = merged.get(key)
        # User-typed values win — only fill empty/zero/missing slots.
        if existing in (None, "", 0, 0.0):
            merged[key] = value
    return merged
