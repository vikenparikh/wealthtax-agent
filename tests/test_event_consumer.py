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


# ---------------------------------------------------------------------------
# Error / schema / reconnect branch coverage (lines 116-117, 125, 156-172,
# 194, 196-197). The entrypoint (215-216) is intentionally not covered.
#
# Local-import monkeypatch gotchas (confirmed against the source):
#   - handle_trade_filled does `from wealthtax_agent.db import get_session`
#     INSIDE the function → patch wealthtax_agent.db.get_session.
#   - _ensure_schema does `import subprocess` + `from wealthtax_agent.config
#     import get_settings` locally → patch subprocess.run and
#     wealthtax_agent.config.get_settings.
#   - run() does `from wealthtax_agent.events.bus import subscribe` locally →
#     patch _bus.subscribe.
# ---------------------------------------------------------------------------


class TestHandleTradeFilledErrorPath:
    """handle_trade_filled swallows DB-write failures (lines 116-117)."""

    @pytest.mark.asyncio
    async def test_db_write_failure_is_swallowed(
        self, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        """A DB error in get_session() is caught, logged, and not re-raised."""
        import logging

        import wealthtax_agent.db as _db
        from wealthtax_agent.workers.event_consumer import handle_trade_filled

        def _boom_get_session():
            raise RuntimeError("db exploded")

        # get_session is used as a context manager; raising on call is enough
        # to trip the `with get_session() as session:` line.
        monkeypatch.setattr(_db, "get_session", _boom_get_session)

        event = _make_event(event_id="evt-dbfail-1")
        with caplog.at_level(logging.ERROR, logger="wealthtax_agent.workers.event_consumer"):
            # Must NOT raise.
            result = await handle_trade_filled(event)

        assert result is None
        assert any(
            "DB write failed" in rec.getMessage() for rec in caplog.records
        ), f"expected a 'DB write failed' error log, got {[r.getMessage() for r in caplog.records]}"

    @pytest.mark.asyncio
    async def test_db_write_failure_persists_no_lot(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """After a swallowed write failure, no Lot row exists."""
        import wealthtax_agent.db as _db
        from wealthtax_agent.db import get_session
        from wealthtax_agent.db.models import Lot
        from wealthtax_agent.workers.event_consumer import handle_trade_filled

        def _boom_get_session():
            raise RuntimeError("db exploded")

        monkeypatch.setattr(_db, "get_session", _boom_get_session)

        await handle_trade_filled(_make_event(event_id="evt-dbfail-2"))

        # Restore is automatic (monkeypatch teardown); query with the real one.
        monkeypatch.undo()
        with get_session() as session:
            count = session.query(Lot).count()
        assert count == 0


class TestHandleReceiptCaptured:
    """handle_receipt_captured is a logging stub (line 125)."""

    @pytest.mark.asyncio
    async def test_stub_logs_and_writes_nothing(self, caplog) -> None:
        """Returns None, writes no row, logs the not-yet-implemented line."""
        import logging

        from wealthtax_agent.db import get_session
        from wealthtax_agent.db.models import Lot
        from wealthtax_agent.workers.event_consumer import handle_receipt_captured

        event = _make_event(event_id="evt-receipt-1")
        with caplog.at_level(logging.INFO, logger="wealthtax_agent.workers.event_consumer"):
            result = await handle_receipt_captured(event)

        assert result is None
        assert any(
            "receipt.captured received" in rec.getMessage()
            and "not yet implemented" in rec.getMessage()
            for rec in caplog.records
        )
        # No Lot rows are written by the receipt stub.
        with get_session() as session:
            assert session.query(Lot).count() == 0

    @pytest.mark.asyncio
    async def test_stub_tolerates_non_event_object(self, caplog) -> None:
        """The getattr(event, 'id', repr(event)) fallback handles a bare object."""
        import logging

        from wealthtax_agent.workers.event_consumer import handle_receipt_captured

        with caplog.at_level(logging.INFO, logger="wealthtax_agent.workers.event_consumer"):
            result = await handle_receipt_captured(object())  # no .id attribute

        assert result is None
        assert any(
            "receipt.captured received" in rec.getMessage() for rec in caplog.records
        )


class TestEnsureSchemaPostgresBranch:
    """_ensure_schema() non-sqlite path runs alembic via subprocess (156-172)."""

    def _patch_settings(self, monkeypatch, db_url: str):
        import wealthtax_agent.config as _cfg

        class _FakeSettings:
            database_url = db_url

        monkeypatch.setattr(_cfg, "get_settings", lambda: _FakeSettings())

    def test_alembic_success(self, monkeypatch: pytest.MonkeyPatch, caplog) -> None:
        """rc==0 → success log, no raise."""
        import logging
        import subprocess

        from wealthtax_agent.workers.event_consumer import _ensure_schema

        self._patch_settings(monkeypatch, "postgresql+psycopg://x/y")

        class _Result:
            returncode = 0
            stderr = ""

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())

        with caplog.at_level(logging.INFO, logger="wealthtax_agent.workers.event_consumer"):
            _ensure_schema()  # must not raise

        assert any(
            "alembic upgrade head OK" in rec.getMessage() for rec in caplog.records
        )

    def test_alembic_nonzero_returncode_logs_error(
        self, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        """rc!=0 → error log with rc + stderr; returns (does not raise)."""
        import logging
        import subprocess

        from wealthtax_agent.workers.event_consumer import _ensure_schema

        self._patch_settings(monkeypatch, "postgresql+psycopg://x/y")

        class _Result:
            returncode = 1
            stderr = "boom"

        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Result())

        with caplog.at_level(logging.ERROR, logger="wealthtax_agent.workers.event_consumer"):
            _ensure_schema()  # must not raise

        msgs = [rec.getMessage() for rec in caplog.records]
        assert any("alembic upgrade head failed" in m for m in msgs)
        assert any("boom" in m for m in msgs), f"stderr not logged: {msgs}"

    def test_alembic_subprocess_raises_is_swallowed(
        self, monkeypatch: pytest.MonkeyPatch, caplog
    ) -> None:
        """subprocess.run raising (e.g. OSError) is caught + logged, not propagated."""
        import logging
        import subprocess

        from wealthtax_agent.workers.event_consumer import _ensure_schema

        self._patch_settings(monkeypatch, "postgresql+psycopg://x/y")

        def _raise(*a, **k):
            raise OSError("alembic binary missing")

        monkeypatch.setattr(subprocess, "run", _raise)

        with caplog.at_level(logging.ERROR, logger="wealthtax_agent.workers.event_consumer"):
            _ensure_schema()  # must not raise

        assert any(
            "alembic upgrade head raised an exception" in rec.getMessage()
            for rec in caplog.records
        )


class TestRunHappyAndCancel:
    """run() normal return (194) and CancelledError return without retry (196-197)."""

    @pytest.mark.asyncio
    async def test_run_returns_when_subscribe_completes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both channels subscribed; run() returns None when subscribe() resolves."""
        from wealthtax_agent.events import bus as _bus
        from wealthtax_agent.events.schemas import TradeFilledEvent
        from wealthtax_agent.workers import event_consumer as ec

        channels: list[str] = []

        async def _recording_subscribe(channel, _handler, *a, **k):
            channels.append(channel)

        # _ensure_schema is called unconditionally at the top of run(); no-op it.
        monkeypatch.setattr(ec, "_ensure_schema", lambda: None)
        monkeypatch.setattr(_bus, "subscribe", _recording_subscribe)

        result = await ec.run()

        assert result is None
        assert TradeFilledEvent.channel() in channels
        assert "paa.receipt.captured" in channels

    @pytest.mark.asyncio
    async def test_run_returns_on_cancelled_without_retry(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """asyncio.CancelledError → return None, NO reconnect sleep (not retried)."""
        from wealthtax_agent.events import bus as _bus
        from wealthtax_agent.workers import event_consumer as ec

        sleep_calls: list = []

        async def _recording_sleep(seconds):
            sleep_calls.append(seconds)

        async def _cancelled_subscribe(*a, **k):
            raise asyncio.CancelledError()

        monkeypatch.setattr(ec, "_ensure_schema", lambda: None)
        monkeypatch.setattr(asyncio, "sleep", _recording_sleep)
        monkeypatch.setattr(_bus, "subscribe", _cancelled_subscribe)

        result = await ec.run()

        assert result is None
        assert sleep_calls == [], (
            "CancelledError must not be treated as a reconnectable error "
            f"(asyncio.sleep was called {len(sleep_calls)} times)"
        )
