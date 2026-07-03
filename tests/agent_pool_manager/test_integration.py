"""Integration tests — skipped unless a real claude binary is available."""
from __future__ import annotations

import shutil
import pytest

# Skip entire module if claude binary absent
pytestmark = pytest.mark.skipif(
    shutil.which("claude") is None,
    reason="claude binary not found — integration tests require a real Claude install",
)
pytest_mark_integration = pytest.mark.integration


@pytest.mark.integration
@pytest.mark.asyncio
async def test_real_subprocess_acquire_query_release():
    """Spawn a real ClaudeSDKClient, prime it, run a simple query, release."""
    from agent_pool_manager.config import AgentPoolConfig
    from agent_pool_manager.pool import Pool

    cfg = AgentPoolConfig(
        target_depth_per_hash=1,
        capacity_total=2,
        max_age_seconds=300,
        refill_poll_interval=1.0,
        prime_timeout_seconds=60,
        acquire_default_timeout=30,
    )
    pool = Pool(cfg)
    options_hash = "integration-test-hash"
    options = {"env": {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-integration-test-token"}}

    await pool._inject_warm(options_hash, options)
    handle_id, meta = await pool.acquire(options_hash, options, timeout=30.0)
    assert handle_id is not None

    # Run one real query
    sub = pool._active[handle_id]
    await sub.proc.query("Say 'ok' and nothing else.")
    responses = []
    async for msg in sub.proc.receive_response():
        responses.append(msg)

    await pool.release(handle_id, reusable=False)
    assert len(responses) > 0
