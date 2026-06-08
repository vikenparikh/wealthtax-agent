"""Field-mapping assertions for retirement / HSA box-based extractors.

Pins the box->field maps for 1099-SA (HSA distributions), 5498 (IRA
contribution info), T4RSP (RRSP income), and T4RIF (RRIF income), whose
specific extracted values were unasserted (test_all_forms_extraction only
checks each yields some fields). Values confirmed by running each extractor.
"""

import wealthtax_agent.forms  # noqa: F401 - populate the registry
from wealthtax_agent.forms.registry import get


def test_1099sa_box_map():
    text = (
        "1099-SA Distributions From an HSA\n"
        "Tax year: 2024\n"
        "Box 1 Gross distribution 3000.00\n"
        "Box 2 Earnings on excess contributions 50.00\n"
        "Box 4 FMV on date of death 0.00"
    )
    assert get("1099-SA").extract(text).fields == {
        "gross_distribution": 3000.0,
        "earnings_on_excess": 50.0,
        "fmv_on_death": 0.0,
    }


def test_5498_box_map():
    text = (
        "5498 IRA Contribution Information\n"
        "Tax year: 2024\n"
        "Box 1 IRA contributions 6000.00\n"
        "Box 2 Rollover contributions 1000.00\n"
        "Box 3 Roth conversion amount 2000.00\n"
        "Box 5 Fair market value 45000.00\n"
        "Box 10 Roth IRA contributions 3000.00"
    )
    assert get("5498").extract(text).fields == {
        "ira_contributions": 6000.0,
        "rollover_contributions": 1000.0,
        "roth_conversion_amount": 2000.0,
        "fair_market_value": 45000.0,
        "roth_ira_contributions": 3000.0,
    }


def test_t4rsp_box_map():
    text = (
        "T4RSP Statement of RRSP Income\n"
        "Tax year: 2024\n"
        "Box 16 Annuity payments 12000.00\n"
        "Box 18 Refund of premiums 5000.00\n"
        "Box 22 Withdrawal and commutation 8000.00\n"
        "Box 30 Income tax deducted 3000.00"
    )
    extract = get("T4RSP").extract(text)
    assert extract.jurisdiction == "CA"
    assert extract.fields == {
        "annuity_payments": 12000.0,
        "refund_of_premiums": 5000.0,
        "withdrawal_and_commutation": 8000.0,
        "tax_deducted": 3000.0,
    }


def test_t4rif_box_map():
    text = (
        "T4RIF Statement of Income from a RRIF\n"
        "Tax year: 2024\n"
        "Box 16 Taxable amounts 15000.00\n"
        "Box 28 Income tax deducted 2500.00\n"
        "Box 26 Designated benefit 4000.00"
    )
    assert get("T4RIF").extract(text).fields == {
        "taxable_amount": 15000.0,
        "tax_deducted": 2500.0,
        "designated_benefit": 4000.0,
    }
