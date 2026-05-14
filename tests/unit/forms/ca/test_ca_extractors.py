from pathlib import Path

import wealthtax_agent.forms  # noqa: F401 - ensure registry is populated
from wealthtax_agent.forms.registry import get


FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "forms" / "ca"


def _read(name: str) -> str:
    return (FIXTURE_ROOT / name).read_text(encoding="utf-8")


def test_t4_extracts_employment_income_and_deductions():
    extractor = get("T4")
    assert extractor is not None

    extract = extractor.extract(_read("t4_sample.txt"))

    assert extract.form_code == "T4"
    assert extract.jurisdiction == "CA"
    assert extract.fields["employment_income"] == 80000.00
    assert extract.fields["income_tax_deducted"] == 14500.00
    assert extract.fields["cpp_contributions"] == 3754.45


def test_t5_extracts_interest_and_dividends():
    extractor = get("T5")
    extract = extractor.extract(_read("t5_sample.txt"))

    assert extract.fields["interest_income"] == 1200.50
    assert extract.fields["taxable_eligible_dividends"] == 1380.00


def test_t5008_computes_capital_gain():
    extractor = get("T5008")
    extract = extractor.extract(_read("t5008_sample.txt"))

    assert extract.fields["proceeds"] == 7500.00
    assert extract.fields["cost_basis"] == 5000.00
    assert extract.fields["capital_gain"] == 2500.00


def test_t2202_extracts_tuition_and_months():
    extractor = get("T2202")
    extract = extractor.extract(_read("t2202_sample.txt"))

    assert extract.fields["eligible_tuition_fees"] == 6500.00
    assert extract.fields.get("full_time_months") == 8


def test_rrsp_extracts_contributions():
    extractor = get("RRSP")
    extract = extractor.extract(_read("rrsp_sample.txt"))

    assert extract.fields["rrsp_contributions"] == 7000.00
