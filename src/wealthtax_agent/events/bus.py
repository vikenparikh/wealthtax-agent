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
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Awaitable, Callable

import redis.asyncio as aioredis

from .schemas import BaseEvent, EVENT_REGISTRY

log = logging.getLogger(__name__)

_REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379")
_ENABLED = os.environ.get("EVENT_BUS_ENABLED", "false").lower() == "true"


def _get_client() -> aioredis.Redis:
    return aioredis.from_url(_REDIS_URL, decode_responses=True)


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
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
            try:
                data: dict[str, Any] = json.loads(message["data"])
                event_class = EVENT_REGISTRY.get(channel)
                if event_class is None:
                    log.warning("no schema registered for channel %s — skipping", channel)
                    continue
                event = event_class.model_validate(data)
                await handler(event)
            except Exception:
                log.error("error handling message on %s", channel, exc_info=True)
            count += 1
            if stop_after is not None and count >= stop_after:
                break
    finally:
        await pubsub.unsubscribe(channel)
        await client.aclose()
