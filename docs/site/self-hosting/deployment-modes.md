# Deployment Modes

Tether supports two deployment modes. The right choice depends on your setup:

| Mode | Best for | Config file |
|------|----------|-------------|
| **Docker Compose** | Most users, easiest to manage | `tether/.env` + `~/.tether-config/` |
| **systemd (direct)** | Advanced Pi setups, no Docker | `~/.tether-config/env` |

## Docker Compose (recommended)

Docker Compose is the standard deployment path. It manages all four services — `api`, `bot`, `mcp`, and `postgres` — as containers with a shared network.

<!-- TODO: Fill in after config-loader-redesign lands. The new `make install` flow simplifies this significantly. -->

## systemd (direct on Pi)

Running services directly on the Pi without Docker. Each service (`tether-api`, `tether-bot`, `tether-mcp`) runs as a systemd unit with an `EnvironmentFile` pointing to `~/.tether-config/env`.

<!-- TODO: Fill in after config-loader-redesign lands. Document the updated systemd unit files and env var sourcing. -->

::: warning Config file split
The Docker Compose path and the systemd path use **different config files** — they don't share the same env file. See [Secrets Reference](./secrets-reference) for the full mapping.
:::
