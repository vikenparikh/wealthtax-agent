"""Ontario provincial surtax (Form ON428).

Ontario levies a surtax on basic provincial tax (after non-refundable credits):
20% of the amount over the first threshold PLUS 36% of the amount over the
second. 2024 thresholds: $5,554 / $7,108. The 20%/36% rates are fixed; the
thresholds are indexed and stored per-year. Previously the engine stopped at
basic provincial tax, under-taxing every meaningful-income Ontario filer (ON is
the default province).
"""
from wealthtax_agent.engines.ca_engine import compute_ca_return
from wealthtax_agent.state import FormExtract


def _t4(employment: float):
    return [FormExtract(form_code="T4", jurisdiction="CA", fields={"employment_income": employment})]


def test_ontario_surtax_both_tiers_2024():
    d = compute_ca_return(_t4(120000.0), 2024, province="ON", user_answers={})
    # basic ON tax (post-credit) = 8,588.39.
    # surtax = 20%x(8588.39-5554) + 36%x(8588.39-7108) = 606.88 + 532.94 = 1,139.82
    assert d.line_items["provincial_surtax"] == 1139.82
    # provincial_tax now includes the Ontario Health Premium ($750 at $120k taxable).
    assert d.line_items["provincial_tax"] == 10478.21


def test_no_surtax_below_first_threshold():
    # $60k -> basic ON tax 2,754.56 < $5,554 -> no surtax.
    d = compute_ca_return(_t4(60000.0), 2024, province="ON", user_answers={})
    assert d.line_items["provincial_surtax"] == 0.0
    # provincial_tax now includes the Ontario Health Premium ($600 at $60k taxable).
    assert d.line_items["provincial_tax"] == 3354.56


def test_ontario_surtax_2023_thresholds():
    # 2023 thresholds $5,315 / $6,802. Just assert a positive surtax applies
    # (per-year thresholds wired) for a high-income ON filer.
    d = compute_ca_return(_t4(120000.0), 2023, province="ON", user_answers={})
    assert d.line_items["provincial_surtax"] > 0.0


def test_other_province_no_surtax():
    # Alberta has no surtax table -> provincial_tax unaffected (no regression).
    d = compute_ca_return(_t4(120000.0), 2024, province="AB", user_answers={})
    assert d.line_items.get("provincial_surtax", 0.0) == 0.0
