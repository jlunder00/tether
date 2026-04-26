# Contributing

## Prerequisites

- Python 3.11+
- Node.js 20+ (for frontend)
- Docker and Docker Compose (for running PostgreSQL locally)
- A Claude Code login (`claude login`)

## Local setup

```bash
# Clone the repo
git clone https://github.com/jlunder00/tether.git
cd tether

# Install Python dependencies (editable, with dev deps)
pip install -e ".[dev]"

# Start the database
docker compose up -d postgres

# Run database migrations
alembic upgrade head

# Start the API server
uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# Start the frontend (separate terminal)
cd frontend && npm install && npm run dev
```

## Branch strategy

| Branch | Purpose |
|--------|---------|
| `main` | Production — auto-deploys via GitHub Actions |
| `feature/*` | New features — branch from main, PR back to main |
| `fix/*` | Bug fixes — same flow |

**Never push directly to `main`.** All changes go through a pull request.

## Commit conventions

Short, imperative present tense: `add calendar drag-to-create`, `fix uuid secure context guard`, `update MCP tool parameter docs`.

No automated tooling enforces a specific format — just be descriptive and keep it under 72 characters for the subject line.

## Pull request checklist

- [ ] Tests pass: `pytest -v`
- [ ] Frontend typechecks: `cd frontend && npm run typecheck`
- [ ] New behavior is covered by tests
- [ ] ACCOUNTING.md updated if a feature status changed
- [ ] No hardcoded secrets or credentials

## CI

GitHub Actions runs tests and the frontend build on every PR and deploys to `main` on merge.
