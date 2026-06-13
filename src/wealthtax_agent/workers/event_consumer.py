"""Event bus consumer — wealthtax-agent.

Subscribes to trad-platform.trade.filled and paa.receipt.captured.
On trade.filled → persists a Lot row (buy or sell side) to the DB.

Resilience: if Redis disconnects, reconnects with exponential back-off up to
MAX_RETRIES before exiting. Each retry interval: min(2**attempt, 60) seconds.

Environment:
    REDIS_URL            redis://redis:6379
    EVENT_BUS_ENABLED    true
    DATABASE_URL         postgresql+psycopg://... (or sqlite:///:memory: in tests)
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

log = logging.getLogger(__name__)

MAX_RETRIES = 5  # maximum number of reconnect attempts before giving up


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

async def handle_trade_filled(event: object) -> None:
    """Persist a Lot row from a TradeFilledEvent.

    Creates:
      - side          : 'buy' or 'sell'
      - ticker        : event.payload.symbol
      - quantity      : int(event.payload.quantity)
      - price         : cents = int(float(fill_price) * 100)
      - original_basis_cents: price_cents * qty  (buy side)
      - proceeds_cents (stored in original_basis_cents for sells, sign convention)
      - trade_date    : event.occurred_at
      - source        : 'trad-platform-event'
      - source_ref    : event.id (deduplication handle)

    A sentinel user_id ("system") is used because trad-platform fills are
    platform-level, not user-scoped. Callers that know the user should upsert
    with the real user_id after the fact.
    """
    from wealthtax_agent.events.schemas import TradeFilledEvent
    from wealthtax_agent.db import get_session, reset_engine_cache
    from wealthtax_agent.db.models import Lot

    if not isinstance(event, TradeFilledEvent):
        log.error("handle_trade_filled: expected TradeFilledEvent, got %s", type(event))
        return

    pl = event.payload
    fill_price_cents = int(float(pl.fill_price) * 100)
    qty = int(pl.quantity)
    side = pl.side.lower()  # "buy" or "sell"

    if side in ("buy", "long"):
        side = "buy"
        basis_cents = fill_price_cents * qty
    else:
        side = "sell"
        basis_cents = fill_price_cents * qty  # proceeds for sells

    try:
        with get_session() as session:
            lot = Lot(
                user_id="system",
                ticker=pl.symbol,
                side=side,
                trade_date=event.occurred_at,
                quantity=qty,
                price=fill_price_cents,
                original_basis_cents=basis_cents,
                source="trad-platform-event",
                source_ref=event.id,
            )
            session.add(lot)
        log.info(
            "Lot persisted: %s %s qty=%d price_cents=%d event_id=%s",
            side.upper(), pl.symbol, qty, fill_price_cents, event.id,
        )
    except Exception:
        log.error("handle_trade_filled: DB write failed for event %s", event.id, exc_info=True)


async def handle_receipt_captured(event: object) -> None:
    """Process a receipt.captured event from PAA.

    Stub — full implementation deferred to Workstream C receipt integration.
    """
    log.info(
        "receipt.captured received: %s (not yet implemented)",
        getattr(event, "id", repr(event)),
    )


# ---------------------------------------------------------------------------
# Worker entry point with reconnect loop
# ---------------------------------------------------------------------------

def _ensure_schema() -> None:
    """Ensure the DB schema is up-to-date before the consumer starts processing events.

    For SQLite (dev / fallback): use SQLAlchemy's ``create_all`` so tests and
    standalone runs work without Alembic being present.

    For any other DB (Postgres in production): run ``alembic upgrade head``
    via subprocess so the consumer is always in sync with the latest migration
    even after a fresh container pull.
    """
    import subprocess
    import sys

    from wealthtax_agent.config import get_settings

    db_url = get_settings().database_url
    if db_url.startswith("sqlite"):
        from wealthtax_agent.db import create_all_for_tests
        create_all_for_tests()
        log.info("schema: SQLite create_all complete (%s)", db_url)
    else:
        try:
            result = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                log.error(
                    "schema: alembic upgrade head failed (rc=%d):\n%s",
                    result.returncode,
                    result.stderr,
                )
            else:
                log.info("schema: alembic upgrade head OK")
        except Exception:
            log.error("schema: alembic upgrade head raised an exception", exc_info=True)


async def run() -> None:
    """Subscribe to relevant channels; reconnect on Redis failure.

    Runs until cancelled or MAX_RETRIES consecutive failures.
    """
    from wealthtax_agent.events.bus import subscribe
    from wealthtax_agent.events.schemas import TradeFilledEvent

    _ensure_schema()

    attempt = 0
    while True:
        try:
            log.info("wealthtax event consumer starting (attempt %d)", attempt)
            await asyncio.gather(
                subscribe(TradeFilledEvent.channel(), handle_trade_filled),
                subscribe("paa.receipt.captured", handle_receipt_captured),
            )
            # subscribe() returns only if EVENT_BUS_ENABLED=false or stop_after reached
            return
        except asyncio.CancelledError:
            log.info("wealthtax event consumer cancelled")
            return
        except Exception as exc:
            attempt += 1
            if attempt >= MAX_RETRIES:
                log.error(
                    "event consumer: Redis failed %d times — giving up: %s",
                    MAX_RETRIES, exc,
                )
                raise
            wait = min(2 ** attempt, 60)
            log.warning(
                "event consumer: Redis error (attempt %d/%d), retrying in %ds: %s",
                attempt, MAX_RETRIES, wait, exc,
            )
            await asyncio.sleep(wait)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
