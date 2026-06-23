"""Dedicated unit tests for forms/_helpers.py — the shared parsing helpers
imported by ~40 CA/US/IN form extractors.

Covers extract_amount_from_matching_line, extract_amount, find_box_amount, and
detect_tax_year. Each assertion checks the exact return value so a behavior
regression fails the test (rather than merely exercising the line).
"""
from wealthtax_agent.forms._helpers import (
    extract_amount,
    extract_amount_from_matching_line,
    find_box_amount,
    detect_tax_year,
)


# ---------------------------------------------------------------------------
# extract_amount_from_matching_line
# ---------------------------------------------------------------------------
def test_matching_line_returns_last_number():
    # (a) keyword line with a trailing number -> last number as float.
    assert extract_amount_from_matching_line("Wages 65000", "wages") == 65000.0


def test_matching_line_keyword_no_digits_returns_none():
    # (b) keyword line with NO digits -> falls through to `return None` (line 18/23).
    assert extract_amount_from_matching_line("Wages only no number", "wages") is None


def test_matching_line_skips_keyword_line_without_number():
    # (c) two keyword lines: first has no number, second does -> second's number.
    text = "Income reported\nIncome 4200"
    assert extract_amount_from_matching_line(text, "income") == 4200.0


def test_matching_line_strips_commas():
    # (d) comma-stripping.
    assert extract_amount_from_matching_line("Total 1,234.50", "total") == 1234.5


def test_matching_line_returns_trailing_of_multiple_numbers():
    # Confirms it returns the LAST number on the line, not the first.
    assert extract_amount_from_matching_line("Box 12 value 999", "value") == 999.0


# ---------------------------------------------------------------------------
# extract_amount
# ---------------------------------------------------------------------------
def test_extract_amount_numeric_group():
    # (a) pattern with a numeric capture group -> float (lines 30-31).
    assert extract_amount("Amount: 1,500.25", r"Amount:\s*([0-9,.]+)") == 1500.25


def test_extract_amount_no_match_returns_none():
    # (b) no match -> None (lines 28-29).
    assert extract_amount("nothing here", r"Amount:\s*([0-9,.]+)") is None


def test_extract_amount_non_numeric_group_returns_none():
    # (c) capture group is non-numeric -> ValueError caught -> None (lines 32-33).
    assert extract_amount("hello world", r"(hello)") is None


# ---------------------------------------------------------------------------
# find_box_amount
# ---------------------------------------------------------------------------
def test_find_box_amount_simple():
    # (a) "Box 14   52000" -> 52000.0.
    assert find_box_amount("Box 14   52000", "14") == 52000.0


def test_find_box_amount_digit_in_word_guard():
    # (b) regression for the documented 199A bug: the "199" in "199A" must NOT
    #     be captured; the real money figure 1500 must be returned.
    assert find_box_amount("Section 199A dividends 1500", "199A") == 1500.0


def test_find_box_amount_no_box_returns_none():
    # (c) no box present -> None.
    assert find_box_amount("just some prose with no markers", "14") is None


def test_find_box_amount_strips_commas():
    assert find_box_amount("Box 1 Wages 65,000.00", "1") == 65000.0


# (d) The ValueError `continue` at lines 54-55 is UNREACHABLE and therefore left
#     uncovered. The captured group is constrained by _NUMBER_RE
#     (`[0-9][0-9,]*(?:\.[0-9]+)?`), so after `.replace(",", "")` the string is
#     always digits with at most one trailing ".<digits>" — i.e. always a valid
#     float() input. No real text can match _NUMBER_RE yet raise ValueError on
#     float(). Fabricating coverage here would require bypassing the regex, which
#     no production call path does. Lines 54-55 are documented dead-defensive code.


# ---------------------------------------------------------------------------
# detect_tax_year
# ---------------------------------------------------------------------------
def test_detect_tax_year_labelled():
    # (a) labelled form -> primary branch.
    assert detect_tax_year("Tax Year: 2024") == 2024


def test_detect_tax_year_bare_fallback():
    # (b) bare 4-digit year -> fallback branch (lines 63-65).
    assert detect_tax_year("issued 2023") == 2023


def test_detect_tax_year_none():
    # (c) no year -> None.
    assert detect_tax_year("no year here") is None
