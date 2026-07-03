"""Tests for WSPublisher."""
from __future__ import annotations

import asyncio

import fakeredis
import pytest
from interactive_agent_layer.ws_publisher import WSPublisher


@pytest.fixture
def publisher():
    return WSPublisher()


async def test_subscribe_returns_queue(publisher):
    q = publisher.subscribe("user1")
    assert isinstance(q, asyncio.Queue)


async def test_push_delivers_to_subscriber(publisher):
    q = publisher.subscribe("user1")
    event = {"type": "test", "data": "hello"}
    await publisher.push("user1", event)
    received = q.get_nowait()
    assert received == event


async def test_push_fan_out_to_multiple_subscribers(publisher):
    q1 = publisher.subscribe("user1")
    q2 = publisher.subscribe("user1")
    event = {"type": "broadcast"}
    await publisher.push("user1", event)
    assert q1.get_nowait() == event
    assert q2.get_nowait() == event


async def test_push_does_not_deliver_to_other_user(publisher):
    q_user1 = publisher.subscribe("user1")
    publisher.subscribe("user2")  # different user
    await publisher.push("user1", {"type": "private"})
    # user1's queue has the event
    assert not q_user1.empty()
    # user2's queue remains empty — no delivery across user channels
    q_user2 = publisher.subscribe("user2")
    assert q_user2.empty()


async def test_unsubscribe_removes_queue(publisher):
    q = publisher.subscribe("user1")
    publisher.unsubscribe("user1", q)
    await publisher.push("user1", {"type": "after-unsub"})
    assert q.empty()


async def test_unsubscribe_unknown_queue_noop(publisher):
    q = asyncio.Queue()
    publisher.unsubscribe("no-such-user", q)  # should not raise


async def test_push_no_subscribers_noop(publisher):
    # No subscriber registered — should not raise
    await publisher.push("nobody", {"type": "ignored"})


async def test_two_sessions_same_user_share_channel(publisher):
    """Contract #6: two sessions for same user_ws_id share one event channel."""
    q = publisher.subscribe("shared-ws-id")
    await publisher.push("shared-ws-id", {"session_id": "s1", "type": "delta"})
    await publisher.push("shared-ws-id", {"session_id": "s2", "type": "delta"})
    e1 = q.get_nowait()
    e2 = q.get_nowait()
    assert e1["session_id"] == "s1"
    assert e2["session_id"] == "s2"


# ---------------------------------------------------------------------------
# Redis dual-write
# ---------------------------------------------------------------------------

async def test_push_also_publishes_to_redis_when_client_set():
    """When a Redis client is provided, push() must publish to user:{id}:events channel."""
    import json
    import fakeredis.aioredis as faioredis

    server = fakeredis.FakeServer()
    fake_client = faioredis.FakeRedis(server=server)
    subscriber = faioredis.FakeRedis(server=server)

    pub = WSPublisher(redis_client=fake_client)
    ps = subscriber.pubsub()
    await ps.subscribe("user:user99:events")
    # Drain the subscribe-confirmation message
    async for msg in ps.listen():
        if msg["type"] == "subscribe":
            break

    event = {"type": "trial_usage_update", "remaining": 7}
    await pub.push("user99", event)

    # Give the message a moment to arrive
    received = None
    async for msg in ps.listen():
        if msg["type"] == "message":
            received = json.loads(msg["data"])
            break

    assert received == event, f"Redis must receive the published event, got: {received}"

    await ps.aclose()
    await subscriber.aclose()
    await fake_client.aclose()


async def test_push_in_process_still_works_without_redis():
    """Without a Redis client, push() delivers only to in-process queues (unchanged)."""
    pub = WSPublisher()  # no redis_client
    q = pub.subscribe("userA")
    await pub.push("userA", {"type": "ping"})
    assert q.get_nowait() == {"type": "ping"}


async def test_push_suppresses_redis_errors():
    """Redis publish failures must not prevent in-process delivery."""
    import fakeredis.aioredis as faioredis

    bad_client = faioredis.FakeRedis()
    await bad_client.aclose()  # close it so any publish raises

    pub = WSPublisher(redis_client=bad_client)
    q = pub.subscribe("userB")
    # Should not raise despite broken Redis client
    await pub.push("userB", {"type": "test"})
    assert q.get_nowait() == {"type": "test"}
