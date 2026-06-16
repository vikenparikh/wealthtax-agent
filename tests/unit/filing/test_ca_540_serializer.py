"""Tests for the California Form 540 state-tax serializer (filing/ca_540.py).

The federal 1040 artifact is federal-only (state income tax was removed from it,
#86/87); this artifact carries the state tax. Covers the envelope safety flags,
the state-line mapping from the engine's line_items, the W-2 box-17 withholding
sum, and the state balance/refund split.
"""

from wealthtax_agent.filing.ca_540 import SCHEMA_VERSION, serialize_ca540
from wealthtax_agent.state import DraftReturn, FormExtract


def _w2(**fields):
    return FormExtract(form_code="W-2", jurisdiction="US", fields=fields)


def _ca_draft(**li):
    base = {"agi": 80000.0, "state_standard_deduction": 5363.0,
            "state_taxable_income": 74637.0, "state_tax": 3483.6}
    base.update(li)
    return DraftReturn(jurisdiction="US", line_items=base, totals={})


def test_ca540_envelope_is_non_transmissible_and_versioned():
    payload = serialize_ca540(_ca_draft(), [], 2024)
    assert payload["transmissible"] is False
    assert payload["schema_version"] == SCHEMA_VERSION == "ca540-0.1-draft"
    assert "Not transmitted" in payload["note"]


def test_ca540_maps_state_lines_and_computes_refund():
    """CA single, AGI $80,000 → state tax $3,483.60; $4,000 withheld (W-2 box 17)
    → refund $516.40 (3,483.60 − 4,000)."""
    draft = _ca_draft()
    payload = serialize_ca540(draft, [_w2(wages=80000, state_income_tax=4000)], 2024,
                              {"filing_status": "single", "state_of_residence": "CA"})
    ca = payload["CA540"]
    assert ca["state_taxable_income"] == 74637.0
    assert ca["state_standard_deduction"] == 5363.0
    assert ca["state_tax"] == 3483.6
    assert ca["state_tax_withheld"] == 4000.0       # sum of W-2 box 17
    assert ca["refund"] == 516.4
    assert ca["amount_you_owe"] == 0.0


def test_ca540_balance_owing_when_underwithheld():
    """$1,000 withheld vs $3,483.60 tax → owe $2,483.60, refund $0."""
    payload = serialize_ca540(_ca_draft(), [_w2(wages=80000, state_income_tax=1000)], 2024)
    ca = payload["CA540"]
    assert ca["amount_you_owe"] == 2483.6
    assert ca["refund"] == 0.0


def test_ca540_state_withholding_sums_multiple_w2s_and_ignores_non_us():
    payload = serialize_ca540(
        _ca_draft(),
        [_w2(state_income_tax=2500), _w2(state_income_tax=1500),
         FormExtract(form_code="T4", jurisdiction="CA", fields={"state_income_tax": 999})],
        2024,
    )
    assert payload["CA540"]["state_tax_withheld"] == 4000.0  # 2500 + 1500; CA T4 ignored
