"""Special-rate long-term gains (unrecaptured §1250 at 25%, collectibles at 28%)
follow the IRS Schedule D Tax Worksheet: each is taxed at a FLAT maximum rate,
and the only relief is a single GLOBAL ceiling — the whole computation may not
exceed the regular tax on all taxable income.

REGRESSION history:
* Original bug: the engine read the ordinary marginal rate at `ordinary_taxable`
  (bottom of the stack). When a deduction zeroed ordinary income that rate was
  10%, so §1250/collectibles were taxed at 10% — badly UNDER-taxed.
* First (rejected) fix: a per-slice `min(cap, incremental ordinary tax at the
  slice's stacked position)`. That is NOT the worksheet — it under-taxes a slice
  that sits in a sub-cap ordinary bracket while the global ceiling doesn't bind
  (~33% of cases, up to ~$4k). The `test_divergence_*` case below pins that.

Correct behaviour: §1250 flat 25%, collectibles flat 28%, then
`total = min(ordinary + 0/15/20% + flat_special, regular_tax_on_all_taxable_income)`.
"""
from wealthtax_agent.engines.us_engine import compute_us_return
from wealthtax_agent.state import FormExtract


def _w2(wages: float) -> FormExtract:
    return FormExtract(form_code="W-2", jurisdiction="US", fields={"wages": wages})


def _mortgage(amount: float) -> FormExtract:
    # Schedule A itemized mortgage interest — the lever used to wipe ordinary
    # income to $0 while leaving preferential income in taxable income.
    return FormExtract(form_code="SCH-A", jurisdiction="US",
                       fields={"mortgage_interest": amount})


def _ltcg_with_special(regular: float, sec1250: float, collectibles: float) -> list:
    # §1250/collectibles are 1099-DIV boxes 2b/2d and are SUBSETS of total
    # long_gain, so the Schedule D total must include them.
    total_long = regular + sec1250 + collectibles
    return [
        FormExtract(form_code="SCH-D", jurisdiction="US",
                    fields={"net_long_term_capital_gain": total_long}),
        FormExtract(form_code="1099-DIV", jurisdiction="US",
                    fields={"unrecaptured_section_1250_gain": sec1250,
                            "collectibles_28_pct": collectibles}),
    ]


def _run(extracts, status="single"):
    return compute_us_return(extracts, year=2024, user_answers={"filing_status": status})


def test_special_gains_stacked_into_top_brackets_taxed_at_caps():
    # Deduction wipes ordinary income to $0, but $250k regular LTCG sits below,
    # lifting the $60k §1250 and $60k collectibles into the 35% bracket — the
    # regular-tax ceiling (~$106k on $370k TI) does NOT bind, so each is taxed at
    # its flat cap:  §1250 0.25*60k = 15,000 + collectibles 0.28*60k = 16,800.
    # PRE-original-bug this was 10% flat → 12,000.
    extracts = [_w2(30_000), _mortgage(30_000),
                *_ltcg_with_special(regular=250_000, sec1250=60_000, collectibles=60_000)]
    d = _run(extracts)
    assert d.line_items["ordinary_tax"] == 0.0, d.line_items["ordinary_tax"]
    assert d.line_items["special_rate_tax"] == 31_800.0, d.line_items["special_rate_tax"]


def test_divergence_flat_rate_not_per_slice_ordinary_rate():
    # THE case that distinguishes the worksheet (flat 25%/28%) from the rejected
    # per-slice model. Ordinary $0, $50k regular LTCG, then $60k §1250 + $60k
    # collectibles. TI = $170k. The special slices land in the 22–24% ordinary
    # brackets, so a per-slice ordinary cap would charge ~22–24% (special ≈
    # 27,790). The IRS worksheet charges FLAT 25%/28% = 31,800 because the global
    # regular-tax ceiling ($33,842 on $170k) does NOT bind
    # (ordinary 0 + 0/15/20% on 50k LTCG = 446.25 + 31,800 = 32,246.25 < 33,842).
    extracts = [_w2(14_600),  # exactly absorbed by the 2024 single std deduction
                *_ltcg_with_special(regular=50_000, sec1250=60_000, collectibles=60_000)]
    d = _run(extracts)
    assert d.line_items["ordinary_tax"] == 0.0, d.line_items["ordinary_tax"]
    # Flat 25%/28% — NOT the ~27,790 the per-slice model produced.
    assert d.line_items["special_rate_tax"] == 31_800.0, d.line_items["special_rate_tax"]
    # Total = ordinary 0 + preferential (0/15/20% on 50k) + flat special; ceiling
    # not binding.
    assert d.line_items["federal_tax"] == 32_246.25, d.line_items["federal_tax"]


def test_flat_caps_apply_for_married_joint_filer():
    # Same mechanism holds under MFJ brackets: ordinary wiped, $500k regular LTCG
    # lifts the $60k §1250 + $60k collectibles into the top MFJ brackets, ceiling
    # doesn't bind → flat 25%/28% = 15,000 + 16,800 = 31,800.
    extracts = [_w2(60_000), _mortgage(60_000),
                *_ltcg_with_special(regular=500_000, sec1250=60_000, collectibles=60_000)]
    d = _run(extracts, status="married_joint")
    assert d.line_items["ordinary_tax"] == 0.0, d.line_items["ordinary_tax"]
    assert d.line_items["special_rate_tax"] == 31_800.0, d.line_items["special_rate_tax"]


def test_global_ceiling_protects_low_income_filer():
    # NON-REGRESSION (ceiling, not floor): a low-income filer whose all-ordinary
    # tax is BELOW the flat 25% result pays the lower amount via the global min.
    # Wages $14,600 absorbed by the std deduction → ordinary $0; a $5,000 §1250
    # gain is the only taxable income. Flat special would be 0.25*5,000 = 1,250,
    # but the regular tax on $5,000 is 0.10*5,000 = 500, so the ceiling binds.
    extracts = [_w2(14_600), *_ltcg_with_special(regular=0, sec1250=5_000, collectibles=0)]
    d = _run(extracts)
    assert d.line_items["ordinary_tax"] == 0.0, d.line_items["ordinary_tax"]
    # special_rate_tax is reported as the amount ACTUALLY paid after the ceiling
    # ($500 = the ordinary 10% rate), not the flat $1,250 — the cap is a ceiling.
    assert d.line_items["special_rate_tax"] == 500.0, d.line_items["special_rate_tax"]
    assert d.line_items["federal_tax"] == 500.0, d.line_items["federal_tax"]
