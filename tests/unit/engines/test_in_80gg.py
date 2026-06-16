"""§80GG — deduction for rent paid by a filer who receives no HRA (old regime only).

Deduction = least of (a) ₹5,000/mo = ₹60,000/yr, (b) 25% of adjusted total income,
(c) rent paid − 10% of adjusted total income. §115BAC disallows it in the new regime,
and it is mutually exclusive with the §10(13A) HRA exemption (gated on hra_received==0).
Before this fix a no-HRA renter got zero rent relief.
"""
from wealthtax_agent.engines.in_engine import compute_in_return
from wealthtax_agent.state import FormExtract


def _form16(**fields):
    return FormExtract(form_code="FORM-16", jurisdiction="IN", fields=fields)


def _draft(year, regime, gross_salary, rent, hra=0.0):
    f = {"gross_salary": gross_salary}
    if hra:
        f["hra_received"] = hra
    return compute_in_return([_form16(**f)], year=year, regime=regime,
                             user_answers={"age": "30", "annual_rent_paid": str(rent)})


def test_80gg_annual_cap_binds():
    # gross 10L → adj income 9.5L (−50k std). (a)60k (b)237,500 (c)145,000 → 60,000.
    d = _draft(2025, "old", 1000000, 240000)
    assert d.line_items["section_80gg"] == 60000.0


def test_80gg_rent_minus_10pct_binds():
    # gross 6L → adj income 5.5L. (a)60k (b)137,500 (c)84,000−55,000=29,000 → 29,000.
    d = _draft(2025, "old", 600000, 84000)
    assert d.line_items["section_80gg"] == 29000.0


def test_80gg_disallowed_in_new_regime():
    d = _draft(2025, "new", 600000, 84000)
    assert d.line_items["section_80gg"] == 0.0


def test_80gg_gated_when_hra_received():
    # Filer with HRA on the slip → §10(13A) governs; §80GG unavailable.
    d = _draft(2025, "old", 600000, 84000, hra=50000.0)
    assert d.line_items["section_80gg"] == 0.0


def test_80gg_zero_when_no_rent():
    d = _draft(2025, "old", 600000, 0)
    assert d.line_items["section_80gg"] == 0.0


def test_80gg_reduces_taxable_income():
    no_gg = _draft(2025, "old", 600000, 0)
    with_gg = _draft(2025, "old", 600000, 84000)
    # taxable income falls by exactly the §80GG deduction (29,000).
    delta = no_gg.totals["taxable_income"] - with_gg.totals["taxable_income"]
    assert round(delta, 2) == 29000.0


def test_80gg_cap_unchanged_2024():
    # The ₹60,000 cap is unchanged across years; 2024 behaves like 2025.
    d = _draft(2024, "old", 1000000, 240000)
    assert d.line_items["section_80gg"] == 60000.0
