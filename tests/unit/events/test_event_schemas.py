"""Tests for the platform event schemas (events/schemas.py).

Pins the envelope defaults, the channel routing + EVENT_REGISTRY, the
JSON serialization (Decimal -> string, datetime -> ISO) with the 8 KB
size guard, payload validation, and a full JSON round-trip back to model.
"""

import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from wealthtax_agent.events.schemas import (
    EVENT_REGISTRY,
    BaseEvent,
    NoteCapturedEvent,
    NoteCapturedPayload,
    ReceiptCapturedEvent,
    ReceiptCapturedPayload,
    TaxDeadlineEvent,
    TaxDeadlinePayload,
    TaxLossHarvestSuggestionEvent,
    TaxLossHarvestSuggestionPayload,
    TradeFilledEvent,
    TradeFilledPayload,
)


def _trade():
    return TradeFilledEvent(
        payload=TradeFilledPayload(
            symbol="QQQ", side="BUY", quantity=Decimal("10"),
            fill_price=Decimal("123.45"), order_id="o-1",
        )
    )


def _deadline(description="File your T1 return"):
    return TaxDeadlineEvent(
        payload=TaxDeadlinePayload(
            deadline_date="2026-04-30", jurisdiction="CA", form="T1", description=description,
        )
    )


def test_base_event_channel_is_abstract():
    with pytest.raises(NotImplementedError):
        BaseEvent.channel()


def test_each_event_has_its_channel():
    assert TradeFilledEvent.channel() == "trad-platform.trade.filled"
    assert TaxDeadlineEvent.channel() == "wealthtax-agent.tax.deadline"
    assert NoteCapturedEvent.channel() == "paa.note.captured"
    assert ReceiptCapturedEvent.channel() == "paa.receipt.captured"
    assert TaxLossHarvestSuggestionEvent.channel() == "wealthtax-agent.harvest.suggested"


def test_event_registry_maps_channels_to_classes():
    assert EVENT_REGISTRY["trad-platform.trade.filled"] is TradeFilledEvent
    assert EVENT_REGISTRY["wealthtax-agent.tax.deadline"] is TaxDeadlineEvent
    assert len(EVENT_REGISTRY) == 5
    # every registry key is the channel of the class it maps to
    assert all(cls.channel() == ch for ch, cls in EVENT_REGISTRY.items())


def test_default_envelope_fields():
    e = _trade()
    assert isinstance(e.id, str) and len(e.id) == 36  # uuid4
    assert e.version == 1
    assert e.occurred_at.tzinfo is not None           # tz-aware utcnow
    assert e.type == "trade.filled"
    assert e.source == "trad-platform"


def test_to_json_bytes_roundtrips_and_serializes_decimal_as_string():
    raw = _trade().to_json_bytes()
    assert isinstance(raw, bytes)
    data = json.loads(raw)
    assert data["type"] == "trade.filled"
    assert data["payload"]["symbol"] == "QQQ"
    assert data["payload"]["quantity"] == "10"        # Decimal -> str in json mode
    assert data["payload"]["fill_price"] == "123.45"


def test_to_json_bytes_enforces_8kb_limit():
    with pytest.raises(ValueError, match="8 KB"):
        _deadline(description="x" * 9000).to_json_bytes()


def test_event_roundtrips_through_json_back_to_model():
    e = _trade()
    restored = TradeFilledEvent.model_validate_json(e.to_json_bytes())
    assert restored.payload.symbol == "QQQ"
    assert restored.payload.quantity == Decimal("10")
    assert restored.id == e.id


def test_trade_side_literal_is_validated():
    with pytest.raises(ValidationError):
        TradeFilledPayload(
            symbol="QQQ", side="HOLD", quantity=Decimal("1"),
            fill_price=Decimal("1"), order_id="o",
        )


def test_note_and_receipt_payload_defaults():
    note = NoteCapturedEvent(payload=NoteCapturedPayload(note_id="n1", user_id="u1"))
    assert note.payload.tags == []
    assert note.source == "paa"
    receipt = ReceiptCapturedEvent(payload=ReceiptCapturedPayload(receipt_id="r1", user_id="u1"))
    assert receipt.payload.currency == "CAD"


def test_harvest_event_channel_and_default_wash_sale_flag():
    h = TaxLossHarvestSuggestionEvent(
        payload=TaxLossHarvestSuggestionPayload(
            user_id="u1", symbol="QQQ", current_price=Decimal("100"),
            cost_basis=Decimal("120"), unrealized_loss=Decimal("20"), jurisdiction="US",
        )
    )
    assert h.channel() == "wealthtax-agent.harvest.suggested"
    assert h.payload.wash_sale_safe is False
