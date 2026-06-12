"""Tests for the async Redis pub/sub bus (events/bus.py).

Redis is mocked and the coroutines are driven with asyncio.run (no real
broker, no pytest-asyncio config dependency). Pins the EVENT_BUS_ENABLED
no-op gating, the fire-and-forget publish (never raises on error), and the
subscribe routing: typed-event dispatch, non-message frames skipped,
unknown channel skipped, and handler exceptions not breaking the loop.
"""

import asyncio
import json
from decimal import Decimal

import wealthtax_agent.events.bus as bus
from wealthtax_agent.events.schemas import TradeFilledEvent, TradeFilledPayload


def _event():
    return TradeFilledEvent(
        payload=TradeFilledPayload(
            symbol="QQQ", side="BUY", quantity=Decimal("1"), fill_price=Decimal("100"), order_id="o1"
        )
    )


class _FakePublishClient:
    def __init__(self, fail=False):
        self.published = []
        self.fail = fail

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def publish(self, channel, raw):
        if self.fail:
            raise RuntimeError("redis down")
        self.published.append((channel, raw))


class _FakePubSub:
    def __init__(self, messages):
        self._messages = messages
        self.unsubscribed = []

    async def subscribe(self, channel):
        pass

    async def unsubscribe(self, channel):
        self.unsubscribed.append(channel)

    async def listen(self):
        for m in self._messages:
            yield m


class _FakeSubClient:
    def __init__(self, pubsub):
        self._pubsub = pubsub
        self.closed = False

    def pubsub(self):
        return self._pubsub

    async def aclose(self):
        self.closed = True


# --- publish -----------------------------------------------------------------


def test_publish_is_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(bus, "_ENABLED", False)
    called = {"v": False}

    def _gc():
        called["v"] = True
        return _FakePublishClient()

    monkeypatch.setattr(bus, "_get_client", _gc)
    asyncio.run(bus.publish(_event()))
    assert called["v"] is False  # no client created


def test_publish_sends_serialized_event_to_channel(monkeypatch):
    monkeypatch.setattr(bus, "_ENABLED", True)
    fake = _FakePublishClient()
    monkeypatch.setattr(bus, "_get_client", lambda: fake)
    ev = _event()
    asyncio.run(bus.publish(ev))
    assert len(fake.published) == 1
    channel, raw = fake.published[0]
    assert channel == TradeFilledEvent.channel()
    assert json.loads(raw)["id"] == ev.id


def test_publish_never_raises_on_error(monkeypatch):
    monkeypatch.setattr(bus, "_ENABLED", True)
    monkeypatch.setattr(bus, "_get_client", lambda: _FakePublishClient(fail=True))
    asyncio.run(bus.publish(_event()))  # must swallow the error


# --- subscribe ---------------------------------------------------------------


def test_subscribe_is_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(bus, "_ENABLED", False)
    called = {"v": False}

    def _gc():
        called["v"] = True
        return _FakeSubClient(_FakePubSub([]))

    monkeypatch.setattr(bus, "_get_client", _gc)

    async def handler(_e):
        pass

    asyncio.run(bus.subscribe("ch", handler))
    assert called["v"] is False


def test_subscribe_dispatches_typed_event_and_unsubscribes(monkeypatch):
    monkeypatch.setattr(bus, "_ENABLED", True)
    raw = _event().to_json_bytes().decode()
    channel = TradeFilledEvent.channel()
    pubsub = _FakePubSub([{"type": "message", "data": raw}])
    monkeypatch.setattr(bus, "_get_client", lambda: _FakeSubClient(pubsub))
    received = []

    async def handler(event):
        received.append(event)

    asyncio.run(bus.subscribe(channel, handler, stop_after=1))
    assert len(received) == 1
    assert isinstance(received[0], TradeFilledEvent)
    assert received[0].payload.symbol == "QQQ"
    assert channel in pubsub.unsubscribed  # cleanup ran


def test_subscribe_skips_non_message_frames(monkeypatch):
    monkeypatch.setattr(bus, "_ENABLED", True)
    raw = _event().to_json_bytes().decode()
    channel = TradeFilledEvent.channel()
    msgs = [{"type": "subscribe", "data": 1}, {"type": "message", "data": raw}]
    monkeypatch.setattr(bus, "_get_client", lambda: _FakeSubClient(_FakePubSub(msgs)))
    received = []

    async def handler(event):
        received.append(event)

    asyncio.run(bus.subscribe(channel, handler, stop_after=1))
    assert len(received) == 1


def test_subscribe_skips_channel_without_registered_schema(monkeypatch):
    monkeypatch.setattr(bus, "_ENABLED", True)
    msgs = [{"type": "message", "data": json.dumps({"foo": "bar"})}]
    monkeypatch.setattr(bus, "_get_client", lambda: _FakeSubClient(_FakePubSub(msgs)))
    received = []

    async def handler(event):
        received.append(event)

    asyncio.run(bus.subscribe("unregistered.channel", handler, stop_after=1))
    assert received == []


def test_subscribe_continues_when_handler_raises(monkeypatch):
    monkeypatch.setattr(bus, "_ENABLED", True)
    raw = _event().to_json_bytes().decode()
    channel = TradeFilledEvent.channel()
    msgs = [{"type": "message", "data": raw}, {"type": "message", "data": raw}]
    monkeypatch.setattr(bus, "_get_client", lambda: _FakeSubClient(_FakePubSub(msgs)))
    calls = []

    async def handler(event):
        calls.append(event)
        raise RuntimeError("handler boom")

    asyncio.run(bus.subscribe(channel, handler, stop_after=2))  # must not raise
    assert len(calls) == 2
