"""tests/test_wash_sale.py — unit tests for US §1091 wash-sale engine."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from wealthtax_agent.engines.wash_sale import (
    LotRecord,
    WashSaleResult,
    _normalise_date,
    detect_wash_sales,
)


def _lot(id: str, ticker: str, side: str, trade_date: date, qty: int, basis_cents: int) -> LotRecord:
    return LotRecord(
        id=id,
        ticker=ticker,
        side=side,
        trade_date=trade_date,
        quantity=qty,
        original_basis_cents=basis_cents,
    )


class TestNoWashSaleGainTrade:
    def test_gain_sale_not_flagged(self):
        """A sale at a gain should never be flagged even with a replacement buy."""
        lots = [
            _lot("b1", "QQQ", "buy",  date(2024, 1, 2), 10, 50_000),   # cost $500
            _lot("s1", "QQQ", "sell", date(2024, 1, 5), 10, 55_000),   # proceeds $550 → gain
            _lot("b2", "QQQ", "buy",  date(2024, 1, 10), 10, 51_000),
        ]
        # Mark sell's adjusted basis = cost of sold shares
        lots[1].adjusted_basis_cents = 50_000
        _, results = detect_wash_sales(lots)
        assert results == [], "Gains should not trigger wash-sale"

    def test_no_replacement_buy_no_wash_sale(self):
        """Loss sale with no repurchase in window should not be flagged."""
        lots = [
            _lot("b1", "QQQ", "buy",  date(2024, 3, 1), 10, 50_000),
            _lot("s1", "QQQ", "sell", date(2024, 3, 15), 10, 45_000),  # loss $50
        ]
        lots[1].adjusted_basis_cents = 50_000
        _, results = detect_wash_sales(lots)
        assert results == []


class TestBasicWashSale:
    def test_replacement_buy_after_sell(self):
        """Buy within 30 days after a loss sale triggers §1091."""
        lots = [
            _lot("b1", "QQQ", "buy",  date(2024, 6, 1), 100, 500_000),   # cost $5 000
            _lot("s1", "QQQ", "sell", date(2024, 6, 15), 100, 480_000),  # proceeds $4 800 → loss $200
            _lot("b2", "QQQ", "buy",  date(2024, 6, 20), 100, 490_000),  # replacement
        ]
        lots[1].adjusted_basis_cents = 500_000  # cost of sold shares
        _, results = detect_wash_sales(lots)

        assert len(results) == 1
        ws: WashSaleResult = results[0]
        assert ws.sell_lot_id == "s1"
        assert ws.replacement_lot_id == "b2"
        assert ws.ticker == "QQQ"
        assert ws.disallowed_loss_cents == 20_000  # $200
        assert ws.basis_adjustment_cents == 20_000

    def test_replacement_buy_before_sell(self):
        """Buy within 30 days *before* the loss sale also triggers §1091."""
        lots = [
            _lot("b1", "QQQ", "buy",  date(2024, 9, 1),  100, 500_000),
            _lot("b2", "QQQ", "buy",  date(2024, 9, 10), 100, 495_000),  # repurchase 5 days before
            _lot("s1", "QQQ", "sell", date(2024, 9, 15), 100, 485_000),  # loss $150
        ]
        lots[2].adjusted_basis_cents = 500_000
        _, results = detect_wash_sales(lots)

        assert any(r.sell_lot_id == "s1" for r in results)

    def test_replacement_lot_basis_adjusted(self):
        """Disallowed loss must be added to replacement lot's adjusted basis."""
        lots = [
            _lot("b1", "QQQ", "buy",  date(2024, 4, 1), 50, 250_000),
            _lot("s1", "QQQ", "sell", date(2024, 4, 10), 50, 240_000),  # loss $100
            _lot("b2", "QQQ", "buy",  date(2024, 4, 15), 50, 245_000),
        ]
        lots[1].adjusted_basis_cents = 250_000
        adjusted_lots, results = detect_wash_sales(lots)

        rep = next(l for l in adjusted_lots if l.id == "b2")
        assert rep.adjusted_basis_cents == 245_000 + results[0].disallowed_loss_cents

    def test_outside_61_day_window_no_flag(self):
        """Replacement buy 31+ days after sell is outside the window."""
        lots = [
            _lot("b1", "QQQ", "buy",  date(2024, 1, 1), 10, 100_000),
            _lot("s1", "QQQ", "sell", date(2024, 1, 10), 10, 90_000),  # loss
            _lot("b2", "QQQ", "buy",  date(2024, 2, 15), 10, 95_000),  # 36 days after — outside window
        ]
        lots[1].adjusted_basis_cents = 100_000
        _, results = detect_wash_sales(lots)
        assert results == []


class TestPartialWashSale:
    def test_partial_replacement_quantity(self):
        """When replacement qty < sell qty, only the covered fraction is disallowed."""
        lots = [
            _lot("b1", "QQQ", "buy",  date(2024, 7, 1), 100, 500_000),
            _lot("s1", "QQQ", "sell", date(2024, 7, 10), 100, 480_000),  # loss $200 on 100sh
            _lot("b2", "QQQ", "buy",  date(2024, 7, 15), 40, 195_000),   # only 40 shares
        ]
        lots[1].adjusted_basis_cents = 500_000
        _, results = detect_wash_sales(lots)

        assert len(results) == 1
        assert results[0].disallowed_loss_cents == int(0.40 * 20_000)  # 40% of $200 loss


class TestMultipleSecurities:
    def test_different_tickers_no_cross_contamination(self):
        lots = [
            _lot("b1", "QQQ", "buy",  date(2024, 2, 1), 10, 50_000),
            _lot("s1", "QQQ", "sell", date(2024, 2, 10), 10, 45_000),   # QQQ loss
            _lot("b2", "SPY", "buy",  date(2024, 2, 15), 10, 48_000),   # SPY repurchase — different ticker
        ]
        lots[1].adjusted_basis_cents = 50_000
        _, results = detect_wash_sales(lots)
        # No wash sale because SPY != QQQ
        assert results == []

    def test_cusip_match_overrides_ticker(self):
        """Same CUSIP marks substantially-identical even with different tickers."""
        lots = [
            _lot("b1", "QQQ", "buy",  date(2024, 3, 1), 10, 50_000),
            _lot("s1", "QQQ", "sell", date(2024, 3, 10), 10, 45_000),
            _lot("b2", "QQQM", "buy", date(2024, 3, 12), 10, 47_000),
        ]
        lots[0].cusip = "46090E103"
        lots[1].cusip = "46090E103"
        lots[2].cusip = "46090E103"  # same CUSIP → substantially identical
        lots[1].adjusted_basis_cents = 50_000
        _, results = detect_wash_sales(lots)
        assert len(results) == 1


class TestEmptyAndEdge:
    def test_empty_input(self):
        adjusted, results = detect_wash_sales([])
        assert adjusted == []
        assert results == []

    def test_only_buys(self):
        lots = [
            _lot("b1", "QQQ", "buy", date(2024, 1, 1), 10, 50_000),
            _lot("b2", "QQQ", "buy", date(2024, 1, 5), 10, 52_000),
        ]
        _, results = detect_wash_sales(lots)
        assert results == []


class TestWashSaleEdgeCases:
    """Edge cases: short-against-the-box, options (caller-side note), DRIP buys."""

    def test_short_against_the_box_same_ticker_triggers_wash_sale(self):
        """Short-against-the-box: selling short while holding long on the *same* ticker.
        Under §1091 the short sale itself is not a wash sale trigger, but a *covering*
        buy within 30 days of a separate loss sale IS a replacement purchase.
        This test models: loss sale on Jan 10 + covering buy (same ticker) on Jan 15 →
        wash sale flagged because the covering buy is within the 30-day window.
        """
        lots = [
            _lot("long1", "QQQ", "buy",  date(2024, 1, 2),  100, 500_000),  # long position
            _lot("sell1", "QQQ", "sell", date(2024, 1, 10), 100, 480_000),  # sell at loss ($200)
            _lot("cover", "QQQ", "buy",  date(2024, 1, 15), 100, 490_000),  # covering buy (within window)
        ]
        lots[1].adjusted_basis_cents = 500_000
        _, results = detect_wash_sales(lots)
        assert len(results) == 1, "Covering buy within 30 days should trigger wash-sale"
        assert results[0].sell_lot_id == "sell1"
        assert results[0].replacement_lot_id == "cover"
        assert results[0].disallowed_loss_cents == 20_000  # $200 loss

    def test_drip_reinvestment_buy_within_window_triggers_wash_sale(self):
        """Dividend Reinvestment Plan (DRIP) purchases are 'buy' lots.
        If a DRIP buy falls within 30 days of a loss sale on the same stock,
        it qualifies as a replacement purchase and triggers §1091.
        """
        lots = [
            _lot("orig",  "VTI", "buy",  date(2024, 3, 1),  50, 1_000_000),   # original buy
            _lot("sale",  "VTI", "sell", date(2024, 3, 20), 50,   980_000),   # loss sale ($200)
            _lot("drip",  "VTI", "buy",  date(2024, 4, 1),   2,    39_000),   # DRIP reinvestment
        ]
        lots[1].adjusted_basis_cents = 1_000_000
        _, results = detect_wash_sales(lots)
        assert len(results) == 1, "DRIP buy within 30 days should be treated as replacement purchase"
        # Only 2 shares covered out of 50 sold → partial disallowance
        proportion = 2 / 50
        expected_disallowed = int(proportion * 20_000)
        assert results[0].disallowed_loss_cents == expected_disallowed

    def test_options_on_same_underlying_are_not_flagged_by_default(self):
        """Options on a security are substantially identical to the underlying only
        in specific conditions (Rev. Rul. 2008-5).  The engine currently requires the
        CALLER to resolve options to their underlying ticker before calling
        detect_wash_sales().  This test documents that different tickers (e.g. QQQ vs
        QQQM without a shared CUSIP) are NOT matched — confirming the caller contract.
        """
        # Model an option buy as a synthetic lot with a different ticker and no CUSIP match
        lots = [
            _lot("b1",    "QQQ",      "buy",  date(2024, 5, 1),  100, 500_000),
            _lot("sell1", "QQQ",      "sell", date(2024, 5, 10), 100, 480_000),  # loss
            _lot("opt",   "QQQ240621C00480000", "buy", date(2024, 5, 12), 1, 150_000),  # call option
        ]
        lots[1].adjusted_basis_cents = 500_000
        _, results = detect_wash_sales(lots)
        # Different ticker + no shared CUSIP → no wash-sale match
        # The caller is responsible for mapping option tickers → underlying before calling
        assert results == [], (
            "Option ticker without CUSIP mapping should NOT trigger wash-sale; "
            "caller must resolve options to underlying before calling detect_wash_sales()"
        )


class TestLotRecordProperties:
    """Cover LotRecord.price_cents and effective_basis_cents (L54, L58-60)."""

    def test_price_cents_divides_basis_by_quantity(self):
        lot = _lot("x", "QQQ", "buy", date(2024, 1, 1), 10, 50_000)
        assert lot.price_cents == 5_000  # 50_000 // 10

    def test_effective_basis_falls_back_to_original_when_adjusted_unset(self):
        lot = _lot("x", "QQQ", "buy", date(2024, 1, 1), 10, 50_000)
        assert lot.adjusted_basis_cents is None
        assert lot.effective_basis_cents == 50_000

    def test_effective_basis_uses_adjusted_when_set(self):
        lot = _lot("x", "QQQ", "buy", date(2024, 1, 1), 10, 50_000)
        lot.adjusted_basis_cents = 99_999
        assert lot.effective_basis_cents == 99_999


class TestNormaliseDate:
    """Cover _normalise_date datetime/str branches (L82, L85)."""

    def test_normalise_accepts_datetime_returns_date(self):
        assert _normalise_date(datetime(2024, 1, 1, 12, 30)) == date(2024, 1, 1)

    def test_normalise_accepts_date_unchanged(self):
        assert _normalise_date(date(2024, 1, 1)) == date(2024, 1, 1)

    def test_normalise_rejects_str(self):
        with pytest.raises(TypeError):
            _normalise_date("2024-01-01")

    def test_detect_handles_datetime_trade_dates(self):
        """Lots carrying datetime trade_date run through detect (exercises L82)."""
        lots = [
            _lot("b1", "QQQ", "buy",  datetime(2024, 6, 1, 9, 30), 100, 500_000),
            _lot("s1", "QQQ", "sell", datetime(2024, 6, 15, 9, 30), 100, 480_000),
            _lot("b2", "QQQ", "buy",  datetime(2024, 6, 20, 9, 30), 100, 490_000),
        ]
        lots[1].adjusted_basis_cents = 500_000
        _, results = detect_wash_sales(lots)
        assert len(results) == 1
        assert results[0].sell_lot_id == "s1"
        assert results[0].disallowed_loss_cents == 20_000


class TestReplacementBranches:
    """Cover same-day skip (L180), pre-flagged skip (L182), full-cover break (L212)."""

    def test_same_day_buy_is_not_a_replacement(self):
        lots = [
            _lot("b1", "QQQ", "buy",  date(2024, 6, 1), 100, 500_000),
            _lot("s1", "QQQ", "sell", date(2024, 6, 15), 100, 480_000),
            _lot("b2", "QQQ", "buy",  date(2024, 6, 15), 100, 490_000),  # same day as sell
        ]
        lots[1].adjusted_basis_cents = 500_000
        _, results = detect_wash_sales(lots)
        assert results == []

    def test_preflagged_replacement_buy_is_skipped(self):
        """A buy already marked is_wash_sale=True is skipped; the next valid buy is used."""
        lots = [
            _lot("b1", "QQQ", "buy",  date(2024, 6, 1), 100, 500_000),
            _lot("s1", "QQQ", "sell", date(2024, 6, 15), 100, 480_000),
            _lot("bf", "QQQ", "buy",  date(2024, 6, 18), 100, 491_000),  # flagged → skipped
            _lot("b2", "QQQ", "buy",  date(2024, 6, 20), 100, 490_000),  # next valid replacement
        ]
        lots[1].adjusted_basis_cents = 500_000
        lots[2].is_wash_sale = True
        _, results = detect_wash_sales(lots)
        assert len(results) == 1
        assert results[0].replacement_lot_id == "b2"
        assert results[0].disallowed_loss_cents == 20_000

    def test_full_coverage_breaks_before_later_replacement(self):
        """When the first replacement fully covers the sold qty, the loop breaks and a
        later in-window buy is never touched (its adjusted_basis_cents stays None)."""
        lots = [
            _lot("b1", "QQQ", "buy",  date(2024, 6, 1), 100, 500_000),
            _lot("s1", "QQQ", "sell", date(2024, 6, 15), 100, 480_000),
            _lot("b2", "QQQ", "buy",  date(2024, 6, 18), 100, 490_000),  # full coverage
            _lot("b3", "QQQ", "buy",  date(2024, 6, 20), 100, 492_000),  # never reached → break
        ]
        lots[1].adjusted_basis_cents = 500_000
        adjusted, results = detect_wash_sales(lots)
        assert len(results) == 1
        assert results[0].replacement_lot_id == "b2"
        b3 = next(l for l in adjusted if l.id == "b3")
        assert b3.adjusted_basis_cents is None

    def test_second_sell_skips_fully_consumed_replacement(self):
        """L218: a later loss sell finds available_qty<=0 on the only replacement buy.

        Two loss sells of the same ticker share ONE replacement buy whose shares
        are fully consumed by the FIRST (earlier) sell. When the SECOND sell reaches
        that same buy in the inner loop, ``available_qty <= 0`` so the buy is
        skipped via ``continue`` (L218). Per §1091 the second sell's loss is then
        ALLOWED (no remaining replacement shares to disallow against).
        """
        src = _lot("src", "QQQ", "buy", date(2024, 3, 1), 20, 200_000)
        s1 = _lot("s1", "QQQ", "sell", date(2024, 3, 10), 10, 90_000)
        s1.adjusted_basis_cents = 100_000          # loss 10_000
        s2 = _lot("s2", "QQQ", "sell", date(2024, 3, 11), 10, 85_000)
        s2.adjusted_basis_cents = 100_000          # loss 15_000
        # ONE replacement buy, 10 shares — fully consumed by s1; in both windows.
        rep = _lot("rep", "QQQ", "buy", date(2024, 3, 20), 10, 95_000)

        adjusted, results = detect_wash_sales([src, s1, s2, rep])

        # Only s1's loss is disallowed; rep has no shares left for s2.
        assert len(results) == 1
        assert results[0].sell_lot_id == "s1"
        assert results[0].replacement_lot_id == "rep"
        assert results[0].disallowed_loss_cents == 10_000

        # rep basis bumped by s1's loss exactly once (95_000 + 10_000), never inflated.
        rep_lot = next(l for l in adjusted if l.id == "rep")
        assert rep_lot.adjusted_basis_cents == 105_000

        # s2's loss survives — no replacement capacity remained (L218 continue).
        s2_lot = next(l for l in adjusted if l.id == "s2")
        assert s2_lot.is_wash_sale is False
