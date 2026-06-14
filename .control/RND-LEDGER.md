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
