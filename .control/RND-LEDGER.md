# wealthtax-agent R&D Ledger

status: ACTIVE

---

## Cycle 1 — RESEARCH (2026-06-13)

### Proposed improvement: Fix §1091 wash-sale replacement-lot over-attribution

**What:** The `detect_wash_sales` engine (`engines/wash_sale.py`) does not track how many
shares of a replacement lot have been *consumed* across multiple loss sells processed in
the same call. When two loss sells for the same ticker both fall within the 61-day window
of a single replacement buy, the engine assigns that replacement buy to *both* sells without
subtracting the shares already used, causing the disallowed-loss amount and the replacement
lot's adjusted basis to be over-reported.

**Confirmed bug (reproduced in RESEARCH step):**

```
src1  QQQ buy  Jan 1  20 sh @ $100   (source lot)
s1    QQQ sell Jan 10 10 sh proceeds=$90  → cost=$100/sh, loss=$100
s2    QQQ sell Jan 11 10 sh proceeds=$89  → cost=$100/sh, loss=$110
rep   QQQ buy  Jan 20 10 sh @ $95   (replacement — 10 shares ONLY)
```

Current engine output:
- s1 → rep, disallowed $100  ✗
- s2 → rep, disallowed $110  ✗  (rep only has 10 shares; fully consumed by s1)
- rep.adjusted_basis_cents = 116,000  (should be 105,000)

§1091-correct output:
- s1 → rep, disallowed $100  (rep 10 sh fully consumed)
- s2 → no replacement available → loss is ALLOWED (no disallowance)
- rep.adjusted_basis_cents = 105,000

**Why measurable / metric:**
- The fix is verifiable with a deterministic unit test that fails before the fix and
  passes after it (fail-before / pass-after gate).
- Metric: `rep.adjusted_basis_cents` must equal 105,000 (not 116,000) and only 1
  WashSaleResult must be produced (not 2) for the minimal reproduction above.
- Tax correctness impact: over-reported disallowances inflate the replacement lot's
  cost basis, causing the user's future gain on that lot to be under-reported — a
  downstream tax error that flows into Schedule D / Form 8949.

**Why this is the highest-value improvement this cycle:**
- It is a correctness bug in the core §1091 tax calculation, not a UX or perf issue.
- The current test suite has no test for the multi-sell / shared-replacement-lot scenario;
  the gap is real (confirmed by reading all tests in `tests/test_wash_sale.py`).
- The fix is narrow, reversible, and self-contained: add a `_consumed_qty` dict keyed
  by `rep_buy.id`, subtract `covered_qty` from its available shares, and skip when
  available shares reach zero.
- The event→DB persistence work (PRs #43/#44) was just completed; the MAINTAIN task
  of proving a real trade.filled persists a row is already covered by
  `TestHandleTradeFilledBuy.test_buy_creates_lot_row` and the full E2E fakeredis test
  in `TestEventBusEndToEnd`. No new value from repeating that here.

**Verify plan:**

Fail-before:
```python
# test_wash_sale_replacement_capacity.py
def test_replacement_lot_not_reused_beyond_its_share_count():
    lots = [
        LotRecord('src1', 'QQQ', 'buy',  date(2024, 1,  1), 20, 200_000),
        LotRecord('s1',   'QQQ', 'sell', date(2024, 1, 10), 10,  90_000),
        LotRecord('s2',   'QQQ', 'sell', date(2024, 1, 11), 10,  89_000),
        LotRecord('rep',  'QQQ', 'buy',  date(2024, 1, 20), 10,  95_000),
    ]
    lots[1].adjusted_basis_cents = 100_000
    lots[2].adjusted_basis_cents = 100_000
    adjusted, results = detect_wash_sales(lots)
    # rep has only 10 shares; s1 consumes them fully
    # s2 has no replacement → loss is allowed
    assert len(results) == 1          # FAILS currently (returns 2)
    assert results[0].sell_lot_id == 's1'
    rep = next(l for l in adjusted if l.id == 'rep')
    assert rep.adjusted_basis_cents == 105_000  # FAILS currently (returns 116000)
```

Pass-after: same test passes once `_consumed_qty` tracking is added to the inner loop.

**Pipeline proof:** `951 passed` on `fix/alembic-event-persistence-tables` (baseline confirmed
in RESEARCH step). After fix, count must be >= 952 (existing 951 + new test(s)).

**Gated?** No — purely advisory/simulation tax logic. No IRS filing, no e-file, no credentials.

**Status:** RESEARCH complete. DEVELOP not yet started.

---

### Honesty note

- Test count at research time: **951 passing** (not ~948 as in charter brief; confirmed by
  running `pytest --no-cov` in the RESEARCH step).
- The MAINTAIN item "prove a trade.filled persists a row" is already covered by existing tests
  (`TestHandleTradeFilledBuy.test_buy_creates_lot_row`, `TestEventBusEndToEnd`). No additional
  work needed there.
- The replacement-lot capacity bug was found by code-reading + a live reproduction probe, not
  from an existing failing test. It is a real gap, not manufactured.
- No holding-period tack-on (§1091 also requires the replacement lot to tack on the holding
  period of the sold shares) was implemented or tested — that is a separate, lower-urgency
  correctness item and is NOT proposed for this cycle (honest scope boundary).

---

## Cycle 1 — DEVELOP (2026-06-13)

### Shipped: §1091 wash-sale replacement-lot over-attribution fix → PR #46

**Branch:** `fix/wash-sale-replacement-capacity` (off `origin/main`).

**Change:** `engines/wash_sale.py` — added a `consumed_qty` map (`rep_buy.id -> shares used`)
carried across the sells loop. Available shares = `rep_buy.quantity - consumed`; a replacement
with no remaining capacity is skipped, so a loss sell with no replacement shares left keeps its
loss allowed. 7-line behavioural change, narrow and reversible.

**Test:** `tests/test_wash_sale_replacement_capacity.py` (2 tests) — proven FAIL-before /
PASS-after by reverting only the engine hunk:
- Before: `len(results) == 2` (`[('s1', 10000), ('s2', 11000)]`), `rep.adjusted_basis_cents == 116_000`.
- After:  `len(results) == 1` (`s1` only), s2 loss ALLOWED, `rep.adjusted_basis_cents == 105_000`.
- Plus a proportional-split case: 15-share rep across two 10-share sells → s1 $100 disallowed,
  s2 $50 disallowed, rep basis += 15_000 (never more).

**Before/after delta:**
| Metric | Before | After |
|---|---|---|
| Disallowances for the shared-replacement scenario | 2 (over-attributed) | 1 (§1091-correct) |
| `rep.adjusted_basis_cents` (10+10 sells, 10-share rep) | 116_000 (inflated) | 105_000 (correct) |
| Total disallowed loss | 21_000 | 10_000 |
| Downstream effect | future gain under-reported on Sch D / 8949 | correct |
| Test count | 951 passing | **953 passing** (+2) |
| Existing `tests/test_wash_sale.py` | green | green (no regressions) |

**Scope honesty:** paper tax-CALC only; no filing/NETFILE/MeF/live paths touched. Holding-period
tack-on (separate §1091 requirement) still NOT implemented — remains a future-cycle item.

---

## Cycle 2 — RESEARCH + DEVELOP (2026-06-13)

### Improvement: Include rents/royalties in the NIIT base (§1411) → PR #47

**Research method:** read the full US tax-assembly path in `engines/us_engine.py`
(QDCGT worksheet, CTC phaseout, AMT, NIIT, FICA). Two real bugs surfaced:
1. **NIIT omits rental + Schedule E income** (line ~412): `investment_income` summed
   interest + ordinary_dividends + gains + royalties but NOT `misc_rents` (1099-MISC
   rents) or `sch_e_supplemental` — both flow into AGI yet escaped the 3.8% tax.
2. CTC phaseout uses `(agi - start) // 1000` (truncates) but §24(b)(2) says "or
   fraction thereof" → should round UP. (Lower value: ≤$50, narrow AGI band — logged
   as a future-cycle candidate, NOT shipped this cycle.)

**Why NIIT chosen (highest-value):** dollar impact scales with rental income × 3.8%
(can be thousands), affects any high-earner landlord, vs. the CTC bug's ≤$50 in a
narrow band. §1411 inclusion of rents/royalties is unambiguous for the default
(passive) case; active business income (Sch C, K-1) is tracked separately and stays
correctly excluded — so the fix is clean with no passive/active ambiguity in the test.

**Why measurable / verify-plan (fails-before / passes-after):**
- `test_niit_includes_rental_income`: $220k W-2 + $30k rents → NIIT 0 before, $1,140 after.
- `test_niit_includes_schedule_e_supplemental_income`: $210k W-2 + $40k Sch E → $1,520 (0 before).
- `test_niit_excludes_active_business_income` (guard): Sch C $300k → NIIT $0 (both before/after).
- Proven by reverting only the engine hunk: the two "includes" tests fail (`0.0 == 1140.0` /
  `0.0 == 1520.0`), then pass with the fix.

**Before/after delta:**
| Metric | Before | After |
|---|---|---|
| NIIT on $30k passive rental (AGI 250k, single) | $0 (omitted) | $1,140 (3.8%) |
| NIIT on $40k Schedule E (AGI 250k, single) | $0 (omitted) | $1,520 (3.8%) |
| NIIT on $300k Schedule C (active) | $0 | $0 (correctly excluded) |
| Test count | 953 passing | **956 passing** (+3) |
| Existing NIIT / engine tests | green | green (no regressions) |

**Scope honesty:** paper tax-CALC only; no filing/NETFILE/MeF/live touched. CTC
fraction-thereof rounding and NIIT MAGI-vs-AGI (FEIE add-back) remain future-cycle items.

---

## Cycle 3 — RESEARCH + DEVELOP (2026-06-13)

### Improvement: Social Security taxed via provisional-income worksheet, not flat 85% → PR #48

**Research method:** the engine self-flagged the gap in a note ("Social Security inclusion
uses a flat 85% approximation; real rule is income-tested"). Confirmed at
`us_engine.py:322` — `taxable_ssa = ssa_net * 0.85` unconditionally. Also confirmed NO
engine-level SS-taxability test existed (only form extraction) — a coverage gap.

**Why highest-value:** affects an entire population (retirees) and the magnitude is large
— a flat 85% inclusion taxes SS-only / low-income retirees who legally owe $0 on benefits.
Unlike the deferred CTC rounding (≤$50, narrow band), this can mis-state taxable income by
the full 85% of benefits. The IRS Pub 915 worksheet is deterministic and well-defined.

**Why measurable / verify-plan (fails-before / passes-after):**
- SS-only $24k single → $0 taxable (was $20,400).
- $20k pension + $20k SS single → $2,500 (50% tier; was $17,000).
- MFJ $10k pension + $30k SS → $0 (base1 32,000; was $25,500).
- GUARD: $100k pension + $30k SS → $25,500 (85% cap, UNCHANGED — proves high earners were
  already correct and the fix does not over-correct).
- Proven by reverting only the engine hunk: 3 fail (20400==0, 17000==2500, 25500==0), the
  guard passes both before/after.

**Before/after delta:**
| Scenario | Before (flat 85%) | After (worksheet) |
|---|---|---|
| SS-only $24k, single | $20,400 taxable | $0 |
| $20k pension + $20k SS, single | $17,000 | $2,500 |
| MFJ $10k pension + $30k SS | $25,500 | $0 |
| $100k pension + $30k SS (guard) | $25,500 | $25,500 (unchanged) |
| Test count | 956 passing | **960 passing** (+4) |
| Engine SS-taxability test coverage | none | 4 tests |

**Scope honesty:** paper tax-CALC only; no filing/live touched. Simplification: tax-exempt
interest not added to provisional income (not tracked by prototype). Future-cycle items still
open: CTC fraction-thereof rounding; NIIT MAGI-vs-AGI (FEIE add-back); §1091 holding-period tack-on.

---

## Cycle 4 — RESEARCH + DEVELOP (2026-06-13)

### Improvement: §1222 short/long netting + §1211 $3,000 current-year capital-loss limit → PR #49

**Research method:** read the US capital-gains section of `us_engine.py`. The income sum used
`max(0.0, short_gain) + max(0.0, long_gain)` (lines ~364-365) — each character floored at zero.
Cross-checked: only *prior-year* carryover (`prior_capital_losses` user answer) reduced ordinary
income; current-year losses had no path. (Rejected alternatives this cycle: §1091 holding-period
tack-on — inert, nothing downstream consumes a replacement lot's holding period; AMT cap-gains
carve-out — the AMT function is already "highly simplified" so an exact-value test would be
arbitrary.)

**Why highest-value:** affects a very large, ordinary population — anyone who sold investments at
a net loss in the year (extremely common). Two correctness failures: (1) current-year net loss
gave $0 deduction vs the $3,000 §1211(b) allowance; (2) short/long not netted (§1222) overstated
income. Both have clear, often-large dollar impact and are unambiguous statute.

**Why measurable / verify-plan (fails-before / passes-after):**
- $5k current ST loss → $3,000 deducted + $2,000 carryover (was $0).
- +$10k ST, −$4k LT → net $6k ST gain (was $10k taxed).
- +$2k ST, −$9k LT → $3,000 deducted + $4,000 carryover (was $2k taxed).
- GUARD: +$5k ST, +$8k LT unchanged.
- Proven by reverting only the engine hunk: 4 assertions fail (0.0==3000.0, 10000.0==6000.0,
  KeyError capital_loss_carryover), then pass.

**Before/after delta:**
| Scenario | Before | After |
|---|---|---|
| $5k current-year ST loss | $0 deducted, loss lost | $3,000 deducted + $2,000 carryover |
| +$10k ST / −$4k LT | income $10,000 | net $6,000 ST gain |
| +$2k ST / −$9k LT | $2,000 taxed | $3,000 deducted + $4,000 carryover |
| Prior-year carryover (existing) | preserved | preserved (unchanged tests) |
| Test count | 960 passing | **964 passing** (+4) |

**Scope honesty:** paper tax-CALC only; no filing/live touched. MFS $1,500 limit not modelled
(status unsupported). Future-cycle items still open: CTC fraction-thereof rounding; NIIT
MAGI-vs-AGI (FEIE add-back); AMT capital-gains preferential carve-out.

---

## Cycle 6 — RESEARCH + DEVELOP (2026-06-14)

### Improvement: India §87A new-regime rebate marginal relief → PR #51

**Research method:** surveyed CA + IN engines (avoided US to not collide with pending #50's QBI
test expectations — the highest-value US item, the ½ SE-tax §164(f) deduction, changes AGI and
would create a merge-order landmine with #50; deferred to after #50 lands). CA dividend gross-up/DTC
(rates 0.150198/0.090301) and capital-gains inclusion are correct; CA's max(0,gains) is right for
Canada. The IN engine's `_surcharge` and §87A rebate both LACK marginal relief. Picked 87A
(fixed ₹7L threshold, cleaner than surcharge's capital-gains entanglement).

**Why highest-value (isolated):** affects every new-regime filer with income just above ₹7,00,000 —
a hard cliff where ₹10,000 of extra income triggered ~₹26,000 of tax. Marginal relief is statutory.
Isolated to the IN engine → no interaction with the pending US PR stack.

**Why measurable / verify-plan (fails-before / passes-after):**
- ₹7.6L salary → ₹7.1L taxable, new regime: rebate ₹16,000, total tax ₹10,400 (was ₹0 / ₹27,040).
- GUARD: ₹9L → ₹8.5L: relief self-limits to ₹0.
- Proven by reverting only the engine hunk: just-above test fails (rebate 0==16000); guard passes.

**MAINTAIN finding (full-suite gate earned its keep):** first attempt based relief on
`tax_before_rebate` (incl. capital-gains tax) and broke `test_in_cess_applied_over_slab_plus_capital_gains`
(₹7.5L salary + ₹5L LTCG over-rebated). Corrected to base relief on `slab_tax` only — §87A never
rebates special-rate CG tax. The existing CG case now passes unchanged (slab ₹30k < excess ₹50k →
relief ₹0 → total tax ₹135,200).

**Before/after delta:**
| Scenario (new regime) | Before | After |
|---|---|---|
| ₹7.6L salary → ₹7.1L taxable | rebate ₹0, tax ₹27,040 | rebate ₹16,000, tax ₹10,400 |
| ₹9L → ₹8.5L (guard) | rebate ₹0 | ₹0 (self-limits) |
| ₹7.5L + ₹5L LTCG (existing) | ₹135,200 | ₹135,200 (unchanged) |
| Test count | 964 passing | **966 passing** (+2) |

**Scope honesty:** paper tax-CALC only; no filing/live touched. Old-regime 87A (no statutory
marginal relief) unchanged. Open future items: surcharge marginal relief (IN), ½ SE-tax deduction
(US, do after #50), CTC fraction-thereof rounding, NIIT MAGI-vs-AGI, AMT cap-gain carve-out.
