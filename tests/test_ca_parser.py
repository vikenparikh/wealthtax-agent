"""tests/test_ca_parser.py — unit tests for the CA form parsers.

Covers ``parsers/ca/{form_t4,form_t5,form_rrsp}.py``, which exposed the
``parse_t4`` / ``parse_t5`` / ``parse_rrsp`` public API (re-exported from
``parsers/ca/__init__``) but carried 0% test coverage. These are rule-based,
PAPER/extraction-only parsers — no tax-math, filing, money-movement, or secret
path is touched. Tests assert real parsed behaviour: box-field extraction,
tax-year detection, text fields, the confidence tiers, and the T4RSP vs
contribution-receipt form-type split.
"""

from __future__ import annotations

from wealthtax_agent.parsers.base import ParsedSlip
from wealthtax_agent.parsers.ca import parse_t4, parse_t5, parse_rrsp


# ---------------------------------------------------------------------------
# T4 — Statement of Remuneration Paid
# ---------------------------------------------------------------------------

_T4_FULL = """
T4 Statement of Remuneration Paid                     2024
Employer's name: Acme Manufacturing Ltd
Province of employment: ON
Box 14: $65,000.00
Box 16: $3,500.00
Box 18: $950.00
Box 22: $8,200.00
Box 52: $1,200.00
Box 44: $500.00
"""


def test_parse_t4_extracts_all_boxes() -> None:
    slip = parse_t4(_T4_FULL, source_filename="t4.pdf")
    assert isinstance(slip, ParsedSlip)
    assert slip.jurisdiction == "CA"
    assert slip.form_type == "T4"
    assert slip.tax_year == 2024
    assert slip.extractor == "rule"
    assert slip.source_filename == "t4.pdf"
    assert slip.fields == {
        "employment_income": 65000.0,
        "employee_cpp_contributions": 3500.0,
        "ei_premiums": 950.0,
        "income_tax_deducted": 8200.0,
        "pension_adjustment": 1200.0,
        "union_dues": 500.0,
    }
    assert slip.text_fields["employer_name"] == "Acme Manufacturing Ltd"
    assert slip.text_fields["province"] == "ON"
    # employment_income present -> high confidence
    assert slip.confidence == "high"
    assert slip.raw_text == _T4_FULL


def test_parse_t4_word_form_alternation() -> None:
    # Exercises the non-"box" alternation branch of the regexes.
    text = "Year 2023\nEmployment income: 42,000.00\nIncome tax deducted: 5,100.00\n"
    slip = parse_t4(text)
    assert slip.tax_year == 2023
    assert slip.fields["employment_income"] == 42000.0
    assert slip.fields["income_tax_deducted"] == 5100.0
    assert slip.confidence == "high"


def test_parse_t4_medium_confidence_without_employment_income() -> None:
    # Fields present but no employment_income -> medium.
    slip = parse_t4("2024\nBox 44: $250.00\n")
    assert slip.fields == {"union_dues": 250.0}
    assert slip.confidence == "medium"


def test_parse_t4_empty_is_low_confidence() -> None:
    slip = parse_t4("nothing useful here")
    assert slip.fields == {}
    assert slip.text_fields == {}
    assert slip.tax_year is None
    assert slip.confidence == "low"


# ---------------------------------------------------------------------------
# T5 — Statement of Investment Income
# ---------------------------------------------------------------------------

_T5_FULL = """
T5 Statement of Investment Income                     2024
Payer's name: Royal Bank of Canada
Box 24: $1,800.00
Box 10: $450.00
Box 13: $320.00
Box 15: $200.00
Box 16: $30.00
"""


def test_parse_t5_extracts_all_boxes() -> None:
    slip = parse_t5(_T5_FULL, source_filename="t5.pdf")
    assert slip.jurisdiction == "CA"
    assert slip.form_type == "T5"
    assert slip.tax_year == 2024
    assert slip.fields == {
        "actual_amount_eligible_dividends": 1800.0,
        "actual_amount_other_dividends": 450.0,
        "interest_cdn_sources": 320.0,
        "foreign_income": 200.0,
        "foreign_tax_paid": 30.0,
    }
    assert slip.text_fields["payer_name"] == "Royal Bank of Canada"
    # >= 2 fields -> high confidence
    assert slip.confidence == "high"


def test_parse_t5_single_field_is_medium() -> None:
    slip = parse_t5("2024\nBox 13: $99.00\n")
    assert slip.fields == {"interest_cdn_sources": 99.0}
    assert slip.confidence == "medium"


def test_parse_t5_empty_is_low() -> None:
    slip = parse_t5("")
    assert slip.fields == {}
    assert slip.tax_year is None
    assert slip.confidence == "low"


# ---------------------------------------------------------------------------
# RRSP — T4RSP statement vs contribution receipt
# ---------------------------------------------------------------------------

_T4RSP = """
T4RSP Statement of RRSP Income                        2024
Plan number: RRSP12345678
Box 22: $5,000.00
Box 30: $750.00
"""

_RRSP_RECEIPT = """
RRSP Contribution Receipt                             2024
Plan number: ABC987654321
RRSP contribution: $3,000.00
"""


def test_parse_rrsp_t4rsp_withdrawal_sets_t4rsp_type() -> None:
    # Regression: the header "Statement of RRSP Income 2024" sits on the same
    # flattened line as the year, yet Box 22 (the authoritative line) must win —
    # rrsp_income is $5,000, NOT 2024. (Old combined regex returned 2024.0.)
    slip = parse_rrsp(_T4RSP, source_filename="t4rsp.pdf")
    assert slip.jurisdiction == "CA"
    assert slip.form_type == "T4RSP"
    assert slip.tax_year == 2024
    assert slip.fields["rrsp_income"] == 5000.0
    assert slip.fields["income_tax_deducted"] == 750.0
    assert slip.text_fields["plan_number"] == "RRSP12345678"
    assert slip.confidence == "high"


def test_parse_rrsp_title_year_not_read_as_income() -> None:
    # Title contains "RRSP Income" trailed by the year, and there is NO Box 22.
    # The year must not be captured as the income amount.
    text = "T4RSP Statement of RRSP Income 2024\nIncome tax deducted: $750.00\n"
    slip = parse_rrsp(text)
    assert "rrsp_income" not in slip.fields
    assert slip.fields["income_tax_deducted"] == 750.0
    # No withdrawal detected -> classified as a receipt.
    assert slip.form_type == "RRSP-RECEIPT"


def test_parse_rrsp_prose_income_without_box_is_accepted() -> None:
    # Legitimate prose income line (no Box 22) with a real money amount: the
    # label fallback IS used and yields the value.
    slip = parse_rrsp("RRSP income: $4,200.00\n")
    assert slip.fields["rrsp_income"] == 4200.0
    assert slip.form_type == "T4RSP"


def test_parse_rrsp_contribution_receipt_type() -> None:
    slip = parse_rrsp(_RRSP_RECEIPT)
    # No withdrawal -> classified as a contribution receipt.
    assert slip.form_type == "RRSP-RECEIPT"
    assert slip.fields["rrsp_contribution"] == 3000.0
    assert slip.text_fields["plan_number"] == "ABC987654321"
    assert slip.confidence == "high"


def test_parse_rrsp_empty_is_low_and_receipt() -> None:
    slip = parse_rrsp("irrelevant text")
    assert slip.fields == {}
    # withdrawal is None -> defaults to receipt classification.
    assert slip.form_type == "RRSP-RECEIPT"
    assert slip.confidence == "low"
