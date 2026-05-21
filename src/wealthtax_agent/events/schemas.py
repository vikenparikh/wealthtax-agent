"""Platform event schemas — v1.

Canonical Pydantic models for all cross-service events. Copy this file (and
bus.py) into each service that publishes or consumes events. Do NOT import
across service boundaries at runtime — each service owns its copy.

Envelope fields are defined on BaseEvent; event-specific data lives in
`payload` which is a typed sub-model per event type.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Base envelope
# ---------------------------------------------------------------------------

class BaseEvent(BaseModel):
    """Shared envelope for every platform event."""

    id: str = Field(default_factory=_new_id, description="UUID4 — consumers deduplicate on this")
    type: str = Field(description="entity.verb — e.g. 'trade.filled'")
    occurred_at: datetime = Field(default_factory=_utcnow)
    source: str = Field(description="Publishing service name — e.g. 'trad-platform'")
    version: int = Field(default=1)
    payload: BaseModel

    model_config = {"arbitrary_types_allowed": True}

    def to_json_bytes(self) -> bytes:
        data = self.model_dump(mode="json")
        import json
        raw = json.dumps(data)
        if len(raw) > 8192:
            raise ValueError(f"Event {self.id} exceeds 8 KB limit ({len(raw)} bytes)")
        return raw.encode()

    @classmethod
    def channel(cls) -> str:
        """Redis pub/sub channel for this event type. Override in subclasses."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# trade.filled  (publisher: trad-platform)
# ---------------------------------------------------------------------------

class TradeFilledPayload(BaseModel):
    symbol: str
    side: Literal["BUY", "SELL"]
    quantity: Decimal
    fill_price: Decimal
    commission: Decimal = Decimal("0")
    order_id: str
    signal_id: str | None = None
    strategy: str | None = None
    profile: str | None = None
    account: str | None = None


class TradeFilledEvent(BaseEvent):
    type: Literal["trade.filled"] = "trade.filled"
    source: Literal["trad-platform"] = "trad-platform"
    payload: TradeFilledPayload  # type: ignore[assignment]

    @classmethod
    def channel(cls) -> str:
        return "trad-platform.trade.filled"


# ---------------------------------------------------------------------------
# tax.deadline  (publisher: wealthtax-agent)
# ---------------------------------------------------------------------------

class TaxDeadlinePayload(BaseModel):
    deadline_date: str          # ISO-8601 date, e.g. "2026-04-30"
    jurisdiction: str           # e.g. "CA", "US-FED"
    form: str                   # e.g. "T1", "1040"
    description: str
    user_id: str | None = None
    days_until: int | None = None


class TaxDeadlineEvent(BaseEvent):
    type: Literal["tax.deadline"] = "tax.deadline"
    source: Literal["wealthtax-agent"] = "wealthtax-agent"
    payload: TaxDeadlinePayload  # type: ignore[assignment]

    @classmethod
    def channel(cls) -> str:
        return "wealthtax-agent.tax.deadline"


# ---------------------------------------------------------------------------
# note.captured  (publisher: paa)
# ---------------------------------------------------------------------------

class NoteCapturedPayload(BaseModel):
    note_id: str
    user_id: str
    title: str | None = None
    tags: list[str] = Field(default_factory=list)
    word_count: int | None = None
    storage_ref: str | None = None  # e.g. Postgres row ID or S3 key


class NoteCapturedEvent(BaseEvent):
    type: Literal["note.captured"] = "note.captured"
    source: Literal["paa"] = "paa"
    payload: NoteCapturedPayload  # type: ignore[assignment]

    @classmethod
    def channel(cls) -> str:
        return "paa.note.captured"


# ---------------------------------------------------------------------------
# receipt.captured  (publisher: paa)
# ---------------------------------------------------------------------------

class ReceiptCapturedPayload(BaseModel):
    receipt_id: str
    user_id: str
    vendor: str | None = None
    amount: Decimal | None = None
    currency: str = "CAD"
    date: str | None = None         # ISO-8601 date
    category: str | None = None
    storage_ref: str | None = None  # external store reference (never raw image in event)


class ReceiptCapturedEvent(BaseEvent):
    type: Literal["receipt.captured"] = "receipt.captured"
    source: Literal["paa"] = "paa"
    payload: ReceiptCapturedPayload  # type: ignore[assignment]

    @classmethod
    def channel(cls) -> str:
        return "paa.receipt.captured"


# ---------------------------------------------------------------------------
# harvest.suggested  (publisher: wealthtax-agent)
# ---------------------------------------------------------------------------

class TaxLossHarvestSuggestionPayload(BaseModel):
    user_id: str
    symbol: str
    current_price: Decimal
    cost_basis: Decimal
    unrealized_loss: Decimal
    estimated_tax_saving: Decimal | None = None
    jurisdiction: str
    wash_sale_safe: bool = False
    rationale: str | None = None


class TaxLossHarvestSuggestionEvent(BaseEvent):
    type: Literal["harvest.suggested"] = "harvest.suggested"
    source: Literal["wealthtax-agent"] = "wealthtax-agent"
    payload: TaxLossHarvestSuggestionPayload  # type: ignore[assignment]

    @classmethod
    def channel(cls) -> str:
        return "wealthtax-agent.harvest.suggested"


# ---------------------------------------------------------------------------
# Registry: channel → event class
# ---------------------------------------------------------------------------

EVENT_REGISTRY: dict[str, type[BaseEvent]] = {
    TradeFilledEvent.channel(): TradeFilledEvent,
    TaxDeadlineEvent.channel(): TaxDeadlineEvent,
    NoteCapturedEvent.channel(): NoteCapturedEvent,
    ReceiptCapturedEvent.channel(): ReceiptCapturedEvent,
    TaxLossHarvestSuggestionEvent.channel(): TaxLossHarvestSuggestionEvent,
}
