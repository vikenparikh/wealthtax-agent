"""IN §80GGC — deduction for donations to political parties / electoral trusts.

Income Tax Act 1961 §80GGC: 100% of the (non-cash) amount donated to a
registered political party or electoral trust is deductible. No upper cap, no
inflation indexing, no sunset. Old regime only (Chapter VI-A, disallowed under
§115BAC). Available to all individuals INCLUDING non-residents (unlike the
resident-only §80U/§80DD/§80DDB). Previously the engine ignored the input.
"""
from wealthtax_agent.engines.in_engine import compute_in_return
from wealthtax_agent.state import FormExtract


def _salary(gross: float = 1_200_000.0):
    return [FormExtract(form_code="FORM-16", jurisdiction="IN", fields={"gross_salary": gross})]


def test_80ggc_full_deduction_old_regime_resident():
    base = compute_in_return(_salary(), 2024, user_answers={}, regime="old", residency_status="ROR")
    d = compute_in_return(
        _salary(), 2024,
        user_answers={"section_80ggc_political_donation": "50000"},
        regime="old", residency_status="ROR",
    )
    # 100% of the donation is deductible.
    assert d.line_items["section_80ggc"] == 50000.0
    # Folded into chapter_via_total -> taxable income falls -> tax strictly lower.
    assert d.estimated_tax < base.estimated_tax


def test_80ggc_disallowed_in_new_regime():
    d = compute_in_return(
        _salary(), 2024,
        user_answers={"section_80ggc_political_donation": "50000"},
        regime="new", residency_status="ROR",
    )
    # Chapter VI-A disallowed under §115BAC -> deduction is zero.
    assert d.line_items["section_80ggc"] == 0.0


def test_80ggc_available_to_non_resident():
    # §80GGC is NOT resident-gated (unlike §80U/§80DD/§80DDB).
    d = compute_in_return(
        _salary(), 2024,
        user_answers={"section_80ggc_political_donation": "50000"},
        regime="old", residency_status="NR",
    )
    assert d.line_items["section_80ggc"] == 50000.0


def test_no_80ggc_input_no_deduction():
    d = compute_in_return(_salary(), 2024, user_answers={}, regime="old", residency_status="ROR")
    assert d.line_items.get("section_80ggc", 0.0) == 0.0
