"""Event bus consumer — wealthtax-agent side.

SKELETON ONLY — implementation belongs to Workstream C (wealthtax-agent
productionization). Do not add business logic here until C lands.

This file defines:
- The channels this service subscribes to.
- Handler stubs that will be filled in by Workstream C.
- An `async run()` entry point for the worker process.

Depends on:
    infra/events/bus.py   (copy from platform-infra)
    infra/events/schemas.py  (copy from platform-infra)

Environment:
    REDIS_URL            redis://redis:6379
    EVENT_BUS_ENABLED    true  (set in Docker Compose for the worker service)
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports — these files will be copied from platform-infra by Workstream C
# ---------------------------------------------------------------------------
# from infra.events.bus import subscribe
# from infra.events.schemas import (
#     TradeFilledEvent,
#     ReceiptCapturedEvent,
# )


# ---------------------------------------------------------------------------
# Handler stubs
# ---------------------------------------------------------------------------

async def handle_trade_filled(event: object) -> None:
    """Process a trade.filled event from trad-platform.

    TODO (Workstream C):
    1. Cast event to TradeFilledEvent.
    2. Persist fill to wealthtax DB (capital_gains table or equivalent).
    3. Trigger cost-basis update via `build_return.py` / `optimize.py`.
    4. If unrealized loss > threshold, emit TaxLossHarvestSuggestionEvent.
    5. Emit TaxDeadlineEvent if a wash-sale window is opened.
    """
    log.info("trade.filled received: %s (stub — not yet implemented)", getattr(event, "id", event))


async def handle_receipt_captured(event: object) -> None:
    """Process a receipt.captured event from PAA.

    TODO (Workstream C):
    1. Cast event to ReceiptCapturedEvent.
    2. Fetch receipt content from external store via storage_ref.
    3. Route to extract_forms.py for expense categorization.
    4. Persist deductible items.
    """
    log.info("receipt.captured received: %s (stub — not yet implemented)", getattr(event, "id", event))


# ---------------------------------------------------------------------------
# Worker entry point
# ---------------------------------------------------------------------------

async def run() -> None:
    """Subscribe to all relevant channels and dispatch to handlers.

    TODO (Workstream C): uncomment and fill in once bus.py is copied here.
    """
    log.info("wealthtax event consumer starting (stub — bus not wired)")

    # Uncomment after Workstream C copies infra/events/ into this repo:
    #
    # await asyncio.gather(
    #     subscribe("trad-platform.trade.filled", handle_trade_filled),
    #     subscribe("paa.receipt.captured", handle_receipt_captured),
    # )
    #
    # For now, just park — the process stays alive so Docker health-checks pass.
    await asyncio.Event().wait()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
