"""Async Redis pub/sub bus helper.

Usage (publisher):
    from infra.events.bus import publish
    from infra.events.schemas import TradeFilledEvent, TradeFilledPayload

    event = TradeFilledEvent(payload=TradeFilledPayload(...))
    await publish(event)

Usage (subscriber):
    from infra.events.bus import subscribe
    from infra.events.schemas import TradeFilledEvent

    async def handle(event: TradeFilledEvent) -> None:
        ...

    await subscribe(TradeFilledEvent.channel(), handle)

Both functions respect the REDIS_URL and EVENT_BUS_ENABLED env vars.
If EVENT_BUS_ENABLED != "true", publish() is a no-op and subscribe() returns
immediately — no Redis connection is attempted.

Idle resilience
---------------
``subscribe()`` reads with ``pubsub.get_message(timeout=...)`` rather than the
blocking ``pubsub.listen()`` async-generator. On a low-traffic / idle channel
``get_message`` simply returns ``None`` when no message arrives inside the
timeout window — an idle window is NOT an error. A read that surfaces a Redis
``TimeoutError`` (socket read timeout on a quiet connection) is likewise
treated as a benign idle tick and the subscription stays alive. Only genuine
connection failures (``ConnectionError`` and friends) propagate, so the
consumer's reconnect/back-off loop can do its job. This is what stops the
``infra-wealth-consumer-1`` crash-loop where idle PAPER channels were treated
as fatal.

The Redis client is built with TCP keepalive and a periodic health check so a
genuinely dead connection is detected and surfaced (as a ConnectionError),
while idle connections are kept warm instead of timing out.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Awaitable, Callable

import redis.asyncio as aioredis
from redis.exceptions import TimeoutError as RedisTimeoutError

from .schemas import BaseEvent, EVENT_REGISTRY

log = logging.getLogger(__name__)

_REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
_ENABLED = os.environ.get("EVENT_BUS_ENABLED", "false").lower() == "true"


def _opt_float(name: str) -> float | None:
    raw = os.environ.get(name)
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _opt_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


# Blocking-read socket timeout. Default None => a quiet/idle connection never
# raises a socket read timeout. Operators can still set REDIS_SOCKET_TIMEOUT,
# but get_message() below tolerates a timeout regardless.
_SOCKET_TIMEOUT = _opt_float("REDIS_SOCKET_TIMEOUT")
# Seconds redis-py waits between PINGs on an idle connection to keep it healthy
# (and to detect a dead one). Must be > 0 to enable.
_HEALTH_CHECK_INTERVAL = _opt_int("REDIS_HEALTH_CHECK_INTERVAL", 30)
# How long a single get_message() blocks before returning None on an idle
# channel. Small enough to react promptly, large enough to avoid busy-spin.
_GET_MESSAGE_TIMEOUT = _opt_float("REDIS_GET_MESSAGE_TIMEOUT") or 1.0


def _client_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "decode_responses": True,
        "socket_keepalive": True,
        "health_check_interval": _HEALTH_CHECK_INTERVAL,
    }
    if _SOCKET_TIMEOUT is not None:
        kwargs["socket_timeout"] = _SOCKET_TIMEOUT
    return kwargs


def _get_client() -> aioredis.Redis:
    return aioredis.from_url(_REDIS_URL, **_client_kwargs())


async def publish(event: BaseEvent) -> None:
    """Publish an event to its canonical channel.

    Fire-and-forget: logs WARN on error, never raises.
    No-op when EVENT_BUS_ENABLED != 'true'.
    """
    if not _ENABLED:
        log.debug("event bus disabled — skipping publish of %s", event.id)
        return

    channel = type(event).channel()
    try:
        raw = event.to_json_bytes().decode()
        async with _get_client() as client:
            await client.publish(channel, raw)
        log.debug("published %s id=%s to %s", event.type, event.id, channel)
    except Exception:
        log.warning("event bus publish failed for %s id=%s", event.type, event.id, exc_info=True)


async def subscribe(
    channel: str,
    handler: Callable[[BaseEvent], Awaitable[None]],
    *,
    stop_after: int | None = None,
) -> None:
    """Subscribe to *channel* and dispatch deserialized events to *handler*.

    Runs until the task is cancelled (or *stop_after* messages for testing).
    No-op when EVENT_BUS_ENABLED != 'true'.

    The handler is called with a typed event object resolved from EVENT_REGISTRY.
    Unknown event types are logged and skipped.
    Exceptions in handler are caught and logged; the loop continues.

    Idle channels are tolerated: ``get_message`` returns ``None`` (and a benign
    Redis ``TimeoutError`` is swallowed) instead of killing the subscription.
    Genuine connection failures propagate so the caller can reconnect.
    """
    if not _ENABLED:
        log.debug("event bus disabled — skipping subscribe on %s", channel)
        return

    client = _get_client()
    pubsub = client.pubsub()
    await pubsub.subscribe(channel)
    log.info("subscribed to channel %s", channel)

    count = 0
    try:
        while True:
            try:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=False,
                    timeout=_GET_MESSAGE_TIMEOUT,
                )
            except (RedisTimeoutError, TimeoutError):
                # Idle low-traffic channel: a socket read timeout here is
                # NORMAL, not fatal. Keep the subscription alive instead of
                # bubbling up and bouncing the whole consumer process.
                log.debug("idle read timeout on %s — continuing", channel)
                continue

            if message is None:
                continue  # no message within the timeout window — idle tick
            if message.get("type") != "message":
                continue
            # A real message frame was consumed — count it (used only by
            # stop_after in tests) regardless of whether it dispatches cleanly.
            count += 1
            try:
                data: dict[str, Any] = json.loads(message["data"])
                event_class = EVENT_REGISTRY.get(channel)
                if event_class is None:
                    log.warning("no schema registered for channel %s — skipping", channel)
                else:
                    event = event_class.model_validate(data)
                    await handler(event)
            except Exception:
                log.error("error handling message on %s", channel, exc_info=True)
            if stop_after is not None and count >= stop_after:
                break
    finally:
        await pubsub.unsubscribe(channel)
        await client.aclose()
