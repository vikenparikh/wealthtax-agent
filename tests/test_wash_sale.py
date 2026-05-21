"""tests/test_wash_sale.py — unit tests for US §1091 wash-sale engine."""

from __future__ import annotations

from datetime import date

import pytest

from wealthtax_agent.engines.wash_sale import LotRecord, WashSaleResult, detect_wash_sales


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
