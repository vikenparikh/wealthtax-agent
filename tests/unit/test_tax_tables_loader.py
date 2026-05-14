import pytest

from wealthtax_agent.config.tax_tables import MissingTableError, compute_progressive_tax, load_tables


def test_load_ca_federal_2024():
    tables = load_tables("ca", 2024)
    assert tables["basic_personal_amount"] > 0
    assert tables["brackets"][0]["rate"] == 0.15


def test_load_us_federal_2024():
    tables = load_tables("us", 2024)
    assert "brackets_by_status" in tables
    assert "single" in tables["brackets_by_status"]


def test_load_on_province_2024():
    tables = load_tables("ca", 2024, sub="provinces", region="on")
    assert tables["province"] == "ON"


def test_missing_table_raises():
    with pytest.raises(MissingTableError):
        load_tables("ca", 1900)


def test_compute_progressive_tax_no_income_returns_zero():
    assert compute_progressive_tax(0.0, [{"up_to": 50000, "rate": 0.1}]) == 0.0


def test_compute_progressive_tax_basic_brackets():
    brackets = [
        {"up_to": 10000, "rate": 0.10},
        {"up_to": 50000, "rate": 0.20},
        {"up_to": None, "rate": 0.30},
    ]
    # 60000: 10% on first 10000 + 20% on next 40000 + 30% on 10000 = 1000 + 8000 + 3000 = 12000
    assert compute_progressive_tax(60000.0, brackets) == 12000.0
