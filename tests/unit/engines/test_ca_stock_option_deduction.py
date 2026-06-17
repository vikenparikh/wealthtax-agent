"""CA Security Options Deduction — line 24900, ITA §110(1)(d).

An employee who exercises qualifying stock options includes the benefit (the
spread between FMV at exercise and the exercise price, T4 box 38) in employment
income (box 14). §110(1)(d)/(d.1) then allows a deduction of 50% of that benefit,
so only half is taxed. The 50% rate is a flat statutory fraction (non-indexed).
The $200,000 annual vesting cap on large-employer options is the filer's
asserted eligibility responsibility. Previously the engine ignored the benefit.
"""
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.state import FormExtract


def _t4(employment: float = 150000.0, withheld: float = 30000.0):
    return [FormExtract(form_code="T4", jurisdiction="CA",
                        fields={"employment_income": employment, "income_tax_deducted": withheld})]


def test_stock_option_deduction_is_half_the_benefit():
    base = compute_ca_return(_t4(), 2024, province="ON", user_answers={})
    d = compute_ca_return(_t4(), 2024, province="ON", user_answers={"security_option_benefit": "40000"})
    # 50% of the $40,000 benefit = $20,000 deduction (line 24900).
    assert d.line_items["stock_option_deduction"] == 20000.0
    # net_income falls by exactly the deduction; tax is strictly lower.
    assert round(base.totals["net_income"] - d.totals["net_income"], 2) == 20000.0
    assert d.line_items["federal_tax"] < base.line_items["federal_tax"]


def test_stock_option_benefit_surfaced():
    d = compute_ca_return(_t4(), 2024, province="ON", user_answers={"security_option_benefit": "40000"})
    assert d.line_items["security_option_benefit"] == 40000.0


def test_partial_benefit_half_deducted():
    d = compute_ca_return(_t4(), 2024, province="ON", user_answers={"security_option_benefit": "10000"})
    assert d.line_items["stock_option_deduction"] == 5000.0


def test_no_stock_option_no_deduction():
    d = compute_ca_return(_t4(), 2024, province="ON", user_answers={})
    assert d.line_items.get("stock_option_deduction", 0.0) == 0.0


def test_non_numeric_benefit_tolerated_no_crash():
    # Guards against the coercion-crash vein (#143): a worded value must not raise.
    d = compute_ca_return(_t4(), 2024, province="ON", user_answers={"security_option_benefit": "forty thousand"})
    assert d.line_items.get("stock_option_deduction", 0.0) == 0.0
