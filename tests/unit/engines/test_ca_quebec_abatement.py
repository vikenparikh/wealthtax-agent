"""Federal Quebec abatement (ITA §120(2), T1 line 44000).

A Quebec resident on Dec 31 reduces federal tax by 16.5% of BASIC federal tax
(tax after non-refundable credits + DTC, BEFORE the OAS recovery tax) — because
Quebec administers programs the federal government funds elsewhere. The 16.5%
rate is long-standing and non-indexed. The engine computed a QC resident's
federal tax identically to other provinces, over-taxing every Quebec filer
federally.
"""
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.state import FormExtract


def _t4(employment: float = 100000.0, **fields):
    return [FormExtract(form_code="T4", jurisdiction="CA",
                        fields={"employment_income": employment, **fields})]


def _basic_federal(li):
    return max(0.0, li["federal_tax_before_credits"]
              - li["federal_non_refundable_credits"] - li["federal_dividend_tax_credit"])


def test_quebec_abatement_reduces_federal_tax():
    on = compute_ca_return(_t4(), 2024, province="ON", user_answers={})
    qc = compute_ca_return(_t4(), 2024, province="QC", user_answers={})
    # Basic federal tax is province-agnostic; QC gets 16.5% off.
    assert qc.line_items["quebec_abatement"] == 2451.34   # 16.5% x 14,856.61
    assert qc.line_items["federal_tax"] == 12405.27        # 14,856.61 - 2,451.34
    assert qc.line_items["federal_tax"] < on.line_items["federal_tax"]
    assert any("Quebec abatement" in n for n in qc.notes)


def test_quebec_abatement_is_16_5pct_of_basic_federal_tax():
    qc = compute_ca_return(_t4(180000.0), 2024, province="QC", user_answers={})
    expected = round(_basic_federal(qc.line_items) * 0.165, 2)
    assert qc.line_items["quebec_abatement"] == expected


def test_no_abatement_outside_quebec():
    for prov in ("ON", "AB", "BC"):
        d = compute_ca_return(_t4(), 2024, province=prov, user_answers={})
        assert d.line_items.get("quebec_abatement", 0.0) == 0.0
        assert not any("Quebec abatement" in n for n in d.notes)


def test_quebec_abatement_only_for_residents():
    d = compute_ca_return(_t4(), 2024, province="QC", user_answers={},
                          residency_status="non_resident")
    assert d.line_items.get("quebec_abatement", 0.0) == 0.0


def test_abatement_base_excludes_oas_clawback():
    # A QC senior with an OAS recovery tax: the abatement base is BASIC federal
    # tax (pre-clawback), so the abatement is NOT inflated by the clawback.
    qc = compute_ca_return(
        _t4(0.0), 2024, province="QC",
        user_answers={"pension_income": "95000", "oas_benefits": "8400", "taxpayer_age": "70"})
    # quebec_abatement must equal 16.5% of basic federal tax (which excludes the
    # clawback added into federal_tax), not 16.5% of the post-clawback figure.
    assert qc.line_items["quebec_abatement"] == round(_basic_federal(qc.line_items) * 0.165, 2)
