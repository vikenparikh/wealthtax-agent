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

## Cycle 5 — RESEARCH + DEVELOP (2026-06-14)

### Improvement: QBI §199A overall limit excludes net capital gain → PR #50

**Research method:** scanned US std-vs-itemized selection (correct — picks max), QBI, and the CA
capital-gains inclusion rate. CA inclusion is correct (50% from table) and CA's `max(0, gains)` is
actually right for Canada (capital losses can't offset ordinary income there). The US QBI line
(`us_engine.py:457`) capped at `min(qbi_eligible, taxable_income) * 0.20` — missing the §199A
subtraction of net capital gain from the taxable-income limit.

**Why highest-value:** affects every pass-through owner (Schedule C / 1099-NEC / K-1) who also has
LTCG or qualified dividends — a common combination. The deduction was overstated whenever
preferential income is present, with impact up to 20% of the capital-gain amount.

**Why measurable / verify-plan (fails-before / passes-after):**
- $50k SCH-C + $100k LTCG → QBI $7,080 (was $10,000).
- $20k SCH-C + $50k qualified dividends → $1,080 (was $4,000).
- GUARD: $50k SCH-C, no capital gain → $7,080 (unchanged).
- Proven by reverting only the engine hunk: the two cap-gain assertions fail (10000==7080,
  4000==1080); guard + existing QBI test pass both ways.

**Before/after delta:**
| Scenario | Before | After |
|---|---|---|
| $50k SCH-C + $100k LTCG | $10,000 | $7,080 |
| $20k SCH-C + $50k qualified divs | $4,000 | $1,080 |
| $50k SCH-C, no cap gain (guard) | $7,080 | $7,080 (unchanged) |
| Test count | 964 passing | **967 passing** (+3) |

**Scope honesty:** paper tax-CALC only; no filing/live touched. §199A wage/UBIA limits and SSTB
phase-out remain unmodelled. Future-cycle items: CTC fraction-thereof rounding; NIIT MAGI-vs-AGI
(FEIE add-back); AMT capital-gains preferential carve-out.
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

---

## Cycle 7 — RESEARCH + DEVELOP (2026-06-14)

### Improvement: One-half self-employment tax deduction (§164(f)) → PR #52

**MAINTAIN-first:** confirmed cycle-5 QBI (#50) merged to main, full suite green (967). #42 + #51
still pending merge.

**Why now / why highest-value:** this was explicitly DEFERRED in cycle-6 because it changes AGI and
would have collided with the then-pending QBI tests (#50). #50 is now merged, clearing the landmine.
It is the highest-value remaining item: EVERY self-employed filer was over-taxed because half their
SE tax was never deducted above the line (§164(f)). Real, common, unambiguous.

**Fix:** compute SE tax + its deductible half before AGI; add the half (½ of SS+Medicare SE tax,
EXCLUDING the 0.9% additional-Medicare surtax) to above-the-line deductions. Refactored
_compute_fica → (total_se_tax, half_deduction).

**Cascade (correct):** lower AGI → lower §199A QBI limit base → 3 QBI tests updated to recomputed
values ($50k SCH-C: $7,080 → $6,373.52; $20k+$50k qual-div: $1,080 → $797.41). No other tests moved
(full-suite verified). These updates are correct consequences, not goalpost-moving.

**Verify-plan (fails-before / passes-after):**
- $50k SCH-C → se_tax_deduction $3,532.39, AGI $46,467.61 (was no deduction, AGI $50,000).
- $300k SCH-C → deductible half strictly < ½ total SE tax (excludes additional-Medicare surtax).
- Proven by reverting only the engine hunk: new tests fail (KeyError se_tax_deduction), then pass.

**Before/after delta:**
| Scenario | Before | After |
|---|---|---|
| $50k SCH-C: AGI | $50,000 | $46,467.61 (−$3,532.39) |
| $50k SCH-C: QBI | $7,080 | $6,373.52 |
| Test count | 967 passing | **969 passing** (+2) |

**Scope honesty:** paper tax-CALC only; no filing/live touched. Secondary §199A nuance (reduce QBI
itself by ½ SE tax) intentionally out of scope. Remaining future items: IN surcharge marginal relief;
CTC fraction-thereof rounding; NIIT MAGI-vs-AGI (FEIE add-back); AMT cap-gain preferential carve-out.
## Cycle 8 — MAINTAIN + DEVELOP (2026-06-14)

### MAINTAIN: resolved conflicting PR #51 (real value)
On sync, PR #51 (India §87A) had gone `CONFLICTING` — a pure append-conflict in `.control/RND-LEDGER.md`
(main carried #50's cycle-5 entry; #51 carried cycle-6, both appended after cycle-4). Merged
origin/main into the branch, resolved the ledger as a union (cycles 1–6 in order), re-ran the full
suite green (969), pushed → #51 is **MERGEABLE/CLEAN** again. Functional files merged cleanly.

### DEVELOP: CTC phase-out rounds excess UP (§24(b)(2)) → PR #53

**Why (honest value):** LOWER-value than prior cycles (≤$50/return) but a genuine, zero-risk
correctness bug. `_compute_ctc` used `(agi - start) // 1000` (floor), but §24(b)(2) reduces the
credit "$50 for each $1,000 or fraction thereof" → round UP. AGI just over a $1,000 boundary gave
$50 too much credit. Fixed with `math.ceil`.

**Verify-plan (fails-before / passes-after):**
- AGI $200,500 (single, 1 child): CTC $1,950 (was $2,000).
- GUARD: AGI $205,000 (exact $5k over): $1,750 (unchanged).
- Proven by reverting only the engine hunk: partial-step test fails (2000==1950), guard passes.

**Convergence note (honest):** the genuinely HIGH-value tax-calculation gaps are now substantially
addressed across US + IN engines (cycles 1–7: §1091 capacity, NIIT rents, SS provisional-income,
§1211/§1222 capital losses, QBI §199A, India §87A marginal relief, ½ SE-tax §164(f)). CTC rounding
was the last clean, unambiguous, zero-risk item. REMAINING backlog is genuinely lower-value OR
carries incorrectness risk — flagged here rather than forced:
  - IN surcharge marginal relief — high $ per return but small population AND real capital-gains-
    surcharge entanglement (tax-at-threshold + 15% CG-surcharge cap). Risk of shipping subtly-wrong
    tax (worse than the current conservative over-tax). NOT to be forced without careful CG modelling.
  - CA basic-personal-amount phase-out — ~$232/top-earner; needs multi-year table-config changes.
  - NIIT MAGI-vs-AGI (FEIE add-back) — only FEIE filers (tiny population).
  - AMT capital-gains preferential carve-out — AMT is already heavily simplified; an exact-value
    test would be arbitrary.
  - §199A: reduce QBI itself by ½ SE tax — secondary reg nuance, small.
Expect future cycles to trend toward HONEST NOTHING-HIGH-VALUE no-ops unless new requirements/forms
land. That is the correct outcome, not a prompt to manufacture work.

**Delta:** test count 967 → **969** (+2). Full suite green.

---

## Cycle 9 — MAINTAIN + DEVELOP (2026-06-14)

### MAINTAIN: full PR stack merged green
All prior PRs (#43–#53) are now merged to main; zero open PRs at cycle start; main green at 973 tests.

### DEVELOP: NIIT threshold uses MAGI (FEIE add-back, §1411(d)) → PR #54

**Why (audience-relevant, not padding):** re-examined the convergence call. NIIT compared net
investment income against the threshold using AGI (us_engine.py:514), but §1411(d)(1) keys NIIT off
MAGI = AGI + the foreign earned income exclusion. A FEIE filer (Form 2555) whose foreign wages are
excluded can sit below the threshold on AGI while worldwide income is over it, wrongly escaping the
3.8% tax. For a CROSS-BORDER (CA/US/IN) tool, FEIE filers are a core audience — this elevates an
otherwise "niche" US item to genuinely relevant. Clean, correct, zero-risk (no entanglement like
the surcharge item).

**Verify-plan (fails-before / passes-after):**
- $150k foreign wages excluded + $80k US interest, single: AGI $80k, MAGI $230k -> NIIT $1,140 (was $0).
- GUARD: $50k excluded + $40k interest -> MAGI $90k < threshold -> $0 (add-back does not over-apply).
- Proven by reverting only the engine hunk: MAGI test fails (0.0==1140.0); guard + 4 existing NIIT tests pass.

**Before/after delta:**
| Scenario | Before | After |
|---|---|---|
| FEIE $150k + $80k interest (single) | NIIT $0 | NIIT $1,140 |
| Non-FEIE returns | unchanged | unchanged (feie_excluded=0 -> MAGI=AGI) |
| Test count | 973 passing | **975 passing** (+2) |

**Scope honesty:** paper tax-CALC only; no filing/live touched. Remaining backlog still genuinely
lower-value or risky: IN surcharge marginal relief (CG-surcharge entanglement — do NOT force);
CA BPA phase-out (~$232, multi-year table change); AMT cap-gain carve-out (AMT too simplified);
§199A reduce-QBI-by-½SE (minor). Expect future cycles to trend toward honest NOTHING-HIGH-VALUE.

---

## Cycle 10 — MAINTAIN + DEVELOP (2026-06-14)

### MAINTAIN: #54 merged, all green
#54 (NIIT MAGI) merged to main (HEAD 6d22f14); all PRs #43–#54 landed; zero open PRs; main green at 975.

### DEVELOP: credit CPP/EI contributions in the CA engine → PR #55

**Why HIGH-value (not padding):** fresh scan of the CA engine credits found that `cpp_contributions`
and `ei_premiums` (T4 boxes 16/18) were collected and echoed in line_items but NEVER credited —
`fed_non_refundable` omitted them. Every employed Canadian pays CPP+EI and is entitled to a 15%
non-refundable credit (lines 30800/31200), so federal tax was overstated for the ENTIRE
employed-Canadian population (~$500–750/return). Large population × material amount × clean fix
(directly analogous to the existing canada_employment_amount credit) = genuinely high-value, and
directly relevant to this cross-border tool's CA users.

**Verify-plan (fails-before / passes-after):**
- T4 $60k + CPP $3,000 + EI $900 vs without: cpp_ei_credit $585.00, federal tax $585 lower.
- Proven by reverting only the engine hunk: new test fails (KeyError cpp_ei_credit); 4 existing CA tests pass.

**Before/after delta:**
| Scenario | Before | After |
|---|---|---|
| T4 $60k + CPP $3k + EI $900 | no CPP/EI credit | $585 credit, federal tax −$585 |
| Test count | 975 passing | **976 passing** (+1) |

**Scope honesty:** paper tax-CALC only; no filing/live touched. Enhanced-CPP-deduction nuance +
multi-employer over-contribution refund are documented simplifications. The CONVERGENCE picture has
shifted: the CA engine had an un-audited high-value gap, so the repo is NOT as converged as cycle-8
implied — worth continuing to audit CA/cross-border surfaces. Remaining flagged-risky/low items
unchanged (IN surcharge marginal relief — do NOT force; CA BPA phase-out; AMT cap-gain carve-out).

---

## Cycle 11 — MAINTAIN + DEVELOP (2026-06-14)

### MAINTAIN: #55 merged green
#55 (federal CPP/EI credit) merged (HEAD a36c96a); all PRs #43–#55 landed; zero open PRs; main green at 976.

### DEVELOP: credit CPP/EI provincially too → PR #56

**Why HIGH-value (and it caught #55 being incomplete):** continuing the CA audit, found that the
PROVINCIAL non-refundable block (prov_non_refundable, line 314) omitted CPP/EI entirely. #55 added
the credit federally only, so every employed Canadian's PROVINCIAL tax was still overstated. CPP/EI
is credited provincially at the province's lowest rate (ON 5.05%), ~$197/return. Same large
population as #55; completes the federal+provincial CPP/EI credit. Clean, zero-risk.

**Verify-plan (fails-before / passes-after):**
- T4 $60k + CPP $3,000 + EI $900 vs without (ON): provincial_cpp_ei_credit $196.95, provincial tax $196.95 lower.
- Proven by reverting only the engine hunk: KeyError provincial_cpp_ei_credit; 5 existing CA tests pass.
- (Self-caught a float-precision assertion bug in the first test draft; corrected with round().)

**Before/after delta:**
| Scenario (ON) | Before | After |
|---|---|---|
| T4 $60k + CPP $3k + EI $900 | no provincial CPP/EI credit | $196.95 credit, provincial tax −$196.95 |
| Test count | 976 passing | **977 passing** (+1) |

**NEW backlog item spotted (logged, not fixed — keeps PR focused):** provincial donations/medical
credits reuse FEDERAL-rate credit amounts (15%/29%) instead of provincial rates (ON 5.05%/11.16%),
over-crediting provincially for donors. Genuine bug; candidate for a future cycle.

**Convergence note:** the CA engine keeps yielding genuine high-value gaps (federal+provincial CPP/EI),
so the repo is clearly NOT converged — the earlier US-centric audit missed the CA credit surface.
Still-open future items: provincial donations/medical rate; CA age amount + pension income amount
(retiree credits); IN surcharge marginal relief (risky — do NOT force); CA BPA phase-out; AMT cap-gain.

---

## Cycle 12 — MAINTAIN + DEVELOP (2026-06-14)

### MAINTAIN: #56 merged green
#56 (provincial CPP/EI) merged (HEAD 21f5519); all PRs #43–#56 landed; zero open PRs; main green at 977.

### DEVELOP: provincial medical credit uses provincial rate → PR #57

**Why (clean, correct, high-value subset):** the prov_non_refundable block reused the FEDERAL
medical credit amount (creditable * 15%) provincially. Medical is a lowest-rate credit, so
provincially it should be creditable * prov_lowest_rate (ON 5.05%). Reusing 15% over-credited
provincially for anyone with medical expenses. Exact for ALL provinces (medical is always
lowest-rate), zero table change, zero risk.

**Verify-plan (fails-before / passes-after):**
- T4 $60k net + $5,000 medical (ON): creditable $3,200 -> provincial credit $161.60 (5.05%),
  federal $480 (15%, unchanged). Before: provincial $480 at federal rate / KeyError.
- Proven by reverting the engine hunk: KeyError provincial_medical_credit; 6 existing CA tests pass.

**Before/after delta:**
| Scenario (ON) | Before | After |
|---|---|---|
| T4 $60k + $5k medical (creditable $3,200) | provincial credit $480 @15% | $161.60 @5.05%; federal $480 unchanged |
| Test count | 977 passing | **978 passing** (+1) |

**Deliberately deferred (no guessing):** provincial DONATIONS credit still reuses federal rates;
provincial donation excess rates (ON 11.16%, BC/AB/QC differ) are province-specific and not in the
tables — would require per-province table additions; left as a tracked backlog item rather than
approximated (avoid shipping wrong tax). Other open items: CA age amount + pension income amount
(retiree credits, need provincial caps); IN surcharge marginal relief (risky — do NOT force);
CA BPA phase-out.

**Convergence note:** the CA credit surface (federal CPP/EI, provincial CPP/EI, provincial medical)
has yielded 3 genuine fixes in a row — the engine was materially under-crediting CA returns. Likely
nearing the end of clean CA credit gaps; the remaining ones need table/per-province data.

---

## Cycle 13 — MAINTAIN + DEVELOP (2026-06-14)

### MAINTAIN: #57 merged green
#57 (provincial medical rate) merged (HEAD 5d20281); all PRs #43–#57 landed; zero open PRs; main green at 978.

### DEVELOP: provincial donation credit at provincial rates (Ontario) → PR #58

**Why (safe, table-driven, high-value for ON):** the donations half of the same bug class as #57 —
prov_non_refundable reused the FEDERAL donation amount (15%/29%) provincially. ON donation credit is
5.05% on the first $200, 11.16% on the excess. Fixed for ON (rate I am confident in) via a new
table field donation_credit_high_rate + a fallback that leaves BC/AB/QC at current behaviour (no
rate-guessing, no regression). ON is ~40% of Canada; donations are common.

**Considered + rejected this cycle:** RRSP deduction cap — the deduction is uncapped (line 170), but
the only available room key (rrsp_room from prior_year) means "remaining room" not "deduction limit",
so capping against it would UNDER-deduct (wrong direction); a correct cap needs a new
rrsp_deduction_limit key nothing populates. Left unfixed rather than ship a wrong-direction change.

**Verify-plan (fails-before / passes-after):**
- $1,000 donation (ON): provincial credit $99.38 (200*5.05% + 800*11.16%), federal $262.00 unchanged.
- Proven by reverting the engine hunk: KeyError provincial_donations_credit; 7 existing CA tests pass; BC/AB/QC fallback unchanged.

**Before/after delta:**
| Scenario (ON) | Before | After |
|---|---|---|
| $1,000 donation | provincial credit $262 @federal | $99.38 @ON; federal $262 unchanged |
| Test count | 978 passing | **979 passing** (+1) |

**Convergence note:** the CA provincial-credit-rate bug is now fixed for medical (#57) + ON donations
(#58). Remaining genuinely-needs-data items: BC/AB/QC donation excess rates; CA age amount + pension
income amount (provincial caps); CA BPA phase-out. Risky-do-not-force: IN surcharge marginal relief.
The clean, no-data, no-risk vein is now largely exhausted — expect upcoming cycles to need confirmed
per-province/table data or to be honest NOTHING-HIGH-VALUE no-ops.

---

## Cycle 14 — MAINTAIN + DEVELOP (2026-06-14)

### MAINTAIN: #58 merged green
#58 (ON provincial donation rate) merged (HEAD f017907); all PRs #43–#58 landed; zero open PRs; main green at 979.

### DEVELOP: credit the pension income amount (federal line 31400) → PR #59

**Why (clean, correct, no data needed):** T4A pension/superannuation income was collected but the
pension income amount credit (federal line 31400) was never applied — a lowest-rate credit on the
first $2,000 of eligible pension income. Retirees with employer pension/annuity overstated federal
tax by up to $300. T4A superannuation qualifies at ANY age (no age gate), and the $2,000 cap is
statutory (hardcodable like the $200 donation / $2,759 medical thresholds already in the engine).
RRIF (65+-only) conservatively excluded. No table change, no risk.

**Verify-plan (fails-before / passes-after):**
- $5,000 T4A pension -> capped at $2,000 -> credit $300.00; $1,200 -> $180.00.
- Proven by reverting the engine hunk: KeyError pension_income_credit; 8 existing CA tests pass.

**Before/after delta:**
| Scenario | Before | After |
|---|---|---|
| $5,000 T4A pension | no credit | $300.00 |
| $1,200 T4A pension | no credit | $180.00 |
| Test count | 979 passing | **981 passing** (+2) |

**Process note:** committed on detached HEAD by mistake (forgot to branch first); recovered by
creating the branch from the commit (`git branch <name> HEAD`) — no work lost, nothing pushed to main.

**Convergence:** federal CA credit gaps (CPP/EI, medical, donations-ON, pension income amount) are now
substantially closed. CLEARLY-remaining items all need confirmed per-province/table DATA (provincial
pension cap, BC/AB/QC donation rates, CA age amount base+phaseout, CA BPA phase-out) or carry risk
(IN surcharge). The clean, no-data, no-risk vein is now ~exhausted — next cycle is likely an HONEST
NOTHING-HIGH-VALUE no-op unless a clean item surfaces on re-scan.

---

## Cycle 16 — DEVELOP (2026-06-14) — CONVERGENCE CALL WAS PREMATURE

### MAINTAIN: main green at 981, zero open PRs (all #43–#59 merged).

### DEVELOP: India house-property loss set-off (§71(3A)) → PR #60

**Correction to cycle-15's no-op:** I declared convergence after auditing the CREDIT paths, but had
NOT audited the INCOME-COMPUTATION paths. A genuine re-scan of income heads found a major bug:
`slab_income` added `max(0.0, income_house_property)`, DISCARDING any net house-property loss. The
most common case — self-occupied home-loan interest (§24(b), up to ₹2,00,000) — is exactly such a
loss, so every OLD-regime homeowner silently lost their entire home-loan-interest deduction. This is
one of India's most-claimed deductions. HIGH-value, large population, clean fix, no data needed.

**Fix:** house-property loss sets off against other income up to ₹2,00,000 (§71(3A)), old regime
only (new regime: no inter-head set-off, and it already disallows self-occupied §24(b)). Cap at ₹2L,
note carry-forward of the excess.

**Verify-plan (fails-before / passes-after):**
- Old regime, ₹10.5L salary + ₹2L self-occupied interest -> taxable ₹8L (was ₹10L, discarded).
- Loss >₹2L (₹3L let-out interest) -> set-off capped at ₹2L -> ₹8L + carry-forward note.
- GUARD: new regime -> no §24(b), no set-off, ₹10L. Proven by reverting hunk (both fail 1000000==800000).

**Before/after delta:**
| Scenario | Before | After |
|---|---|---|
| Old regime ₹10.5L salary + ₹2L self-occupied interest | taxable ₹10L | ₹8L |
| Loss >₹2L | taxable ₹10L | ₹8L (capped) + carry-forward |
| Test count | 981 passing | **984 passing** (+3) |

**LESSON:** "converged" was wrong — I had only audited credits. Income heads (salary, house property,
CG, business, other sources) are a separate surface. Audit BOTH income computation AND credits before
ever claiming convergence. Not-modelled edge noted: house-property loss spilling onto capital gains.

---

## Cycle 17 — MAINTAIN + DEVELOP (2026-06-14)

### MAINTAIN: #60 merged green
#60 (IN house-property loss set-off) merged (HEAD 803e958); all PRs #43–#60 landed; zero open PRs; main green at 984.

### DEVELOP: India professional tax deduction (§16(iii), old regime) → PR #61

**Why (continuing the income-path audit):** swept all three engines' max(0,...) for loss-discards and
income heads for collected-but-unused fields. Findings: CA income comprehensive (self_emp_t4a +
foreign_property_income both in total_income); US capital losses handled (#49). Genuine gap: the IN
salary head allowed standard deduction + HRA but NEVER §16(iii) professional tax — a real, common
deduction (₹2,500) for salaried filers in PT states (Maharashtra/Karnataka/WB/etc., large population).
Read from user_answers like HRA/home-loan interest, so not inert. Clean, regime-aware, ₹2,500
statutory cap, no rate-guessing.

**Verify-plan (fails-before / passes-after):**
- Old regime, ₹10.5L salary, ₹2,500 PT -> taxable ₹9,97,500 (was ₹10L).
- ₹9,000 input -> capped at ₹2,500. GUARD: new regime -> 0 (disallowed). Proven by reverting hunk (KeyError).

**Before/after delta:**
| Scenario | Before | After |
|---|---|---|
| Old regime ₹10.5L salary + ₹2,500 PT | taxable ₹10L | ₹9,97,500 |
| Test count | 984 passing | **987 passing** (+3) |

**Audited-clean this cycle (no bug):** CA income composition complete; US/CA loss floors correct
(CA capital loss floored = correct for Canada). DEFERRED-risky: IN intra-capital-gains loss netting
(§70 STCG-vs-LTCG set-off across equity/other × pre/post-change matrix — intricate, error-prone,
smaller population; not forced, same caution as IN surcharge). Income paths now substantially swept
(house property #60, professional tax #61). Remaining genuine items need new inputs (inert) or carry
implementation risk. Convergence likely near again — but cycle-15's premature call means I keep
sweeping a fresh surface each cycle before declaring no-op.

---

## Cycle 18 — MAINTAIN + DEVELOP (2026-06-14)

### MAINTAIN: #61 merged green
#61 (IN professional tax) merged (HEAD a0e5a10); all PRs #43–#61 landed; zero open PRs; main green at 987.

### DEVELOP: India ROR requires resident in 2 of last 10 years (§6(6)) → PR #62

**Why (fresh surface = residency; audience-relevant):** audited engines/residency.py (US SPT, CA
183, IN §6) — SPT weighting (31d + 1/3 + 1/6 ≥183), CA 183, IN basic §6 all correct. GAP: the
ROR-vs-RNOR test (line 113) checked only the 730-days-in-7-years condition, omitting §6(6)'s second
condition — resident in ≥2 of the last 10 years. Misses the common RETURNING-NRI case (lots of
recent days but resident ≤1 of last 10) -> wrongly ROR (worldwide income taxed) instead of RNOR
(foreign income exempt). Core cross-border audience, high $ impact (foreign income).

**Why clean (not inert):** recommend_residency already reads user_answers flags and threads them to
india_residency; added resident_years_in_last_10 the same way (user_answers["india_resident_years_in_last_10"]),
default 2 preserves all prior behaviour (23 existing residency tests pass unchanged).

**Verify-plan (fails-before / passes-after):**
- 730+ days but resident 1 of 10 -> RNOR (was ROR). Both met -> ROR. Default -> ROR (preserved).
- Orchestrator end-to-end: returning NRI -> RNOR. Proven by reverting hunk ('ROR'=='RNOR').

**Before/after delta:**
| Scenario | Before | After |
|---|---|---|
| 730+ days, resident 1 of 10 years | ROR | RNOR |
| Test count | 987 passing | **990 passing** (+3) |

**Audited-clean this cycle:** US SPT formula, CA 183-day, IN §6 day-count all correct; treaty hints
advisory. DEFERRED-risky still: IN intra-capital-gains loss netting (§70 matrix). Surfaces now swept:
credits, income heads, residency. Remaining items need per-province DATA or carry risk. Cross-border
audience-relevance (FEIE→NIIT-MAGI, returning-NRI→ROR) keeps surfacing genuine fixes — keep that lens.

---

## Cycle 20 — MAINTAIN + DEVELOP (2026-06-14) — corrects cycle-19's no-op too

### MAINTAIN: #62 merged green
#62 (IN ROR §6(6)) merged (HEAD 04e0d8e); all PRs #43–#62 landed; zero open PRs; main green at 990.

### DEVELOP: India capital losses must not offset salary/other income (§70/§71) → PR #63

**Correction to cycle-19's no-op:** I'd flagged "IN capital-gains loss netting" as risky/deferred and
declared a no-op. But the RISKY part is only the full multi-category §70 set-off ORDERING. The
under-taxing bug — a capital loss illegally reducing SALARY tax — has a CLEAN, SAFE fix I missed:
floor the TOTAL cg_tax at 0. PROBED and confirmed reachable: ₹1L STCG-equity loss cut total tax
₹117,000 -> ₹101,400 (negative cg_tax -₹15,000 spilling onto slab). This is UNDER-taxing (penalty-risk
direction) — high-value to fix.

**Fix:** `cg_tax = max(0, sum of category taxes)` (preserves LEGAL intra-CG netting — a loss in one
category offsets a gain in another — but a NET loss can't reduce slab tax) + floor STCG-other-slab at 0.
Carry-forward of excess loss not modelled.

**Verify-plan (fails-before / passes-after):**
- ₹10.5L salary + ₹1L STCG-equity loss -> tax unchanged ₹117,000 (was ₹101,400).
- Intra-CG netting preserved: ₹50k STCG loss still offsets ₹2L LTCG gain.
- STCG-other loss doesn't reduce salary. Proven by reverting hunk (101400==117000).

**Before/after delta:**
| Scenario | Before | After |
|---|---|---|
| ₹10.5L salary + ₹1L STCG loss | tax ₹101,400 (illegal cut) | ₹117,000 |
| Test count | 990 passing | **993 passing** (+3) |

**LESSON (again):** don't lump a whole area into "risky/deferred" — decompose it. The full §70 ORDERING
is risky, but the floor-at-0 anti-illegal-offset is clean and safe. Cycle-19's no-op was premature on
this specific item (though the surface sweep was otherwise sound). Full §70 multi-category set-off
ordering + cross-year carry-forward remain genuinely deferred (intricate).

---

## Cycle 21 — MAINTAIN + DEVELOP (2026-06-14)

### MAINTAIN: #63 merged green
#63 (IN capital-loss anti-offset) merged (HEAD 0fd1534); all PRs #43–#63 landed; zero open PRs; main green at 993.

### DEVELOP: Alberta provincial donation credit at AB rates → PR #64

**Why (clean extension, confident rate):** the provincial donation-rate bug (federal 15%/29% applied
provincially) was fixed for ON in #58 via a table-driven mechanism with a safe fallback. Alberta's
donation credit is a well-documented 10%/21% (the 21% excess rate is famously above AB's top tax
rate). Extended #58 to AB by adding donation_credit_high_rate: 0.21 to the AB tables (2023-25) — the
engine logic already handles it. BC/QC stay on the federal fallback (rates not yet confirmed; no
guessing, no regression).

**Considered + still-deferred (decomposition didn't yield a clean sub-fix):** IN surcharge — including
CG in the surcharge THRESHOLD is coupled to the CG-surcharge-15%-cap (doing one without the other
over-taxes); genuinely entangled, not forced.

**Verify-plan (fails-before / passes-after):**
- $1,000 donation (AB) -> provincial credit $188.00 (200*10% + 800*21%) vs federal-rate $262.00.
- Proven by reverting only the AB table change (262==188).

**Before/after delta:**
| Scenario (AB) | Before | After |
|---|---|---|
| $1,000 donation | provincial credit $262 @federal | $188.00 @ AB 10%/21% |
| Test count | 993 passing | **994 passing** (+1) |

**Status:** provincial donation rates now correct for ON (#58) + AB (#64). BC/QC need confirmed
legislated rates (tracked). Remaining backlog unchanged: surcharge entangled; age/std-deduction need
input; QC out of scope; full §70 cap-gain ORDERING + carry-forward deferred. Clean vein narrowing —
mostly per-province-data extensions and risky/entangled items left.

---

## Cycle 25 — FULL LIFECYCLE (2026-06-14) — convergence claim corrected AGAIN

MATRIX | deduct RPP contributions + union dues (T4 boxes 20/44, lines 20700/21200) | every CA employee with an employer pension plan or union membership was over-taxed (a major, very common deduction silently dropped) | fail: KeyError rpp_deduction / taxable income unreduced — pass: T4 $80k + RPP $5k + dues $1.2k -> taxable -$6,200 | gated? N | PR #65

**RESEARCH method that found it:** cross-checked that EVERY field the T4 extractor captures is consumed
by the engine. The extractor populated rpp_contributions (box 20) and union_dues (box 44) but the
engine read only employment_income/cpp/ei/withheld — RPP + union dues were collected and discarded.

**LESSON (3rd convergence correction):** my prior "all surfaces swept" claims audited the engine's
own income/credit code but NOT the extractor→engine field-consumption contract. New permanent check:
for each form, diff the fields the EXTRACTOR captures against the fields the ENGINE reads; any captured-
but-unused field is a candidate bug. This is a distinct surface from the engine-internal sweep.

Suite 994 -> 995. Convergence is NOT confirmed — re-run the extractor-vs-engine field audit for ALL
forms (US/CA/IN) next cycle before any further no-op.

---

## Cycle 26 — FULL LIFECYCLE (2026-06-14) — extractor-vs-engine field audit (US/IN)

MATRIX | tax 1099-DIV box 2a capital gain distributions as LTCG | mutual-fund/ETF capital gain distributions (very common in taxable accounts) were captured but dropped -> under-reported income/tax | fail: long_term_capital_gain $0 — pass: $8,000 box-2a -> $8,000 LTCG | gated? N | PR #66

**MAINTAIN:** #65 merged green (HEAD 11693da); main green at 995.

**Audit completed (extractor-captured fields vs engine-read fields):**
- US: box 2a capital_gain_distributions captured-but-unused -> FIXED (#66). Other US captured-but-unused
  are niche/complex/documented (early_withdrawal_penalty above-line deduction; tax_exempt_interest =
  documented SS-provisional simplification; excess-SS/medicare withholding; tips; collectibles/1250/1202
  special-rate gains; dependent_care_benefits). early_withdrawal_penalty is the cleanest follow-up.
- CA: clean after #65 (pension_adjustment is correctly informational-only — affects next-year RRSP room,
  not current tax).
- IN: FOLLOW-UP found — Form-16 extractor captures `professional_tax` but the engine reads the manual
  user_answer `professional_tax_paid` (key mismatch from #61): a form-uploaded professional tax is not
  deducted, only manual entry. Genuine wiring gap, ~₹2,500, next-cycle candidate.

Suite 995 -> 996. NOT converged: IN professional_tax key-bridge + US early_withdrawal_penalty remain.

---

## Cycle 27 — FULL LIFECYCLE (2026-06-14)

MATRIX | read professional tax from Form 16 (not only the manual user answer) | §16(iii) deduction (#61) was wired only to a manual key, so form-uploaded professional tax — the primary path — was silently dropped | fail: form professional_tax ₹2,500 -> deduction ₹0 / taxable ₹10L — pass: -> ₹9,97,500 | gated? N | PR #67

**MAINTAIN:** #66 merged green (HEAD 8773593); main green at 996.

This is the IN follow-up flagged in cycle-26's audit (Form-16 `professional_tax` extract key did not
match the engine's `professional_tax_paid` user-answer read). Fixed with form-then-manual fallback +
₹2,500 cap. Suite 996 -> 997.

**Remaining from the extractor-vs-engine audit:** US early_withdrawal_penalty (1099-INT box 2, an
above-the-line deduction; captured-but-unused) — next-cycle candidate (niche-ish). After that the
extractor-vs-engine contract is substantially clean; the other captured-but-unused US fields are
special-rate/complex (collectibles 28%, unrecaptured 1250, §1202, dependent-care benefits, excess
SS/Medicare withholding) or documented simplifications (tax-exempt interest -> SS provisional income).

---

## Cycle 28 — FULL LIFECYCLE (2026-06-14)

MATRIX | deduct 1099-INT box 2 early-withdrawal penalty (above the line) | a Schedule-1 above-the-line deduction was captured but omitted from above_line, overstating AGI | fail: KeyError early_withdrawal_penalty / AGI unreduced — pass: $500 penalty -> AGI $92,500 | gated? N | PR #68

**MAINTAIN:** #67 merged green (HEAD 188fcba); main green at 997.

Last clean item from the extractor-vs-engine field-consumption audit. The audit produced 4 fixes:
#65 (CA RPP/union dues), #66 (US 1099-DIV box 2a LTCG), #67 (IN Form-16 professional tax), #68 (US
early-withdrawal penalty). The extractor-vs-engine contract is now substantially clean — the
remaining captured-but-unused fields are special-rate/complex (collectibles 28%, unrecaptured §1250,
§1202 small-business stock, dependent-care benefits, excess SS/Medicare withholding -> multi-employer
refund) or documented simplifications (tax-exempt interest -> SS provisional income), none a clean
no-data no-risk fix. Suite 997 -> 998.

Convergence likely again next cycle unless a new surface/audit angle or external data/input appears —
but per the repeated lessons (cycles 16/20/25), I will sweep a FRESH angle before any no-op.

---

## Cycle 29 — FULL LIFECYCLE (2026-06-14)

MATRIX | deduct declared 80D health-insurance total (not only granular self/parents) | 80C reads section_80c_declared but 80D ignored section_80d_declared (captured by Form-16 + wizard) -> common declared health-insurance deduction dropped -> over-taxed | fail: section_80d ₹0 / taxable ₹10L — pass: ₹25,000 / ₹9,75,000 | gated? N | PR #69

**MAINTAIN:** #68 merged green (HEAD a4bb468); main green at 998. Test suite crossed 1000.

**Fresh-angle audit (intake/extractor -> engine field-consumption for the manual-DEDUCTION path):**
compared declared-total keys vs granular keys. 80C handles its declared total (line 327); 80D did
NOT (asymmetry) -> FIXED. Verified consistent: 80C declared read; 80D declared now read; 80CCD1B/80E/
80G/80TTA-TTB are single-key (no declared/granular split). This is a DISTINCT contract from the
form-field audit (#65-#68): the same field can be captured by BOTH a form and the wizard, and the
engine must read the declared-total variant, not only the itemized sub-keys.

Suite 998 -> 1000. NOT yet converged on this angle until I confirm no other declared-vs-granular gaps;
80C/80D were the only two with that split, both now correct. Next cycle: sweep another fresh angle
(e.g., senior-citizen / age-conditional deduction caps actually applied) before any no-op.

---

## Cycle 30 — FULL LIFECYCLE (2026-06-14)

MATRIX | implement 80CCD(2) employer NPS deduction (both regimes) | comments said Chapter VI-A is "old regime only, except 80CCD(2)" but 80CCD(2) was never coded -> new-regime (default) filers with employer NPS lost a ~10%-of-salary deduction | fail: KeyError section_80ccd_2 / taxable ₹10L — pass: ₹60k deducted -> ₹9,40,000 | gated? N | PR #70

**MAINTAIN:** #69 merged green (HEAD 9cca363); main green at 1000.

**Fresh-angle audit (regime-gating):** checked which deductions the comments/law allow in the NEW
regime vs what the engine actually applies. The standard deduction (₹50k) is applied in new regime;
HRA/§16(iii)/chapter-VI-A correctly old-only — EXCEPT 80CCD(2), which the comments explicitly named
as the exception but was missing. Implemented in both regimes (subtracted outside the old-regime
gate). Also audited senior/age-conditional (80TTA savings-only vs 80TTB all-deposit = correct;
senior slab brackets + 80D senior caps wired correctly) — clean.

Suite 1000 -> 1002. Audit angles that paid off this run of cycles: extractor->engine field consumption
(#65-68), declared-vs-granular deduction keys (#69), regime-gating exceptions (#70). NOT converged —
next cycle sweep another fresh angle (e.g., NR/RNOR foreign-source filtering completeness across ALL
income heads, not just other_income).

---

## Cycle 31 — FULL LIFECYCLE (2026-06-14)

MATRIX | §87A base rebate excludes special-rate capital-gains tax | the at/under-threshold rebate used tax_before_rebate (slab+CG) so it zeroed out equity-LTCG tax for low-income filers with CG; #51 fixed the marginal-relief branch but left the base case inconsistent (under-taxing) | fail: rebate ₹25,000 / total tax ₹0 — pass: rebate ₹15,000 / ₹10,400 (LTCG tax survives) | gated? N | PR #71

**MAINTAIN:** #70 merged green (HEAD d04f10a); main green at 1002.

**Fresh-angle audit (internal consistency between related code paths):** the #51 marginal-relief fix
used slab_tax to exclude special-rate CG from the §87A rebate, but the BASE rebate branch still used
tax_before_rebate — same statutory principle, inconsistent implementation. Fixed the base branch to
match. (Also examined NR/RNOR foreign-source filtering: only other_income + salary are flagged;
capital gains / house property lack foreign-source flags -> an NR/RNOR with foreign CG/rental is
over-taxed, but this needs NEW per-head foreign-source inputs -> tracked, not a clean no-input fix.)

Suite 1002 -> 1003. NEW audit angle that paid off: INTERNAL CONSISTENCY between sibling code paths
(base vs marginal-relief rebate). NOT converged — next cycle sweep for other sibling-path
inconsistencies or the NR/RNOR per-head foreign-source completeness if inputs are added.
## Cycle 32 — FULL LIFECYCLE (2026-06-14)

MATRIX | phase out federal BPA for high earners ($15,705 -> $14,156 over $173,205-$246,752 net income) | BPA was flat, over-crediting all high-income Canadians (~$232) — a CRA rule since 2020 | fail: BPA $15,705 at $300k net income — pass: $14,156 (floor) | gated? N | PR #72

**MAINTAIN:** #70 merged green (HEAD d04f10a); #71 open/mergeable; main green at 1002.

**Fresh-angle audit (tax-table VALUE/coverage correctness):** checked whether table values are current
and whether known statutory phase-outs/floors are present. IN 2025 table verified correct (₹75k std
deduction + widened slabs + 87A). CA federal table had a FLAT BPA — missing the 2020+ high-income
phase-out. Implemented (table-driven floor, 2024 confirmed; other years flat fallback = no regression).
Self-caught a test-field bug (BPA is in DraftReturn.credits, not line_items) — corrected.

Suite 1002 -> 1004. NEW audit angle: table-value currency + missing statutory phase-outs/floors. NOT
converged — sweep US/CA other-year table values + any other missing phase-outs (e.g. US CTC/PTC FPL
thresholds, OAS clawback indexation) next cycle; BC/QC/other-year CA BPA floors need confirmed values.

---

## Cycle 33 — FULL LIFECYCLE (2026-06-14)

MATRIX | include W-2 box 17 state income tax in SALT | SALT read only SCH-A.state_local_taxes; W-2 box 17 (captured, usually the LARGEST SALT component) was dropped -> itemizers in high-tax states over-taxed | fail: salt_deduction_capped $0 — pass: $9,000 (W-2 box 17) | gated? N | PR #73

**MAINTAIN:** #71 merged green; #72 rebased onto main + MERGEABLE after merge-train conflict (ledger
union, lease-pushed); main green at 1003 (#72's +2 makes its branch 1005).

**Re-examination angle (revisit under-rated audit findings):** in cycle-26 I marked W-2 box 17
state_income_tax "niche" — wrong. For ITEMIZERS state income tax is the biggest SALT component, and
the engine read only the Sch A field. Fixed with form-then-fallback (Sch A total preferred, else W-2
box 17) to avoid double-counting. LESSON: revisit items previously dismissed as niche — value depends
on the sub-population (here, itemizers in high-tax states).

Suite (branch) 1005. NOT converged — re-audit other "niche"-tagged captured-but-unused fields
(dependent_care_benefits, excess SS/medicare withholding -> multi-employer refund, allocated/SS tips)
for any with a non-trivial sub-population next cycle.
## Cycle 34 — FULL LIFECYCLE (2026-06-14)

MATRIX | credit excess Social Security tax from multiple employers | W-2 box 4 SS tax withheld captured but unread; 2+ employers over the wage base over-withhold and the excess is a refundable credit (Sch 3 line 11) -> multi-job filers lost a material refund | fail: excess_social_security_tax KeyError — pass: 2 W-2s $14,880 -> $4,426.80 credit | gated? N | PR #74

**MAINTAIN:** #72 merged; #73 rebased onto main + MERGEABLE after merge-train conflict (ledger union,
lease-pushed). main green at 1005. Adopted ALWAYS-rebase-before-push (git fetch + git rebase
origin/main just before each push) to stop the shared-ledger collisions — this PR pushed conflict-free.

**Angle (continue niche-revisit):** excess SS tax credit — sub-population (multiple jobs over the
wage base) is real, amount material. Gated on 2+ W-2s (single-employer over-withholding is the
employer's to fix). Suite -> 1007. Remaining niche captured-but-unused: dependent_care_benefits
(needs the dependent-care credit, complex), allocated/SS tips (extraction nuance). NOT converged but
the captured-but-unused vein is nearly exhausted of clean items.
## Cycle 35 — FULL LIFECYCLE (2026-06-14)

MATRIX | add tax-exempt interest to SS provisional income (§86) | worksheet adds tax-exempt interest back but engine omitted it (documented #48 gap); 1099-INT box 8 captured-but-unused -> retirees with muni bonds + SS under-reported taxable benefits | fail: taxable SS $0 — pass: $9,600 (provisional $40k -> 85% tier) | gated? N | PR #75

**MAINTAIN:** #73, #74 open/mergeable (pending merge); main green at 1005. Rebase-before-push held —
this PR pushed conflict-free.

Correctness item (per directive's §70/71/AB pattern): closes the §86 provisional-income gap I
documented as a simplification in #48 — tax-exempt interest is added to provisional income (NOT to
taxable income; the interest stays exempt). Under-taxing fix for muni-bond retirees. Suite -> 1006.

## Cycle 36 — FULL LIFECYCLE (2026-06-14)

MATRIX | fix §112A LTCG-equity exemption double-counting across the Jul-23-2024 rate change | the ₹1.25L LTCG-equity exemption is a single ANNUAL amount, but the engine applied a fresh exemption to BOTH the pre-change (10%) and post-change (12.5%) slices — double-exempting filers with gains both sides of Jul 23 2024 and under-exempting pre-only filers | fail: ₹80k-pre + ₹2L-post asserted tax_ltcg_equity 9375 (double-exempt) — pass: single ₹1.25L exemption applied to higher-rate post slice first -> 17375 (post 75k@12.5%=9375 + pre 80k@10%=8000) | gated? N | PR #76

**MAINTAIN:** #74 + #75 merged to main; rebased onto latest origin/main (ledger union, Cycle renumbered
34->kept, mine 35->36); suite green at 1011. Rebase-before-push held.

**Angle (table-value/statutory correctness, NOT captured-but-unused):** §112A is a single annual
exemption per the Finance Act 2024 — verified the YAML thresholds (pre 1L/10%/15%/20%; post
1.25L/12.5%/20%/12.5%) are correct; the bug was purely in how `_capital_gains_split` applied them.
Exemption now consumed against the higher-rate post-change gains first (taxpayer-favourable). Updated
the existing `test_ltcg_equity_split_pre_and_post_change` (it had asserted the buggy double-exempt
value) + 2 new edge tests in test_engine_edge_cases.py (post-only full-exemption; no double-exempt
across Jul23).

## Cycle 37 — FULL LIFECYCLE (2026-06-14)

MATRIX | add refundable Additional Child Tax Credit (ACTC, Form 8812) | CTC was applied non-refundable only (max(0, tax - ctc)); families whose tax liability cannot absorb the full CTC lost the refundable portion entirely -> low/modest-income families with children received $0 benefit | fail: additional_child_tax_credit KeyError — pass: single $20k wages + 2 kids -> $2,625 refund (15% x (20000-2500), under the $3,400 per-child cap and the $3,460 unused CTC) | gated? N | PR #77

**MAINTAIN:** #76 merged to main (HEAD e524438); baseline suite green at 1012. Rebase-before-push held.

**Angle (refundability of an existing non-refundable credit):** the CTC was computed and phased out
correctly but only ever reduced tax to zero — the statutory refundable ACTC (Form 8812) was missing.
Refundable amount = min(unused CTC, $1,700/child [2024], 15% of earned income over $2,500). Added
refundable_per_child (1600 2023 / 1700 2024-25), earned_income_floor (2500), refundable_rate (0.15)
to the us ctc tables; engine credits ACTC as a payment (balance -= actc) alongside excess-SS-tax.
Earned income = wages + max(0, SE income). 3 tests: earned-floor binds ($2,625), very-low-earned
binds ($375), fully-absorbed guard ($0). Suite 1012 -> 1015.

## Cycle 38 — FULL LIFECYCLE (2026-06-15)

MATRIX | add W-2 box 8 allocated tips to taxable income | box 8 (allocated tips) is NOT in box 1, and the engine read only box 1 wages -> a tipped worker's allocated tips escaped income tax entirely (under-taxation); box 7 SS tips ARE in box 1 and must NOT be re-added | fail: line_items has no 'allocated_tips' (KeyError); $5k tips add $0 tax — pass: line_items['allocated_tips']=$5,000, $5k taxed at 22% marginal = +$1,100; box-7 guard proves no double-count | gated? N | PR #78

**MAINTAIN:** #77 merged to main (HEAD 9ff44d7); baseline suite green at 1015. Rebase-before-push held.

**Angle (re-audit "niche"-tagged captured-but-unused W-2 fields, per cycle-33 lesson):** the W-2
extractor captures box 7 (social_security_tips) and box 8 (allocated_tips) but the engine read
neither. Box 8 allocated tips are statutorily excluded from box 1 and must be reported as income
(Form 1040 line 1c) — pure under-taxation gap for tipped/hospitality workers. Added as a dedicated
income line into other_income + surfaced as line_items['allocated_tips']; box 7 left unread (already
inside box 1 — a guard test proves no double-count). The Form 4137 SS/Medicare-on-tips computation is
a separate model the engine does not implement — noted, not silently dropped. Suite 1015 -> 1017.

**Remaining captured-but-unused W-2 fields:** dependent_care_benefits (box 10, excess-over-$5,000
add-back needs Form 2441 + care expenses), nonqualified_plans (box 11). Next cycle: DCB box-10 excess
or sweep a fresh statutory angle.

## Cycle 39 — FULL LIFECYCLE (2026-06-15)

MATRIX | add US additional standard deduction for age 65+/blindness (Form 1040) | engine applied only the BASE standard deduction; every senior/blind filer taking the standard deduction was over-taxed (a near-universal retiree situation). Per-box amounts are table-driven and higher for unmarried filers | fail: single 65+ std stays $14,600 / MFJ 3-box stays $29,200 — pass: single 65+ -> $16,550 (+$1,950 -> -$234 tax at 12%); MFJ both-65+-one-blind -> $33,850 (29,200 + 3x1,550); single ignores spouse boxes (guard) | gated? N | PR #79

**MAINTAIN:** #78 merged to main (HEAD 6d62d02); baseline suite green at 1017. Rebase-before-push held.

**Angle (missing statutory feature, large population):** the US engine had NO age-65/blind additional
standard deduction. Form 1040 counts boxes (taxpayer 65+, taxpayer blind, + spouse boxes for MFJ);
each box adds one unit of the year/status amount (2023 1850/1500, 2024 1950/1550, 2025 2000/1600 —
unmarried/married). Implemented as table-driven `additional_standard_deduction` block in us/{2023,2024,
2025}.yaml + `_additional_std_boxes` box-counter (spouse boxes gated to MFJ) folded into std_deduction
BEFORE the itemized comparison (itemizers who beat the boosted standard are unaffected). Years without
the table key default to 0 -> no regression. Suite 1017 -> 1020.

**Considered-but-rejected this cycle:** W-2 box 10 dependent_care_benefits excess-over-$5,000 add-back
— REJECTED as a clean fix because the employer already includes the >$5k excess in box 1, and the
real Form 2441 taxable-benefit computation needs care-expense + spouse-earned-income inputs the engine
lacks; forcing "excess>$5k is taxable" would double-count. Left as a genuine but input-blocked item.

**Remaining candidates:** box 11 nonqualified_plans (niche); CA age amount + pension income amount
(retiree credits) — re-verify whether already covered; NR/RNOR per-head foreign-source flags (needs
new inputs). Next cycle sweep CA retiree credits or a fresh statutory angle.

## Cycle 40 — FULL LIFECYCLE (2026-06-15)

MATRIX | add CA federal age amount credit (line 30100) for taxpayers 65+ | engine had pension income amount but NO age amount; every Canadian senior taking the credit was over-taxed. Lowest-rate credit on a base that phases out at 15% of net income over the year threshold | fail: no 'age_amount_credit' line item (KeyError); age flag changes nothing — pass: 65+ at $40k net -> $1,318.50 credit (8790x0.15) -> -$1,318.50 federal tax; phase-out at $64,325 net -> $868.50 (5,790x0.15); under-65 guard -> $0 | gated? N | PR #80

**MAINTAIN:** #79 merged to main (HEAD 4bfc9c9); baseline suite green at 1020. Rebase-before-push held.

**Angle (missing statutory retiree credit, large population — pairs with #79 US age deduction):**
the CA engine modelled the pension income amount (line 31400) but not the age amount (line 30100).
Added table-driven `age_amount` block to ca/{2023,2024,2025}.yaml (max 8396/8790/9028; threshold
42335/44325/45522; reduction 0.15) + `_is_65_or_older` gate (truthy flag or numeric taxpayer_age>=65).
Credit = max(0, max - 0.15*(net_income - threshold)) * lowest_rate, folded into fed_non_refundable;
federal only (provincial age amount not modelled, mirrors pension income amount). Missing table key OR
no age input -> 0 (no regression). Suite 1020 -> 1023.

**Remaining candidates:** provincial age amount (per-province table data); box 11 nonqualified_plans
(US, niche); NR/RNOR per-head foreign-source flags (needs new inputs); IN surcharge marginal relief
(flagged risky — do NOT force). The clean no-new-input statutory-credit vein is thinning — next cycle
may trend toward NOTHING-HIGH-VALUE unless a fresh angle surfaces.

## Cycle 41 — FULL LIFECYCLE (2026-06-15)

MATRIX | include RRIF income in CA pension income amount (line 31400) at 65+ | the credit base used only T4A superannuation and excluded RRIF outright (commented "conservatively excluded"); but RRIF (T4RIF) IS eligible pension income at 65+ -> a 65+ retiree on the standard RRSP->RRIF path (often no employer superannuation) was denied up to $300 credit | fail: RRIF-only 65+ -> pension_income_credit $0; super+RRIF -> $180 (super only) — pass: RRIF-only 65+ -> $300 (min(10k,2k)*0.15); super $1,200 + RRIF $5,000 -> $300 (combined base capped at $2k); under-65 RRIF guard -> $0 | gated? N | PR #81

**MAINTAIN:** #80 merged to main (HEAD 77cbcd2); baseline suite green at 1023. Rebase-before-push held.

**Angle (correctness unlocked by NEW infra — the #80 age gate):** cycle-40 added `_is_65_or_older`;
that gate makes the previously-"conservatively excluded" RRIF income correctly includable in the
pension income amount base at 65+. RRIF/RRSP->RRIF is the standard Canadian decumulation path, so this
is a large, well-defined population (65+ retirees with little/no registered-pension-plan superannuation).
Base now = pension_income (+ rrif_income iff 65+), capped at $2,000, credited at lowest rate. No new
inputs (rrif_income already extracted at T4RIF; age gate already present). Suite 1023 -> 1026.

**Remaining candidates:** provincial age amount + provincial pension amount (per-province data); US box
11 nonqualified_plans (niche); NR/RNOR per-head foreign-source flags (needs new inputs); IN surcharge
marginal relief (risky — do NOT force). The clean no-new-input statutory vein is now genuinely thin —
expect the next cycle to trend toward HONEST NOTHING-HIGH-VALUE unless a fresh audit angle surfaces.

## Cycle 42 — FULL LIFECYCLE (2026-06-15)

MATRIX | make CA OAS clawback threshold year-specific (was hardcoded 2024 $90,997) | the OAS recovery-tax threshold is indexed annually (2023 $86,912 / 2024 $90,997 / 2025 $93,454) but the engine hardcoded $90,997 for ALL years -> a 2023 retiree between $86,912-$90,997 got NO clawback (under-tax) and a 2025 retiree between $90,997-$93,454 was over-clawed (over-tax) | fail: 2023 $89k net -> clawback $0 (uses 90997); 2025 $92k net -> clawback $150.45 — pass: 2023 -> $313.20 (over $86,912 x15%); 2025 -> $0 (under $93,454); 2024 $95k guard -> $600.45 | gated? N | PR #82

**MAINTAIN:** #81 merged to main (HEAD 47727d9); baseline suite green at 1026. Rebase-before-push held.

**Angle (table-currency / hardcoded-constant bug — the #72 BPA / #32 angle):** swept the CA engine for
year-specific constants applied across years. OAS recovery threshold was a literal $90,997 used for
2023/2024/2025. Moved to `oas_recovery_threshold` in ca/{2023,2024,2025}.yaml (fallback to 90997.0 if
absent -> no regression); also rounded the clawback to 2dp (was an unrounded float; consistent with
age_amount_credit). Suite 1026 -> 1029.

**Remaining candidates:** provincial age/pension amounts (per-province data); US box 11 nonqualified_
plans (niche); NR/RNOR per-head foreign flags (needs inputs); IN surcharge marginal relief (risky).
Worth a dedicated next-cycle sweep: OTHER hardcoded constants across all three engines (US/CA/IN) — e.g.
US NIIT/additional-medicare thresholds, IN OAS-equivalent, CA CPP/EI maxima — same table-currency angle
may have more instances. If that sweep finds nothing clean, next cycle is honest NOTHING-HIGH-VALUE.

## Cycle 43 — FULL LIFECYCLE (2026-06-15)

MATRIX | make US AMT exemption/phaseout/rate-breakpoint year-specific (were hardcoded 2024) | _compute_amt took fed_tables but ignored it — exemption ($85,700/$133,300), phaseout ($609,350/$1,218,700) and the 26%/28% breakpoint ($232,600) were all hardcoded 2024 values applied to every year -> AMT mis-computed for all 2023/2025 returns (2023 exemption overstated $4,400 -> AMT understated $1,144) | fail: _compute_amt(300k, single) returns identical value for 2023 and 2024 (diff $0) — pass: 2023 single AMT exceeds 2024 by $1,144; MFJ by $1,768; 2024 single guard = $55,718 | gated? N | PR #83

**MAINTAIN:** #82 merged to main (HEAD cb29499); baseline suite green at 1029. Rebase-before-push held.

**Angle (continued hardcoded-constant sweep from #82):** swept US/CA/IN engines for year-indexed
constants applied across years. AMT was the highest-value instance — four constants, large per-return
dollar impact, all wrong for non-2024 years. Moved to an `amt` block (exemption/phaseout per status +
single-valued rate_breakpoint) in us/{2023,2024,2025}.yaml; `_compute_amt` now reads fed_tables with
the 2024 values as fallback (no regression). Tested directly against the real loaded year tables.
Suite 1029 -> 1032.

**Still-open instances of THIS class (logged, NOT bundled — keep PRs focused):** (1) US PTC FPL base
`14580 + 5140*(hh-1)` hardcoded in `_compute_ptc` (line ~173) — indexed annually; (2) CA medical-
expense fixed threshold `2759` (line ~294) — indexed (2023 $2,635 / 2025 $2,834). Both are genuine
table-currency bugs for next cycles. NOT statutory-fixed: confirmed SS §86 base ($25k/$32k), $3,000
cap-loss limit, IN §16 prof-tax $2,500, IN §71(3A) $2L are fixed-by-statute (correctly hardcoded).

## Cycle 44 — FULL LIFECYCLE (2026-06-15) [5-primitive: research subagent -> worktree -> PR]

MATRIX | make US PTC federal-poverty-line base year-specific (was hardcoded 2024) | _compute_ptc hardcoded the FPL base 14580 + 5140*(hh-1) for every year and did not even receive year/fed_tables; the FPL is indexed annually (a coverage year uses prior-year HHS guidelines: 1-person 2023 $13,590 / 2024 $14,580 / 2025 $15,060) -> ACA marketplace filers mis-placed across applicable-% buckets for 2023 AND 2025 | fail: _compute_ptc ignores year tables, 2023 single $35k AGI returns $10,600 (uses 2024 base) — pass: 2023 -> $9,900 (FPL% 2.575 -> 6%); 2025 $37k -> $10,520 (FPL% 2.457 -> 4%); 2024 $35k guard -> $10,600 | gated? N | PR #84

**MAINTAIN:** #83 merged to main (HEAD da2d75c); baseline suite green at 1032. Rebase-before-push held.

**5-primitive method:** (1) RESEARCH subagent validated both logged table-currency candidates (US PTC
FPL vs CA medical threshold), surfaced the correct indexed values, and recommended PTC as higher-value
(unbounded per-return $ impact via the applicable-% the FPL drives, wrong for 2 of 3 years) despite
needing a signature change; CA medical was bounded to ~$11-19/return. (2) DEVELOP in a git worktree
(/tmp/wt-ptc). (3) PR. Threaded fed_tables into _compute_ptc (mirrors the adjacent _compute_ctc(...,
fed_tables) call) + `fpl` block in us/{2023,2024,2025}.yaml (one_person/additional_person), 2024 values
as fallback (no regression). Suite 1032 -> 1035.

**Explicit follow-up (do NOT oversell this fix):** the applicable-% STEP TABLE inside _compute_ptc
(lines ~183-194: 5 hardcoded buckets) is still approximate and NOT year-accurate — only the FPL base is
fixed. Real Form 8962 uses a smooth annually-indexed applicable-figure table + the post-IRA 400%-cliff
removal (year-dependent through 2025). Tracked, not done.

**Remaining table-currency item:** CA medical-expense threshold $2,759 (2023 $2,635 / 2025 $2,834) —
clean (year+fed_tables already in scope, no signature change), but bounded ~$11-19/return: a genuine
but LOW-value fix. After it, this hardcoded-constant class is converged; expect NOTHING-HIGH-VALUE next
unless a fresh angle surfaces.

## Cycle 46 — FULL LIFECYCLE (2026-06-15) [5-primitive: research subagent -> worktree -> PR]

MATRIX | replace US PTC applicable-% step table with the real piecewise-linear Form 8962 ramp | _compute_ptc used a 5-bucket STEP function holding each bucket's UPPER value (flat 8.5% across 300-400% FPL etc.), materially over-charging mid-range ACA filers; the statutory applicable figure is a piecewise-LINEAR ramp through anchors (150%,0)(200%,2%)(250%,4%)(300%,6%)(400%,8.5%), capped 8.5% with no cliff (ARPA/IRA 2021-2025) | fail: at exactly 300% FPL step gave 8.5% -> contribution $3,717.90 -> credit $4,482.10 — pass: ramp gives 6.0% -> $2,624.40 -> credit $5,575.60; 275% interpolates to 5.0% ($5,495.25); 200% boundary 2.0% ($5,916.80); 450% caps 8.5% no-cliff guard ($3,423.15) | gated? N | PR #85

**MAINTAIN:** #84 merged to main (HEAD e0851c7); baseline suite green at 1035. Rebase-before-push held.

**5-primitive method:** (1) RESEARCH subagent pinned the exact Form 8962 Table 2 schedule and CAUGHT an
error in my proposed single-slope formula — the real schedule has per-tier slopes (300-400% is shallower,
0.025 vs 0.04), so a single line 1.5->4.0 understates contribution at 250-300%. Used the 5-anchor table
instead. (2) DEVELOP in git worktree (/tmp/wt-ptc2). (3) PR. Implemented `_ptc_applicable_figure` linear
interpolation + a YAML `ptc.applicable_figure` anchor block + `cap_applicable_pct` in us/{2023,2024,2025}
.yaml (identical across years — indexing suspended 2021-2025; FPL base already year-specific from #84).
Code fallback = enhanced schedule so a table without the block doesn't regress.

**Existing-test correction (NOT a regression):** the 3 #84 FPL-base tests asserted dollar values computed
under the OLD step function; the corrected ramp changes those amounts (year-specificity PROPERTY still
holds — 2023 $35k $10,494.41 != 2024 $35k $10,739.23). Updated their expected values + docstrings; renamed
`_2024_unchanged` -> `_2024` (no longer "unchanged"). Suite 1035 -> 1039 (+4 new applicable-figure tests).

**Flagged follow-ups (NOT done, not oversold):** (1) <100% FPL: engine still treats <150% as 0%
contribution -> over-credits genuine sub-100% filers who are generally PTC-ineligible (has narrow lawful-
immigrant exceptions -> needs an input to handle correctly; left as-is). (2) Form 8962 uses applicable
figure x (MAGI/household income); engine approximates with agi. (3) Post-2025 the 400% cliff returns ->
a 2026 table would add a cliff anchor (the table-driven design makes this a YAML edit). This class is now
genuinely converged; expect NOTHING-HIGH-VALUE next unless #85+ merges open something or a new year appears.

## Cycle 47 — FULL LIFECYCLE (2026-06-15) [5-primitive: research subagent -> worktree -> PR]

MATRIX | federal 1040 MeF line 24 (Total tax) must exclude state income tax | us_mef.py mapped line24_total_tax to the engine's totals["total_tax"] = federal_tax + STATE_tax + se_tax; lines 22/23 are already federal-only, so line24 contradicted line22+line23 and overstated a federal filer's Total Tax by the entire state income tax (CA/NY filers, commonly $2k-$15k+) | fail: federal $8k + SE $1k + state $3k -> line24 $12,000 — pass: line24 $9,000 (= line22+line23, federal-only); invariant line24==line22+line23 holds | gated? N | PR #86

**MAINTAIN:** #85 merged to main (HEAD fc6ca1f); baseline suite green at 1039. Rebase-before-push held.

**Method:** 5-primitive. RESEARCH subagent audited the PREVIOUSLY-UNAUDITED surfaces (estimated_tax.py
§6654, filing serializers, optimize.py) — verified §6654 correct (incl. exact $150k 110%/100% boundary),
CA/IN serializers clean, optimize.py acceptable. It surfaced this us_mef issue but rated HOLD (non-
transmitted artifact). I VERIFIED directly: federal_tax already folds in AMT (us_engine:601) + NIIT
(us_engine:620), and line22/23 are federal-only, so line24=line22+line23 is the unambiguous Form-1040
definition — the state-tax inclusion is a clear bug with a known-correct value, not a design choice.
Developed in worktree (/tmp/wt-mef). All existing serializer/real-flow tests are state-free so the fix
changes only state-bearing returns; suite 1039 -> 1041 (+2). Updated one synthetic test that had
conflated line24 with total_tax (added federal_tax/self_employment_tax to its line_items).

**DELIBERATELY DEFERRED (design decision, NOT forced — flagged for operator):** line33_total_payments
omits ACTC + excess-SS, and line34/line37 (refund/owing) reflect the engine's COMBINED federal+state
position. Making the whole federal artifact federal-only-and-reconciling is a real semantics decision
(it would remove the user's only combined-net view since no STATE artifact is generated yet). Tracked:
build a state artifact + decide federal-only vs combined refund display. Did NOT unilaterally change it.

**Convergence:** core engines + §6654 + CA/IN serializers verified correct across two deep audits. After
this, the remaining items all need a design decision (us_mef refund semantics + state artifact) or new
inputs (<100% FPL exceptions) — expect HOLD next unless the operator green-lights the state-artifact design.

## Cycle 49 — FULL LIFECYCLE (2026-06-15) [5-primitive: research subagent -> worktree -> PR]

MATRIX | complete federal-only 1040 MeF artifact: line28 ACTC + line33 payments + reconciling refund | after #86 made line24 federal-only, line33 still = withholding ONLY (omitted ACTC + excess-SS), there was NO line28, and line34/line37 still pulled the engine's COMBINED federal+state refund -> the federal artifact didn't reconcile (line34 != line33-line24) when state tax present, and refundable ACTC/excess-SS never showed as payments | fail: no line28 key; line33 $300 (withholding only) for a $1.7k-ACTC + $500-excess-SS filer; federal refund showed combined owe — pass: line28 $1,700; line33 $2,500; line34 federal refund $2,500; state filer fed refund $1,000 != combined owe $2,000; PTC-double-count guard | gated? N | PR #87

**MAINTAIN:** #86 merged to main (HEAD 55023ef); baseline suite green at 1041. Rebase-before-push held.

**Why not HOLD (the #86-merge unblock):** last cycle I DEFERRED line33/line34 as a design decision
(federal-only vs combined). #86 merging = operator ENDORSED federal-only federal-1040 semantics, so
completing the same bug class is sanctioned, not a unilateral call. RESEARCH subagent resolved the crux:
the engine NETS net-PTC into federal_tax (line24), so line33 must EXCLUDE PTC (proven algebraically:
PTC-in-line24-reduction === PTC-in-line33-payment for the refund, so adding both double-counts). line33
= withholding + ACTC + excess-SS; ptc_repayment correctly stays in line24 (it's a Sch-2 tax).

**Fix:** added line28_additional_child_tax_credit; line33 = withholding+ACTC+excess-SS; line34/line37
computed from line24/line33 (federal-only, reconciling) instead of totals[]. State-free equivalence
proven (line34==engine refund when state=0) -> existing state-free tests green. Suite 1041 -> 1045 (+4).

**Flagged (cosmetic fidelity, NOT correctness — do NOT "fix" by adding PTC to line33, double-counts):**
because net-PTC stays in line24, the artifact's line24/line33 each understate the strict-IRS values by
the PTC amount (refund/owe still exactly correct). A form-faithful refactor would relocate PTC to line31
(needs federal_tax decomposition) — out of scope. The us_mef federal-1040 bug class is now CLOSED
(line24 #86 + line28/33/34/37 this cycle). Next: state artifact (so combined view has a home) or HOLD.

## Cycle 51 — FULL LIFECYCLE (2026-06-15) [5-primitive: research subagent -> worktree -> PR]

MATRIX | India engine: credit advance tax + self-assessment tax + TCS as prepaid taxes (not just TDS) | balance = total_tax − total_tds credited ONLY TDS; advance tax (paid quarterly by anyone with business/capital-gains/professional income) + self-assessment tax + TCS were unmodelled -> the FULL liability showed as owing for a huge population who had already pre-paid | fail: no 'advance_tax' line_item; ₹2.96L liability + ₹1L advance -> balance owing still ₹2.96L — pass: balance owing ₹1.96L; advance+self-assessment+TCS pool can refund (overpay ₹20k -> refund ₹20k); no-input case byte-identical | gated? N | PR #88

**MAINTAIN:** #87 merged to main (HEAD c9c1845); baseline suite green at 1045. Rebase-before-push held.

**Re-examination win (corrected a prior under-rating):** in C50 I filed India advance/self-assessment
tax under "engine scope expansion" and downgraded it. On re-examination it is a genuine high-value
CORRECTNESS bug: ignoring advance tax produces a flat-wrong balance/refund (off by the full prepaid
amount) for the large non-salary-income population. RESEARCH subagent confirmed the ITR Part B-TTI model
(total_taxes_paid = TDS + TCS + advance + self-assessment; balance = total_tax − total_taxes_paid; no
cap/ordering) and that §234B/§234C shortfall interest is a SEPARATE liability-side computation to keep
out of scope (noted in-engine). Clean additive user_answers inputs (advance_tax_paid /
self_assessment_tax_paid / tcs_collected), matching the engine's professional_tax_paid pattern.

**Change:** in_engine total_taxes_paid pool + line_items (advance_tax/self_assessment_tax/tcs/
total_taxes_paid) + totals (total_taxes_paid); in_itr PartB_TTI gains TCS/AdvanceTax/SelfAssessmentTax/
TotalTaxesPaid. No-input case byte-identical -> existing tests green. Suite 1045 -> 1049.

**Flagged (out of scope, noted in-engine):** §234B/§234C interest on advance-tax shortfall (liability-
side, separate). Remaining tracked: US state artifact (design green-light); CA refundable benefits
CWB/GST (engine scope); <100% FPL exceptions (new input); IN surcharge marginal relief (narrow+risky).

## Cycle 52 — FULL LIFECYCLE (2026-06-15) [5-primitive: research subagent -> worktree -> PR]

MATRIX | add Canada Workers Benefit (CWB, Schedule 6) as a refundable credit | the CA engine modelled only non-refundable credits + TDS-style withholding; the CWB is a REFUNDABLE credit claimed ON the T1 (unlike GST/CCB which CRA pays separately) that increases the return refund -> low-income workers' refund was understated by up to $1,518 (single) / $2,616 (family) | fail: no 'canada_workers_benefit' line_item (KeyError) — pass: $15k working income -> full $1,518; $30k -> $940.35 (partial phaseout); $2,500 below floor -> $0; $40k fully phased out -> $0; family flag -> $2,616; refundable (refund = CWB − residual tax) | gated? N | PR #89

**MAINTAIN:** #88 merged to main (HEAD 1c5539f); baseline suite green at 1049. Rebase-before-push held.

**Re-examination win (same lens as C51):** "CA models no refundable benefits" was logged as scope. But
CWB specifically is a T1 refundable credit (Schedule 6) -> omitting it understates the RETURN refund =
correctness bug (distinct from GST/HST credit + CCB, which CRA auto-calcs and pays SEPARATELY, not on
the T1). RESEARCH subagent confirmed SHIP (clean single-filer federal v1), corrected my threshold values
(my ~$24,975/$28,494 were 2023; 2024 = $26,149/$29,833), and rated 2025 values MEDIUM confidence.

**Change:** federal CWB basic = min(max, 0.27·(working_income−3000)) − 0.15·(net_income−threshold),
floored at 0, credited as a payment (balance −= cwb, mirrors US ACTC). Table block in ca/{2023,2024}.yaml
ONLY — 2025 OMITTED (medium-confidence values; fallback cwb=0 -> no regression; flagged for CRA figures).
Inputs: taxpayer_age (existing, ≥19 gate, default 19), full_time_student (new, default no),
has_spouse_or_dependant (new, unlocks family max). Surfaced line_items['canada_workers_benefit'];
netfile auto-reflects the refund. Suite 1049 -> 1055.

**Excluded + flagged (noted in-engine):** disability supplement (needs DTC); provincial AB/QC/NU
reconfigurations (note when province in {AB,QC,NU}); true family AFNI (spousal income unmodelled — note);
secondary-earner exemption; 2025 table (pending official CRA Schedule 6 values). Next: 2025 CWB values,
or US state artifact (design), or HOLD.

## Cycle 53 — FULL LIFECYCLE (2026-06-15) [5-primitive: research subagent -> worktree -> PR]

MATRIX | add US Earned Income Tax Credit (EITC, Form 1040 line 27) as a refundable credit | the engine omitted the EITC entirely (noted out-of-scope x2); it is the single largest refundable credit for low-income workers (up to $7,830 for 3+ kids, 2024) -> their refund was understated by thousands. Direct US analog of the CA CWB (#89) | fail: no 'earned_income_credit' line_item — pass: 1 kid $15k -> $4,213 (plateau); $40k single -> $1,451.66 (phaseout); MFJ $40k -> $2,557.47 (higher start); 2 kids + $12k investment -> $0 (cliff); childless no-age -> $0; childless age30 $9k -> $632 | gated? N | PR #90

**MAINTAIN:** #89 merged to main (HEAD 904cf00); baseline suite green at 1055. Rebase-before-push held.

**Re-examination win #3 (same lens as #88 IN-advance-tax, #89 CA-CWB):** "EITC out of scope" was a
flat-wrong-refund bug for a huge population. RESEARCH subagent verified full 2023/2024/2025 parameter
tables (statutory rates 7.65/34/40/45% in, 7.65/15.98/21.06/21.06% out), gave a SHIP-flagged verdict,
and surfaced two honest compromises: (1) num_deps approximates qualifying-children (can over-credit
non-qualifying dependents — loudly noted; follow-up = dedicated input); (2) the 0-kid age-25-64 gate
needs a NEW numeric taxpayer_age input in us_engine (it only had the boolean 65+); absent age -> 0-kid
credit withheld (conservative).

**Change:** `_compute_eitc` (phase-in min(earned*rate,max) − phaseout_rate*max(0,max(earned,agi)−start),
MFJ-vs-other start); full `eitc` table block replaced the incomplete 2024 stub + added to 2023/2025;
investment cliff includes tax-exempt interest; FEIE (Form 2555) + MFS hard-bar; subtract from balance
(mirrors ACTC); line_items/credits['earned_income_credit']; us_mef line27 + included in line33 payments
(so the MeF refund matches the engine). Updated the one ACTC test whose refund now also includes EITC.
Suite 1055 -> 1062.

**Flagged out of scope (notes):** qualifying-child tests (num_deps proxy), SSN validity, "qualifying
child of another", MFS-living-apart exception (all MFS barred), half-year residency, combat-pay election,
prior-year-earned-income lookback. Follow-up: dedicated num_qualifying_children input. Remaining tracked:
US state artifact (design); IN surcharge marginal relief (narrow+risky); <100% FPL exceptions (input).

## Cycle 54 — FULL LIFECYCLE (2026-06-15) [5-primitive: research subagent -> worktree -> PR]

MATRIX | split CTC ($2,000 under-17) from the Credit for Other Dependents ($500) | _compute_ctc gave the full $2,000 CTC to EVERY dependent; only children under 17 qualify, others (17+, parents, relatives) get the $500 ODC -> 17+ dependents over-credited by $1,500 each AND the refundable ACTC was inflated by counting non-children | fail: no 'credit_for_other_dependents' key; 3 deps (1 other) -> $6,000 CTC — pass: $4,000 CTC + $500 ODC; default (no input) -> $4,000/$0 (no regression); phaseout reduces ODC first ($410k MFJ -> ODC $0, CTC $4,000); ACTC uses children only (1 child -> $1,700 not $3,400 cap) | gated? N | PR #91

**MAINTAIN:** #90 merged to main (HEAD 76e460c); baseline suite green at 1062. Rebase-before-push held.

**Distinct over-credit bug (not a refundable-credit variant):** unlike the refundable wave (#88/89/90 which
ADDED missing credits), this CORRECTS an over-credit in a core existing credit. RESEARCH subagent gave a
SHIP verdict, confirmed ODC=$500 flat 2023-2025, the combined CTC+ODC phase-out, and that the ACTC must
count qualifying children only. The one MEDIUM-confidence point (CTC-vs-ODC phaseout ordering) -> chose
ODC-first (taxpayer-favorable, 8812-consistent; only shifts the split inside the phaseout band) w/ comment.

**Change:** new `_num_other_dependents` input (default 0 -> all deps are children -> NO regression);
`_compute_ctc` returns (ctc_children, odc); federal_tax consumes ctc+odc; ACTC uses num_qualifying_kids
and ODC absorbs tax first (so refundable CTC survives); odc_per_dependent:500 in ctc YAML x3 years;
line_items/credits['credit_for_other_dependents']. Suite 1062 -> 1066. All existing CTC/ACTC tests green
(additive). 

**Flagged follow-up:** the same num_deps-as-qualifying-children proxy still affects EITC (#90) — a unified
qualifying-child input (with the differing CTC<17 vs EITC<19 age tests) would close both. Remaining tracked:
US state artifact (design); IN surcharge marginal relief (narrow+risky); <100% FPL (input); 2025 CWB (CRA).

## Cycle 55 — FULL LIFECYCLE (2026-06-15) [5-primitive: research subagent -> worktree -> PR]

MATRIX | EITC qualifying-children count distinct from raw dependent count (closes #90 flagged compromise) | _compute_eitc bucketed on raw num_deps; an EITC qualifying child is under-19 (not a parent/relative), so a filer supporting a dependent PARENT got the 1-child EITC (~$4,213) instead of the childless credit -> ~$3,938 over-credit for a common situation | fail: dependent-parent (num_eitc_qualifying_children=0) -> $4,213 — pass: -> $274.75 (childless, age-40 gate passes); default (no input) -> $4,213 (no regression); coexists with #91 ODC (17yo: ODC $500 + EITC 1-child) | gated? N | PR #92

**MAINTAIN:** #91 merged to main (HEAD 7bca23c); baseline suite green at 1066. Rebase-before-push held.

**Closes a self-flagged defect:** _compute_eitc's own docstring already admitted "num_children is approximated
by the dependent count, so this can over-credit dependents who are not EITC-qualifying children." RESEARCH
subagent verified EITC qualifying-child = under-19/under-24-student/disabled (NOT a parent), confirmed it's a
DIFFERENT test than CTC under-17 (so a 17-18yo is an EITC child but a CTC other-dependent), and that the new
input must be INDEPENDENT from #91's num_other_dependents (they overlap deliberately, don't sum to num_deps).
SHIP verdict (material + common dependent-parent case).

**Change:** `_num_eitc_qualifying_children(user_answers, num_deps)` defaults to num_deps (no regression),
capped at num_deps; EITC call site uses it instead of num_deps; childless-age-gate (25-64) handles the
0-child result correctly via existing logic. Suite 1066 -> 1069.

**Credit-accuracy seam now substantially complete:** ACTC #77, PTC #84/85, EITC #90, EITC-children #92,
CWB #89, IN-prepaid #88, CTC/ODC split #91. Remaining: US state artifact (design); IN surcharge marginal
relief (narrow+risky); <100% FPL (input/niche); 2025 CWB (CRA data); IN §234B/C interest. Likely HOLD next.

## Cycle 56 — FULL LIFECYCLE (2026-06-15) [5-primitive: research subagent -> worktree -> PR]

MATRIX | tax a qualifying surviving spouse (QSS) as MFJ, not single | _resolve_filing_status coerced any status outside {single,mfj,hoh} to 'single', so a QSS (recently widowed w/ dependent child, IRC §2(a)) — a computational clone of MFJ — got single brackets + $14,600 deduction instead of MFJ's $29,200 -> over-taxed | fail: QSS $80k -> std deduction $14,600 / ordinary_tax $9,441 — pass: $29,200 / $5,632 (over-tax of $3,809 fixed); QSS $300k AGI 1 child -> full $2,000 CTC (MFJ $400k start, not single's wiped-to-$0); 'qss' short alias works | gated? N | PR #93

**MAINTAIN:** #92 merged to main (HEAD d0945be); baseline suite green at 1069. Rebase-before-push held.

**Distinct surface (filing status, not credits):** RESEARCH subagent tabulated all 16 status-driven
sites and confirmed EVERY MFJ branch keys on the exact string "married_filing_jointly", so a one-line
alias QSS->married_filing_jointly inherits them ALL correctly (brackets, std deduction, additional-std,
LTCG, CTC/EITC/AMT/NIIT/FICA thresholds, SS base). Verified artifacts use the RAW user filing_status
(us_mef.py:39, build_return.py:86) so QSS is NOT mislabeled as MFJ. Chose the alias over duplicating MFJ
values into 6 YAML blocks + 8 branches (14 error-prone edit sites). SKIPPED MFS (=single except the top
37% bracket >$365,600 + EITC-disallow; low value). Spouse-65/blind boxes are opt-in -> harmless for QSS.

**Change:** alias qss/qualifying_surviving_spouse/qualifying_widow(er)/... -> married_filing_jointly in
_resolve_filing_status before the validity check. Flagged the minor EITC-start approximation in a comment.
Suite 1069 -> 1072. Zero other edits needed (the string-keyed branches do the rest).

**Remaining (design/risky/niche/data — likely HOLD next):** US state artifact (design); IN surcharge
marginal relief (narrow+risky, CG-cap entangled); <100% FPL (input); 2025 CWB values (CRA data); IN
§234B/C interest; full MFS support (low value). The clean distinct-bug vein is now very thin.

## Cycle 57 — FULL LIFECYCLE (2026-06-15) [5-primitive: research subagent -> worktree -> PR]

MATRIX | cap the IRA and HSA above-the-line deductions at their statutory contribution limits | the engine took user-entered HSA/IRA amounts at FACE VALUE with no cap (student-loan interest WAS capped); an over-limit entry under-states AGI AND under-taxes Social Security (provisional income) -> double under-payment. The IRA limit even already sat in the YAML, IGNORED | fail: $20k IRA entry -> $20k deduction — pass: capped $7,000 (age 40) / $8,000 (50+ catch-up); HSA $10k -> $8,300 family / $4,150 self; within-limit $5k unchanged | gated? N | PR #94

**MAINTAIN:** #93 merged to main (HEAD 1394b07); baseline suite green at 1072. Rebase-before-push held.

**"Table exists but ignored" pattern (like #83 AMT / #84 PTC):** the `ira: {contribution_limit, catchup_
50_plus}` block was in all 3 YAMLs but never read; HSA had no block. RESEARCH subagent confirmed the limits
(IRA 6500/7000/7000 +1000 catch-up @50; HSA self 3850/4150/4300, family 7750/8300/8550, +1000 @55), gave a
SHIP-both verdict (genuine: feeds AGI + SS provisional = double under-pay, not just a data-entry guardrail),
and flagged the catch-up key name (catchup_50_plus / catchup_55_plus) + that taxpayer_age was parsed BELOW
the deduction site (hoisted it).

**Change:** read fed_tables ira/hsa; IRA cap = limit + (catch-up if age>=50); HSA cap = (family default |
self) limit + (catch-up if age>=55); min() the deduction, note the excess. Added hsa YAML block x3 (IRA
needed no YAML change). hsa_coverage input defaults 'family' (errs toward the higher cap -> never wrongly
denies a family filer's legit deduction). Hoisted taxpayer_age above line 506 (removed the duplicate EITC
parse). Suite 1072 -> 1077.

**Flagged out of scope (notes):** IRA MAGI deduction phase-out for employer-plan participants; the
ira_401k_contributions key conflates IRA + 401(k) (401k is pre-tax, not a separate deduction) — left as-is.
Remaining tracked: US state artifact (design); IN surcharge marginal relief (risky); <100% FPL; 2025 CWB
(CRA data); IN §234B/C. Vein thinning -> likely HOLD next.

## Cycle 58 — FULL LIFECYCLE (2026-06-15) [5-primitive: research subagent -> worktree -> PR]

MATRIX | apply the §213 7.5%-of-AGI floor to Schedule A medical expenses | the engine added SCH-A medical_expenses to the itemized total at FACE VALUE; §213 only allows the excess over 7.5% of AGI -> over-deduction that can wrongly tip itemizing past the standard deduction and under-tax | fail: no 'medical_expense_deductible' key; sch_a total $30,000 ($10k medical + $20k mortgage at $80k AGI) — pass: floor $6,000 -> deductible $4,000 -> sch_a $24,000; $5k medical < floor -> $0; IRA $7k lowers AGI to $73k -> floor $5,475 -> $4,525 | gated? N | PR #95

**MAINTAIN:** #94 merged to main (HEAD 2e870c8); baseline suite green at 1077. Rebase-before-push held.

**Over-deduction lens, 2nd US instance (after #94 IRA/HSA):** swept other jurisdictions' deduction caps —
IN §80C/80CCD/80D are properly capped (line 337 etc.); CA RRSP is uncapped but its cap needs prior-year
NOA room (input-blocked, skipped). The clean high-value US item: SCH-A medical had NO 7.5% AGI floor.
RESEARCH subagent confirmed 7.5% (permanent since CAA 2021, all years), AGI base is post-above-line (so
the #94 IRA/HSA caps flow through correctly), and CRITICALLY verified NO existing test encodes the unfloored
behavior (the sch_a fixture has medical $4,200 but its consumers only assert extraction, not totals) -> zero
regression risk. SHIP.

**Change:** medical_deductible = max(0, medical_raw - 0.075*agi), table-driven via schedule_a.medical_agi_
floor_rate (0.075 default) in us/{2023,2024,2025}.yaml; surfaced line_items['medical_expense_deductible'] +
a §213 note. Floor uses the post-above-line AGI (block sits after agi=line 615). Suite 1077 -> 1080.

**Remaining (design/risky/niche/input/data):** US state artifact (design); CA RRSP room cap (NOA input);
IN surcharge marginal relief (risky); <100% FPL (input); 2025 CWB (CRA data); IN §234B/C; full MFS;
charitable 60%-AGI / mortgage $750k limits (rarer). Vein thinning -> likely HOLD next.

## Cycle 59 — FULL LIFECYCLE (2026-06-15) [5-primitive: broad-sweep subagent -> worktree -> PR]

MATRIX | credit the Additional Medicare tax withheld in W-2 box 6 (Form 8959 Part IV) | the engine adds the 0.9% Additional Medicare tax to the liability (via _compute_fica) but never credited the employer's matching box-6 withholding -> every high-wage W-2 employee was double-charged the 0.9% surtax they already paid via paycheck | fail: no 'additional_medicare_tax_withheld' key; $300k single owes $900 more — pass: box 6 $5,250 -> $900 credit cancels the $900 liability; box 6 at exactly 1.45% -> $0 credit (guard) | gated? N | PR #96

**MAINTAIN:** #95 merged to main (HEAD cb5e671); baseline suite green at 1080. Rebase-before-push held.

**Found via a FINAL broad sweep** (income inclusion / FICA / dividend-CG stacking / deductions / refund
assembly across all 3 engines). The subagent VERIFIED CORRECT: US income assembly (no double-count), SE/SS
cap + half-SE-deduction-excludes-0.9%, NIIT MAGI+FEIE, qual-div/LTCG stacking, CA gross-up/DTC/inclusion/
clawback/CWB, IN salary/house-property/CG-split/87A/prepaid. The ONE bug: box-6 additional-Medicare
withholding (0.9% above 1.45%) was extracted but unread, so the liability had no offsetting credit ->
$900 over-tax @ $300k, $2,700 @ $500k. Clean (data in scope, no new input/table).

**Change:** addl_medicare_withheld = max(0, box6_medicare_tax_withheld - 1.45%*medicare_wages); credited in
the balance line alongside excess-SS; line_items['additional_medicare_tax_withheld'] + Form 8959 note.
Suite 1080 -> 1082.

**CONVERGENCE CALL:** the broad sweep found exactly ONE clean material bug (this) and verified the rest
correct. After this merges, the engine is substantially converged. Remaining items ALL design-gated
(US state artifact), input-blocked (CA RRSP room, <100% FPL), need external data (2025 CWB), risky (IN
surcharge marginal relief), or rare (charitable 60%/mortgage $750k, full MFS). EXPECT HOLD next cycle.

## Cycle 63 — FULL LIFECYCLE (2026-06-15) [5-primitive: research subagent -> worktree -> PR]

MATRIX | size the US 1040-ES quarterly voucher on net owed (balance_owing), not total_tax-withholding | quarterly_us_1040es sized vouchers at total_tax-withholding, ignoring the refundable credits + extra payments (EITC/ACTC/excess-SS/addl-Medicare) the engine nets into balance_owing -> a self-employed filer with credits was told to pay up to 2x too much per quarter. The CA sibling already used balance_owing | fail: total_tax $10k - wh $2k = $8k -> $2,000/qtr (credits ignored) — pass: balance_owing $4k -> $1,000/qtr; existing $1,750/qtr fixtures corrected to carry balance_owing | gated? N | PR #97

**MAINTAIN:** #96 merged to main (HEAD cdee9ad); baseline suite green at 1082. Rebase-before-push held.

**Found via probing an UNAUDITED surface:** filing/quarterly.py (the quarterly voucher generator) and the
build_return.py PDF field-mapping were never audited (C47 covered §6654 estimated_tax.py + the JSON/XML
serializers, NOT these). PDF field dicts pull correct keys (only the already-tracked federal-vs-combined
issue). quarterly_us_1040es had the bug; RESEARCH subagent confirmed 1040-ES required estimate = liability
- withholding - REFUNDABLE CREDITS (so balance_owing is the correct + more-accurate base; no reason to
prefer total_tax-withholding), the $1,000 threshold semantics hold, and that exactly 2 existing fixtures
(test_quarterly_vouchers.py:35,43) omitted balance_owing and needed it added (legit fixture correction,
keeps the $1,750/qtr assertion). CA function unchanged (already correct).

**Change:** annual_owed = balance_owing (was max(0, total_tax-withholding)); total_tax/withholding still
read for the informational voucher lines. Corrected 2 fixtures + 1 new credit-netting test. Suite 1082->1083.

**Table values verified correct C62, engine logic C59, this closes the last unaudited computation surface
(quarterly vouchers). Remaining ALL design/input/data/risky/rare. EXPECT HOLD next.**

## Cycle 64 — FULL LIFECYCLE (2026-06-15) [dependency-security axis; cross-fleet CVE recon, operator-approved pilot]

MATRIX | remediate application-dependency CVEs — bump starlette + cryptography | a fleet-wide pip-audit recon (across sibling repos) found this repo's venv carried starlette 1.2.1 (CVE-2026-54282/54283, DoS — transitive via fastapi 0.136.3, which permits >=0.46.0) and cryptography 48.0.0 (GHSA-537c-gmf6-5ccf); requirements pinned `cryptography>=42` (floor permitted the patch but the installed version was stale) and had NO explicit starlette floor | fail: pip-audit reports 10 known vulns across 2 APP packages (starlette x3 + cryptography x1; ignoring pip/setuptools toolchain) — pass: add `starlette>=1.3.1` floor + raise `cryptography>=48.0.1` in requirements.txt; venv upgraded to starlette 1.3.1 / cryptography 49.0.0; pip-audit app-dep vulns = 0; 1083 tests green + scripts/validate.sh ✅ (Streamlit boot smoke) | gated? N | PR #98

**Axis note:** this is the dependency-SECURITY axis, orthogonal to the tax-computation lane the cron normally
works (which is converged — C63 said "EXPECT HOLD next"). Found by a cross-fleet CVE recon run from the
ai-agents-platform R&D loop; operator approved a single-repo pilot here (most-exposed of the fleet).

**Out of scope (flagged, not fixed):** the venv's `pip` 23.0.1 + `setuptools` 66.1.1 carry their own CVEs,
but they are the venv BOOTSTRAP toolchain — not declared in requirements.txt, not shipped with the app, and
low real risk (they affect installing untrusted packages, not the running tax app). Correct fix is the
Dockerfile/base-image layer, not app requirements; pinning pip in app requirements is non-standard. Left for
a base-image hygiene pass.

**Change:** requirements.txt — `cryptography>=42`→`cryptography>=48.0.1`, new `starlette>=1.3.1` (explicit
security floor for the fastapi-transitive dep). No code change (a dep bump has no unit test; the audit delta
+ green suite + boot smoke is the proof). Additive + revertible.

## Cycle 65 — FULL LIFECYCLE (2026-06-15) [5-primitive: OPERATOR-APPROVED scope -> research -> worktree -> PR]

MATRIX | add the California Form 540 state-tax artifact (completes the #86/87 federal-only refactor) | the engine computes CA state_tax but NO state artifact surfaced it — the federal 1040 was made federal-only (#86/87, "state tax belongs on a state artifact") leaving the state tax with no deliverable | fail: no 'ca_540_json' artifact for a CA filer — pass: CA resident $80k + $4k box-17 -> ca_540_json with state_tax $3,483.60, withheld $4,000, refund $516.40; NY/non-CA filer -> NO 540 (gate) | gated? N | PR #99

**MAINTAIN:** #97 + #98(security CVE) merged to main (rebased onto eb2f1cb); baseline suite green at 1083. Rebase-before-push held (resolved a ledger union with the security Cycle-64 entry).

**Convergence break = OPERATOR GREEN-LIGHT.** After many honest HOLD cycles (correctness vein exhausted,
quadruple-verified C59/C62/C63/C64), I surfaced the fork via AskUserQuestion; operator chose "Build CA
state-tax artifact." RESEARCH subagent designed it: state line_items (state_tax/state_taxable_income/
state_standard_deduction/agi all confirmed by running the engine), state withholding recomputed from W-2
box 17 (not a line_item), balance = state_tax - withheld; mirror the in_itr/us_mef envelope. CRITICAL
GATE TRAP: gate on state_of_residence=="CA" (NOT line_item presence — TX/FL/WA load + spread state_tax=0;
NY is state-taxed but not a 540). FilingArtifact jurisdiction="US" (CA-state of a US filer; "CA" would
mislabel as Canada), form_code="CA-540".

**Change:** new filing/ca_540.py serialize_ca540 (transmissible=False, schema ca540-0.1-draft); wired into
build_return._us_artifacts gated CA+state_tax>0; 4 serializer tests + 2 gate tests. Purely additive — no
engine/federal-artifact change. Suite 1083 -> 1089.

**Flagged (v1 scope):** CA-only (the one state w/ real income tax in the engine's tables); simple summary
JSON (not a full Form 540 line layout); no CA-specific credits/AMT (uses the engine's state_tax from AGI).

## Cycle 66 — FULL LIFECYCLE (2026-06-15) [5-primitive: in-scope completion of the operator-approved CA-540 artifact]

MATRIX | add a human-readable CA Form 540 PDF alongside the #99 JSON | the CA-540 artifact (shipped #99) emitted ONLY JSON, while every other jurisdiction emits a human-readable PDF (federal 1040 PDF, CA T1 PDF) -> the state tax had no PDF deliverable, an inconsistency | fail: only 'ca_540_json' for a CA filer, no 'ca_540_pdf' — pass: ca_540_pdf present, mime application/pdf, valid %PDF- bytes, transmissible False; same CA-residence gate | gated? N | PR #TBD

**MAINTAIN:** #99 (CA-540 JSON) merged to main (HEAD 344e66f); baseline suite green at 1089. Rebase-before-push held.

**Note:** the wakeup re-fired the "build CA artifact" prompt AFTER #99 already merged — recognized the stale
re-fire, did NOT rebuild the JSON; instead did the natural in-scope completion: a CA-540 PDF via the existing
fill_form("us", year, "CA-540", {...}) pattern (no template -> fill_form's plain-text draft-PDF fallback, same
as the 1040/T1 PDFs). Mirrors the federal-1040 PDF block exactly; same CA-residence gate. Purely additive.
Suite stays 1089 (extended the existing CA-540 build_return test with PDF assertions rather than a new test).

**CA state-tax artifact now COMPLETE (JSON #99 + PDF #66), consistent with the 1040 (PDF+JSON) and T1 (PDF+XML)
pairings. Further state work (other states, CA credits/AMT, real 540 template) is a fresh operator scope call.**

## Cycle 67 — FULL LIFECYCLE (2026-06-15) [5-primitive: research subagent -> worktree -> PR]

MATRIX | add CA Mental Health Services Tax (1% over $1M, R&TC §17043) to state tax | the engine's CA state_tax was only the bracket tax (topping at 12.3%); CA levies a SEPARATE flat 1% Mental Health Services Tax on taxable income over $1M (the published 13.3% top = 12.3% + 1% MHS) -> CA filers >$1M taxable under-taxed by 1% of the excess, now visibly wrong on the new CA-540 artifact | fail: no 'state_mental_health_surcharge' key; $2M-taxable single state_tax $227,394.76 — pass: surcharge $10,000 -> state_tax $237,394.76; $500k-taxable guard -> $0 surcharge | gated? N | PR #TBD

**MAINTAIN:** #100 (CA-540 PDF) merged to main (HEAD ccb5819); baseline suite green at 1089. Rebase-before-push held.

**Surfaced BY the CA-540 work:** building the CA-540 artifact (#99/#100) made CA state-tax correctness matter
more; the C62 table-value audit had verified US-federal/CA-federal(Canada)/ON-province but NOT the US-CA-STATE
brackets. Checked them -> top 12.3%, MHS omitted. RESEARCH subagent confirmed MHS = flat 1%/$1M-threshold/all-
statuses/permanent/taxable-income-base, and the clean SELF-GATING design (read from the CA state table -> only
CA's YAML carries the key -> NY/TX get 0; no `if state=="CA"` branch).

**Change:** `mental_health_surcharge: {rate:0.01, threshold:1000000}` in ca/{2023,2024,2025} state yaml; engine
adds `state_mhs = rate*max(0, st_taxable-threshold)` to state_tax + surfaces `state_mental_health_surcharge` in
state_breakdown; CA-540 serializer shows the line. No existing test breaks (all CA fixtures sub-$1M). Suite 1089->1091.

**CA state-tax now: bracket tax + MHS surcharge, surfaced on the CA-540. Further CA-state correctness (CA-specific
credits, CA AMT, CA AGI nonconformity adjustments) remains a flagged scope expansion.**

## Cycle 69 — FULL LIFECYCLE (2026-06-15) [5-primitive: research subagent -> worktree -> PR]

MATRIX | give CA head-of-household filers their own state schedule (was mapped to single) | us_engine state block mapped HoH->single (st_status = mfj else single), so CA HoH filers got the SINGLE state std deduction ($5,363) instead of CA's HoH/married tier ($11,080, 2x single) -> single parents over-taxed (~$532/return at $90k AGI) | fail: CA HoH $90k state_standard_deduction $5,363 / taxable $84,637 — pass: $11,080 / $78,920; single filers unchanged (guard) | gated? N | PR #TBD

**MAINTAIN:** #101 merged (HEAD 2e0b2e1); #102 (CA std-deduction) open/mergeable; baseline suite green at 1091. Rebase-before-push held.

**SHIP-PARTIAL (disciplined data-confidence split):** RESEARCH subagent found CA HoH STD DEDUCTION fully
confident (CA structurally has single + a married/HoH/QSS tier = 2x single -> HoH std = MFJ value), but CA
HoH BRACKET thresholds NOT >=85% confident -> did NOT ship guessed brackets. NY HoH genuinely uses the SINGLE
brackets (correct now); NY HoH std-deduction gap deferred (moderate confidence).

**Change:** engine 3-way status map with SINGLE-FALLBACK (`st_brackets = _bbs.get(st_status) or _bbs.get(
"single")`; `st_std = _std.get(st_status, _std.get("single"))`) -> regression-proof: states without a HoH key
keep single byte-for-byte. Added CA `standard_deduction.head_of_household` = FTB-correct ($10,726 2023, $11,080
2024+2025; 2024 matches #102's pending MFJ correction). CA HoH now uses the higher std deduction + (fallback)
single brackets. Suite 1091 -> 1093. No existing test touched (none exercised state HoH).

**Flagged follow-ups (need FTB data, NOT shipped — discipline):** CA HoH BRACKET thresholds (FTB Schedule X)
would fix the remaining bracket-narrowing over-tax (~$1,700 more in the unverified example); NY HoH std
deduction (~$11,200). ca/2025 std-deduction staleness (from #102) still open.

## Cycle 70 — FULL LIFECYCLE (2026-06-15) [5-primitive: research subagent -> worktree -> PR]

MATRIX | give NY head-of-household filers their own state standard deduction | the NY state table had only single ($8,000) + MFJ; NY's IT-201 HoH standard deduction is a distinct $11,200 (statutory, NY Tax Law §614) -> NY HoH filers fell back to the single $8,000 (via the #103 3-way map fallback) and were over-taxed ~$176/return at $90k | fail: NY HoH $90k state_standard_deduction $8,000 / taxable $82,000 — pass: $11,200 / $78,800; NY single unchanged (guard) | gated? N | PR #TBD

**MAINTAIN:** #103 (CA HoH map) merged (HEAD c61f94a); #102 (CA std) open; baseline suite green at 1093. Rebase-before-push held.

**Confidence-bar judgment (the discipline from #103, applied the other way):** in #103 I HELD the CA HoH BRACKETS
(<85% — INDEXED yearly thresholds). Here the NY HoH std deduction is a FIXED STATUTORY value (not indexed), and
the repo's already-correct NY single $8,000 / MFJ $16,050 corroborate the source -> RESEARCH subagent rated HoH
$11,200 at ~92%, clearing the bar. So shipping NY-HoH-std while having held CA-HoH-brackets is CONSISTENT (fixed
statutory > indexed threshold on verifiability), not contradictory.

**Change:** added `standard_deduction.head_of_household: 11200` to ny/{2023,2024,2025}.yaml. ZERO code change —
the #103 engine 3-way map already reads head_of_household w/ single-fallback. NY HoH correctly keeps single rate
brackets (only the deduction differed). MFS->single ($8,000) and QSS->MFJ ($16,050) confirmed correct. Suite 1093->1095.

**US-state seam (from the CA-540 artifact) now: #101 CA-MHS, #102 CA-std, #103 CA-HoH-std, #70 NY-HoH-std. Remaining
DATA-BLOCKED/complex: CA HoH brackets (indexed, <85%), NY tax-benefit recapture (complex), 2025 CA std (#102). HOLD likely next.**

## Cycle 72 — FULL LIFECYCLE (2026-06-15) [5-primitive: systematic captured-but-unused audit -> worktree -> PR]

MATRIX | read Form 1098 box 1 mortgage interest into the itemized deduction | the 1098 extractor captured mortgage_interest_received but the engine read mortgage interest ONLY from SCH-A.mortgage_interest -> a homeowner who uploaded a 1098 (the standard lender slip) without a Sch A entry silently LOST the entire (usually largest) itemized deduction | fail: 1098-only filer ($120k wages, $9k SALT, $18k 1098) itemized $9,000 < std $14,600 -> takes standard, $18k dropped — pass: itemized $27,000 -> itemizes; Sch A + 1098 -> $27,000 (no double-count) | gated? N | PR #TBD

**MAINTAIN:** #104 merged (HEAD 7658949); #102 + #105 open; baseline suite green at 1095. Rebase-before-push held.

**Systematic captured-but-unused audit (the #105 lesson, done comprehensively):** RESEARCH subagent cross-referenced
ALL 29 US + 15 CA + 5 IN extractor fields vs engine reads. Found 6 genuine money-drops; the rest informational
(verified). HIGHEST VALUE = 1098 mortgage interest (largest itemized line, every homeowner, cleanest fix = exact
clone of the W-2-box-17 SALT fallback #73). Shipped it. NO double-count (prefer Sch A when present).

**Runner-up DROPS flagged for follow-up (clean, lower-value):** IN FORM-16.section_80e_declared (student-loan
interest, old regime — literal sibling of the shipped section_80d_declared; also restores the cross-border §80E
single-claim guardrail); IN FORM-26AS.advance_tax_paid (form-captured advance tax, key-mismatch w/ the #88
user_answers path — same class as the #67 professional_tax fix); CA T4A.lump_sum_payments box 018 (dropped taxable
income); 1099-DIV box 5 section_199A_dividends (REIT QBI, low value). 1098-T tuition = no education credit modelled
(missing feature, not a clean add). $750k acquisition-debt mortgage limit still not modelled (matches Sch A).

Suite 1095 -> 1097.

## Cycle 73 — FULL LIFECYCLE (2026-06-16) [5-primitive: backlog from C72 audit -> worktree -> PR]

MATRIX | read §80E student-loan interest from Form 16 (was manual-only) | the Form-16 extractor captured section_80e_declared but the engine read §80E only from user_answers["student_loan_interest_in"] -> a Form-16 upload silently dropped the (uncapped, old-regime) student-loan-interest deduction AND blinded the cross-border single-claim guardrail (which keys on line_items["section_80e"]) | fail: Form-16 with §80E ₹50k -> section_80e ₹0 — pass: ₹50,000; form preferred over manual (no double-count); manual-only still ₹40k | gated? N | PR #TBD

**MAINTAIN:** #106 (1098 mortgage) merged (HEAD f3c19d0); #102 + #105 open; baseline suite green at 1097. Rebase-before-push held.

**2nd item from the C72 captured-but-unused audit backlog.** Form-then-manual FALLBACK (prefer form, else manual)
— safer than §80D's add-both pattern (no double-count). Restores the cross-border §80E guardrail (the product's
differentiator). Suite 1097 -> 1100.

**Remaining audit-backlog drops (clean, prioritized):** IN FORM-26AS.advance_tax_paid (form-captured advance tax,
key-mismatch w/ #88 user_answers — any regime, direct $ on balance); CA T4A.lump_sum_payments box 018 (dropped
taxable income); 1099-DIV box5 §199A REIT dividends (QBI, low). §80D add-both pattern (in_engine:371-372) could
double-count form+manual — a harmonization follow-up (use fallback like §80E/SALT/1098).

## Cycle 74 — FULL LIFECYCLE (2026-06-16) [5-primitive: C72-audit backlog -> worktree -> PR]

MATRIX | credit advance tax reported on an uploaded Form 26AS (was manual-only) | the FORM-26AS extractor captured advance_tax_paid but the engine read advance tax only from user_answers["advance_tax_paid"] -> a 26AS upload (the standard tax-credit statement) left advance tax uncredited, OVERSTATING the balance owing for any filer who pre-paid (#88 added it via manual entry only) | fail: FORM-26AS advance ₹1L -> advance_tax ₹0 / balance owing ₹2,96,400 — pass: ₹1,00,000 credited / balance ₹1,96,400; form preferred over manual (no double-count) | gated? N | PR #TBD

**MAINTAIN:** #107 (§80E) merged (HEAD 06b34e4); #102 + #105 open; baseline suite green at 1100. Rebase-before-push held.

**3rd item from the C72 captured-but-unused audit backlog.** Same form-vs-manual bridge class as #67 (professional_tax)
and #107 (§80E). Form-then-manual FALLBACK (no double-count). Direct $-for-$ on the balance, any regime — higher
value than §80E (old-regime-only deduction). Completes the #88 advance-tax work for the 26AS-upload path. Suite 1100->1102.

**Remaining C72 backlog:** CA T4A.lump_sum_payments box 018 (dropped taxable income); 1099-DIV box5 §199A REIT
dividends (QBI, low); §80D add-both harmonization (in_engine:371-372 sums form+manual -> double-count risk).

## Cycle 75 — FULL LIFECYCLE (2026-06-16) [5-primitive: C72-audit backlog -> worktree -> PR]

MATRIX | include T4A box 018 lump-sum payments in CA income | the T4A extractor captured lump_sum_payments (box 018) but the engine read only T4A boxes 016/020/048/022 -> taxable lump-sum income (retiring allowance, DPSP/RPP commutation; line 13000 other income) was fully DROPPED, under-taxing recipients | fail: T4A lump $20k -> no 'lump_sum_income' key; total_income excludes it — pass: $20,000 into total_income (tax +$5,930); correctly NOT pension-income-amount-eligible (credit $0) | gated? N | PR #TBD

**MAINTAIN:** #108 merged (HEAD 2c2841b); #102 + #105 open; baseline suite green at 1102. Rebase-before-push held.

**4th item from the C72 captured-but-unused audit = the last clean MONEY-DROP.** Added box 018 to total_income +
line_items['lump_sum_income']; correctly excluded from pension_income (lump-sum isn't pension-income-amount-eligible).
Suite 1102 -> 1104.

**C72 audit backlog now substantially closed:** genuine money-drops shipped = 1098 mortgage #106, IN §80E #107, IN
advance-tax-26AS #108, CA T4A lump-sum #75(this). REMAINING = only low-value/cosmetic: 1099-DIV box5 §199A REIT
dividends (QBI, ~20% of a niche field); §80D add-both harmonization (double-count risk, no current test triggers it);
T4RIF box22 (sign-ambiguous). The captured-but-unused VEIN IS NOW ESSENTIALLY EXHAUSTED -> expect HOLD/low-value next.

## Cycle 76 — FULL LIFECYCLE (2026-06-16) [5-primitive: federal-completeness pivot -> worktree -> PR]

MATRIX | US education credits (AOTC + Lifetime Learning, Form 8863) | the 1098-T extractor captured box 1 tuition + box 5 scholarships but NO US engine code ever read them -> a real federal credit worth up to $2,500/student (40% refundable) was entirely absent | fail-before: line_items has no 'education_credit_chosen' key (KeyError) -> pass-after: single MAGI $50k, $4k tuition -> AOTC $2,500 (nonref $1,500 cuts federal_tax, refundable $1,000 cuts balance); MAGI $85k -> 0.5 phaseout -> $1,250; $4k less $1,500 scholarship -> net $2,500 -> $2,125 | gated? N | PR #110

**MAINTAIN:** origin/main HEAD 3b656d3 (#109 T4A merged); base == HEAD, no rebase needed; baseline suite green at 1104.

**Pivot OFF the (now-exhausted) captured-but-unused vein into FEDERAL COMPLETENESS.** Take-the-better v1: compute
both AOTC and LLC, pick the larger, apply MAGI phaseout ($80-90k single / $160-180k MFJ), split refundable
(40% AOTC only) from non-refundable. One YAML block (fixed across 2023/24/25), one helper
(`_compute_education_credits`), two one-token edits to the tax/balance lines, 6 new line_items.
Sharp edge handled: structured extractor emits `qualified_tuition_payments` while NL intake emits
`qualified_tuition_paid`/`qualified_education_expense` -> engine sums all spellings or NL tuition yields $0.
Confidence: fixed-statutory thresholds (>=90%); MFS guard is defensive (engine maps MFS->single). Suite 1104 -> 1113.

## Cycle 78 — FULL LIFECYCLE (2026-06-16) [5-primitive: residency-gate correctness -> worktree -> PR]

MATRIX | deny §87A rebate to non-residents (NR); resident-only relief | in_engine.py rebate block (427-448) gated ONLY on income threshold with NO residency check -> a non-resident with India-source income at/under the rebate threshold wrongly received up to ₹25,000 (new) / ₹12,500 (old) of rebate + 4% cess they are statutorily barred from, UNDER-stating the draft balance owing. Common for NRIs with Indian rental/FD-interest/part-year salary. RNOR is a RESIDENT under the Act and correctly KEEPS the rebate | fail-before: NR ₹6L India-salary new regime -> rebate ₹12,500, tax ₹0 -> pass-after: rebate ₹0, tax ₹13,000 (12,500 slab + 4% cess); RNOR + ROR unchanged (rebate ₹12,500, tax ₹0) | gated? N | PR #112

**MAINTAIN:** origin/main HEAD eb6e993 (#110 education credits merged); #111/#105/#102 still OPEN; base==HEAD, no rebase; baseline suite 1113.

**Residency-correctness gate (not captured-but-unused).** §87A is resident-only; the discriminator (residency_status)
was already plumbed through _compute_one_regime but the rebate block ignored it. Gate on the LITERAL "NR" (not
is_nr_or_rnor) so RNOR — a resident whose only distinction is foreign-income exemption — keeps the rebate. The fix
sets rebate=0 for NR; everything downstream (surcharge->cess->balance) already consumes `rebate`, so no income-side
recompute, no serializer change (in_itr.py already reads rebate_87a). Default residency_status="ROR" -> dominant
single-jurisdiction population untouched. Confidence 92% (single statutory gate, no data/constants). Suite 1113->1117.

**ZERO collision:** lands entirely in in_engine.py rebate block (427-448); #111=ca_engine.py, #105=us_engine.py+US tables,
#102=ca/2024.yaml. The IN prepaid-tax work (#88/#108) is a different region (459-481) -> negligible merge risk.
RESEARCH next-best deferred: US 1099-R box 7 §72(t) penalty (clean but contends us_engine.py w/ #105).

## Cycle 79 — FULL LIFECYCLE (2026-06-16) [5-primitive: filing-serializer reconciliation -> worktree -> PR]

MATRIX | include refundable AOTC + additional-Medicare-withheld in 1040 line 33 (total payments) | filing/us_mef.py line33_total_payments summed only withholding + ACTC + EITC + excess-SS, DROPPING two refundable items the engine already credits in its balance (us_engine:919): education_credit_refundable (refundable AOTC, up to $1,000/student, Form 8863->1040 L29) and additional_medicare_tax_withheld (W-2 box-6 over-withholding, Form 8959 Part IV->Sch3 L11). The filing artifact's line34_overpayment/line37_amount_you_owe thus CONTRADICTED the engine's own totals['refund']/['balance_owing'] -> filer shown owing more / refunded less by up to $1,000/student + box-6 surplus | fail-before: $0 tax/$200 wh/$1,000 refundable-AOTC -> line33 $200, line34 $200 -> pass-after: line33 $1,200, line34 $1,200 (matches engine refund) | gated? N | PR #113

**MAINTAIN:** origin/main HEAD eb6e993 (#110 merged); #112/#111/#105/#102 OPEN; base==HEAD, no rebase; baseline 1113.

**Filing-serializer reconciliation bug (engine read-only).** The refundable AOTC key only exists because #110 (education
credits) merged -> its refundable portion landed in the engine balance but the MeF serializer was never updated to
pay it out. Pure addition of two existing line_items keys into the existing line-33 sum; mirrors the shipped
ACTC/EITC/excess-SS pattern. Also surfaced explicit line25c (addl-Medicare) + line29 (refundable education) for form
fidelity. Net PTC stays EXCLUDED (already netted into federal_tax/L24 — pinned by test_net_ptc_not_double_counted).
Key-name gotchas: additional_medicare_tax_withheld (NOT addl_), education_credit_refundable (NOT education_refundable
local var). Confidence 92%. Suite 1113->1117.

**ZERO collision:** primary+only edit is filing/us_mef.py (+ its test); engine is read-only. #112=in_engine.py,
#111=ca_engine.py, #105=us_engine.py+US tables, #102=ca/2024.yaml -> none overlap. RESEARCH picked this specifically
to keep the cycle non-colliding while the 4-PR queue drains. Next-best US 1099-R §72(t) still deferred (contends us_engine.py w/ #105).

**REBASED onto origin/main 7888b3a (#112 merged mid-cycle); ledger union (Cycle 78 then 79). No code conflict — ledger-only.**
## Cycle 80 — FULL LIFECYCLE (2026-06-16) [5-primitive: CA serializer reconciliation -> worktree -> PR]

MATRIX | emit refundable Canada Workers Benefit in the NETFILE Tax block | filing/ca_netfile.py serialize_t1 <Tax> block emitted FederalTax/ProvincialTax/BPA/TaxWithheld/BalanceOwing/Refund but DROPPED canada_workers_benefit, which the engine subtracts to PRODUCE that balance (ca_engine:444 balance = total_tax - tax_withheld - cwb). A reader summing the XML's own visible lines could NOT reconcile to the emitted BalanceOwing/Refund whenever cwb>0 -> artifact contradicts itself; understates payments applied -> hand-filer computes larger owing/smaller refund. Low-income CA filers (working income > $3k floor); CWB ~$1,400 single / ~$2,400 family | fail-before: $1,200 tax/$1,500 wh/$1,400 CWB -> no <CanadaWorkersBenefit> element, visible lines don't reconcile to Refund $1,700 -> pass-after: <CanadaWorkersBenefit>1400.00</...>, total_tax - wh - cwb = -refund reconciles | gated? N | PR #114

**MAINTAIN:** origin/main HEAD 7888b3a (#112 merged); #113/#111/#105/#102 OPEN; base==HEAD, no rebase; baseline 1117.

**Direct follow-on to #113 (us_mef line-33) — the SAME engine<->serializer reconciliation bug class on the CA side.**
Last cycle's lesson ("a credit can reach the engine balance yet be dropped from the filing artifact; sweep
ca_netfile/in_itr/ca_540") paid off immediately. CWB is the ONLY payment-side item besides tax_withheld in
ca_engine's balance, and the NETFILE Tax block omitted it. Pure additive serializer fix (engine read-only); one
<CanadaWorkersBenefit> element after <TaxWithheld>; defaults 0.00 when no cwb table / non-resident -> no regression.
Key-name verified: line_items["canada_workers_benefit"] (snake_case, NOT cwb), lives in line_items NOT credits.
RESEARCH confirmed in_itr.py FULLY reconciles (87A/surcharge/cess/prepaid-tax all present) -> no second bug there.
Confidence 92%. Suite 1117->1120.

**ZERO collision:** primary+only edit is filing/ca_netfile.py (+ its test); engine read-only. #113=us_mef.py,
#111=ca_engine.py, #105=us_engine.py+US tables, #102=ca/2024.yaml -> none overlap. Serializer-reconciliation vein:
us_mef (#113) + ca_netfile (this) shipped; in_itr verified clean; ca_540/quarterly not yet swept (next candidates).

**REBASED onto origin/main d503d6c (#113 merged mid-cycle); ledger union (Cycle 79 then 80). No code conflict — ledger-only.**

## Cycle 82 — FULL LIFECYCLE (2026-06-16) [5-primitive: India income-head completeness -> worktree -> PR]

MATRIX | §57(iia) standard deduction on family pension (Income from Other Sources) | in_engine.py Other Sources block (262-272) aggregated only bank interest + dividends + generic other_income; NO family-pension handling and NO §57 deduction anywhere (verified: grep family_pension/section_57 in src/ = empty). A filer entering family pension via the other_income key was taxed in FULL, over-taxing by up to ₹15,000 (old) / ₹25,000 (new). §57(iia) is one of the few deductions §115BAC does NOT disallow -> applies under BOTH regimes (default new-regime filer too). Common population (widows/dependants of deceased employees) | fail-before: ₹90k family pension new regime AY25 -> taxable ₹90k, no deduction line_item -> pass-after: deduction ₹25,000 (min(30k,25k)), taxable ₹65k into total_income | gated? N | PR #115

**MAINTAIN:** origin/main HEAD d503d6c (#113 merged); #114/#111/#105/#102 OPEN; base==HEAD, no rebase; baseline 1121.

**NOT a HOLD — in_engine.py freshly UN-contended (its §87A PR #112 merged) reopened the India surface.** Last cycle's
HOLD was scoped to the exhausted serializer vein, not whole-repo convergence. Family pension is a genuine missing
income-head deduction with FIXED statutory constants (1/3 fraction + ₹15k/₹25k caps), no guessed per-year market data.
Deduction = min(family_pension/3, cap); cap regime-specific via tables.get("deductions") (₹15k old; ₹25k new AY25,
but ₹15k new in 2024.yaml since the Budget-2024 bump starts AY2025-26 — per-year correct). Net flows into other_income
(so NR/RNOR foreign-exclusion + slab_income paths apply automatically). +3 line_items. Confidence 88%. Suite 1121->1127.

**ZERO collision:** in_engine.py + in/2024.yaml + in/2025.yaml; none of #114(ca_netfile)/#111(ca_engine)/#105(us_engine+US
tables)/#102(ca/2024.yaml). VERIFIED absence first (grep) before building — heeded the cycle-81 lesson (read the
target before trusting a "missing" claim). RESEARCH next-best after #105 lands: US 1099-R §72(t) early-withdrawal penalty.

**REBASED onto origin/main 03b66e1 (#114 merged mid-cycle); ledger union (Cycle 80 then 82; Cycle 81 was a HOLD on its own unmerged branch). No code conflict — ledger-only.**

## Cycle 85 — FULL LIFECYCLE (2026-06-16) [5-primitive: IN ITR serializer reconciliation -> worktree -> PR]

MATRIX | serialize §80CCD(2) employer-NPS into the draft ITR ScheduleVIA | in_engine.py computes sec_80ccd_2 and NETS it from total_income (436: total_income = gross - chapter_via_total - sec_80ccd_2; line_item at 540), but in_itr.py ScheduleVIA (62-69) emitted Section80C/80CCD1B/80D/80E/80G/80TTAor80TTB + TotalChapterVIA=chapter_via_total -> NO Section80CCD2, and TotalChapterVIA was SHORT by sec_80ccd_2. chapter_via_total deliberately excludes 80CCD2 (the one Chapter-VIA item allowed in NEW regime, the IN default). So GrossTotalIncome - TotalChapterVIA != TotalIncome whenever employer NPS>0 -> artifact under-reports the deduction the engine already applied; hand-filer over-states taxable income | fail-before: ₹50k employer-NPS -> no Section80CCD2 key (KeyError), TotalChapterVIA short -> pass-after: Section80CCD2_EmployerNPS ₹50,000 + TotalChapterVIA folds it in -> GTI - TotalVIA == TotalIncome reconciles | gated? N | PR #118

**MAINTAIN:** origin/main HEAD 78f060c (#115 merged); #117/#116/#111/#105/#102 OPEN (5 PRs; #117 a PARALLEL lane on build_return.py); base==HEAD, no rebase; baseline 1130.

**Serializer-reconciliation vein extends to the IN ITR — but a DEDUCTIONS-schedule gap, not a tax-balance gap.** A
cycle-80 audit said in_itr "fully reconciles" on TAX (87A/surcharge/cess/prepaid) — TRUE; but it didn't check the
ScheduleVIA DEDUCTIONS total vs the income reduction. §80CCD(2) (new-regime salaried filers w/ employer NPS — the exact
population that uses it) was dropped. Pure additive serializer fix (engine read-only): +Section80CCD2_EmployerNPS, and
TotalChapterVIA = chapter_via_total + sec_80ccd_2 so GTI-TotalVIA==TotalIncome. _f default 0.0 -> no-NPS filers byte-
identical. Confidence 92%. Suite 1130->1133.

**ZERO collision:** primary+only edit filing/in_itr.py (+ its test); engine read-only. Verified via gh pr diff vs all 5
open PRs — #116 (nearest, IN) edits in_engine.py+in/yamls for §80GG, different file. Serializer-recon vein now: us_mef
#113 + ca_netfile #114 + in_itr 80CCD2 (this) shipped; ca_540/quarterly/pdf_fill verified clean; build_return is #117.
RESEARCH also audited us/states ny/tx/fl/wa + ca/provinces ab/bc/on/qc (BPAs/brackets all CORRECT) + residency + cross_border (clean).

## Cycle 83 — FULL LIFECYCLE (2026-06-16) [ARTIFACT-GENERATION axis; research subagent -> worktree -> PR]

MATRIX | federal 1040 PDF showed COMBINED fed+state refund/owing, contradicting its own federal-only MeF JSON | build_return._us_artifacts fed the federal `us_1040_pdf` from draft.totals['balance_owing'/'refund'], which are COMBINED (us_engine: total_tax=fed+state+se, then nets only FEDERAL payments against it). The federal `us_mef_json` was refactored federal-only in #86/#87 (line24=fed+se; line34/37=reconciled). So for any state-taxed (e.g. CA) filer the two FEDERAL artifacts of the SAME return disagreed on the headline figure, and the human-readable PDF — what the filer reads — overstated federal amount-owed. This is the tracked "federal-vs-combined" PDF note (C63), genuinely unfixed | fail-before: CA filer fed_tax 9000/withholding 10000 (federal refund 1000) + state_tax 3000 (combined owing 2000) -> PDF refund "0.00"/balance_owing "2000.00" (≠ MeF) -> pass-after: PDF refund "1000.00"/balance_owing "0.00", == MeF line34/line37 by construction | gated? N | PR #117

**Axis:** operator-directed ARTIFACT-GENERATION scope (real filing SUBMISSION stays operator-gated — untouched here; pure draft-artifact display fix; `transmissible=False` invariant unchanged). Distinct from the cron's per-credit/per-line engine+serializer vein.

**The fix (single-source, no third copy):** serialize_1040 is already called in _us_artifacts and already computes the federal-only line34_overpayment/line37_amount_you_owe. Reordered to compute the MeF dict FIRST, then drive the PDF's refund/balance_owing from `mef_dict[...]["IRS1040"]["line34_overpayment"/"line37_amount_you_owe"]` -> PDF and JSON identical by construction. ONLY build_return.py touched (NOT the cron-hot us_mef.py) -> zero code-collision; no engine/serializer/submission change.

**Found by a RESEARCH subagent (operator-directed artifact-gen scope).** Suite 1131 green + scripts/validate.sh ✅ (Streamlit boot). No code change to any serializer/engine.

**ZERO collision:** confined to build_return.py's federal-PDF mapping dict — a surface C63 explicitly probed but left (the cron works *_engine.py + the JSON/XML serializers). Ledger-race only; rebase-defensive.
