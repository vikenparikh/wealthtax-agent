"""Yonkers resident income tax surcharge.

A Yonkers resident pays a surcharge of 16.75% of their net New York State tax
(IT-201 / Form IT-201-ATT). Fixed/non-indexed. The engine modelled NY state tax
and NYC local tax but not the Yonkers surcharge, under-charging Yonkers
residents. Gated on state="NY" + city_of_residence="Yonkers".
"""
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


def _ny(wages, status="single", city=None, state="NY"):
    ua = {"filing_status": status}
    if city is not None:
        ua["city_of_residence"] = city
    return compute_us_return(
        [FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": wages})],
        year=2024, state=state, user_answers=ua)


def test_yonkers_resident_pays_16_75pct_of_state_tax():
    d = _ny(88000.0, "single", city="Yonkers")
    # NY state tax 4,235.00; Yonkers surcharge 16.75% = 709.36.
    assert d.line_items["state_tax"] == 4235.0
    assert d.line_items["yonkers_surcharge"] == 709.36
    no_city = _ny(88000.0, "single", city=None)
    assert d.totals["total_tax"] == round(no_city.totals["total_tax"] + 709.36, 2)
    # Yonkers residents are not NYC residents -> no NYC tax.
    assert d.line_items["nyc_local_tax"] == 0.0


def test_non_yonkers_ny_resident_no_surcharge():
    d = _ny(88000.0, "single", city=None)
    assert d.line_items.get("yonkers_surcharge", 0.0) == 0.0


def test_yonkers_only_in_new_york_state():
    d = _ny(88000.0, "single", city="Yonkers", state="CA")
    assert d.line_items.get("yonkers_surcharge", 0.0) == 0.0


def test_yonkers_string_variants():
    for c in ("Yonkers", "yonkers", "YONKERS"):
        d = _ny(88000.0, "single", city=c)
        assert d.line_items["yonkers_surcharge"] == 709.36
