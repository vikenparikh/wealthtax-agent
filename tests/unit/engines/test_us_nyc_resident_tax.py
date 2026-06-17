"""New York City resident personal income tax.

A NYC resident pays NYC personal income tax ON TOP of New York State tax, on the
same NY taxable income, at progressive rates 3.078%–3.876% (fixed/non-indexed).
The engine computed NY state tax but dropped the NYC layer entirely, under-
charging every NYC resident. Gated on state="NY" + city_of_residence="NYC".
"""
import pytest
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


def _ny(wages, status="single", city=None, state="NY"):
    ua = {"filing_status": status}
    if city is not None:
        ua["city_of_residence"] = city
    return compute_us_return(
        [FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": wages})],
        year=2024, state=state, user_answers=ua)


def test_nyc_resident_pays_local_tax_on_top_of_state():
    d = _ny(88000.0, "single", city="NYC")
    # NY taxable income 80,000 (88,000 - 8,000 std). NYC single tax:
    # 12000*.03078 + 13000*.03762 + 25000*.03819 + 30000*.03876 = 2,975.97.
    assert d.line_items["state_taxable_income"] == 80000.0
    assert d.line_items["nyc_local_tax"] == 2975.97
    # State tax is unchanged; NYC is additive to total tax.
    no_city = _ny(88000.0, "single", city=None)
    assert d.line_items["state_tax"] == no_city.line_items["state_tax"]
    assert d.totals["total_tax"] == round(no_city.totals["total_tax"] + 2975.97, 2)


def test_ny_resident_outside_nyc_pays_no_local_tax():
    d = _ny(88000.0, "single", city=None)
    assert d.line_items.get("nyc_local_tax", 0.0) == 0.0


def test_nyc_uses_mfj_brackets():
    # MFJ NYC brackets are wider; verify the schedule is status-keyed.
    single = _ny(120000.0, "single", city="NYC")
    mfj = _ny(120000.0, "mfj", city="NYC")
    assert mfj.line_items["nyc_local_tax"] != single.line_items["nyc_local_tax"]
    assert mfj.line_items["nyc_local_tax"] > 0.0


def test_nyc_tax_only_in_new_york_state():
    # City "NYC" but state CA -> no NYC tax (gate on NY state).
    d = _ny(88000.0, "single", city="NYC", state="CA")
    assert d.line_items.get("nyc_local_tax", 0.0) == 0.0


def test_non_resident_city_string_variants():
    for c in ("New York City", "new york city", "nyc"):
        d = _ny(88000.0, "single", city=c)
        assert d.line_items["nyc_local_tax"] == 2975.97
