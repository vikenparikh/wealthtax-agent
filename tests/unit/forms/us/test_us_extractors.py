from pathlib import Path

import wealthtax_agent.forms  # noqa: F401 - ensure registry is populated
from wealthtax_agent.forms.registry import get


FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "forms" / "us"


def _read(name: str) -> str:
    return (FIXTURE_ROOT / name).read_text(encoding="utf-8")


def test_w2_extracts_wages_and_withholding():
    extractor = get("W-2")
    extract = extractor.extract(_read("w2_sample.txt"))

    assert extract.jurisdiction == "US"
    assert extract.fields["wages"] == 80000.00
    assert extract.fields["federal_income_tax_withheld"] == 12000.00
    assert extract.fields["social_security_wages"] == 80000.00


def test_1099_int_extracts_box_1_and_3():
    extractor = get("1099-INT")
    extract = extractor.extract(_read("1099_int_sample.txt"))

    assert extract.fields["interest_income"] == 500.00
    assert extract.fields["us_treasury_interest"] == 100.00


def test_1099_div_extracts_ordinary_and_qualified():
    extractor = get("1099-DIV")
    extract = extractor.extract(_read("1099_div_sample.txt"))

    assert extract.fields["ordinary_dividends"] == 2000.00
    assert extract.fields["qualified_dividends"] == 1500.00


def test_1099_b_extracts_gain_and_term():
    extractor = get("1099-B")
    extract = extractor.extract(_read("1099_b_sample.txt"))

    assert extract.fields["proceeds"] == 12000.00
    assert extract.fields["cost_basis"] == 8000.00
    assert extract.fields["gain_loss"] == 4000.00
    assert extract.fields["term"] == 1.0


def test_1099_nec_extracts_nec():
    extractor = get("1099-NEC")
    extract = extractor.extract(_read("1099_nec_sample.txt"))

    assert extract.fields["nonemployee_compensation"] == 15000.00


def test_1098_e_extracts_student_loan_interest():
    extractor = get("1098-E")
    extract = extractor.extract(_read("1098_e_sample.txt"))

    assert extract.fields["student_loan_interest"] == 2200.00
