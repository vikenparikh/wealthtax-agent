"""User-requested scenario: stocks allocated in US, vested in Canada.

Inputs:
  - RSUs granted in US Jan 2022
  - Vested March 2024 when the user was a Canadian resident
  - Total vest value: $30,000 USD
  - Between grant and vest: 200 workdays in US + 400 workdays in Canada

Sourcing (IRS Rev. Proc. 2008-23 / CRA Folio S5-F2-C1):
  - US-source = 30000 × 200/600 = $10,000 (taxed by US as compensation)
  - CA-source = 30000 × 400/600 = $20,000 (taxed by Canada as resident)

A Canadian resident is also taxed on the FULL vest (Canada taxes residents on
world income), then claims a foreign tax credit for the US tax paid on the
US-source portion.
"""

import pytest

from wealthtax_agent.engines.cross_border import rsu_sourcing_split
from wealthtax_agent.state import FormExtract


def test_rsu_sourcing_math():
    split = rsu_sourcing_split(30000.0, workdays_us=200, workdays_ca=400)
    assert split["US"] == pytest.approx(10000.0, abs=0.01)
    assert split["CA"] == pytest.approx(20000.0, abs=0.01)


def test_rsu_sourcing_drives_dual_jurisdiction_filing(build_state, run_graph):
    """The user enters the RSU vest as a single W-2 line; the sourcing helper
    decides what goes where. For the test, we enter the already-split amounts
    so we can assert the engines pick them up correctly.
    """
    split = rsu_sourcing_split(30000.0, workdays_us=200, workdays_ca=400)

    extracts = [
        # US 1040-NR: only the US-sourced portion of the RSU vest is taxable.
        FormExtract(form_code="W-2", jurisdiction="US",
                    fields={"wages": split["US"], "federal_income_tax_withheld": 1500.0},
                    text_fields={"payer_name": "BigCo RSU vest"}),
        # CA T4 resident return: the FULL vest is reported as employment income
        # (resident-of-CA pays Canadian tax on world income), and the US-source
        # tax becomes an FTC.
        FormExtract(form_code="T4", jurisdiction="CA",
                    fields={"employment_income": 30000.0},
                    text_fields={"payer_name": "BigCo RSU vest"}),
    ]
    state = build_state(
        jurisdictions=["US", "CA"],
        extracts=extracts,
        residency_days={"US": 60, "CA": 305},
        user_answers={
            "filing_status": "single",
            "state_of_residence": "CA",
            "province_of_residence": "ON",
            "has_primary_ties_ca": "yes",
        },
    )
    result = run_graph(state)

    # US engine sees the US-sourced portion as wages (1040-NR style).
    assert result.draft_returns["US"].line_items["wages"] == pytest.approx(10000.0, abs=0.01)
    # CA engine sees the FULL vest (resident on world income).
    assert result.draft_returns["CA"].line_items["employment_income"] == 30000.0

    # Residency expectations
    assert result.residency_status["US"] == "nonresident"
    assert result.residency_status["CA"] == "resident"

    # The cross-border + FTC machinery should surface an FTC hint.
    warnings_blob = " ".join(result.warnings)
    assert "Cross-border" in warnings_blob
    assert any("Foreign tax credit" in w for w in result.warnings)


def test_rsu_zero_workdays_raises_no_division_error():
    split = rsu_sourcing_split(30000.0, 0, 0, 0)
    assert split == {"US": 0.0, "CA": 0.0, "IN": 0.0}


def test_rsu_three_country_split_proportional():
    split = rsu_sourcing_split(90000.0, workdays_us=100, workdays_ca=100, workdays_in=100)
    assert split["US"] == 30000.0
    assert split["CA"] == 30000.0
    assert split["IN"] == 30000.0
