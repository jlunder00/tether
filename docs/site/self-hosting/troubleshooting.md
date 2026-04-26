# Troubleshooting

## The app starts but no one can log in

**Symptom:** Web UI loads, but login fails or sessions expire immediately.

**Likely cause:** `TETHER_JWT_SECRET` is not set, so Tether is using the insecure default (`dev-secret-change-in-production`). All tokens signed with this default will not be trusted in a production configuration.

**Fix:** Set a strong random secret. See [Secrets Reference](./secrets-reference).

---

## Database errors on startup

**Symptom:** `api` or `bot` container fails with `role "tether_app" does not exist` or permission errors on queries.

**Cause:** The `tether_app` PostgreSQL role has not been created. This role is required for row-level security to work correctly — the application must not connect as the superuser.

**Fix:** Run the following once inside the postgres container:

```bash
docker exec -it tether-postgres psql -U tether -d tether
```

```sql
CREATE ROLE tether_app WITH LOGIN PASSWORD 'your-strong-password';
GRANT CONNECT ON DATABASE tether TO tether_app;
GRANT USAGE ON SCHEMA public TO tether_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO tether_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO tether_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO tether_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO tether_app;
```

Then set `TETHER_APP_PASSWORD` in your config to match the password you used.

---

## MCP tools return no data

**Symptom:** Claude Code can connect to the MCP server but all reads return empty results.

**Likely cause:** `TETHER_USER_ID` is not set, so MCP queries run with no user scope.

**Fix:** Set `TETHER_USER_ID` to your Tether user ID in the MCP service config. <!-- TODO: explain how to find user ID once auth docs are written -->

---

## `crypto.randomUUID` error in the browser

**Symptom:** The web app throws a `TypeError: crypto.randomUUID is not a function` in certain browsers or when accessing over HTTP.

**Cause:** `crypto.randomUUID()` requires a [secure context](https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts) (HTTPS or localhost). Accessing Tether over a plain HTTP LAN address (e.g. a Tailscale IP) triggers this.

**Fix:** Access Tether over HTTPS, or use `localhost` for local development. For Tailscale setups, use the machine's `*.ts.net` hostname with HTTPS enabled.

---

## Something else?

<!-- TODO: Add more common issues as they're reported. Link to GitHub Issues for things not covered here. -->
