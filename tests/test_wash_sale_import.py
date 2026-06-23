"""tests/test_wash_sale_import.py — import_trad_platform_fills sqlite ingestion.

Covers L269-304 of wealthtax_agent.engines.wash_sale: reading fills from a
Trad-Platform ``audit.sqlite`` into LotRecords, and the OperationalError branch
when the expected ``audit_events`` schema is absent.

All sqlite fixtures live under tmp_path — no network, no real DB engine, no LLM.
"""

from __future__ import annotations

import sqlite3

from wealthtax_agent.engines.wash_sale import LotRecord, import_trad_platform_fills


def _make_audit_db(path: str) -> None:
    """Build a sqlite DB matching the exact columns/filters the function queries.

    SELECT id, symbol, side, filled_at, qty, fill_price
    FROM audit_events WHERE event_type = 'fill' AND symbol = ?
    """
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE audit_events (
            id          TEXT,
            symbol      TEXT,
            side        TEXT,
            filled_at   TEXT,
            qty         INTEGER,
            fill_price  REAL,
            event_type  TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO audit_events VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            ("1", "QQQ", "BUY",  "2024-06-01T09:30:00", 10, 500.0, "fill"),
            ("2", "QQQ", "SELL", "2024-06-15T09:30:00", 10, 480.0, "fill"),
            ("3", "SPY", "BUY",  "2024-06-02T09:30:00",  5, 400.0, "fill"),  # other ticker → filtered
        ],
    )
    conn.commit()
    conn.close()


class TestImportTradPlatformFills:
    def test_happy_path_imports_target_ticker_only(self, tmp_path):
        db = tmp_path / "audit.sqlite"
        _make_audit_db(str(db))

        lots = import_trad_platform_fills(str(db), user_id="user1", ticker="QQQ")

        # Other-ticker (SPY) row is filtered out by the WHERE symbol = ? clause.
        assert len(lots) == 2
        assert all(isinstance(l, LotRecord) for l in lots)
        assert all(l.ticker == "QQQ" for l in lots)

    def test_side_is_lowercased(self, tmp_path):
        db = tmp_path / "audit.sqlite"
        _make_audit_db(str(db))

        lots = import_trad_platform_fills(str(db), user_id="user1", ticker="QQQ")
        sides = {l.id: l.side for l in lots}
        assert sides["1"] == "buy"
        assert sides["2"] == "sell"

    def test_original_basis_cents_is_qty_times_price_cents(self, tmp_path):
        db = tmp_path / "audit.sqlite"
        _make_audit_db(str(db))

        lots = import_trad_platform_fills(str(db), user_id="user1", ticker="QQQ")
        by_id = {l.id: l for l in lots}
        # 10 shares @ $500.00 → 10 * int(500.0 * 100) = 10 * 50_000 = 500_000
        assert by_id["1"].original_basis_cents == 10 * int(500.0 * 100)
        assert by_id["1"].original_basis_cents == 500_000
        # 10 shares @ $480.00 → 480_000
        assert by_id["2"].original_basis_cents == 480_000

    def test_iso_filled_at_parsed_to_date(self, tmp_path):
        from datetime import date

        db = tmp_path / "audit.sqlite"
        _make_audit_db(str(db))

        lots = import_trad_platform_fills(str(db), user_id="user1", ticker="QQQ")
        by_id = {l.id: l for l in lots}
        assert by_id["1"].trade_date == date(2024, 6, 1)
        assert by_id["2"].trade_date == date(2024, 6, 15)

    def test_quantity_preserved(self, tmp_path):
        db = tmp_path / "audit.sqlite"
        _make_audit_db(str(db))

        lots = import_trad_platform_fills(str(db), user_id="user1", ticker="QQQ")
        assert all(l.quantity == 10 for l in lots)

    def test_schema_mismatch_returns_empty(self, tmp_path):
        """A DB without the audit_events table → OperationalError branch → []."""
        db = tmp_path / "empty.sqlite"
        sqlite3.connect(str(db)).close()  # valid sqlite file, no tables

        lots = import_trad_platform_fills(str(db), user_id="user1", ticker="QQQ")
        assert lots == []
