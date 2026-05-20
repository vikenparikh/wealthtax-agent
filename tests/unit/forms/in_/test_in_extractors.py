"""Verify each India form extractor pulls expected fields out of the fixture."""

from pathlib import Path

import wealthtax_agent.forms  # noqa: F401 - populate registry
from wealthtax_agent.forms.registry import get


FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "forms" / "in"


def _read(name: str) -> str:
    return (FIXTURE_ROOT / name).read_text(encoding="utf-8")


def test_form16_extracts_salary_and_deductions():
    extract = get("FORM-16").extract(_read("form16_sample.txt"))
    assert extract.jurisdiction == "IN"
    assert extract.fields["gross_salary"] == 1800000.00
    assert extract.fields["basic_salary"] == 900000.00
    assert extract.fields["hra_received"] == 360000.00
    assert extract.fields["standard_deduction_salary"] == 50000.00
    assert extract.fields["section_80c_declared"] == 150000.00
    assert extract.fields["section_80d_declared"] == 25000.00
    assert extract.fields["tds_deducted"] == 184000.00


def test_form16a_extracts_interest_and_tds():
    extract = get("FORM-16A").extract(_read("form16a_sample.txt"))
    assert extract.jurisdiction == "IN"
    assert extract.fields["interest_income"] == 45000.00
    assert extract.fields["tds_deducted"] == 5300.00


def test_form26as_extracts_total_tds():
    extract = get("FORM-26AS").extract(_read("form26as_sample.txt"))
    assert extract.jurisdiction == "IN"
    assert extract.fields["total_tds"] == 189300.00


def test_ais_extracts_interest_and_dividends():
    extract = get("AIS").extract(_read("ais_sample.txt"))
    assert extract.jurisdiction == "IN"
    assert extract.fields["interest_income"] == 12500.00
    assert extract.fields["dividend_income"] == 8000.00


def test_stock_gain_extracts_pre_post_split():
    extract = get("STOCK-GAIN").extract(_read("stock_gain_sample.txt"))
    assert extract.jurisdiction == "IN"
    assert extract.fields["stcg_equity_pre_change"] == 20000.00
    assert extract.fields["stcg_equity_post_change"] == 30000.00
    assert extract.fields["ltcg_equity_pre_change"] == 60000.00
    assert extract.fields["ltcg_equity_post_change"] == 150000.00
