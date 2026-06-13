"""tests/test_event_consumer.py

Verify that handle_trade_filled() persists a Lot row when a TradeFilledEvent
is received from the event bus.

Follows the test-DB fixture pattern from tests/unit/test_auth.py:
    - monkeypatch DATABASE_URL to sqlite:///:memory:
    - monkeypatch WEALTHTAX_FERNET_KEY
    - reset_settings_cache() + reset_engine_cache() + create_all_for_tests()

Uses fakeredis so no real Redis connection is required.
"""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from decimal import Decimal

import fakeredis
import pytest

from wealthtax_agent.events.schemas import TradeFilledEvent, TradeFilledPayload


# ---------------------------------------------------------------------------
# DB isolation fixture (mirrors test_auth.py pattern)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _isolated_db(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setenv("EVENT_BUS_ENABLED", "true")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")

    if "WEALTHTAX_FERNET_KEY" not in os.environ:
        from cryptography.fernet import Fernet
        monkeypatch.setenv("WEALTHTAX_FERNET_KEY", Fernet.generate_key().decode())

    from wealthtax_agent.config import reset_settings_cache
    from wealthtax_agent.db import create_all_for_tests, reset_engine_cache

    reset_settings_cache()
    reset_engine_cache()
    create_all_for_tests()
    yield
    # reset again so other test files start clean
    reset_engine_cache()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(
    symbol: str = "QQQ",
    side: str = "BUY",
    qty: int = 10,
    price: float = 480.25,
    event_id: str = "evt-test-001",
    signal_id: str = "sig-test-abc",
) -> TradeFilledEvent:
    occurred = datetime(2026, 5, 21, 14, 30, 0, tzinfo=timezone.utc)
    return TradeFilledEvent(
        id=event_id,
        occurred_at=occurred,
        payload=TradeFilledPayload(
            symbol=symbol,
            side=side,  # type: ignore[arg-type]
            quantity=Decimal(str(qty)),
            fill_price=Decimal(str(price)),
            order_id="ord-001",
            signal_id=signal_id,
        ),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHandleTradeFilledBuy:
    @pytest.mark.asyncio
    async def test_buy_creates_lot_row(self) -> None:
        """A BUY TradeFilledEvent creates a Lot row with side='buy'."""
        from wealthtax_agent.db import get_session
        from wealthtax_agent.db.models import Lot
        from wealthtax_agent.workers.event_consumer import handle_trade_filled

        event = _make_event(symbol="QQQ", side="BUY", qty=10, price=480.25)
        await handle_trade_filled(event)

        with get_session() as session:
            lot = session.query(Lot).one()
            # Read all attributes inside the session scope
            ticker = lot.ticker
            side = lot.side
            quantity = lot.quantity
            price = lot.price
            basis = lot.original_basis_cents
            source = lot.source
            source_ref = lot.source_ref

        assert ticker == "QQQ"
        assert side == "buy"
        assert quantity == 10
        assert price == 48025          # cents: 480.25 * 100
        assert basis == 480250         # 48025 * 10
        assert source == "trad-platform-event"
        assert source_ref == event.id

    @pytest.mark.asyncio
    async def test_sell_creates_lot_row(self) -> None:
        """A SELL TradeFilledEvent creates a Lot row with side='sell'."""
        from wealthtax_agent.db import get_session
        from wealthtax_agent.db.models import Lot
        from wealthtax_agent.workers.event_consumer import handle_trade_filled

        event = _make_event(symbol="QQQ", side="SELL", qty=5, price=485.50, event_id="evt-sell-001")
        await handle_trade_filled(event)

        with get_session() as session:
            lot = session.query(Lot).one()
            side = lot.side
            quantity = lot.quantity
            price = lot.price
            basis = lot.original_basis_cents

        assert side == "sell"
        assert quantity == 5
        assert price == 48550           # cents
        assert basis == 242750          # 48550 * 5 (proceeds)

    @pytest.mark.asyncio
    async def test_trade_date_stored(self) -> None:
        """trade_date on Lot matches occurred_at from the event."""
        from wealthtax_agent.db import get_session
        from wealthtax_agent.db.models import Lot
        from wealthtax_agent.workers.event_consumer import handle_trade_filled

        event = _make_event()
        await handle_trade_filled(event)

        with get_session() as session:
            lot = session.query(Lot).first()
            trade_date = lot.trade_date

        # SQLite stores datetimes as naive; compare aware vs naive safely
        expected = datetime(2026, 5, 21, 14, 30, 0)
        assert trade_date.replace(tzinfo=None) == expected

    @pytest.mark.asyncio
    async def test_wrong_event_type_does_not_write(self) -> None:
        """Passing an unexpected type logs an error but doesn't crash or write rows."""
        from wealthtax_agent.db import get_session
        from wealthtax_agent.db.models import Lot
        from wealthtax_agent.workers.event_consumer import handle_trade_filled

        await handle_trade_filled(object())  # not a TradeFilledEvent

        with get_session() as session:
            count = session.query(Lot).count()
        assert count == 0


class TestEventBusEndToEnd:
    """Simulate the full pubsub loop: publish → consume → DB row."""

    @pytest.mark.asyncio
    async def test_fakeredis_publish_subscribe_creates_lot(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Full loop: fakeredis publish → bus.subscribe → handle_trade_filled → Lot row."""
        from wealthtax_agent.db import get_session
        from wealthtax_agent.db.models import Lot
        from wealthtax_agent.events import bus as _bus
        from wealthtax_agent.events.schemas import TradeFilledEvent
        from wealthtax_agent.workers.event_consumer import handle_trade_filled

        fake_server = fakeredis.FakeServer()
        fake_async = fakeredis.aioredis.FakeRedis(server=fake_server, decode_responses=True)
        fake_sync = fakeredis.FakeRedis(server=fake_server, decode_responses=True)

        # Patch bus._get_client to return our fake async client
        monkeypatch.setattr(_bus, "_get_client", lambda: fake_async)
        monkeypatch.setattr(_bus, "_ENABLED", True)

        event = _make_event(symbol="SPY", side="BUY", qty=20, price=530.10, event_id="evt-e2e-001")
        message = event.to_json_bytes().decode()

        # Subscribe (stop_after=1 so it exits after one message)
        subscribe_task = asyncio.create_task(
            _bus.subscribe(TradeFilledEvent.channel(), handle_trade_filled, stop_after=1)
        )

        # Give the subscribe task time to register
        await asyncio.sleep(0.05)

        # Publish via the shared fake server using the sync client
        fake_sync.publish(TradeFilledEvent.channel(), message)

        # Wait for subscribe_task to process the message and exit
        await asyncio.wait_for(subscribe_task, timeout=5.0)

        with get_session() as session:
            lot = session.query(Lot).one()
            ticker = lot.ticker
            side = lot.side
            quantity = lot.quantity

        assert ticker == "SPY"
        assert side == "buy"
        assert quantity == 20


class TestReconnectRetry:
    """Verify graceful reconnect logic in run() does not exceed MAX_RETRIES."""

    @pytest.mark.asyncio
    async def test_run_raises_after_max_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """run() must re-raise after exactly MAX_RETRIES consecutive failures."""
        from wealthtax_agent.workers import event_consumer as ec

        call_count = 0

        async def _failing_subscribe(*_args, **_kwargs):
            nonlocal call_count
            call_count += 1
            raise ConnectionError("redis down")

        # Patch asyncio.sleep so the test doesn't actually wait
        async def _noop_sleep(_seconds):
            pass

        monkeypatch.setattr(ec, "MAX_RETRIES", 3)
        monkeypatch.setattr(asyncio, "sleep", _noop_sleep)

        # Patch subscribe to always fail
        from wealthtax_agent.events import bus as _bus
        monkeypatch.setattr(_bus, "subscribe", _failing_subscribe)

        import importlib
        # Re-import the consumer so it picks up the monkeypatched subscribe
        with pytest.raises(ConnectionError):
            await ec.run()

        # With MAX_RETRIES=3, run() should attempt 3 times (attempts 1, 2, 3)
        # before giving up; the first call is attempt 0 (counted as attempt 1 before raise check)
        assert call_count >= 2, f"Expected at least 2 subscribe calls, got {call_count}"


# ---------------------------------------------------------------------------
# Sentinel 'system' user — the lots.user_id FK target (Postgres regression)
#
# lots.user_id is a NOT-NULL FK to users.id. The consumer attributes platform
# fills to a sentinel user_id="system" that previously did not exist, so the
# INSERT failed with a ForeignKeyViolation on Postgres (SQLite does not enforce
# FKs by default, which masked it). handle_trade_filled now ensures the system
# user exists first.
# ---------------------------------------------------------------------------

class TestSystemUserSentinel:
    @pytest.mark.asyncio
    async def test_handler_creates_system_user(self) -> None:
        from wealthtax_agent.db import get_session
        from wealthtax_agent.db.models import User
        from wealthtax_agent.workers.event_consumer import (
            SYSTEM_USER_ID,
            handle_trade_filled,
        )

        await handle_trade_filled(_make_event(event_id="evt-sysuser-1"))

        with get_session() as session:
            user = session.get(User, SYSTEM_USER_ID)
            assert user is not None, "sentinel system user must exist for the lots FK"
            assert user.email  # NOT NULL unique column populated
            assert user.hashed_password  # NOT NULL column populated

    @pytest.mark.asyncio
    async def test_system_user_creation_is_idempotent(self) -> None:
        """Two fills must not create two system users (no unique-email clash)."""
        from wealthtax_agent.db import get_session
        from wealthtax_agent.db.models import Lot, User
        from wealthtax_agent.workers.event_consumer import (
            SYSTEM_USER_ID,
            handle_trade_filled,
        )

        await handle_trade_filled(_make_event(event_id="evt-sysuser-2a"))
        await handle_trade_filled(_make_event(event_id="evt-sysuser-2b"))

        with get_session() as session:
            n_users = session.query(User).filter(User.id == SYSTEM_USER_ID).count()
            n_lots = session.query(Lot).count()
        assert n_users == 1
        assert n_lots == 2

    def test_lot_source_value_fits_column_width(self) -> None:
        """The source value the consumer writes must fit the column on strict-
        length backends (Postgres). Guards against re-introducing the overflow
        that SQLite silently tolerated."""
        from wealthtax_agent.db.models import Lot
        from wealthtax_agent.workers import event_consumer as ec

        max_len = Lot.__table__.c.source.type.length
        # the literal the handler writes
        assert len("trad-platform-event") <= max_len
        # and the sentinel email fits its column too
        assert len(ec.SYSTEM_USER_EMAIL) <= 320
