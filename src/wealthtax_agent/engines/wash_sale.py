"""US §1091 wash-sale detection and basis adjustment.

Algorithm
---------
For each *sell* lot where ``gain_loss_cents < 0`` (a loss):

1. Scan all *buy* lots for the same ticker (or substantially-identical
   security) with a ``trade_date`` within the 61-day window
   [sell_date - 30 days, sell_date + 30 days].

2. If a replacement buy exists, the loss is disallowed.  The disallowed
   amount is added to ``adjusted_basis_cents`` of the earliest matching
   replacement lot (partial coverage handled proportionally when qty differs).

3. A ``WashSale`` record is produced for each disallowed loss.

Integration with Trad-Platform
--------------------------------
Import fills from Trad-Platform's ``audit.sqlite`` as ``Lot`` rows with
``source="trad_audit"`` before calling ``detect_wash_sales``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

log = logging.getLogger(__name__)

_WASH_WINDOW_DAYS = 30  # 30 before + 30 after = 61-day total window


@dataclass
class LotRecord:
    """In-memory representation of a Lot for wash-sale computation.

    Uses integer cents throughout to avoid float rounding errors.
    """

    id: str
    ticker: str
    side: str                    # "buy" | "sell"
    trade_date: date
    quantity: int                # shares
    original_basis_cents: int    # total cost basis (cents)
    adjusted_basis_cents: Optional[int] = None  # set by wash-sale adjustment
    is_wash_sale: bool = False
    cusip: Optional[str] = None

    @property
    def price_cents(self) -> int:
        return self.original_basis_cents // max(self.quantity, 1)

    @property
    def effective_basis_cents(self) -> int:
        if self.adjusted_basis_cents is not None:
            return self.adjusted_basis_cents
        return self.original_basis_cents


@dataclass
class WashSaleResult:
    """Output from ``detect_wash_sales``.

    All monetary fields are in cents.
    """

    sell_lot_id: str
    replacement_lot_id: str
    ticker: str
    sell_date: date
    replacement_buy_date: date
    disallowed_loss_cents: int   # positive = loss that was disallowed
    basis_adjustment_cents: int  # same as disallowed_loss for full coverage
    note: str = ""


def _normalise_date(d) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    raise TypeError(f"Expected date/datetime, got {type(d)}")


def _same_security(a: LotRecord, b: LotRecord) -> bool:
    """True if ``a`` and ``b`` refer to the same or substantially-identical security.

    Substantially-identical: same CUSIP when available, otherwise same ticker
    (case-insensitive).  Options on the same underlying are NOT flagged here —
    the caller should resolve them before building LotRecords.
    """
    if a.cusip and b.cusip and a.cusip == b.cusip:
        return True
    return a.ticker.upper() == b.ticker.upper()


def detect_wash_sales(lots: List[LotRecord]) -> Tuple[List[LotRecord], List[WashSaleResult]]:
    """Identify wash sales and apply basis adjustments.

    Parameters
    ----------
    lots:
        Flat list of buy and sell lots, any order.

    Returns
    -------
    adjusted_lots:
        Same lots, mutated in-place with ``adjusted_basis_cents`` and
        ``is_wash_sale`` set where applicable.
    wash_sales:
        One ``WashSaleResult`` per disallowed loss.

    Notes
    -----
    - Lots are processed chronologically.
    - Partial share coverage is handled: if the replacement buy has fewer
      shares than the sell, only that fraction of the loss is disallowed.
    - The function does NOT write to the database — callers persist the
      results via ``db.repo``.
    """
    # Sort chronologically for deterministic processing
    sorted_lots = sorted(lots, key=lambda x: _normalise_date(x.trade_date))
    sells = [l for l in sorted_lots if l.side == "sell"]
    buys  = [l for l in sorted_lots if l.side == "buy"]

    results: List[WashSaleResult] = []

    for sell in sells:
        sell_date = _normalise_date(sell.trade_date)
        proceeds_cents = sell.original_basis_cents  # for a sell, basis = cost of shares being sold
        # gain_loss = proceeds - cost; we need actual proceeds.
        # LotRecord stores total cost of the *buy*; for a *sell* original_basis_cents
        # represents the proceeds received.  Loss = cost_of_shares - proceeds.
        # Determine if this sell is at a loss.
        # We can only tell if we have matching buy lots.  Skip gain lots.
        # Find the buy(s) that were *acquired* at the same ticker to compute cost.
        # In the simplified model: basis is supplied by the caller.
        # original_basis_cents on a sell lot = proceeds; on a buy lot = cost.
        sell_proceeds_cents = sell.original_basis_cents
        # Find all buys for the same security within the window
        window_start = sell_date - timedelta(days=_WASH_WINDOW_DAYS)
        window_end   = sell_date + timedelta(days=_WASH_WINDOW_DAYS)

        # Replacement buys: same security, within 61-day window.
        # Exclude buys that predated the sell by more than the window (source lots).
        # Specifically, if a buy occurred before the sell AND is the only/earliest buy
        # for that ticker, it is the *source* lot being sold — not a replacement.
        # We approximate this by: pre-sell buys are only replacements if they occur
        # AFTER another buy of the same security has already been sold (i.e., the
        # position was closed and then re-entered before the loss sale).
        # Simpler heuristic: pre-sell buys within the window are replacements only if
        # there is at least one other buy for the same ticker on an EARLIER date that
        # could be the source lot.
        earliest_buy_date_per_ticker: dict = {}
        for b in buys:
            key = (b.ticker.upper(), b.cusip or "")
            d = _normalise_date(b.trade_date)
            if key not in earliest_buy_date_per_ticker or d < earliest_buy_date_per_ticker[key]:
                earliest_buy_date_per_ticker[key] = d

        replacement_buys = []
        for b in buys:
            if not _same_security(sell, b):
                continue
            bd = _normalise_date(b.trade_date)
            if not (window_start <= bd <= window_end):
                continue
            if bd == sell_date:
                continue  # same-day — not a replacement
            if b.is_wash_sale:
                continue
            # If this buy is BEFORE the sell date, check that it is not the only/earliest
            # buy (which would make it the source lot, not a replacement)
            if bd < sell_date:
                key = (b.ticker.upper(), b.cusip or "")
                earliest = earliest_buy_date_per_ticker.get(key)
                if earliest is not None and earliest == bd:
                    # This is the earliest buy for this ticker — likely the source lot
                    continue
            replacement_buys.append(b)

        if not replacement_buys:
            continue

        # Determine loss.  We need the original cost basis of the sold shares.
        # For 1099-B scenarios the *sell* LotRecord's adjusted_basis_cents holds
        # the cost if pre-populated; fall back to 0 (caller must populate).
        cost_of_sold_cents = sell.adjusted_basis_cents or 0
        loss_cents = cost_of_sold_cents - sell_proceeds_cents

        if loss_cents <= 0:
            # No loss → no wash sale
            continue

        # Apply disallowance to earliest replacement buy(s)
        remaining_loss = loss_cents
        remaining_qty  = sell.quantity

        for rep_buy in sorted(replacement_buys, key=lambda x: _normalise_date(x.trade_date)):
            if remaining_loss <= 0 or remaining_qty <= 0:
                break

            covered_qty = min(rep_buy.quantity, remaining_qty)
            proportion  = covered_qty / sell.quantity
            disallowed  = int(proportion * loss_cents)

            # Add disallowed loss to replacement lot's basis
            if rep_buy.adjusted_basis_cents is None:
                rep_buy.adjusted_basis_cents = rep_buy.original_basis_cents
            rep_buy.adjusted_basis_cents += disallowed
            rep_buy.is_wash_sale = False  # the *replacement* buy is not tainted

            sell.is_wash_sale = True

            results.append(WashSaleResult(
                sell_lot_id=sell.id,
                replacement_lot_id=rep_buy.id,
                ticker=sell.ticker,
                sell_date=sell_date,
                replacement_buy_date=_normalise_date(rep_buy.trade_date),
                disallowed_loss_cents=disallowed,
                basis_adjustment_cents=disallowed,
                note=(
                    f"§1091: {covered_qty} of {sell.quantity} shares of {sell.ticker} "
                    f"sold {sell_date} at a loss of ${loss_cents/100:.2f}; "
                    f"replacement buy {_normalise_date(rep_buy.trade_date)} — "
                    f"${disallowed/100:.2f} disallowed, added to replacement basis."
                ),
            ))

            remaining_loss -= disallowed
            remaining_qty  -= covered_qty

        log.debug(
            "wash-sale: %s sold %s → %d result(s), total disallowed $%.2f",
            sell.ticker,
            sell_date,
            len([r for r in results if r.sell_lot_id == sell.id]),
            sum(r.disallowed_loss_cents for r in results if r.sell_lot_id == sell.id) / 100,
        )

    return sorted_lots, results


def import_trad_platform_fills(audit_db_path: str, user_id: str, ticker: str = "QQQ") -> List[LotRecord]:
    """Read fills from Trad-Platform's ``audit.sqlite`` and return LotRecords.

    Only imports fills for ``ticker`` (default QQQ).  Caller passes the list
    to ``detect_wash_sales``.
    """
    import sqlite3
    import uuid

    conn = sqlite3.connect(audit_db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, symbol, side, filled_at, qty, fill_price
            FROM audit_events
            WHERE event_type = 'fill' AND symbol = ?
            ORDER BY filled_at
            """,
            (ticker,),
        ).fetchall()
    except sqlite3.OperationalError:
        log.warning("audit.sqlite schema mismatch — no fills imported")
        return []
    finally:
        conn.close()

    lots: List[LotRecord] = []
    for row in rows:
        qty = int(row["qty"])
        price_cents = int(float(row["fill_price"]) * 100)
        total_cents = qty * price_cents
        trade_dt = datetime.fromisoformat(row["filled_at"]) if isinstance(row["filled_at"], str) else row["filled_at"]
        lots.append(LotRecord(
            id=str(row["id"]),
            ticker=row["symbol"],
            side=row["side"].lower(),  # "buy" | "sell"
            trade_date=trade_dt.date() if isinstance(trade_dt, datetime) else trade_dt,
            quantity=qty,
            original_basis_cents=total_cents,
        ))
    return lots
