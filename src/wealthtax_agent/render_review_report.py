"""Cached review-report renderer (P2-AC10).

The review report is read by reviewers (and is downloaded by users), so it may
be re-rendered multiple times per session — e.g. on every Streamlit rerun while
the reviewer is typing. The underlying totals are pure functions of the
``DraftReturn``, so we memoise the engine-compute step keyed on a stable
fingerprint of the draft.

Test contract (P2-AC10): calling :func:`render_review_report` twice with the
same ``DraftReturn`` results in exactly one call to
:func:`compute_review_totals` (the "underlying engine compute function").
"""

from __future__ import annotations

import hashlib
import json
from typing import Dict

from .state import DraftReturn


def _draft_fingerprint(draft: DraftReturn) -> str:
    """Stable sha256 hash of the fields that influence the review report."""
    payload = {
        "jurisdiction": draft.jurisdiction,
        "tax_year": draft.tax_year,
        "total_income": draft.total_income,
        "taxable_income": draft.taxable_income,
        "estimated_tax": draft.estimated_tax,
        "estimated_refund": draft.estimated_refund,
        "line_items": dict(sorted(draft.line_items.items())),
        "totals": dict(sorted(draft.totals.items())),
        "credits": dict(sorted(draft.credits.items())),
        "notes": list(draft.notes),
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def compute_review_totals(draft: DraftReturn) -> Dict[str, float]:
    """Engine-side aggregation that feeds the rendered report.

    Patched in P2-AC10 tests to assert the cache prevents re-computation.
    """
    return {
        "total_income": float(draft.totals.get("total_income", draft.total_income)),
        "taxable_income": float(draft.totals.get("taxable_income", draft.taxable_income)),
        "total_tax": float(draft.totals.get("total_tax", draft.estimated_tax)),
        "refund": float(draft.totals.get("refund", draft.estimated_refund)),
        "balance_owing": float(draft.totals.get("balance_owing", 0.0)),
    }


_RENDER_CACHE: Dict[str, str] = {}


def clear_review_report_cache() -> None:
    """Drop the memoised render cache. Called by tests + on logout."""
    _RENDER_CACHE.clear()


def render_review_report(draft: DraftReturn, *, reviewer_name: str = "") -> str:
    """Render the review report for ``draft``; cached by draft fingerprint.

    Calling twice with the same draft returns the cached string and skips the
    :func:`compute_review_totals` call entirely — that's the P2-AC10 invariant.
    """
    fp = _draft_fingerprint(draft)
    cache_key = f"{fp}::{reviewer_name.strip()}"
    cached = _RENDER_CACHE.get(cache_key)
    if cached is not None:
        return cached

    totals = compute_review_totals(draft)
    juris = draft.jurisdiction or "—"
    reviewer = reviewer_name.strip() or "Not provided"
    lines = [
        f"{juris} Review Report",
        "=" * (len(juris) + 14),
        f"Reviewer:        {reviewer}",
        f"Tax year:        {draft.tax_year or 'n/a'}",
        f"Total income:    {totals['total_income']:>14,.2f}",
        f"Taxable income:  {totals['taxable_income']:>14,.2f}",
        f"Total tax:       {totals['total_tax']:>14,.2f}",
        f"Refund:          {totals['refund']:>14,.2f}",
        f"Balance owing:   {totals['balance_owing']:>14,.2f}",
    ]
    report = "\n".join(lines) + "\n"
    _RENDER_CACHE[cache_key] = report
    return report
