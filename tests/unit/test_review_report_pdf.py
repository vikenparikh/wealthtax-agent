"""P2-AC3 — :func:`build_review_report_pdf` must emit a real PDF with
jurisdiction-specific labels.

Contract enforced here:
  - returns ``bytes`` whose first four bytes are ``%PDF``
  - CA artifact embeds a "T1" line-item label
  - US artifact embeds a "Schedule 1" label
  - IN artifact embeds an "ITR" section header
"""

from __future__ import annotations

import pytest

from wealthtax_agent.render_review_report import build_review_report_pdf
from wealthtax_agent.state import DraftReturn


def _draft(jurisdiction: str) -> DraftReturn:
    return DraftReturn(
        jurisdiction=jurisdiction,
        tax_year=2024,
        total_income=90_000.0,
        taxable_income=82_500.0,
        estimated_tax=15_200.0,
        estimated_refund=300.0,
        line_items={"primary_line": 90_000.0},
        totals={
            "total_income": 90_000.0,
            "taxable_income": 82_500.0,
            "total_tax": 15_200.0,
            "refund": 300.0,
            "balance_owing": 0.0,
        },
    )


@pytest.mark.parametrize("jurisdiction", ["CA", "US", "IN"])
def test_returns_bytes_with_pdf_magic(jurisdiction: str) -> None:
    pdf = build_review_report_pdf(_draft(jurisdiction))
    assert isinstance(pdf, bytes), f"{jurisdiction}: expected bytes, got {type(pdf)}"
    assert pdf[:4] == b"%PDF", (
        f"{jurisdiction}: expected PDF magic header, got {pdf[:8]!r}"
    )


def test_ca_pdf_embeds_t1_line_item() -> None:
    pdf = build_review_report_pdf(_draft("CA"))
    assert b"T1" in pdf, "CA review PDF must reference a T1 line item"


def test_us_pdf_embeds_schedule_1_label() -> None:
    pdf = build_review_report_pdf(_draft("US"))
    assert b"Schedule 1" in pdf, "US review PDF must reference Schedule 1"


def test_in_pdf_embeds_itr_section_header() -> None:
    pdf = build_review_report_pdf(_draft("IN"))
    assert b"ITR" in pdf, "IN review PDF must reference an ITR section header"


def test_pdf_carries_total_tax_numeric() -> None:
    """Sanity: the engine totals propagate into the rendered body."""
    pdf = build_review_report_pdf(_draft("CA"))
    # 15,200.00 is the total_tax we seeded. reportlab encodes it as Tj literal.
    assert b"15,200" in pdf or b"15200" in pdf


def test_pdf_stamps_non_transmissible_warning() -> None:
    """Every review PDF must flag itself as a non-transmissible draft."""
    pdf = build_review_report_pdf(_draft("US"))
    assert b"NON-TRANSMISSIBLE" in pdf or b"non-transmissible" in pdf.lower()


def test_unknown_jurisdiction_still_returns_valid_pdf() -> None:
    """Defensive: an unmapped jurisdiction must not crash; PDF must still be valid."""
    draft = _draft("CA")
    draft.jurisdiction = None  # simulate missing jurisdiction
    pdf = build_review_report_pdf(draft)
    assert pdf[:4] == b"%PDF"
