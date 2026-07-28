"""US preferential-rate income (qualified dividends + LTCG) must be capped at
taxable income.

IRS Qualified Dividends & Capital Gain / Schedule D Tax Worksheets tax
preferential income only up to taxable income: when the standard/itemized
deduction exceeds ordinary income, the excess absorbs preferential income too —
you never pay 0/15/20% on more gain than remains in taxable income.

REGRESSION: the engine floored `ordinary_taxable` at 0 but did not shrink the
preferential side, so a filer whose deduction exceeded ordinary income was
OVER-taxed on the full preferential amount (e.g. $50k of qualified dividends as
sole income was billed $446 instead of $0).
"""
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


def _w2(wages: float) -> FormExtract:
    return FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": wages})


def _div(qualified: float) -> FormExtract:
    return FormExtract(form_code="1099-DIV", jurisdiction="US",
                       fields={"ordinary_dividends": qualified, "qualified_dividends": qualified})


def _ltcg(amount: float) -> FormExtract:
    return FormExtract(form_code="SCH-D", jurisdiction="US",
                       fields={"net_long_term_capital_gain": amount})


def _run(extracts, status="single"):
    return compute_us_return(extracts, year=2024, user_answers={"filing_status": status})


def test_sole_qualified_dividends_under_0pct_breakpoint_is_zero():
    # $50k qualified dividends, no other income. Std deduction $14,600 →
    # taxable income $35,400, entirely preferential and BELOW the 2024 single 0%
    # LTCG breakpoint ($47,025) → correct federal preferential tax = $0.
    # Pre-fix the engine taxed the full $50k → $446.25.
    d = _run([_div(50_000)])
    assert d.line_items["preferential_tax"] == 0.0, d.line_items["preferential_tax"]


def test_ltcg_with_deduction_absorbing_ordinary_not_overtaxed():
    # $5k wages + $100k LTCG. AGI $105k; taxable income $90,400; the $14,600
    # deduction wipes the $5k wages and absorbs $9,600 of LTCG, so only $90,400
    # of preferential income is taxed: 15% × ($90,400 − $47,025) = $6,506.25.
    # Pre-fix: 15% × ($100,000 − $47,025) = $7,946.25 (overcharge $1,440).
    d = _run([_w2(5_000), _ltcg(100_000)])
    assert d.line_items["preferential_tax"] == 6_506.25, d.line_items["preferential_tax"]


def test_normal_case_unchanged():
    # Ordinary income comfortably exceeds the deduction, so the cap does not bind
    # and behaviour is unchanged: $100k wages + $10k LTCG → 15% × $10k = $1,500.
    d = _run([_w2(100_000), _ltcg(10_000)])
    assert d.line_items["preferential_tax"] == 1_500.0, d.line_items["preferential_tax"]


def test_preferential_tax_never_exceeds_uncapped():
    # The cap only ever REDUCES tax (fail-safe): across the deduction boundary,
    # preferential tax is monotone and never taxes more gain than taxable income.
    below = _run([_div(30_000)])        # taxable 15,400 — all under 0% breakpoint
    at = _run([_div(60_000)])           # taxable 45,400 — still under 0% breakpoint
    assert below.line_items["preferential_tax"] == 0.0
    assert at.line_items["preferential_tax"] == 0.0
