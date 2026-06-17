"""India §87A rebate eligibility must use TOTAL income (incl. capital gains).

§87A caps the rebate's income ceiling (₹7,00,000 new / ₹5,00,000 old) on TOTAL
income per §2(45) — which INCLUDES special-rate capital gains. The engine tested
only slab income (which excludes equity/other CG), so a salaried filer with a
large capital gain slipped under the threshold and wrongly got the rebate. (The
rebate AMOUNT is still correctly limited to slab tax — it never offsets CG tax.)
"""
from wealthtax_agent.engines.in_engine import compute_in_return
from wealthtax_agent.state import FormExtract


def _salary_and_ltcg_other(gross_salary: float, ltcg_other: float):
    return [
        FormExtract(form_code="FORM-16", jurisdiction="IN", fields={"gross_salary": gross_salary}),
        FormExtract(form_code="STOCK-GAIN", jurisdiction="IN", fields={"ltcg_other": ltcg_other}),
    ]


def test_no_87a_rebate_when_cg_pushes_total_over_threshold_new_regime():
    # Salary slab income ₹6,50,000 (<= ₹7L) but + ₹10,00,000 LTCG-other ->
    # total income ₹16,50,000 > ₹7L -> rebate barred.
    d = compute_in_return(_salary_and_ltcg_other(700000.0, 1000000.0), 2024,
                          regime="new", residency_status="ROR")
    assert d.credits["rebate_87a"] == 0.0
    # slab 20,000 + LTCG 2,00,000 = 2,20,000; +4% cess = 2,28,800.
    assert d.estimated_tax == 228800.0


def test_no_87a_rebate_when_cg_over_threshold_old_regime():
    # Slab income ₹4,80,000 (<= ₹5L) + ₹7,00,000 LTCG-other -> total > ₹5L.
    d = compute_in_return(_salary_and_ltcg_other(530000.0, 700000.0), 2024,
                          regime="old", residency_status="ROR")
    assert d.credits["rebate_87a"] == 0.0
    # slab 11,500 + LTCG 1,40,000 = 1,51,500; +4% cess = 1,57,560.
    assert d.estimated_tax == 157560.0


def test_87a_rebate_preserved_for_salary_only_filer():
    # Regression: no capital gains, slab income ₹5,00,000 <= ₹7L -> full rebate.
    d = compute_in_return(
        [FormExtract(form_code="FORM-16", jurisdiction="IN", fields={"gross_salary": 550000.0})],
        2024, regime="new", residency_status="ROR")
    assert d.credits["rebate_87a"] == 10000.0  # slab tax 5% x (500000-300000)
    assert d.estimated_tax == 0.0


def test_87a_rebate_allowed_at_exact_threshold_with_cg():
    # Salary income ₹6,00,000 + ₹1,00,000 LTCG-other = total ₹7,00,000 exactly
    # (<= threshold) -> rebate still allowed.
    d = compute_in_return(_salary_and_ltcg_other(650000.0, 100000.0), 2024,
                          regime="new", residency_status="ROR")
    assert d.credits["rebate_87a"] == 15000.0
