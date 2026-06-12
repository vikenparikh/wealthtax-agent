"""Dedicated unit tests for the India ITR JSON serializer.

Previously `serialize_itr` was exercised only indirectly via the cross-border
scenario aggregate, so a serializer regression surfaced as a scenario failure
with no direct pointer. These pin its contract:
- top-level envelope (transmissible=false, note, schema_version)
- regime selection from line_items["regime"]
- section/schedule field mapping and None→0.0 coercion
- PartB totals sourced from draft.totals (not line_items)
- AttachedSources filtered to IN-jurisdiction extracts only
"""
from __future__ import annotations

from wealthtax_agent.filing.in_itr import serialize_itr
from wealthtax_agent.state import DraftReturn, FormExtract


def _in_draft(**li_overrides) -> DraftReturn:
    line_items = {
        "regime": 1.0,
        "gross_salary": 1_200_000.0,
        "standard_deduction_salary": 50_000.0,
        "income_salary": 1_150_000.0,
        "section_80c": 150_000.0,
        "section_80e": 40_000.0,
        "chapter_via_total": 190_000.0,
        "ltcg_equity_total": 200_000.0,
        "ltcg_equity_taxable": 100_000.0,
        "ltcg_equity_exempt": 100_000.0,
        "slab_tax": 100_000.0,
        "cess": 4_000.0,
        "total_tds": 90_000.0,
        # bank_interest deliberately absent → serializer must coerce to 0.0
    }
    line_items.update(li_overrides)
    return DraftReturn(
        jurisdiction="IN",
        line_items=line_items,
        totals={
            "taxable_income": 960_000.0,
            "total_tax": 104_000.0,
            "refund": 0.0,
            "balance_owing": 14_000.0,
        },
    )


def test_envelope_is_non_transmissible_and_versioned():
    payload = serialize_itr(_in_draft(), extracts=[], year=2025)
    assert payload["transmissible"] is False
    assert payload["schema_version"] == "in-itr-0.1"
    assert "Not submitted" in payload["note"]
    assert payload["ITR"]["PartA_GEN"]["AssessmentYear"] == 2025


def test_regime_new_when_flag_set_old_otherwise():
    new = serialize_itr(_in_draft(regime=1.0), extracts=[], year=2025)
    old = serialize_itr(_in_draft(regime=0.0), extracts=[], year=2025)
    assert new["ITR"]["PartA_GEN"]["Regime"] == "New"
    assert old["ITR"]["PartA_GEN"]["Regime"] == "Old"


def test_schedule_field_mapping_and_none_coercion():
    itr = serialize_itr(_in_draft(), extracts=[], year=2025)["ITR"]
    assert itr["ScheduleS_Salary"]["GrossSalary"] == 1_200_000.0
    assert itr["ScheduleVIA_Deductions"]["Section80C"] == 150_000.0
    assert itr["ScheduleVIA_Deductions"]["Section80E"] == 40_000.0
    assert itr["ScheduleCG_CapitalGains"]["LTCGEquityTaxable"] == 100_000.0
    # absent line item must coerce to 0.0, not crash or propagate null
    assert itr["ScheduleOS_OtherSources"]["BankInterest"] == 0.0


def test_partb_totals_come_from_totals_not_line_items():
    itr = serialize_itr(_in_draft(), extracts=[], year=2025)["ITR"]
    assert itr["PartB_TI"]["TotalIncome"] == 960_000.0
    assert itr["PartB_TTI"]["TotalTax"] == 104_000.0
    assert itr["PartB_TTI"]["BalanceOwing"] == 14_000.0


def test_attached_sources_filtered_to_india_only():
    extracts = [
        FormExtract(form_code="FORM16", jurisdiction="IN", source_filename="form16.pdf"),
        FormExtract(form_code="W-2", jurisdiction="US", source_filename="w2.pdf"),
        FormExtract(form_code="AIS", jurisdiction="IN", source_filename="ais.pdf"),
    ]
    sources = serialize_itr(_in_draft(), extracts=extracts, year=2025)["ITR"]["AttachedSources"]
    codes = {s["form_code"] for s in sources}
    assert codes == {"FORM16", "AIS"}  # US extract excluded
    assert all(s["source_filename"].endswith(".pdf") for s in sources)


def test_empty_draft_serializes_to_zeros_without_error():
    payload = serialize_itr(DraftReturn(jurisdiction="IN"), extracts=[], year=2024)
    itr = payload["ITR"]
    assert itr["ScheduleS_Salary"]["GrossSalary"] == 0.0
    assert itr["PartB_TI"]["TotalIncome"] == 0.0
    assert payload["transmissible"] is False
