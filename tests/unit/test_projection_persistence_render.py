"""Boundary/fallback coverage for projection.py, persistence.py, render_review_report.py.

Found via a fan-out audit subagent; the exit-gated run confirms every value.
Covers branches the happy-path suites miss: projection year-list + growth
rounding, persistence filename/missing/skip/corrupt paths, and the review-report
default fallbacks (unknown jurisdiction, blank reviewer, missing tax year,
totals-dict fallback to top-level fields).
"""

import json
from pathlib import Path

import pytest

from wealthtax_agent.persistence import (
    list_saved_years,
    load_all_prior_returns,
    load_state,
    save_state,
)
from wealthtax_agent.projection import _grow_extracts, fallback_table_years_available
from wealthtax_agent.render_review_report import compute_review_totals, render_review_report
from wealthtax_agent.state import DraftReturn, FormExtract, GraphState


# --- projection --------------------------------------------------------------


def test_fallback_table_years_available_known_and_unknown():
    ca = fallback_table_years_available("CA")
    assert 2024 in ca and ca == sorted(ca)
    assert fallback_table_years_available("ZZ") == []


def test_grow_extracts_handles_empty_fields():
    out = _grow_extracts([FormExtract(form_code="T4", jurisdiction="CA", fields={})], 0.10)
    assert len(out) == 1 and out[0].fields == {}


def test_grow_extracts_rounds_grown_values():
    out = _grow_extracts([FormExtract(form_code="T4", jurisdiction="CA", fields={"x": 100.0})], 0.105)
    assert out[0].fields == {"x": 110.5}


# --- persistence -------------------------------------------------------------


def test_save_state_uses_zero_filename_when_year_missing(tmp_path):
    assert save_state(GraphState(filing_year=None), root=tmp_path).name == "0.json"


def test_load_state_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_state(1999, root=tmp_path)


def test_list_saved_years_skips_non_int_and_non_json(tmp_path):
    save_state(GraphState(filing_year=0), root=tmp_path)
    (tmp_path / "notes.json").write_text("{}", encoding="utf-8")   # stem not an int
    (tmp_path / "backup.txt").write_text("x", encoding="utf-8")    # not .json
    assert list_saved_years(tmp_path) == [0]


def test_list_saved_years_empty_for_missing_root(tmp_path):
    assert list_saved_years(tmp_path / "does_not_exist") == []


def test_load_all_prior_returns_skips_corrupt_files(tmp_path):
    save_state(GraphState(filing_year=2022), root=tmp_path)
    (tmp_path / "2021.json").write_text("{ not valid json", encoding="utf-8")
    prior = load_all_prior_returns(2024, root=tmp_path)
    assert sorted(prior.keys()) == [2022]  # corrupt 2021 skipped


# --- render_review_report ----------------------------------------------------


def test_render_review_report_default_fallbacks():
    draft = DraftReturn(
        jurisdiction=None, tax_year=None,
        total_income=0.0, taxable_income=0.0, estimated_tax=0.0, estimated_refund=0.0,
    )
    out = render_review_report(draft, reviewer_name="   ")
    assert out.splitlines()[0] == "— Review Report"   # jurisdiction or "—"
    assert "Not provided" in out                       # blank reviewer
    assert "n/a" in out                                # missing tax year


def test_compute_review_totals_falls_back_to_top_level_fields():
    draft = DraftReturn(
        jurisdiction="CA", total_income=55000.0, taxable_income=48000.0,
        estimated_tax=9000.0, estimated_refund=250.0, totals={},
    )
    assert compute_review_totals(draft) == {
        "total_income": 55000.0,
        "taxable_income": 48000.0,
        "total_tax": 9000.0,
        "refund": 250.0,
        "balance_owing": 0.0,
    }
