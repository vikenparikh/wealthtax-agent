"""§1091 wash-sale: a replacement buy cannot be attributed beyond its share count.

RND-LEDGER cycle-1 bug: ``detect_wash_sales`` did not track how many shares of a
replacement buy had already been consumed by an earlier loss sell processed in
the same call. When two loss sells for the same ticker both fall inside the
61-day window of a single replacement buy, the engine assigned that buy to BOTH
sells without subtracting the shares already used — over-reporting the disallowed
loss and inflating the replacement lot's adjusted basis (which then under-reports
future gain on Schedule D / Form 8949).

This test FAILS before the ``consumed_qty`` fix (returns 2 results,
rep.adjusted_basis_cents == 116_000) and PASSES after (1 result,
rep.adjusted_basis_cents == 105_000).
"""
from __future__ import annotations

from datetime import date

from wealthtax_agent.engines.wash_sale import LotRecord, detect_wash_sales


def _scenario() -> list[LotRecord]:
    # Source position (earliest buy → treated as the lot being sold, never a
    # replacement). 20 shares @ $100.
    src1 = LotRecord("src1", "QQQ", "buy", date(2024, 1, 1), 20, 200_000)

    # Two loss sells, one day apart. For a sell, original_basis_cents = proceeds
    # and adjusted_basis_cents = cost basis of the shares sold. Both are losses.
    s1 = LotRecord("s1", "QQQ", "sell", date(2024, 1, 10), 10, 90_000)
    s1.adjusted_basis_cents = 100_000          # loss = 100_000 - 90_000 = 10_000
    s2 = LotRecord("s2", "QQQ", "sell", date(2024, 1, 11), 10, 89_000)
    s2.adjusted_basis_cents = 100_000          # loss = 100_000 - 89_000 = 11_000

    # ONE replacement buy with only 10 shares — enough to replace s1's 10 shares
    # and nothing more. It sits inside the 61-day window of both sells.
    rep = LotRecord("rep", "QQQ", "buy", date(2024, 1, 20), 10, 95_000)

    return [src1, s1, s2, rep]


def test_replacement_lot_not_reused_beyond_its_share_count():
    adjusted, results = detect_wash_sales(_scenario())

    # rep holds 10 shares; s1 consumes all of them, so only s1's loss is
    # disallowed. s2 has no remaining replacement capacity → its loss is ALLOWED.
    assert len(results) == 1, f"expected 1 disallowance, got {len(results)}: {[ (r.sell_lot_id, r.disallowed_loss_cents) for r in results ]}"
    assert results[0].sell_lot_id == "s1"
    assert results[0].replacement_lot_id == "rep"
    assert results[0].disallowed_loss_cents == 10_000

    # Replacement lot basis is bumped by exactly s1's disallowed loss, once.
    rep = next(l for l in adjusted if l.id == "rep")
    assert rep.adjusted_basis_cents == 105_000  # 95_000 + 10_000, NOT 116_000

    # The over-attribution guard: total disallowed cannot exceed the single
    # sell that the replacement capacity actually covered.
    assert sum(r.disallowed_loss_cents for r in results) == 10_000

    # s2's loss survives (not tainted) because no replacement shares remained.
    s2 = next(l for l in adjusted if l.id == "s2")
    assert s2.is_wash_sale is False


def test_replacement_capacity_split_across_two_sells():
    """A replacement buy larger than one sell but smaller than two is consumed
    proportionally: it fully covers the first sell and partially the second."""
    src = LotRecord("src", "QQQ", "buy", date(2024, 2, 1), 30, 300_000)
    s1 = LotRecord("s1", "QQQ", "sell", date(2024, 2, 10), 10, 90_000)
    s1.adjusted_basis_cents = 100_000          # loss 10_000
    s2 = LotRecord("s2", "QQQ", "sell", date(2024, 2, 11), 10, 90_000)
    s2.adjusted_basis_cents = 100_000          # loss 10_000
    # 15 replacement shares: covers all of s1 (10) and 5 of s2's 10.
    rep = LotRecord("rep", "QQQ", "buy", date(2024, 2, 20), 15, 150_000)

    adjusted, results = detect_wash_sales([src, s1, s2, rep])

    by_sell = {r.sell_lot_id: r for r in results}
    assert set(by_sell) == {"s1", "s2"}
    # s1: 10/10 shares replaced → full $100 loss disallowed.
    assert by_sell["s1"].disallowed_loss_cents == 10_000
    # s2: only 5/10 shares replaced → half its $100 loss disallowed.
    assert by_sell["s2"].disallowed_loss_cents == 5_000

    # rep basis += 10_000 (s1) + 5_000 (s2) = 15_000; never more than its
    # 15 shares' worth of disallowance.
    rep_lot = next(l for l in adjusted if l.id == "rep")
    assert rep_lot.adjusted_basis_cents == 165_000  # 150_000 + 15_000
