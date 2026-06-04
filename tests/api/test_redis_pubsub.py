"""Tests for api.redis_pubsub — cross-process event delivery via Redis.

Covers:
- subscribe_and_forward: forwards Redis channel messages to a WS client
- subscribe_and_forward: cancels cleanly on asyncio.CancelledError
- subscribe_and_forward: swallows WS send failures (disconnected client)
- No-op behaviour when REDIS_URL is not configured (tested via WSPublisher
  having no redis_client — covered in test_ws_publisher.py)
"""
from __future__ import annotations

import asyncio
import json

import fakeredis
import fakeredis.aioredis as faioredis
import pytest

pytestmark = pytest.mark.timeout(60)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeWS:
    """Minimal WS stub — captures sent JSON frames."""

    def __init__(self):
        self.sent: list[dict] = []
        self._fail_on_send = False

    async def send_json(self, data: dict) -> None:
        if self._fail_on_send:
            raise RuntimeError("WS disconnected")
        self.sent.append(data)


# ---------------------------------------------------------------------------
# subscribe_and_forward
# ---------------------------------------------------------------------------

async def test_subscribe_and_forward_delivers_event_to_ws():
    """Events published to user:{id}:events must arrive at the WS client."""
    from api.redis_pubsub import subscribe_and_forward

    server = fakeredis.FakeServer()
    publisher = faioredis.FakeRedis(server=server)
    ws = _FakeWS()
    user_id = "user-sub-test"

    # Start subscription task
    task = asyncio.create_task(
        subscribe_and_forward(ws, user_id, server=server)
    )
    await asyncio.sleep(0)  # let the task start and subscribe

    event = {"type": "trial_usage_update", "remaining": 4}
    await publisher.publish(f"user:{user_id}:events", json.dumps(event))

    # Give the subscription task time to receive and forward
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises((asyncio.CancelledError, Exception)):
        await task

    assert event in ws.sent, f"WS must receive the published event, got: {ws.sent}"
    await publisher.aclose()


async def test_subscribe_and_forward_cancels_cleanly():
    """CancelledError must propagate cleanly — no hanging tasks or exceptions."""
    from api.redis_pubsub import subscribe_and_forward

    server = fakeredis.FakeServer()
    ws = _FakeWS()

    task = asyncio.create_task(
        subscribe_and_forward(ws, "user-cancel", server=server)
    )
    await asyncio.sleep(0)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass  # expected


async def test_subscribe_and_forward_swallows_ws_send_failures():
    """WS send failures must not crash the subscriber task."""
    from api.redis_pubsub import subscribe_and_forward

    server = fakeredis.FakeServer()
    publisher = faioredis.FakeRedis(server=server)
    ws = _FakeWS()
    ws._fail_on_send = True  # simulate disconnected client
    user_id = "user-fail"

    task = asyncio.create_task(
        subscribe_and_forward(ws, user_id, server=server)
    )
    await asyncio.sleep(0)

    await publisher.publish(f"user:{user_id}:events", json.dumps({"type": "x"}))
    await asyncio.sleep(0.05)

    # Task must still be running (not crashed by WS failure)
    assert not task.done(), "subscriber task must survive WS send failures"

    task.cancel()
    with pytest.raises((asyncio.CancelledError, Exception)):
        await task

    await publisher.aclose()


async def test_subscribe_and_forward_multiple_events_in_order():
    """Multiple events must arrive at the WS in publish order."""
    from api.redis_pubsub import subscribe_and_forward

    server = fakeredis.FakeServer()
    publisher = faioredis.FakeRedis(server=server)
    ws = _FakeWS()
    user_id = "user-order"

    task = asyncio.create_task(
        subscribe_and_forward(ws, user_id, server=server)
    )
    await asyncio.sleep(0)

    events = [
        {"type": "status", "message": "one"},
        {"type": "status", "message": "two"},
        {"type": "turn_complete", "final_text": "done"},
    ]
    for ev in events:
        await publisher.publish(f"user:{user_id}:events", json.dumps(ev))

    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises((asyncio.CancelledError, Exception)):
        await task

    assert ws.sent == events, f"events must arrive in order, got: {ws.sent}"
    await publisher.aclose()
