"""Agent pool core — Pool class, Subprocess dataclass, lifecycle management."""
from __future__ import annotations

import asyncio
import dataclasses
import datetime
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from claude_agent_sdk import ClaudeSDKClient
from claude_agent_sdk.types import (
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    ResultMessage,
)

from .config import AgentPoolConfig
from .control import ControlBridge, ControlTimeout
from .homes import HomeDirPool

if TYPE_CHECKING:
    from pathlib import Path
    from .metrics import PoolMetrics

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Diagnostic helpers — sensitive value redaction.
#
# The warm spawn path runs in production with the user's OAuth token in env.
# We need visibility into what's actually being passed to the subprocess,
# but must never log the raw token.  ``_redact_env`` shows the key names
# and a short prefix of each value (8 chars) so we can confirm shape without
# leaking secrets.
# ---------------------------------------------------------------------------

_SENSITIVE_ENV_KEYS = frozenset({
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "TETHER_JWT_SECRET",
    "VAULT_KEY",
})


def _redact_env(env: dict | None) -> dict:
    """Return a redacted copy of an env dict — sensitive values become ``<len=N prefix=XXX...>``.

    Non-sensitive values are passed through unchanged.  Used in diagnostic
    logs so the env composition is visible without leaking secrets.
    """
    if not env:
        return {}
    out: dict[str, str] = {}
    for k, v in env.items():
        sval = str(v) if v is not None else ""
        if k in _SENSITIVE_ENV_KEYS:
            prefix = sval[:8] if len(sval) >= 8 else sval
            out[k] = f"<len={len(sval)} prefix={prefix!r}>"
        else:
            out[k] = sval
    return out


def _mcp_servers_form(mcp_servers: Any) -> str:
    """Return a short string describing the form of an mcp_servers value.

    The Claude SDK accepts ``dict[str, McpServerConfig] | str | Path`` but
    we historically pass a ``list[str]`` from ``_V2_0_OPTIONS``.  The list
    form falls through to ``str(value)`` in the SDK, which is suspected
    to be a contributor to the 15 s warm-spawn hang.
    """
    if mcp_servers is None:
        return "None"
    if isinstance(mcp_servers, dict):
        return f"dict(keys={list(mcp_servers.keys())})"
    if isinstance(mcp_servers, list):
        return f"list({mcp_servers!r})"
    if isinstance(mcp_servers, (str, bytes)):
        return f"str(len={len(mcp_servers)})"
    return f"other(type={type(mcp_servers).__name__})"


def _options_summary(options: dict[str, Any]) -> dict:
    """Return a compact, redacted summary of the options dict for logging.

    Keys whose values are large or sensitive are summarised rather than
    dumped in full — this keeps log lines readable in fly.io's log stream.
    """
    return {
        "model": options.get("model"),
        "allowed_tools_count": len(options.get("allowed_tools", []) or []),
        "max_turns": options.get("max_turns"),
        "permission_mode": options.get("permission_mode"),
        "mcp_servers_form": _mcp_servers_form(options.get("mcp_servers")),
        "env_keys": sorted((options.get("env") or {}).keys()),
        "env_redacted": _redact_env(options.get("env")),
        "extra_keys": sorted(
            k for k in options.keys()
            if k not in {"model", "allowed_tools", "max_turns", "permission_mode",
                          "mcp_servers", "env"}
        ),
    }


# MCP server URL for the tether MCP service (supervisord, port 5001).
_MCP_TETHER_URL = "http://localhost:5001/sse"


def _expand_mcp_placeholders(options: dict[str, Any], mcp_key: str) -> dict[str, Any]:
    """Expand the ``['tether']`` MCP placeholder into a real SSE config dict.

    The static ``_V2_0_OPTIONS`` in ``bot.agent_dispatch`` carries
    ``mcp_servers=['tether']`` as a stable hash-stable placeholder.  The SDK
    expects ``dict[str, McpServerConfig]``; passing a list causes it to fall
    through to ``str(value)`` which produces ``--mcp-config "['tether']"`` on
    the CLI — an unparseable value that causes a 15 s connect hang.

    This function is called at ``_spawn_and_prime`` time (not at options-dict
    creation time) so the hash computed from the placeholder stays stable
    across the warm endpoint and dispatch_v2_0 callers.

    Returns a shallow-copied options dict with ``mcp_servers`` replaced.
    Does NOT mutate the input dict.
    """
    mcp_servers = options.get("mcp_servers")
    if not (isinstance(mcp_servers, list) and "tether" in mcp_servers):
        return options  # already correct form or absent — no copy needed

    result = dict(options)
    result["mcp_servers"] = {
        "tether": {
            "type": "sse",
            "url": _MCP_TETHER_URL,
            "headers": {"Authorization": f"Bearer {mcp_key}"},
        }
    }
    return result


class PoolExhausted(Exception):
    """Raised when no warm subprocess becomes available within the timeout."""


@dataclass
class _CallbackContext:
    """Mutable handle-id slot shared between Subprocess and its can_use_tool callback.

    The callback is set at ClaudeSDKClient construction (before a handle_id
    exists); the pool fills in ``handle_id`` at acquire() time so the bridge
    request carries the correct identifier.
    """
    handle_id: str = ""


def _extract_pid(client: ClaudeSDKClient) -> int | None:
    """Best-effort PID extraction from the SDK client's transport."""
    try:
        transport = client._transport
        proc = getattr(transport, "_process", None) if transport is not None else None
        return proc.pid if proc is not None else None
    except Exception:
        return None


@dataclass
class Subprocess:
    """Tracks one ClaudeSDKClient instance and its metadata."""

    proc: ClaudeSDKClient
    options_hash: str
    options: dict[str, Any]
    spawned_at: float = field(default_factory=time.monotonic)
    primed_at: float = field(default_factory=time.monotonic)
    last_used_at: float = field(default_factory=time.monotonic)
    in_use: bool = False
    callback_ctx: _CallbackContext = field(default_factory=_CallbackContext)
    # Ephemeral MCP api_key created at spawn time; revoked on _terminate.
    # None when pool has no DB access or no user_id was available at spawn.
    mcp_key_id: str | None = None
    mcp_user_id: str | None = None
    # Isolated home directory assigned at spawn time; released on _terminate.
    # None when home pool is not configured.
    home_path: "Path | None" = None

    def is_expired(self, max_age_seconds: int) -> bool:
        return (time.monotonic() - self.spawned_at) > max_age_seconds


class Pool:
    """In-memory pool of warm ClaudeSDKClient subprocesses.

    Partitioned by ``options_hash``.  TTL draining happens on acquire
    (drain-on-touch), not via a background timer.
    """

    def __init__(self, config: AgentPoolConfig, *, pg_pool: Any = None) -> None:
        self.config = config
        # warm queue per options_hash
        self._warm: dict[str, asyncio.Queue[Subprocess]] = {}
        # active (handed-out) subprocesses keyed by handle_id
        self._active: dict[str, Subprocess] = {}
        # count of currently-spawning tasks per options_hash
        self._warming: dict[str, int] = {}
        # cached options payload per options_hash (for refill)
        self._options_cache: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        # shared bridge for all control-protocol forwarding
        self.control_bridge = ControlBridge(
            timeout_seconds=config.control_response_timeout_seconds
        )
        # optional metrics instance — attach via pool._metrics = metrics
        self._metrics: "PoolMetrics | None" = None
        # optional asyncpg pool for ephemeral MCP key creation/revocation
        self._pg_pool: Any = pg_pool
        # optional home directory pool — set via initialize_home_pool()
        self._home_pool: HomeDirPool | None = None

    async def initialize_home_pool(self) -> None:
        """Create and seed the home directory pool.

        Must be called once before _spawn_and_prime if home isolation is
        desired.  Safe to call multiple times (idempotent).
        """
        if self._home_pool is None:
            self._home_pool = HomeDirPool(self.config)
        await self._home_pool.initialize()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def acquire(
        self,
        options_hash: str,
        options: dict[str, Any],
        timeout: float | None = None,
        user_id: str | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Hand out a warm subprocess for the given options_hash.

        Blocks until one is available or ``timeout`` seconds elapses.
        Drains expired entries before returning.

        Returns ``(handle_id, metadata)`` where metadata contains
        ``subprocess_pid`` and ``ready_at``.

        Raises :exc:`PoolExhausted` if timeout is exceeded.
        """
        if timeout is None:
            timeout = self.config.acquire_default_timeout

        t_start = time.monotonic()
        self._options_cache[options_hash] = options
        deadline = t_start + timeout
        queue = self._get_or_create_queue(options_hash)

        exhausted = PoolExhausted(
            f"No warm subprocess for hash {options_hash!r} within {timeout}s"
        )
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise exhausted

                try:
                    sub = queue.get_nowait()
                except asyncio.QueueEmpty:
                    # Wait for a warm item to appear, then re-check the deadline.
                    try:
                        sub = await asyncio.wait_for(queue.get(), timeout=min(remaining, 0.1))
                    except asyncio.TimeoutError:
                        continue

                # Drain expired entries
                if sub.is_expired(self.config.max_age_seconds):
                    latency_ms = (time.monotonic() - t_start) * 1000
                    log.info(
                        "pool.expire options_hash=%s user_id=%s age_s=%.1f latency_ms=%.1f",
                        options_hash, user_id,
                        time.monotonic() - sub.spawned_at, latency_ms,
                    )
                    if self._metrics:
                        self._metrics.expire_total.inc()
                    asyncio.create_task(self._terminate(sub))
                    continue

                # User isolation: the warm queue is keyed by options_hash, which is
                # intentionally computed from the static placeholder so the hash
                # stays stable across users.  But each subprocess now carries an
                # ephemeral MCP Bearer token minted for the user that triggered its
                # warm spawn.  A subprocess spawned for user A must not serve user B.
                # If there is a user mismatch, terminate and try the next entry.
                if (
                    sub.mcp_user_id is not None
                    and user_id is not None
                    and sub.mcp_user_id != user_id
                ):
                    log.info(
                        "pool.user_mismatch options_hash=%s sub_user=%s req_user=%s"
                        " — discarding subprocess to prevent cross-user MCP key leak",
                        options_hash, sub.mcp_user_id, user_id,
                    )
                    asyncio.create_task(self._terminate(sub))
                    continue

                # Hand it out
                handle_id = str(uuid.uuid4())
                sub.in_use = True
                sub.last_used_at = time.monotonic()
                sub.callback_ctx.handle_id = handle_id
                async with self._lock:
                    self._active[handle_id] = sub

                latency_s = time.monotonic() - t_start
                latency_ms = latency_s * 1000
                log.info(
                    "pool.acquire handle_id=%s user_id=%s options_hash=%s latency_ms=%.1f",
                    handle_id, user_id, options_hash, latency_ms,
                )
                if self._metrics:
                    self._metrics.acquire_total.inc()
                    self._metrics.acquire_latency_seconds.observe(latency_s)

                meta = {
                    "subprocess_pid": _extract_pid(sub.proc),
                    "ready_at": datetime.datetime.utcnow().isoformat() + "Z",
                }
                return handle_id, meta

        except PoolExhausted:
            latency_ms = (time.monotonic() - t_start) * 1000
            log.info(
                "pool.acquire_timeout options_hash=%s user_id=%s timeout_s=%.2f latency_ms=%.1f",
                options_hash, user_id, timeout, latency_ms,
            )
            if self._metrics:
                self._metrics.acquire_timeout_total.inc()
            raise

    async def release(self, handle_id: str, reusable: bool = False) -> None:
        """Release a handle.

        ``reusable=True`` → return subprocess to warm queue (caller asserts
        no sensitive history).  ``reusable=False`` (default) → terminate.
        """
        async with self._lock:
            sub = self._active.pop(handle_id, None)
        if sub is None:
            return

        sub.in_use = False
        sub.last_used_at = time.monotonic()

        log.info(
            "pool.release handle_id=%s options_hash=%s reusable=%s",
            handle_id, sub.options_hash, reusable,
        )
        if self._metrics:
            self._metrics.release_total.inc()

        if reusable and not sub.is_expired(self.config.max_age_seconds):
            queue = self._get_or_create_queue(sub.options_hash)
            await queue.put(sub)
            log.debug("Subprocess returned to warm queue for hash %s", sub.options_hash)
        else:
            await self._terminate(sub)

    async def interrupt(self, handle_id: str) -> None:
        """Send an interrupt to the active subprocess for the given handle."""
        async with self._lock:
            sub = self._active.get(handle_id)
        if sub is None:
            raise KeyError(f"No active handle {handle_id!r}")
        await sub.proc.interrupt()

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def warm_count(self, options_hash: str) -> int:
        """Current warm queue depth for this options_hash."""
        q = self._warm.get(options_hash)
        return q.qsize() if q else 0

    def active_count(self) -> int:
        return len(self._active)

    def warming_count(self, options_hash: str | None = None) -> int:
        if options_hash is not None:
            return self._warming.get(options_hash, 0)
        return sum(self._warming.values())

    def total_count(self) -> int:
        """Total subprocesses: warm + active + warming."""
        warm = sum(q.qsize() for q in self._warm.values())
        return warm + self.active_count() + self.warming_count()

    def status(self) -> dict[str, Any]:
        """Pool-wide status snapshot."""
        partitions: dict[str, dict[str, int]] = {
            h: {"warm": q.qsize(), "warming": self._warming.get(h, 0)}
            for h, q in self._warm.items()
        }
        for sub in self._active.values():
            slot = partitions.setdefault(sub.options_hash, {"warm": 0, "warming": 0})
            slot["active"] = slot.get("active", 0) + 1

        return {
            "partitions": partitions,
            "total_warm": sum(p["warm"] for p in partitions.values()),
            "total_active": self.active_count(),
            "total_warming": self.warming_count(),
            "capacity_total": self.config.capacity_total,
        }

    # ------------------------------------------------------------------
    # Internal helpers — also used by RefillLoop and tests
    # ------------------------------------------------------------------

    async def _inject_warm(
        self,
        options_hash: str,
        options: dict[str, Any],
        *,
        user_id: str | None = None,
    ) -> None:
        """Spawn, prime, and push one subprocess to the warm queue.

        Used directly by RefillLoop and by tests via FakeClient patch.
        Silently no-ops at capacity.
        """
        if not await self._try_inject_warm(options_hash, options, user_id=user_id):
            log.debug("Capacity full — skipping inject for hash %s", options_hash)

    async def _try_inject_warm(
        self,
        options_hash: str,
        options: dict[str, Any],
        *,
        user_id: str | None = None,
    ) -> bool:
        """Attempt to spawn-and-prime one subprocess.

        Returns True if spawned, False if at capacity or if the spawn guard fires.

        Spawn guard: if options['env'] does not contain CLAUDE_CODE_OAUTH_TOKEN,
        the spawn is rejected with a WARNING.  Subprocesses launched without OAuth
        credentials time out after connect_timeout_seconds (15 s) with no useful
        output, waste pool capacity, and leave asyncio "Task exception was never
        retrieved" errors in the logs.  The guard fires before the warming counter
        is incremented, so rejected attempts do not count against capacity.

        All known spawn paths (RefillLoop.hint, RefillLoop.run_once, _inject_warm)
        converge here, so this single check covers the entire spawn surface.
        """
        log.info(
            "pool.inject_warm_entry options_hash=%s warm=%d active=%d warming=%d capacity=%d",
            options_hash,
            self.warm_count(options_hash),
            len(self._active),
            self.warming_count(options_hash),
            self.config.capacity_total,
        )

        token = (options.get("env") or {}).get("CLAUDE_CODE_OAUTH_TOKEN")
        if not token:
            log.warning(
                "pool.spawn_guard: options_hash=%s missing CLAUDE_CODE_OAUTH_TOKEN in env"
                " — skipping spawn to prevent auth-timeout waste",
                options_hash,
            )
            if self._metrics:
                self._metrics.spawn_guard_rejection_total.inc()
            return False

        async with self._lock:
            if self.total_count() >= self.config.capacity_total:
                log.info(
                    "pool.inject_warm_capacity_full options_hash=%s total=%d capacity=%d",
                    options_hash, self.total_count(), self.config.capacity_total,
                )
                return False
            self._warming[options_hash] = self._warming.get(options_hash, 0) + 1

        try:
            sub = await self._spawn_and_prime(options_hash, options, user_id=user_id)
        finally:
            async with self._lock:
                self._warming[options_hash] = max(
                    0, self._warming.get(options_hash, 1) - 1
                )

        queue = self._get_or_create_queue(options_hash)
        await queue.put(sub)
        self._options_cache[options_hash] = options
        log.info("pool.refill options_hash=%s warm_depth=%d", options_hash, queue.qsize())
        if self._metrics:
            self._metrics.refill_total.inc()
        return True

    async def _spawn_and_prime(
        self,
        options_hash: str,
        options: dict[str, Any],
        *,
        user_id: str | None = None,
    ) -> Subprocess:
        """Spawn a ClaudeSDKClient, connect, and send the priming prompt.

        Diagnostic logging: this method is the prime suspect for the 15 s
        warm-spawn hang in prod.  We log:

          * The options summary (redacted) before constructing sdk_options
          * Timing checkpoints around ``client.connect()`` and priming
          * The full exception details on connect failure (type, message,
            time spent, subprocess PID if any)
          * Subprocess stderr lines piped via the SDK's ``stderr`` callback,
            so the CLI's own error output is visible in fly.io logs

        Without these, ``connect()`` can hang for 15 s with no observable
        cause from the application side.
        """
        log.info(
            "pool.spawn_start options_hash=%s summary=%r",
            options_hash,
            _options_summary(options),
        )

        ctx = _CallbackContext()

        # Ephemeral MCP key injection — expand ['tether'] placeholder into a
        # real SSE config dict with a per-spawn Bearer token.  The key is
        # created here (not at options-dict creation time) so the options hash
        # computed from the placeholder stays stable across warm-endpoint and
        # dispatch_v2_0 callers.
        mcp_key_id: str | None = None
        if self._pg_pool is not None and user_id:  # truthy: excludes None and ""
            try:
                import db.postgres as pg
                from db.pg_queries.api_keys import create_key as _create_key
                async with pg.get_conn(self._pg_pool, user_id=user_id) as _conn:
                    _raw_key, _key_rec = await _create_key(
                        _conn, user_id=user_id, name=f"pool_mcp_{options_hash[:8]}"
                    )
                mcp_key_id = _key_rec["id"]
                options = _expand_mcp_placeholders(options, _raw_key)
                log.info(
                    "pool.mcp_key_created options_hash=%s key_id=%s",
                    options_hash, mcp_key_id,
                )
            except Exception:
                log.warning(
                    "pool.mcp_key_create_failed options_hash=%s"
                    " — spawning without MCP auth injection",
                    options_hash,
                    exc_info=True,
                )
                # Strip the ['tether'] placeholder so the subprocess doesn't hang
                # waiting for a tether MCP server it cannot authenticate with.
                # An empty dict tells the SDK "no MCP servers" — clean start.
                options = dict(options)
                options["mcp_servers"] = {}

        # Inject initialize timeout — tells the SDK how long to wait before
        # treating a connect() call as failed.  Use setdefault so a caller-
        # supplied value is not overridden.
        env = dict(options.get("env") or {})
        env.setdefault(
            "CLAUDE_CODE_STREAM_CLOSE_TIMEOUT",
            str(self.config.initialize_timeout_ms),
        )
        options = dict(options)
        options["env"] = env

        # Assign an isolated home directory if the home pool is available.
        # This eliminates ~/.claude.json file-lock contention when multiple
        # subprocesses spawn simultaneously.
        home_path: "Path | None" = None
        if self._home_pool is not None:
            try:
                home_path = await asyncio.wait_for(
                    self._home_pool.acquire(),
                    timeout=self.config.connect_timeout_seconds,
                )
            except asyncio.TimeoutError:
                log.warning(
                    "pool.home_acquire_timeout options_hash=%s timeout_s=%.1f"
                    " — spawning without isolated home dir",
                    options_hash,
                    self.config.connect_timeout_seconds,
                )
            if home_path is not None:
                env = dict(options["env"])
                env["HOME"] = str(home_path)
                options["env"] = env

        # Wire subprocess stderr to our logger so CLI errors surface in
        # fly.io's log stream.  Without this, stderr is dropped on the floor.
        def _stderr_cb(line: str) -> None:
            log.info(
                "pool.subprocess_stderr options_hash=%s line=%s",
                options_hash, line.rstrip(),
            )

        options_with_stderr = dict(options)
        # Don't overwrite a caller-supplied stderr callback.
        options_with_stderr.setdefault("stderr", _stderr_cb)

        # Turn on the CLI's debug-to-stderr mode so the SDK protocol traces
        # also flow through our stderr callback.  Without this we only see
        # whatever the CLI writes to stderr on its own (which is typically
        # nothing on a successful run and very little even on errors).
        # This is the single most useful flag for diagnosing a connect() hang.
        existing_extra = dict(options_with_stderr.get("extra_args") or {})
        existing_extra.setdefault("debug-to-stderr", None)
        options_with_stderr["extra_args"] = existing_extra

        sdk_options = self._build_sdk_options(
            options_with_stderr,
            can_use_tool=self._make_forwarding_callback(ctx),
        )
        client = ClaudeSDKClient(options=sdk_options)

        # If we created an ephemeral MCP key and the spawn fails (connect
        # timeout, OAuth failure, prime error, etc.) the Subprocess dataclass
        # is never constructed so _terminate is never called.  Guard here to
        # ensure the key is revoked on any failure after creation.
        try:
            t_connect_start = time.monotonic()
            try:
                await asyncio.wait_for(
                    client.connect(),
                    timeout=self.config.connect_timeout_seconds,
                )
            except Exception as exc:
                elapsed = time.monotonic() - t_connect_start
                pid = _extract_pid(client)
                log.warning(
                    "pool.connect_failed options_hash=%s exc_type=%s msg=%s"
                    " elapsed_s=%.2f pid=%s timeout_s=%.1f",
                    options_hash,
                    type(exc).__name__,
                    str(exc) or "<no message>",
                    elapsed,
                    pid,
                    self.config.connect_timeout_seconds,
                )
                # Kill the underlying subprocess so a failed spawn doesn't leave a
                # zombie Claude CLI process holding memory until the OS cleans it up.
                # This covers both auth failures (70 s timeout) and other errors.
                try:
                    transport = getattr(client, "_transport", None)
                    proc = getattr(transport, "_process", None) if transport is not None else None
                    if proc is not None:
                        proc.kill()
                        # asyncio.subprocess.Process.wait() is a coroutine; a
                        # synchronous subprocess.Popen.wait() is not.  Guard against
                        # the sync case so a future SDK transport change doesn't
                        # silently suppress the TypeError and leave zombies.
                        if asyncio.iscoroutinefunction(getattr(proc, "wait", None)):
                            await proc.wait()
                        else:
                            log.warning(
                                "pool.cleanup: proc.wait() is not a coroutine for hash=%s"
                                " — skipping await; subprocess may remain as zombie",
                                options_hash,
                            )
                except Exception:
                    pass
                raise

            connect_elapsed = time.monotonic() - t_connect_start
            log.info(
                "pool.connect_done options_hash=%s elapsed_s=%.2f pid=%s",
                options_hash, connect_elapsed, _extract_pid(client),
            )

            # Prime: send a cheap prompt so the subprocess pays its init cost now
            t_prime_start = time.monotonic()
            try:
                await asyncio.wait_for(
                    self._do_prime(client),
                    timeout=self.config.prime_timeout_seconds,
                )
                log.info(
                    "pool.prime_done options_hash=%s elapsed_s=%.2f",
                    options_hash, time.monotonic() - t_prime_start,
                )
            except asyncio.TimeoutError:
                log.warning(
                    "pool.prime_timeout options_hash=%s elapsed_s=%.2f timeout_s=%d"
                    " — keeping unprimed client",
                    options_hash,
                    time.monotonic() - t_prime_start,
                    self.config.prime_timeout_seconds,
                )

        except Exception:
            # Spawn failed after key was created — revoke key to prevent orphan rows.
            if mcp_key_id is not None and self._pg_pool is not None and user_id:
                try:
                    import db.postgres as pg
                    from db.pg_queries.api_keys import revoke_key as _revoke_key
                    async with pg.get_conn(self._pg_pool, user_id=user_id) as _conn:
                        await _revoke_key(_conn, mcp_key_id, user_id)
                    log.info(
                        "pool.mcp_key_revoked_on_spawn_failure options_hash=%s key_id=%s",
                        options_hash, mcp_key_id,
                    )
                except Exception:
                    log.warning(
                        "pool.mcp_key_revoke_on_spawn_failure_failed key_id=%s",
                        mcp_key_id,
                        exc_info=True,
                    )
            if home_path is not None and self._home_pool is not None:
                self._home_pool.release(home_path)
            raise

        now = time.monotonic()
        return Subprocess(
            proc=client,
            options_hash=options_hash,
            options=options,
            spawned_at=now,
            primed_at=now,
            callback_ctx=ctx,
            mcp_key_id=mcp_key_id,
            mcp_user_id=user_id,
            home_path=home_path,
        )

    @staticmethod
    async def _do_prime(client: ClaudeSDKClient) -> None:
        """Send the priming prompt and drain the response."""
        await client.query("respond with only 'ready'")
        async for msg in client.receive_response():
            if isinstance(msg, ResultMessage):
                break

    def _make_forwarding_callback(self, ctx: _CallbackContext):
        """Return a can_use_tool callback that forwards decisions over the bridge.

        The callback is bound to ``ctx`` — a mutable context whose ``handle_id``
        is filled in at acquire() time.  On timeout the callback returns a deny
        result (fail-closed).
        """
        bridge = self.control_bridge

        async def _callback(tool_name: str, tool_input: dict[str, Any], _context: Any):
            try:
                response = await bridge.request(
                    ctx.handle_id,
                    "can_use_tool",
                    {"tool_name": tool_name, "tool_input": tool_input},
                )
            except ControlTimeout:
                log.warning(
                    "can_use_tool timed out for handle=%s tool=%s — denying",
                    ctx.handle_id, tool_name,
                )
                return PermissionResultDeny(message="control_response timeout")

            if response.get("decision") == "allow":
                return PermissionResultAllow()
            return PermissionResultDeny(
                message=response.get("denial_message", "denied by caller")
            )

        return _callback

    @staticmethod
    def _build_sdk_options(
        options: dict[str, Any],
        can_use_tool: Any = None,
    ) -> ClaudeAgentOptions:
        """Convert the options dict to ClaudeAgentOptions, ignoring unknown keys.

        Diagnostic logging: emit which keys were passed through to the SDK
        and which were filtered out.  This helps explain unexpected SDK
        behaviour when callers pass dict-shaped options that don't map 1:1
        to ``ClaudeAgentOptions`` fields.

        Field enumeration uses ``dataclasses.fields()``, NOT ``dir()`` —
        ``dir()`` on a dataclass class omits fields declared with
        ``default_factory`` (env, mcp_servers, allowed_tools, extra_args,
        plugins, add_dirs, betas, disallowed_tools).  Using ``dir()`` here
        silently dropped the user's OAuth token from the subprocess env,
        which was the root cause of the 15 s warm-spawn timeout in prod.
        """
        known = {f.name for f in dataclasses.fields(ClaudeAgentOptions)}
        filtered = {k: v for k, v in options.items() if k in known}
        dropped = sorted(k for k in options.keys() if k not in known)
        if can_use_tool is not None:
            filtered["can_use_tool"] = can_use_tool

        log.info(
            "pool.sdk_options known_keys=%s dropped_keys=%s mcp_servers_form=%s",
            sorted(filtered.keys()),
            dropped,
            _mcp_servers_form(filtered.get("mcp_servers")),
        )
        return ClaudeAgentOptions(**filtered)

    def _get_or_create_queue(self, options_hash: str) -> asyncio.Queue[Subprocess]:
        if options_hash not in self._warm:
            self._warm[options_hash] = asyncio.Queue()
        return self._warm[options_hash]

    async def _terminate(self, sub: Subprocess) -> None:
        # Disconnect first — this guarantees no further MCP calls will be made
        # by the subprocess before we invalidate its credential.  Revoking
        # before disconnect would leave a window where in-flight MCP requests
        # receive 401 responses.
        try:
            await sub.proc.disconnect()
        except Exception:
            pass

        # Revoke ephemeral MCP key after the subprocess is disconnected.
        # Failure must not propagate — log and continue.
        if sub.mcp_key_id is not None and self._pg_pool is not None and sub.mcp_user_id:
            try:
                import db.postgres as pg
                from db.pg_queries.api_keys import revoke_key as _revoke_key
                async with pg.get_conn(self._pg_pool, user_id=sub.mcp_user_id) as _conn:
                    await _revoke_key(_conn, sub.mcp_key_id, sub.mcp_user_id)
                log.info(
                    "pool.mcp_key_revoked options_hash=%s key_id=%s",
                    sub.options_hash, sub.mcp_key_id,
                )
            except Exception:
                log.warning(
                    "pool.mcp_key_revoke_failed key_id=%s",
                    sub.mcp_key_id,
                    exc_info=True,
                )

        # Return the isolated home directory to the pool.
        if sub.home_path is not None and self._home_pool is not None:
            self._home_pool.release(sub.home_path)
