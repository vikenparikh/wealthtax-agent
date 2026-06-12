"""Specific field-mapping assertions for box-based extractors.

test_all_forms_extraction.py only checks each form classifies + yields *some*
fields; test_us_extractors / test_ca_extractors assert specific values for the
1099-INT/DIV/B/NEC, W-2, T4, T5 family. These pin the box->field maps for
1099-R, 1099-G, 1099-MISC, and T4A, whose specific mappings were unasserted.
Expected values confirmed by running each extractor read-only.
"""

import wealthtax_agent.forms  # noqa: F401 - populate the registry
from wealthtax_agent.forms.registry import get


def test_1099r_box_map():
    text = (
        "1099-R Distributions From Pensions\n"
        "Tax year: 2024\n"
        "Box 1 Gross distribution 50000.00\n"
        "Box 2a Taxable amount 40000.00\n"
        "Box 4 Federal income tax withheld 8000.00\n"
        "Box 5 Employee contributions 2000.00"
    )
    extract = get("1099-R").extract(text)
    assert extract.jurisdiction == "US"
    assert extract.fields == {
        "gross_distribution": 50000.0,
        "taxable_amount": 40000.0,
        "federal_income_tax_withheld": 8000.0,
        "employee_contributions": 2000.0,
    }


def test_1099g_box_map():
    text = (
        "1099-G Certain Government Payments\n"
        "Tax year: 2024\n"
        "Box 1 Unemployment compensation 7000.00\n"
        "Box 2 State or local tax refund 1200.00\n"
        "Box 4 Federal income tax withheld 700.00"
    )
    assert get("1099-G").extract(text).fields == {
        "unemployment_compensation": 7000.0,
        "state_local_tax_refund": 1200.0,
        "federal_income_tax_withheld": 700.0,
    }


def test_1099misc_box_map():
    text = (
        "1099-MISC Miscellaneous Information\n"
        "Tax year: 2024\n"
        "Box 1 Rents 18000.00\n"
        "Box 2 Royalties 2500.00\n"
        "Box 3 Other income 1000.00"
    )
    assert get("1099-MISC").extract(text).fields == {
        "rents": 18000.0,
        "royalties": 2500.0,
        "other_income": 1000.0,
    }


def test_t4a_box_map():
    text = (
        "T4A Statement of Pension, Retirement, Annuity\n"
        "Tax year: 2024\n"
        "Box 016 Pension or superannuation 24000.00\n"
        "Box 048 Fees for services 5000.00\n"
        "Box 105 Scholarships 3000.00\n"
        "Box 022 Income tax deducted 4000.00"
    )
    extract = get("T4A").extract(text)
    assert extract.jurisdiction == "CA"
    assert extract.fields == {
        "pension_or_superannuation": 24000.0,
        "fees_for_services": 5000.0,
        "scholarships": 3000.0,
        "tax_deducted": 4000.0,
    }
