"""Edge-case coverage for the progressive-bracket calculator + table loader.

test_tax_tables_loader.py covers the happy paths (load CA/US/ON, one basic
bracket case). This pins the branches that drive every engine's tax math:
empty/negative income, the open-ended top bracket, exact bracket boundaries,
multi-bracket cumulation, rounding, and a missing rate; plus available_years
and the _load_yaml mapping guard.
"""

from pathlib import Path

import pytest

from wealthtax_agent.config.tax_tables import (
    MissingTableError,
    _load_yaml,
    available_years,
    compute_progressive_tax,
)

_TWO = [{"up_to": 50000, "rate": 0.10}, {"up_to": None, "rate": 0.20}]


# --- compute_progressive_tax -------------------------------------------------


def test_empty_brackets_returns_zero():
    assert compute_progressive_tax(50000.0, []) == 0.0


def test_negative_income_returns_zero():
    assert compute_progressive_tax(-100.0, [{"up_to": 1000, "rate": 0.1}]) == 0.0


def test_income_within_first_bracket():
    assert compute_progressive_tax(30000.0, _TWO) == 3000.0  # 30000 * 0.10


def test_income_exactly_at_bracket_boundary():
    # 50000 fills the first bracket exactly; nothing spills into the top bracket.
    assert compute_progressive_tax(50000.0, _TWO) == 5000.0


def test_income_spans_into_open_top_bracket():
    # 50000*0.10 + 50000*0.20 = 5000 + 10000
    assert compute_progressive_tax(100000.0, _TWO) == 15000.0


def test_three_brackets_cumulative():
    brackets = [
        {"up_to": 10000, "rate": 0.10},
        {"up_to": 30000, "rate": 0.20},
        {"up_to": None, "rate": 0.30},
    ]
    # 1000 + 4000 + 3000
    assert compute_progressive_tax(40000.0, brackets) == 8000.0


def test_result_is_rounded_to_two_decimals():
    assert compute_progressive_tax(100.0, [{"up_to": None, "rate": 0.1333}]) == 13.33


def test_missing_rate_defaults_to_zero():
    assert compute_progressive_tax(1000.0, [{"up_to": None}]) == 0.0


# --- available_years ---------------------------------------------------------


def test_available_years_sorted_for_known_jurisdiction():
    years = available_years("ca")
    assert 2024 in years
    assert years == sorted(years)
    assert all(isinstance(y, int) for y in years)


def test_available_years_is_case_insensitive():
    assert available_years("CA") == available_years("ca")


def test_available_years_empty_for_unknown_jurisdiction():
    assert available_years("zz") == []


# --- _load_yaml --------------------------------------------------------------


def test_load_yaml_missing_file_raises():
    with pytest.raises(MissingTableError, match="not found"):
        _load_yaml(Path("/no/such/tax_table.yaml"))


def test_load_yaml_rejects_non_mapping(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("- a\n- b\n", encoding="utf-8")  # a YAML list, not a mapping
    with pytest.raises(MissingTableError, match="not a mapping"):
        _load_yaml(bad)
