"""Cached review-report renderer (P2-AC10) + PDF builder (P2-AC3).

The review report is read by reviewers (and is downloaded by users), so it may
be re-rendered multiple times per session — e.g. on every Streamlit rerun while
the reviewer is typing. The underlying totals are pure functions of the
``DraftReturn``, so we memoise the engine-compute step keyed on a stable
fingerprint of the draft.

Test contracts:
  - P2-AC10: :func:`render_review_report` twice with the same ``DraftReturn``
    triggers exactly one :func:`compute_review_totals` call.
  - P2-AC3: :func:`build_review_report_pdf` returns ``bytes`` starting with
    ``%PDF`` and embeds jurisdiction-specific labels (T1 / Schedule 1 / ITR).
"""

from __future__ import annotations

import hashlib
import json
from io import BytesIO
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


# ---------------------------------------------------------------------------
# P2-AC3 — jurisdiction-aware PDF builder.
#
# Emits a one-page review PDF that always starts with the %PDF magic header
# and carries jurisdiction-specific labels so downstream review tooling (or a
# human reviewer scanning the artifact) can confirm the right schedule was
# rendered. Uses reportlab when available; falls back to a minimal hand-rolled
# PDF if not (keeps the unit test runnable in stripped sandbox environments).
# ---------------------------------------------------------------------------


# Jurisdiction → (heading printed at the top, line-item label printed in body).
# These strings are what P2-AC3 asserts on:
#   CA → "T1" line item
#   US → "Schedule 1" label
#   IN → "ITR" section header
_JURISDICTION_LABELS: Dict[str, Dict[str, str]] = {
    "CA": {
        "heading": "T1 General — Review Draft",
        "line_label": "T1 line 15000 (Total income)",
        "section": "Canada Revenue Agency draft",
    },
    "US": {
        "heading": "Form 1040 — Review Draft",
        "line_label": "Schedule 1 — Additional Income & Adjustments",
        "section": "Internal Revenue Service draft",
    },
    "IN": {
        "heading": "ITR — Review Draft",
        "line_label": "ITR Part B-TI (Total Income)",
        "section": "Income Tax Department (ITR section)",
    },
}


def _minimal_pdf_fallback(text_lines: list[str]) -> bytes:
    """Hand-rolled minimal single-page PDF. Used when reportlab is unavailable.

    The output is a valid one-page PDF that starts with ``%PDF-1.4`` so the
    P2-AC3 magic-bytes check passes regardless of the environment.
    """
    # Build a single text stream
    content_lines = ["BT", "/F1 12 Tf", "72 750 Td", "14 TL"]
    for line in text_lines:
        # Escape parentheses & backslashes for PDF literal strings
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content_lines.append(f"({escaped}) Tj T*")
    content_lines.append("ET")
    stream_body = "\n".join(content_lines).encode("latin-1", errors="replace")

    objects: list[bytes] = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    objects.append(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
    )
    objects.append(
        f"<< /Length {len(stream_body)} >>\nstream\n".encode("ascii")
        + stream_body
        + b"\nendstream"
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = BytesIO()
    out.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for idx, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{idx} 0 obj\n".encode("ascii"))
        out.write(body)
        out.write(b"\nendobj\n")
    xref_pos = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.write(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.write(f"{off:010d} 00000 n \n".encode("ascii"))
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_pos}\n%%EOF\n".encode("ascii")
    )
    return out.getvalue()


def build_review_report_pdf(draft: DraftReturn) -> bytes:
    """Build a one-page jurisdiction-aware review PDF for ``draft``.

    Returns raw PDF bytes whose first four bytes are ``%PDF``. The body carries
    a jurisdiction-specific heading + line-item label per P2-AC3:
      - CA → "T1" line item
      - US → "Schedule 1" label
      - IN → "ITR" section header
    """
    juris = (draft.jurisdiction or "—").upper()
    labels = _JURISDICTION_LABELS.get(juris, {
        "heading": f"{juris} — Review Draft",
        "line_label": f"{juris} primary line item",
        "section": f"{juris} draft",
    })
    totals = compute_review_totals(draft)

    text_lines = [
        labels["heading"],
        labels["section"],
        f"Tax year: {draft.tax_year or 'n/a'}",
        "",
        labels["line_label"] + f": {totals['total_income']:,.2f}",
        f"Taxable income: {totals['taxable_income']:,.2f}",
        f"Total tax: {totals['total_tax']:,.2f}",
        f"Refund: {totals['refund']:,.2f}",
        f"Balance owing: {totals['balance_owing']:,.2f}",
        "",
        "NON-TRANSMISSIBLE DRAFT — for review only.",
    ]

    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
    except Exception:
        return _minimal_pdf_fallback(text_lines)

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    # Disable stream compression so the body text remains searchable in the
    # raw bytes — the P2-AC3 contract grep-matches against the artifact.
    c.setPageCompression(0)
    # Stamp jurisdiction labels into the PDF Info dictionary as well, which
    # is always plain-text in the output regardless of stream compression.
    c.setTitle(labels["heading"])
    c.setSubject(labels["line_label"])
    c.setKeywords(
        [labels["section"], "NON-TRANSMISSIBLE", "WealthTax Agent review draft"]
    )
    c.setFont("Helvetica-Bold", 16)
    c.drawString(72, 740, text_lines[0])
    c.setFont("Helvetica", 10)
    c.drawString(72, 722, text_lines[1])
    c.drawString(72, 708, text_lines[2])
    c.setFont("Helvetica", 11)
    y = 680
    for line in text_lines[4:]:
        c.drawString(72, y, line)
        y -= 16
    c.save()
    return buf.getvalue()
