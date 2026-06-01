"""P2-AC5 — property-tax inputs flow through CA and US engines.

* CA engine accepts ``property_tax_paid`` via ``user_answers``.
  - Eligible expense capped at $12,000.
  - Credit applied at the lowest federal rate (mirrors student-loan credit shape).
  - Surfaces in ``line_items`` and reduces ``estimated_tax`` (total_tax).

* US engine accepts ``state_local_property_tax`` via ``user_answers``.
  - Combined with ``SCH-A.state_local_taxes``, capped together at $10,000 SALT.
  - Surfaces in ``line_items`` and (when itemising wins) reduces ``estimated_tax``.
"""

from __future__ import annotations

import pytest

from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


# ---------------------------------------------------------------------------
# CA — property_tax_paid
# ---------------------------------------------------------------------------
def _ca_t4(income: float = 100_000.0) -> FormExtract:
    return FormExtract(
        form_code="T4",
        jurisdiction="CA",
        fields={"employment_income": income, "income_tax_deducted": 20_000.0},
    )


def test_ca_property_tax_paid_flows_into_line_items() -> None:
    draft = compute_ca_return(
        [_ca_t4()],
        year=2024,
        province="ON",
        user_answers={"property_tax_paid": "4000"},
    )
    assert draft.line_items["property_tax_paid"] == pytest.approx(4000.0)
    assert draft.line_items["property_tax_eligible"] == pytest.approx(4000.0)
    assert draft.line_items["property_tax_credit"] > 0


def test_ca_property_tax_credit_reduces_total_tax() -> None:
    baseline = compute_ca_return([_ca_t4()], year=2024, province="ON")
    with_tax = compute_ca_return(
        [_ca_t4()],
        year=2024,
        province="ON",
        user_answers={"property_tax_paid": 5_000.0},
    )
    assert with_tax.estimated_tax < baseline.estimated_tax
    # Credit should be lowest-rate-based, so the saving is roughly 15% * $5,000 = $750.
    saving = baseline.estimated_tax - with_tax.estimated_tax
    assert 500 < saving < 1000, f"unexpected saving: {saving}"


def test_ca_property_tax_capped_at_twelve_thousand() -> None:
    draft_capped = compute_ca_return(
        [_ca_t4()],
        year=2024,
        province="ON",
        user_answers={"property_tax_paid": 20_000.0},
    )
    draft_at_cap = compute_ca_return(
        [_ca_t4()],
        year=2024,
        province="ON",
        user_answers={"property_tax_paid": 12_000.0},
    )
    assert draft_capped.line_items["property_tax_eligible"] == pytest.approx(12_000.0)
    # Beyond the cap, eligible expense and credit must equal the cap scenario.
    assert draft_capped.line_items["property_tax_credit"] == pytest.approx(
        draft_at_cap.line_items["property_tax_credit"]
    )
    assert draft_capped.estimated_tax == pytest.approx(draft_at_cap.estimated_tax)
    assert any("$12,000 cap" in n for n in draft_capped.notes)


def test_ca_property_tax_default_zero_when_unspecified() -> None:
    draft = compute_ca_return([_ca_t4()], year=2024, province="ON")
    assert draft.line_items["property_tax_paid"] == 0.0
    assert draft.line_items["property_tax_credit"] == 0.0


def test_ca_property_tax_negative_input_ignored() -> None:
    draft = compute_ca_return(
        [_ca_t4()],
        year=2024,
        province="ON",
        user_answers={"property_tax_paid": "-5000"},
    )
    assert draft.line_items["property_tax_eligible"] == 0.0
    assert draft.line_items["property_tax_credit"] == 0.0


# ---------------------------------------------------------------------------
# US — state_local_property_tax (SALT cap $10,000)
# ---------------------------------------------------------------------------
def _us_w2(wages: float = 200_000.0) -> FormExtract:
    return FormExtract(
        form_code="W-2",
        jurisdiction="US",
        fields={"wages": wages, "federal_income_tax_withheld": 30_000.0},
    )


def test_us_property_tax_flows_into_line_items() -> None:
    draft = compute_us_return(
        [_us_w2()],
        year=2024,
        user_answers={"state_local_property_tax": "6000"},
    )
    assert draft.line_items["state_local_property_tax"] == pytest.approx(6000.0)
    # No SCH-A state_local_taxes, so SALT bucket = 6000 (under the cap).
    assert draft.line_items["salt_deduction_capped"] == pytest.approx(6000.0)


def test_us_property_tax_capped_at_ten_thousand_salt() -> None:
    # 8000 state_local_taxes + 5000 property tax = 13000 → capped at 10000.
    extracts = [
        _us_w2(),
        FormExtract(
            form_code="SCH-A",
            jurisdiction="US",
            fields={"state_local_taxes": 8000.0},
        ),
    ]
    draft = compute_us_return(
        extracts,
        year=2024,
        user_answers={"state_local_property_tax": 5_000.0},
    )
    assert draft.line_items["salt_deduction_capped"] == pytest.approx(10_000.0)
    assert any("SALT cap applied" in n for n in draft.notes)


def test_us_property_tax_reduces_total_tax_when_itemising_wins() -> None:
    """High-income taxpayer with enough Schedule A items will itemise — adding
    property tax then bumps the deduction up to the SALT cap and lowers tax."""
    base_extracts = [
        _us_w2(wages=400_000.0),
        FormExtract(
            form_code="SCH-A",
            jurisdiction="US",
            fields={
                "mortgage_interest": 25_000.0,
                "charitable_gifts": 5_000.0,
                "state_local_taxes": 2_000.0,
            },
        ),
    ]
    baseline = compute_us_return(base_extracts, year=2024)
    with_tax = compute_us_return(
        base_extracts,
        year=2024,
        user_answers={"state_local_property_tax": 8_000.0},
    )
    assert with_tax.estimated_tax < baseline.estimated_tax
    # SALT goes from 2000 → 10000 (capped), so itemised deduction rises by ~8000.
    delta_itemised = (
        with_tax.line_items["itemized_deduction_sch_a"]
        - baseline.line_items["itemized_deduction_sch_a"]
    )
    assert delta_itemised == pytest.approx(8_000.0)


def test_us_property_tax_default_zero_when_unspecified() -> None:
    draft = compute_us_return([_us_w2()], year=2024)
    assert draft.line_items["state_local_property_tax"] == 0.0


def test_us_property_tax_no_cap_message_when_under_threshold() -> None:
    draft = compute_us_return(
        [_us_w2()],
        year=2024,
        user_answers={"state_local_property_tax": 3_000.0},
    )
    assert not any("SALT cap applied" in n for n in draft.notes)
