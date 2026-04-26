# Deployment Modes

Docker Compose is the recommended and supported deployment path. It handles all services and their dependencies with a single command.

## Docker Compose (recommended)

Runs `api`, `bot`, `mcp`, and `postgres` as containers on a shared network. Works on any Linux machine with Docker installed.

<!-- TODO: Fill in with full compose reference. -->

## systemd (without Docker)

Running services directly on the host as systemd units is possible but not the primary supported path. Unit files are in `systemd/` in the repo.

<!-- TODO: Decide whether to document or deprecate. -->
