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


def test_partb_surfaces_prepaid_taxes():
    """Part B-TTI must surface the full taxes-paid pool: TDS, TCS, advance tax,
    self-assessment tax, and their total — not TDS alone.

    FAILS before: PartB_TTI has no AdvanceTax / SelfAssessmentTax / TCS /
    TotalTaxesPaid keys."""
    itr = serialize_itr(_in_draft(advance_tax=60_000.0, self_assessment_tax=10_000.0,
                                  tcs=5_000.0, total_taxes_paid=165_000.0),
                        extracts=[], year=2025)["ITR"]
    tti = itr["PartB_TTI"]
    assert tti["TotalTDS"] == 90_000.0
    assert tti["AdvanceTax"] == 60_000.0
    assert tti["SelfAssessmentTax"] == 10_000.0
    assert tti["TCS"] == 5_000.0
    assert tti["TotalTaxesPaid"] == 165_000.0


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


def test_section_80ccd2_surfaced_in_schedule_via():
    """§80CCD(2) employer-NPS is computed and netted from income by the engine but
    was dropped from the serialized ScheduleVIA — under-reporting the deduction the
    engine already applied. It must now appear and be folded into TotalChapterVIA."""
    payload = serialize_itr(
        _in_draft(section_80ccd_2_employer_nps=50_000.0, chapter_via_total=190_000.0),
        extracts=[], year=2025,
    )
    via = payload["ITR"]["ScheduleVIA_Deductions"]
    assert via["Section80CCD2_EmployerNPS"] == 50_000.0
    # TotalChapterVIA reconciles: chapter_via_total (190k) + 80CCD2 (50k) = 240k.
    assert via["TotalChapterVIA"] == 240_000.0


def test_total_chapter_via_reconciles_gross_minus_total_income():
    """The artifact must be internally consistent: GrossTotalIncome − TotalChapterVIA
    == TotalIncome, which only holds once 80CCD(2) is in the total."""
    payload = serialize_itr(
        _in_draft(
            section_80ccd_2_employer_nps=50_000.0,
            chapter_via_total=190_000.0,
            gross_total_income=1_200_000.0,
        ),
        extracts=[], year=2025,
        # totals.taxable_income from _in_draft = 960_000 = 1_200_000 − 190_000 − 50_000
    )
    itr = payload["ITR"]
    gross = itr["PartB_TI"]["GrossTotalIncome"]
    total_via = itr["ScheduleVIA_Deductions"]["TotalChapterVIA"]
    total_income = itr["PartB_TI"]["TotalIncome"]
    assert round(gross - total_via, 2) == total_income


def test_no_employer_nps_unchanged():
    # Absent 80CCD2 → key reads 0.0, TotalChapterVIA unchanged (no regression).
    payload = serialize_itr(_in_draft(chapter_via_total=190_000.0), extracts=[], year=2025)
    via = payload["ITR"]["ScheduleVIA_Deductions"]
    assert via["Section80CCD2_EmployerNPS"] == 0.0
    assert via["TotalChapterVIA"] == 190_000.0


def test_disability_and_disease_sections_surfaced_in_schedule_via():
    """§80U/§80DD/§80DDB/§80EEB/§80GG are computed by the engine and already
    folded into chapter_via_total, but were never serialized into ScheduleVIA —
    so a hand-filer couldn't see the per-section attribution of a disability,
    specified-disease, EV-loan, or no-HRA-rent claim. Surface them WITHOUT
    touching TotalChapterVIA (the total already includes them)."""
    # 80U severe disability ₹1.25L + 80DDB senior medical ₹1L; chapter_via_total
    # = 150k(80c)+40k(80e)+125k(80u)+100k(80ddb) = 415k.
    payload = serialize_itr(
        _in_draft(
            section_80u=125_000.0,
            section_80ddb=100_000.0,
            chapter_via_total=415_000.0,
        ),
        extracts=[], year=2025,
    )
    via = payload["ITR"]["ScheduleVIA_Deductions"]
    assert via["Section80U"] == 125_000.0
    assert via["Section80DDB"] == 100_000.0
    # TotalChapterVIA must NOT double-count: chapter_via_total already includes
    # both, and there's no 80CCD2 here, so the total is exactly 415k.
    assert via["TotalChapterVIA"] == 415_000.0


def test_eeb_and_gg_and_dd_sections_surfaced():
    payload = serialize_itr(
        _in_draft(
            section_80eeb=150_000.0,   # EV-loan interest cap
            section_80gg=60_000.0,     # no-HRA rent annual cap
            section_80dd=75_000.0,     # dependant disability (non-severe)
        ),
        extracts=[], year=2025,
    )
    via = payload["ITR"]["ScheduleVIA_Deductions"]
    assert via["Section80EEB"] == 150_000.0
    assert via["Section80GG"] == 60_000.0
    assert via["Section80DD"] == 75_000.0


def test_new_via_sections_absent_default_to_zero():
    # No disability/disease/EV/rent claims → all five rows coerce to 0.0,
    # TotalChapterVIA unchanged (no regression to the existing total).
    via = serialize_itr(_in_draft(chapter_via_total=190_000.0), extracts=[], year=2025)["ITR"]["ScheduleVIA_Deductions"]
    assert via["Section80U"] == 0.0
    assert via["Section80DD"] == 0.0
    assert via["Section80DDB"] == 0.0
    assert via["Section80EEB"] == 0.0
    assert via["Section80GG"] == 0.0
    assert via["TotalChapterVIA"] == 190_000.0


def test_schedule_bp_surfaces_business_income():
    """Business/Profession income (PGBP) is folded into slab_income → taxable_income
    by the engine, but the ITR had no Business schedule — the income was invisible in
    the artifact though it was taxed. ScheduleBP_Business now surfaces it."""
    payload = serialize_itr(_in_draft(business_income=350000.0), extracts=[], year=2025)
    bp = payload["ITR"]["ScheduleBP_Business"]
    assert bp["NetIncome"] == 350000.0


def test_schedule_bp_defaults_to_zero_when_absent():
    payload = serialize_itr(_in_draft(), extracts=[], year=2025)
    assert payload["ITR"]["ScheduleBP_Business"]["NetIncome"] == 0.0


def test_schedule_bp_present_on_empty_draft():
    payload = serialize_itr(DraftReturn(jurisdiction="IN"), extracts=[], year=2025)
    assert payload["ITR"]["ScheduleBP_Business"]["NetIncome"] == 0.0
