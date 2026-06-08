"""Dedicated tests for the US MeF JSON serializer (filing/us_mef.py).

serialize_1040 was only spot-checked in test_filing_artifacts.py
(transmissible + tax-year). These tests pin the ReturnHeader handling
(filing-status / dependents coercion / state), the 1040 line mapping —
including the two composed lines (capital gain = STCG + LTCG, tax =
ordinary + preferential) and the AGI line_items/totals fallback — the
US-only Slips filter, defaults, and JSON-serializability with the
transmissible=False security flag intact.
"""

import json

from wealthtax_agent.filing.us_mef import SCHEMA_VERSION, serialize_1040
from wealthtax_agent.state import DraftReturn, FormExtract


def _draft(line_items=None, totals=None, credits=None):
    return DraftReturn(
        jurisdiction="US",
        line_items=line_items or {},
        totals=totals or {},
        credits=credits or {},
    )


def test_envelope_flags_and_schema():
    payload = serialize_1040(_draft(), [], 2025)
    assert payload["transmissible"] is False
    assert payload["schema_version"] == SCHEMA_VERSION
    assert "Do not transmit" in payload["note"]


def test_return_header_defaults_when_no_user_answers():
    header = serialize_1040(_draft(), [], 2025)["ReturnHeader"]
    assert header["TaxYear"] == 2025
    assert header["FilingStatus"] == "single"
    assert header["Dependents"] == 0
    assert header["StateOfResidence"] == ""


def test_return_header_reads_user_answers_and_coerces_dependents():
    header = serialize_1040(
        _draft(), [], 2025,
        {"filing_status": "married_joint", "num_dependents": "3", "state_of_residence": "CA"},
    )["ReturnHeader"]
    assert header["FilingStatus"] == "married_joint"
    assert header["Dependents"] == 3          # coerced from str
    assert header["StateOfResidence"] == "CA"


def test_dependents_blank_string_coerces_to_zero():
    header = serialize_1040(_draft(), [], 2025, {"num_dependents": ""})["ReturnHeader"]
    assert header["Dependents"] == 0


def test_capital_gain_line_sums_short_and_long_term():
    draft = _draft(line_items={"short_term_capital_gain": 1500.0, "long_term_capital_gain": 4000.0})
    f1040 = serialize_1040(draft, [], 2025)["ReturnData"]["IRS1040"]
    assert f1040["line7_capital_gain_loss"] == 5500.0


def test_tax_line_sums_ordinary_and_preferential():
    draft = _draft(line_items={"ordinary_tax": 9000.0, "preferential_tax": 750.0})
    f1040 = serialize_1040(draft, [], 2025)["ReturnData"]["IRS1040"]
    assert f1040["line16_tax"] == 9750.0


def test_agi_prefers_line_items_then_totals():
    from_line_items = serialize_1040(_draft(line_items={"agi": 71000.0}), [], 2025)
    assert from_line_items["ReturnData"]["IRS1040"]["line11_agi"] == 71000.0
    from_totals = serialize_1040(_draft(totals={"agi": 68000.0}), [], 2025)
    assert from_totals["ReturnData"]["IRS1040"]["line11_agi"] == 68000.0


def test_core_lines_map_from_line_items_and_totals():
    draft = _draft(
        line_items={
            "wages": 84000.0,
            "interest_income": 320.0,
            "qualified_dividends": 600.0,
            "ordinary_dividends": 800.0,
            "student_loan_interest_deduction": 2500.0,
            "standard_deduction": 0.0,
            "tax_withheld": 12000.0,
        },
        totals={"total_income": 85720.0, "taxable_income": 70000.0, "total_tax": 11000.0,
                "refund": 1000.0, "balance_owing": 0.0},
        credits={"standard_deduction": 14600.0, "child_tax_credit": 2000.0},
    )
    f = serialize_1040(draft, [], 2025)["ReturnData"]["IRS1040"]
    assert f["line1a_wages"] == 84000.0
    assert f["line2b_taxable_interest"] == 320.0
    assert f["line9_total_income"] == 85720.0
    assert f["line10_adjustments"] == 2500.0
    assert f["line12_standard_deduction"] == 14600.0   # from credits
    assert f["line15_taxable_income"] == 70000.0
    assert f["line19_child_tax_credit"] == 2000.0
    assert f["line24_total_tax"] == 11000.0
    assert f["line25a_federal_income_tax_withheld"] == 12000.0
    assert f["line34_overpayment"] == 1000.0


def test_slips_include_only_us_extracts():
    extracts = [
        FormExtract(form_code="W-2", jurisdiction="US", source_filename="w2.pdf", fields={"wages": 84000.0}),
        FormExtract(form_code="T4", jurisdiction="CA", source_filename="t4.pdf", fields={"employment_income": 1.0}),
        FormExtract(form_code="FORM-16", jurisdiction="IN", source_filename="f.pdf", fields={"gross_salary": 1.0}),
    ]
    slips = serialize_1040(_draft(), extracts, 2025)["ReturnData"]["Slips"]
    assert len(slips) == 1
    assert slips[0]["form_code"] == "W-2"
    assert slips[0]["fields"] == {"wages": 84000.0}


def test_missing_values_default_to_zero():
    f = serialize_1040(_draft(), [], 2025)["ReturnData"]["IRS1040"]
    assert f["line1a_wages"] == 0.0
    assert f["line24_total_tax"] == 0.0
    assert f["line11_agi"] == 0.0


def test_payload_is_json_serializable_and_keeps_false_flag():
    payload = serialize_1040(
        _draft(line_items={"wages": 84000.0}),
        [FormExtract(form_code="W-2", jurisdiction="US", source_filename="w2.pdf", fields={"wages": 84000.0})],
        2025,
        {"filing_status": "single", "num_dependents": "0"},
    )
    dumped = json.dumps(payload)
    assert '"transmissible": false' in dumped
    assert json.loads(dumped)["ReturnData"]["IRS1040"]["line1a_wages"] == 84000.0
