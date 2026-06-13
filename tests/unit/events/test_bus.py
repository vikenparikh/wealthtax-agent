"""Tests for the async Redis pub/sub bus (events/bus.py).

Redis is mocked and the coroutines are driven with asyncio.run (no real
broker, no pytest-asyncio config dependency). Pins the EVENT_BUS_ENABLED
no-op gating, the fire-and-forget publish (never raises on error), and the
subscribe routing: typed-event dispatch, non-message frames skipped,
unknown channel skipped, handler exceptions not breaking the loop, and —
critically — idle tolerance: ``get_message`` returning None (idle) or
raising a Redis ``TimeoutError`` (idle socket read) must NOT kill the
subscription. That idle-as-fatal behaviour is what crash-looped
infra-wealth-consumer-1.
"""

import asyncio
import json
from decimal import Decimal

import redis.asyncio as aioredis
from redis.exceptions import TimeoutError as RedisTimeoutError

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
    """Drives the subscribe() get_message() loop from a scripted list.

    Each script item is one of:
      * a dict             -> returned as a message frame
      * None               -> an idle tick (no message within the timeout)
      * an Exception inst. -> raised (e.g. a socket read TimeoutError)
      * an Exception class -> instantiated and raised

    Once the script is drained, get_message returns None forever (idle), so
    tests must terminate via stop_after on a *counted* message.
    """

    def __init__(self, messages):
        self._messages = list(messages)
        self.unsubscribed = []
        self.get_message_calls = 0

    async def subscribe(self, channel):
        pass

    async def unsubscribe(self, channel):
        self.unsubscribed.append(channel)

    async def get_message(self, ignore_subscribe_messages=False, timeout=None):
        self.get_message_calls += 1
        await asyncio.sleep(0)  # cooperatively yield
        if not self._messages:
            return None
        item = self._messages.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, type) and issubclass(item, BaseException):
            raise item("idle read timeout")
        return item


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


# --- idle tolerance (the crash-loop regression) ------------------------------


def test_subscribe_tolerates_idle_none_then_processes(monkeypatch):
    """get_message() returning None (no traffic in the timeout window) is an
    idle tick, not a failure: the loop keeps going and still delivers a later
    real message."""
    monkeypatch.setattr(bus, "_ENABLED", True)
    raw = _event().to_json_bytes().decode()
    channel = TradeFilledEvent.channel()
    msgs = [None, None, None, {"type": "message", "data": raw}]
    monkeypatch.setattr(bus, "_get_client", lambda: _FakeSubClient(_FakePubSub(msgs)))
    received = []

    async def handler(event):
        received.append(event)

    asyncio.run(bus.subscribe(channel, handler, stop_after=1))
    assert len(received) == 1  # survived 3 idle ticks, then processed


def test_subscribe_tolerates_read_timeout_then_processes(monkeypatch):
    """A Redis socket read TimeoutError on an idle connection must NOT bubble
    up and bounce the consumer. This is the exact failure that crash-looped
    infra-wealth-consumer-1 (~1465 restarts)."""
    monkeypatch.setattr(bus, "_ENABLED", True)
    raw = _event().to_json_bytes().decode()
    channel = TradeFilledEvent.channel()
    # both the redis-specific TimeoutError and the builtin one must be tolerated
    msgs = [RedisTimeoutError, TimeoutError("idle"), {"type": "message", "data": raw}]
    monkeypatch.setattr(bus, "_get_client", lambda: _FakeSubClient(_FakePubSub(msgs)))
    received = []

    async def handler(event):
        received.append(event)

    asyncio.run(bus.subscribe(channel, handler, stop_after=1))  # must not raise
    assert len(received) == 1


def test_subscribe_propagates_non_timeout_errors(monkeypatch):
    """A genuine connection failure (not a timeout) must propagate so the
    consumer's reconnect/back-off loop can act — idle tolerance must not
    swallow real outages."""
    monkeypatch.setattr(bus, "_ENABLED", True)
    channel = TradeFilledEvent.channel()
    from redis.exceptions import ConnectionError as RedisConnectionError

    msgs = [RedisConnectionError("connection lost")]
    monkeypatch.setattr(bus, "_get_client", lambda: _FakeSubClient(_FakePubSub(msgs)))

    async def handler(_e):
        pass

    raised = False
    try:
        asyncio.run(bus.subscribe(channel, handler, stop_after=1))
    except RedisConnectionError:
        raised = True
    assert raised, "real connection errors must propagate to the reconnect loop"


# --- client resilience kwargs ------------------------------------------------


def test_get_client_uses_resilient_kwargs(monkeypatch):
    """The pub/sub client must be built with keepalive + a periodic health
    check so idle connections stay warm (and dead ones are detected) instead
    of timing out as fatal."""
    captured = {}

    def _fake_from_url(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(aioredis, "from_url", _fake_from_url)
    bus._get_client()

    kw = captured["kwargs"]
    assert kw.get("socket_keepalive") is True
    assert kw.get("health_check_interval", 0) > 0
    assert kw.get("decode_responses") is True
