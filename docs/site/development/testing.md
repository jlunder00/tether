# Testing

## Running tests

```bash
# All tests
pytest -v

# Single file
pytest tests/bot/test_handler_utils.py -v

# Database tests (requires DATABASE_URL)
DATABASE_URL=postgresql://tether_app:tether_app_dev@localhost:5432/tether pytest tests/db/ -v

# Skip database tests
pytest -v --ignore=tests/db
```

## Test layout

Tests mirror the source layout:

```
tests/
  api/        REST endpoint tests
  bot/        Pipeline and message handler tests
  db/         PostgreSQL query and RLS tests
  mcp/        MCP tool tests
```

## pytest configuration

- `asyncio_mode = auto` — all async test functions are automatically treated as async tests
- Fixtures in `tests/conftest.py` provide database connections, mock Telegram senders, and test app clients

## Database tests

DB tests require a running PostgreSQL instance. The connection is controlled by the `DATABASE_URL` environment variable. In CI, a temporary test database is spun up via Docker.

```bash
# Start a test database
docker compose up -d postgres

# Run with the test database
DATABASE_URL=postgresql://tether_app:tether_app_dev@localhost:5432/tether pytest tests/db/ -v
```

RLS (row-level security) tests verify that users can only access their own data. These tests connect as the `tether_app` role (non-superuser) to ensure RLS policies are active.

## Writing tests

- Follow existing patterns in the relevant `tests/` subdirectory
- Use `AsyncMock` for async dependencies
- DB tests should clean up after themselves — use transactions that roll back, or explicit teardown
- Prompt changes are high-impact — test with real messages (integration test path) before merging
