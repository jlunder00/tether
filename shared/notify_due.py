"""Redis next-due gating for notification checks (anchors/followups).

Purpose
-------
`_run_notification_check` (api/routes/internal.py) and the polling-loop
inline block (bot/message_handler.py `run_polling`) both need to answer
"is there any real notification work due for this user right now?" without
paying a Postgres round-trip to find out — otherwise every invocation
(regardless of caller frequency) keeps managed Postgres (Neon) awake even
when the app is completely idle.

This module caches, per user, the earliest time at which either of two
TIME-based components next becomes due:

  - ``anchor``   — next anchor-schedule boundary (start/end of a time block)
  - ``followup`` — next pre/post-ack followup ping

Each component is written independently (``set_component_due``) by whichever
code just computed a fresh estimate for it. This means a single Redis query
(``get_due_user_ids``) — done by the cron-style entry point — sees a user
as due if ANY one component says so, regardless of which side wrote it.

Meeting events are NOT modeled as a component here, and never have been
written by any caller. They're PUSH-based (delivered via an in-process
WS-listener queue owned by tether-premium's
``tether_premium.bot.scheduling.events``, at unpredictable times) rather
than time-based, so there's no meaningful "next_due timestamp" to
precompute for them — they don't fit this module's timestamp-gating model.
``drain_meeting_events`` already self-gates for free (it checks its queue
is non-empty before ever touching Postgres) and is deliberately called
UNCONDITIONALLY by ``run_polling``, exempt from the ``is_due()`` gate here
— see the call site in bot/message_handler.py for the reasoning. If meeting
events ever need cross-process draining (e.g. the event queue moving to a
shared backing store), that redesign should introduce its own mechanism
rather than reusing this module's timestamp model.

Redis layout
------------
- ``notify:due:{user_id}`` — HASH, fields are component names, values are
  Unix timestamps (float, as strings). This is the durable per-component
  record.
- ``notify:due_queue`` — ZSET, member=user_id, score=min() of that user's
  known component values. This is the only thing the cheap "who's due"
  query touches — an O(log N) range scan, no per-user Postgres reads.

Fail-open philosophy
---------------------
Redis is a cache, not a source of truth — the real due-ness is always
whatever Postgres/application state says. If Redis is unavailable (no
``REDIS_URL``, connection error) or a user has never been cached before
(cold start, new link, post-flush), every read here fails OPEN: treat the
user as due. This guarantees gating can only ever save a round-trip it
would otherwise have made — it can never *cause* a real notification to
be skipped. Writes fail silently (logged) for the same reason: a dropped
cache write just means "we'll re-check sooner than strictly necessary,"
never "we silently stopped checking."

``get_due_user_ids`` distinguishes "Redis unavailable" (returns ``None`` —
caller should fall back to the old unfiltered behaviour) from "Redis
available, confirmed nothing due" (returns ``[]``) — these must not be
conflated, or callers could never safely skip work.
"""
from __future__ import annotations

import logging
import os
import time as _time
from datetime import datetime, timedelta
from typing import Any, Literal

logger = logging.getLogger(__name__)

_DUE_QUEUE_KEY = "notify:due_queue"
_DUE_HASH_PREFIX = "notify:due"
_ANCHORS_KEY_PREFIX = "notify:anchors"

# Set once this process has logged that REDIS_URL is unconfigured, so the
# warning fires once (at ERROR — this is a config problem, not a transient
# blip) instead of spamming on every gated call (e.g. every ~30s polling
# tick). See _warn_no_redis_configured_once() and log_startup_status().
_logged_no_redis_configured = False

# Safety-net TTL on per-user cache entries. If a code path ever fails to
# recompute-after-run (a bug), the entry eventually expires and reads fall
# back to the "unknown user" fail-open path rather than staying wrong forever.
_SAFETY_TTL_SECONDS = 24 * 3600

Component = Literal["anchor", "followup"]


def get_redis_url() -> str | None:
    """Return REDIS_URL from environment, or None if unset."""
    return os.environ.get("REDIS_URL") or None


def _due_hash_key(user_id: str) -> str:
    return f"{_DUE_HASH_PREFIX}:{user_id}"


def anchors_cache_key(user_id: str) -> str:
    """Redis key for a user's cached anchor schedule (used by callers that
    refresh the anchor cache on anchor CRUD)."""
    return f"{_ANCHORS_KEY_PREFIX}:{user_id}"


def _warn_no_redis_configured_once() -> None:
    """Log, once per process, that REDIS_URL is unconfigured.

    This fires only for the "genuinely no REDIS_URL in this process's
    environment" case (not test overrides via redis_client/server, and not
    real Redis errors — those keep their own per-occurrence logging).
    ERROR level and one-shot: this is exactly the class of bug that shipped
    silently in PR #468 (bot process missing REDIS_URL in supervisord.conf,
    fixed in PR #470) — a config gap, not a transient blip, and a per-tick
    WARNING spam was easy to miss/ignore in logs.
    """
    global _logged_no_redis_configured
    if _logged_no_redis_configured:
        return
    _logged_no_redis_configured = True
    logger.error(
        "notify_due: REDIS_URL not set in this process — Neon idle-spin-down "
        "gating fails open (always 'due') for every check made from here. "
        "If this process calls shared.notify_due (currently: api, bot), the "
        "gating fix is silently doing nothing in this process — check "
        "supervisord.conf's [program:*] environment= line for REDIS_URL."
    )


def log_startup_status() -> None:
    """Log this process's notify_due/Redis configuration once, at startup.

    Call this once during process startup (e.g. api's lifespan, bot's
    main()) — it's the single check that would have made the missing
    REDIS_URL on [program:bot] (see PR #470) immediately obvious in logs
    instead of silently inert gating discovered only via later investigation.
    """
    if get_redis_url():
        logger.info(
            "notify_due: REDIS_URL configured — Neon idle-spin-down gating active"
        )
    else:
        _warn_no_redis_configured_once()


_client_cache: dict[str, Any] = {}


async def _get_client(
    redis_client: Any = None,
    redis_url: str | None = None,
    server: Any = None,
) -> Any:
    """Build (or reuse) an async Redis client. Returns None if unavailable.

    Real (URL-based) clients are cached module-level, keyed by URL, so
    repeated gated calls (e.g. every ~30s polling tick) reuse one
    redis.asyncio client/connection pool instead of constructing a new one
    on every call. Test-injection paths (``redis_client=...`` or
    ``server=...``) are deliberately NOT cached — each call still returns
    the caller-provided client or a fresh ``FakeRedis`` wrapper, exactly as
    before, so test isolation is unaffected.
    """
    if redis_client is not None:
        return redis_client
    if server is not None:
        import fakeredis.aioredis as faioredis

        return faioredis.FakeRedis(server=server)
    url = redis_url or get_redis_url()
    if url is None:
        _warn_no_redis_configured_once()
        return None
    cached = _client_cache.get(url)
    if cached is not None:
        return cached
    import redis.asyncio as aioredis

    client = aioredis.from_url(url)
    _client_cache[url] = client
    return client


async def set_component_due(
    user_id: str,
    component: Component,
    next_ts: float,
    *,
    redis_client: Any = None,
    redis_url: str | None = None,
    server: Any = None,
) -> None:
    """Record *component*'s next-due timestamp for *user_id*.

    Recomputes the combined ``due_queue`` score as the min of all known
    components for this user, so the user is surfaced as due as soon as
    ANY single component says so.

    Best-effort: any Redis error (including "not configured") is logged and
    swallowed — a dropped cache write never blocks or breaks the caller.
    """
    client = await _get_client(redis_client, redis_url, server)
    if client is None:
        # _get_client already logged the (once-per-process) "not configured"
        # ERROR — no per-call log here to avoid ~30s-tick spam.
        return
    try:
        hkey = _due_hash_key(user_id)
        await client.hset(hkey, component, repr(next_ts))
        await client.expire(hkey, _SAFETY_TTL_SECONDS)
        raw = await client.hgetall(hkey)
        values = [float(v) for v in raw.values()]
        combined = min(values) if values else next_ts
        await client.zadd(_DUE_QUEUE_KEY, {user_id: combined})
    except Exception:
        logger.warning(
            "notify_due.set_component_due: Redis error — failing open "
            "(user_id=%s component=%s)",
            user_id, component, exc_info=True,
        )


async def get_due_user_ids(
    now: float | None = None,
    *,
    redis_client: Any = None,
    redis_url: str | None = None,
    server: Any = None,
) -> list[str] | None:
    """Return user_ids whose combined next-due score is <= *now*.

    Returns ``None`` (the fail-open sentinel) if Redis is unavailable or
    errors — callers MUST treat that distinctly from an empty list: ``None``
    means "gating unavailable, fall back to the real unfiltered check";
    ``[]`` means "gating confirms nothing is due right now."
    """
    if now is None:
        now = _time.time()
    client = await _get_client(redis_client, redis_url, server)
    if client is None:
        # _get_client already logged the (once-per-process) "not configured"
        # ERROR — no per-call log here to avoid spam on every cron tick.
        return None
    try:
        members = await client.zrangebyscore(_DUE_QUEUE_KEY, "-inf", now)
        return [
            m.decode() if isinstance(m, (bytes, bytearray)) else m
            for m in members
        ]
    except Exception:
        logger.warning(
            "notify_due.get_due_user_ids: Redis error — failing open",
            exc_info=True,
        )
        return None


async def is_due(
    user_id: str,
    now: float | None = None,
    *,
    redis_client: Any = None,
    redis_url: str | None = None,
    server: Any = None,
) -> bool:
    """Cheap single-user due check — used by the polling-loop path.

    Fails open to True: an unknown user (cold start / new link), a Redis
    error, or Redis being unconfigured all resolve to "due," never to
    "skip." This mirrors ``get_due_user_ids``'s fail-open contract but
    collapses "unavailable" and "unknown" to the same True result since a
    single-user caller has no useful fallback distinction to make.
    """
    if now is None:
        now = _time.time()
    client = await _get_client(redis_client, redis_url, server)
    if client is None:
        return True
    try:
        score = await client.zscore(_DUE_QUEUE_KEY, user_id)
        if score is None:
            return True  # never cached — fail open
        return float(score) <= now
    except Exception:
        logger.warning(
            "notify_due.is_due: Redis error — failing open (user_id=%s)",
            user_id, exc_info=True,
        )
        return True


# ---------------------------------------------------------------------------
# Anchor schedule cache (JSON list) + pure next-boundary computation
# ---------------------------------------------------------------------------

async def set_cached_anchors(
    user_id: str,
    anchors: list[dict],
    *,
    redis_client: Any = None,
    redis_url: str | None = None,
    server: Any = None,
) -> None:
    """Refresh the cached anchor schedule for *user_id*.

    Called on anchor create/update/delete (rare, synchronous) and
    opportunistically whenever a real anchor-transition check fetches
    anchors from Postgres anyway (zero extra cost — self-healing cache).
    """
    import json

    client = await _get_client(redis_client, redis_url, server)
    if client is None:
        # _get_client already logged the (once-per-process) "not configured"
        # ERROR — no per-call log here to avoid spam.
        return
    try:
        await client.set(
            anchors_cache_key(user_id), json.dumps(anchors), ex=_SAFETY_TTL_SECONDS
        )
    except Exception:
        logger.warning(
            "notify_due.set_cached_anchors: Redis error — failing open "
            "(user_id=%s)", user_id, exc_info=True,
        )


async def get_cached_anchors(
    user_id: str,
    *,
    redis_client: Any = None,
    redis_url: str | None = None,
    server: Any = None,
) -> list[dict] | None:
    """Return the cached anchor schedule for *user_id*, or None on a cache
    miss / Redis error (caller should fall back to a real Postgres fetch,
    which should then call ``set_cached_anchors`` to repopulate)."""
    import json

    client = await _get_client(redis_client, redis_url, server)
    if client is None:
        return None
    try:
        raw = await client.get(anchors_cache_key(user_id))
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        logger.warning(
            "notify_due.get_cached_anchors: Redis error — treating as cache miss "
            "(user_id=%s)", user_id, exc_info=True,
        )
        return None


def next_anchor_boundary(anchors: list[dict], now: datetime) -> datetime | None:
    """Return the next time an anchor's active window starts or ends, strictly
    after *now*. Pure function of (schedule, now) — no I/O.

    Returns None if there are no anchors at all (nothing to ever wake up
    for on the anchor side — the followup component still governs).

    This recurs daily by construction: candidate boundaries are always
    "the next occurrence of this time-of-day, today or tomorrow," so no
    explicit midnight-rollover handling is needed.
    """
    if not anchors:
        return None

    candidates: list[datetime] = []
    for anchor in anchors:
        try:
            h, m = map(int, anchor["time"].split(":"))
            duration = anchor.get("duration_minutes", 0)
        except (KeyError, ValueError, AttributeError, TypeError):
            # A malformed anchor row (bad/missing "time") must not crash the
            # whole computation for every other anchor — skip it. This keeps
            # `next_anchor_boundary` a safe pure function callers can rely on
            # even against imperfect data, rather than requiring every call
            # site to defend against it individually.
            logger.warning(
                "notify_due.next_anchor_boundary: skipping malformed anchor row: %r",
                anchor,
            )
            continue
        for day_offset in (0, 1):
            day = (now + timedelta(days=day_offset)).date()
            start = datetime(day.year, day.month, day.day, h, m)
            end = start + timedelta(minutes=duration)
            if start > now:
                candidates.append(start)
            if end > now:
                candidates.append(end)

    if not candidates:
        return None
    return min(candidates)
