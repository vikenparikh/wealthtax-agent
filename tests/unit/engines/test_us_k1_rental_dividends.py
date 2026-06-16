"""US K-1 box 2 (rental real estate) and box 6a (ordinary dividends) income.

The K-1 extractor captures all 7 boxes but the engine read only 5 — box 2 net rental
real-estate income and box 6a total ordinary dividends were dropped. Box 6a is the
worse bug: box 6b (qualified) was added to qualified_dividends and then backed out of
the ordinary base at the preferential rate, but without 6a in ordinary income that
back-out subtracted income that was never added — under-taxing the dividend.
"""
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


def _w2(wages=80000.0):
    return FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": wages})


def _k1(**fields):
    return FormExtract(form_code="K-1", jurisdiction="US", fields=fields)


def _single(*extracts):
    return compute_us_return(list(extracts), year=2024,
                             user_answers={"filing_status": "single", "num_dependents": "0"})


def test_k1_box2_rental_in_total_income():
    d = _single(_w2(), _k1(net_rental_real_estate_income=20000.0))
    base = _single(_w2())
    assert d.line_items["k1_rental_real_estate"] == 20000.0
    assert round(d.totals["total_income"] - base.totals["total_income"], 2) == 20000.0


def test_k1_box6a_ordinary_dividends_in_income():
    # Box 6a total dividend must enter ordinary_dividends (and total income).
    d = _single(_w2(), _k1(ordinary_dividends=4000.0, qualified_dividends=4000.0))
    base = _single(_w2())
    assert d.line_items["ordinary_dividends"] == 4000.0
    assert round(d.totals["total_income"] - base.totals["total_income"], 2) == 4000.0


def test_k1_dividends_not_undertaxed_by_phantom_backout():
    # With box 6a now in ordinary income, adding a fully-qualified K-1 dividend must
    # INCREASE tax (preferential rate on real income), never decrease it.
    base = _single(_w2())
    with_div = _single(_w2(), _k1(ordinary_dividends=4000.0, qualified_dividends=4000.0))
    assert with_div.estimated_tax >= base.estimated_tax


def test_k1_rental_increases_tax():
    base = _single(_w2())
    with_rental = _single(_w2(), _k1(net_rental_real_estate_income=20000.0))
    assert with_rental.estimated_tax > base.estimated_tax


def test_k1_business_income_unchanged_regression():
    # Box 1 ordinary business income was already read — adding the new reads must
    # not disturb it.
    d = _single(_w2(), _k1(ordinary_business_income=50000.0))
    assert d.line_items["self_employment_income"] == 50000.0
    assert d.line_items["k1_rental_real_estate"] == 0.0


def test_no_k1_no_regression():
    d = _single(_w2())
    assert d.line_items["k1_rental_real_estate"] == 0.0
