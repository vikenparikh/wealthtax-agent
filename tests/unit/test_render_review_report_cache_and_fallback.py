"""Coverage for the cached render path + the hand-rolled PDF fallback.

Targets ``render_review_report`` (P2-AC10 cache invariant) and
``_minimal_pdf_fallback`` / the reportlab-unavailable fallback branch in
``build_review_report_pdf``. Tests-only — no production code changed.

Hygiene: the module owns a process-global render cache (``_RENDER_CACHE``).
The ``_reset_cache`` fixture clears it around every test so there is no
cross-test order dependence.
"""

from __future__ import annotations

import builtins

import pytest

import wealthtax_agent.render_review_report as rrr
from wealthtax_agent.render_review_report import (
    build_review_report_pdf,
    clear_review_report_cache,
    render_review_report,
    _minimal_pdf_fallback,
)
from wealthtax_agent.state import DraftReturn


@pytest.fixture(autouse=True)
def _reset_cache():
    clear_review_report_cache()
    yield
    clear_review_report_cache()


def _draft(jurisdiction: str = "CA") -> DraftReturn:
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


class _CallCounter:
    """Wraps the real compute fn so we can both delegate and count calls."""

    def __init__(self, real):
        self._real = real
        self.calls = 0

    def __call__(self, draft):
        self.calls += 1
        return self._real(draft)


def test_render_cache_hit_skips_recompute(monkeypatch):
    counter = _CallCounter(rrr.compute_review_totals)
    monkeypatch.setattr(rrr, "compute_review_totals", counter)

    draft = _draft("CA")
    first = render_review_report(draft, reviewer_name="Alice")
    second = render_review_report(draft, reviewer_name="Alice")

    assert first == second
    assert counter.calls == 1


def test_render_cache_keys_on_reviewer_name(monkeypatch):
    counter = _CallCounter(rrr.compute_review_totals)
    monkeypatch.setattr(rrr, "compute_review_totals", counter)

    draft = _draft("CA")
    render_review_report(draft, reviewer_name="Alice")
    render_review_report(draft, reviewer_name="Bob")

    # Distinct reviewer_name => distinct cache key => two computes.
    assert counter.calls == 2


def test_clear_review_report_cache_forces_recompute(monkeypatch):
    counter = _CallCounter(rrr.compute_review_totals)
    monkeypatch.setattr(rrr, "compute_review_totals", counter)

    draft = _draft("CA")
    render_review_report(draft, reviewer_name="Alice")
    clear_review_report_cache()
    render_review_report(draft, reviewer_name="Alice")

    assert counter.calls == 2


def test_minimal_pdf_fallback_is_valid_pdf():
    pdf = _minimal_pdf_fallback(["Line one", "Line two"])
    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF-1.4")
    assert b"xref" in pdf
    assert b"trailer" in pdf
    assert pdf.rstrip().endswith(b"%%EOF")


def test_minimal_pdf_fallback_escapes_special_chars():
    # A line with the three chars the escaper handles: ( ) and backslash.
    pdf = _minimal_pdf_fallback([r"weird (paren) and \\backslash"])
    assert pdf.startswith(b"%PDF-1.4")
    # Escaped forms must appear in the content stream.
    assert b"\\(" in pdf
    assert b"\\)" in pdf
    assert b"\\\\" in pdf


def test_build_pdf_falls_back_when_reportlab_unavailable(monkeypatch):
    real_import = builtins.__import__

    def _no_reportlab(name, *args, **kwargs):
        if name.startswith("reportlab"):
            raise ImportError(f"forced: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_reportlab)

    pdf = build_review_report_pdf(_draft("CA"))

    assert pdf.startswith(b"%PDF-1.4")
    assert b"NON-TRANSMISSIBLE" in pdf
    assert b"xref" in pdf
    assert b"trailer" in pdf
