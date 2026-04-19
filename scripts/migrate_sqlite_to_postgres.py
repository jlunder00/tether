#!/usr/bin/env python3
"""One-time migration: SQLite (auth.db + per-user .db files) → Postgres.

Usage:
    python scripts/migrate_sqlite_to_postgres.py [--dry-run]

Options:
    --dry-run   Print row counts without writing to Postgres.

Prerequisites:
    DATABASE_URL env var pointing to Postgres with superuser or pg_bypassrls
    privilege (required — see C1 fix note).
    TETHER_CONFIG_DIR env var (default: ~/.tether-config).

Idempotency:
    Most tables use ON CONFLICT DO NOTHING and are safe to re-run.
    Exception: conversation_history, orchestrator_conversation, invocation_log,
    and state_monitor_log have no natural unique key. These tables are skipped
    per-user if the user already has rows in Postgres (safe re-run behavior).
    To force a full re-migration, truncate those tables first.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import uuid as _uuid
from pathlib import Path
from typing import Any

import asyncpg
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.postgres import register_jsonb_codec


# ── Config ────────────────────────────────────────────────────────────────────

CONFIG_DIR = Path(os.environ.get("TETHER_CONFIG_DIR", Path.home() / ".tether-config"))
AUTH_DB = CONFIG_DIR / "auth.db"
USERS_DIR = CONFIG_DIR / "users"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _open_sqlite(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _parse_json(val: str | None, *, context: str = "") -> dict | list | None:
    if val is None:
        return None
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError) as e:
        ctx = f" ({context})" if context else ""
        raise ValueError(f"Malformed JSON{ctx}: {e!r} — value: {val[:120]!r}") from e


def _to_bool(val: Any) -> bool:
    return bool(val)


def _parse_dt(val: str | None) -> datetime | None:
    """Parse SQLite ISO timestamp string → UTC-aware datetime for asyncpg."""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(val).replace(" ", "T")).replace(tzinfo=timezone.utc)


def _topo_sort_nodes(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    """Return context_node rows in topological order (parents before children).

    Raises ValueError if a cycle is detected in parent_id references.
    Nodes referencing a parent not in rows are included without their parent.
    """
    by_id = {r["id"]: r for r in rows}
    result: list[sqlite3.Row] = []
    visited: set[str] = set()
    in_progress: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visited:
            return
        if node_id in in_progress:
            raise ValueError(
                f"Cycle detected in context_nodes at id={node_id!r}. "
                "Fix the SQLite data before migrating."
            )
        row = by_id.get(node_id)
        if row is None:
            return
        in_progress.add(node_id)
        parent_id = row["parent_id"]
        if parent_id and parent_id not in visited:
            visit(parent_id)
        in_progress.discard(node_id)
        if node_id not in visited:
            result.append(row)
            visited.add(node_id)

    for row in rows:
        visit(row["id"])
    return result


def _safe_fetch_table(sq: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    """Fetch all rows from a SQLite table, returning [] if the table doesn't exist."""
    try:
        return sq.execute(f"SELECT * FROM {table}").fetchall()
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            print(f"  INFO: {table} not found in SQLite schema (old DB), skipping")
            return []
        raise


# ── Dry-run counting ──────────────────────────────────────────────────────────

async def dry_run_report() -> None:
    if not AUTH_DB.exists():
        print(f"ERROR: auth.db not found at {AUTH_DB}")
        sys.exit(1)

    auth = _open_sqlite(AUTH_DB)
    print("=== Auth DB ===")
    for table in ("users", "oauth_connections", "invite_tokens",
                  "telegram_connections", "telegram_link_codes"):
        try:
            count = auth.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        except sqlite3.OperationalError:
            count = "MISSING"
        print(f"  {table}: {count}")

    users = auth.execute("SELECT id, username FROM users").fetchall()
    print(f"\n=== Per-user DBs ({len(users)} users) ===")

    per_user_tables = [
        "anchors", "plans", "tasks", "task_dependencies", "dependencies",
        "subtasks", "links", "context_entries", "task_context", "milestones",
        "milestone_tasks", "followup_state", "acknowledgements", "check_ins",
        "edit_history", "conversation_history", "staging_mutations",
        "orchestrator_conversation", "invocation_log", "state_monitor_log",
        "beacon_state", "kanban_columns", "user_settings", "context_nodes",
        "node_sections", "node_tasks", "sessions",
    ]

    totals: dict[str, int] = {t: 0 for t in per_user_tables}
    for user in users:
        db_path = USERS_DIR / f"{user['id']}.db"
        if not db_path.exists():
            print(f"  {user['username']} ({user['id']}): NO DB FILE")
            continue
        uconn = _open_sqlite(db_path)
        print(f"\n  {user['username']} ({user['id']}):")
        for table in per_user_tables:
            try:
                count = uconn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                totals[table] += count
            except sqlite3.OperationalError:
                count = "-"
            print(f"    {table}: {count}")

    print("\n=== Totals ===")
    for t, c in totals.items():
        print(f"  {t}: {c}")

    # Postgres connectivity check
    database_url = os.environ.get("DATABASE_URL")
    print("\n=== Postgres Connectivity ===")
    if not database_url:
        print("  DATABASE_URL not set — skipping Postgres check")
    else:
        try:
            pg_conn = await asyncpg.connect(dsn=database_url)
            version = await pg_conn.fetchval("SELECT version()")
            try:
                await pg_conn.execute("SET row_security = off")
                rls_ok = "OK (superuser/pg_bypassrls)"
            except Exception:
                rls_ok = "FAILED — will abort on actual migration"
            tables = await pg_conn.fetch(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            )
            await pg_conn.close()
            print(f"  Connected: {version[:50]}")
            print(f"  SET row_security = off: {rls_ok}")
            print(f"  Tables in schema: {len(tables)}")
        except Exception as e:
            print(f"  Connection FAILED: {e}")


# ── Main migration ────────────────────────────────────────────────────────────

async def migrate(dry_run: bool = False) -> None:
    if dry_run:
        await dry_run_report()
        return

    if not AUTH_DB.exists():
        print(f"ERROR: auth.db not found at {AUTH_DB}")
        sys.exit(1)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)

    conn = await asyncpg.connect(dsn=database_url)
    await register_jsonb_codec(conn)
    # Bypass RLS for the migration session (requires superuser or pg_bypassrls role).
    # The Postgres schema uses FOR ALL policies with no WITH CHECK clause — Postgres
    # implicitly uses USING as WITH CHECK, so INSERT fails without RLS bypass.
    try:
        await conn.execute("SET row_security = off")
    except asyncpg.InsufficientPrivilegeError:
        print("FATAL: cannot SET row_security = off — requires superuser or pg_bypassrls role.")
        print("  Fix: re-run with superuser DATABASE_URL, or:")
        print("  GRANT pg_bypassrls TO <migration_user>;")
        await conn.close()
        sys.exit(1)

    # SQLite timestamps are naive UTC strings; enforce UTC session to prevent offset shifts.
    await conn.execute("SET TIME ZONE 'UTC'")

    try:
        async with conn.transaction():
            await _migrate_auth(conn)
            await _migrate_users(conn)

        print("\nRebuilding FTS indexes...")
        try:
            await conn.execute("REINDEX INDEX idx_node_sections_search")
            print("  idx_node_sections_search: done")
        except Exception as e:
            print(f"  idx_node_sections_search: WARN — REINDEX failed: {e}")

        print("\n=== Migration Summary ===")
        print("  Auth tables: migrated")
        print("  Per-user data: see per-user output above")
        print("  Review any WARN or SUMMARY lines above for data integrity issues.")
        print("  Run row-count verification queries to confirm data landed correctly.")
    finally:
        await conn.close()

    print("\nMigration complete.")


async def _migrate_auth(conn: asyncpg.Connection) -> None:
    auth = _open_sqlite(AUTH_DB)

    # users
    users = auth.execute("SELECT * FROM users").fetchall()
    inserted = 0
    for row in users:
        result = await conn.execute(
            """INSERT INTO users (id, username, email, password_hash, is_admin, created_at)
               VALUES ($1, $2, $3, $4, $5, $6)
               ON CONFLICT DO NOTHING""",
            _uuid.UUID(row["id"]),
            row["username"],
            row["email"],
            row["password_hash"],
            _to_bool(row["is_admin"]),
            _parse_dt(row["created_at"]),
        )
        if result != "INSERT 0 0":
            inserted += 1
    print(f"users: {inserted}/{len(users)} inserted")

    # oauth_connections
    rows = auth.execute("SELECT * FROM oauth_connections").fetchall()
    inserted = 0
    for row in rows:
        result = await conn.execute(
            """INSERT INTO oauth_connections (user_id, provider, provider_user_id, access_token, refresh_token)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT DO NOTHING""",
            _uuid.UUID(row["user_id"]),
            row["provider"],
            row["provider_user_id"],
            row["access_token"],
            row["refresh_token"],
        )
        if result != "INSERT 0 0":
            inserted += 1
    print(f"oauth_connections: {inserted}/{len(rows)} inserted")

    # invite_tokens
    rows = auth.execute("SELECT * FROM invite_tokens").fetchall()
    inserted = 0
    for row in rows:
        result = await conn.execute(
            """INSERT INTO invite_tokens (token, created_by, used_by, expires_at, created_at)
               VALUES ($1, $2, $3, $4, $5)
               ON CONFLICT DO NOTHING""",
            row["token"],
            _uuid.UUID(row["created_by"]),
            _uuid.UUID(row["used_by"]) if row["used_by"] else None,
            _parse_dt(row["expires_at"]),
            _parse_dt(row["created_at"]),
        )
        if result != "INSERT 0 0":
            inserted += 1
    print(f"invite_tokens: {inserted}/{len(rows)} inserted")

    # telegram_connections
    rows = auth.execute("SELECT * FROM telegram_connections").fetchall()
    inserted = 0
    for row in rows:
        result = await conn.execute(
            """INSERT INTO telegram_connections (user_id, telegram_chat_id)
               VALUES ($1, $2)
               ON CONFLICT DO NOTHING""",
            _uuid.UUID(row["user_id"]),
            row["telegram_chat_id"],
        )
        if result != "INSERT 0 0":
            inserted += 1
    print(f"telegram_connections: {inserted}/{len(rows)} inserted")

    # telegram_link_codes
    rows = auth.execute("SELECT * FROM telegram_link_codes").fetchall()
    inserted = 0
    for row in rows:
        result = await conn.execute(
            """INSERT INTO telegram_link_codes (code, telegram_chat_id, created_at)
               VALUES ($1, $2, $3)
               ON CONFLICT DO NOTHING""",
            row["code"],
            row["telegram_chat_id"],
            _parse_dt(row["created_at"]),
        )
        if result != "INSERT 0 0":
            inserted += 1
    print(f"telegram_link_codes: {inserted}/{len(rows)} inserted")


async def _migrate_users(conn: asyncpg.Connection) -> None:
    auth = _open_sqlite(AUTH_DB)
    users = auth.execute("SELECT id, username FROM users").fetchall()
    failed: list[tuple[str, str]] = []

    for user in users:
        user_id = _uuid.UUID(user["id"])
        db_path = USERS_DIR / f"{user['id']}.db"
        if not db_path.exists():
            print(f"\n[{user['username']}] no DB file at {db_path}, skipping")
            continue
        print(f"\n[{user['username']}] migrating {db_path}")
        uconn = _open_sqlite(db_path)
        try:
            async with conn.transaction():
                await _migrate_user_data(conn, uconn, user_id)
        except Exception as e:
            print(f"\n[{user['username']}] FAILED: {e}")
            failed.append((user["username"], str(e)))

    if failed:
        print("\n=== MIGRATION FAILURES ===")
        for username, err in failed:
            print(f"  FAILED: {username}: {err}")
        sys.exit(1)


async def _migrate_user_data(
    pg: asyncpg.Connection,
    sq: sqlite3.Connection,
    user_id: _uuid.UUID,
) -> None:
    uid = user_id  # shorthand
    skipped_task_context = 0
    null_milestone_context = 0

    # ── anchors ───────────────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "anchors")
    n = 0
    for r in rows:
        result = await pg.execute(
            """INSERT INTO anchors (id, user_id, name, time, duration_minutes,
                   flexibility, strictness, color, position, followup_config)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
               ON CONFLICT DO NOTHING""",
            _uuid.UUID(r["id"]), uid,
            r["name"], r["time"], r["duration_minutes"],
            r["flexibility"], r["strictness"], r["color"], r["position"],
            _parse_json(r["followup_config"], context=f"anchors id={r['id']} followup_config"),
        )
        if result != "INSERT 0 0":
            n += 1
    print(f"  anchors: {n}/{len(rows)}")

    # ── plans ─────────────────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "plans")
    n = 0
    for r in rows:
        result = await pg.execute(
            "INSERT INTO plans (date, user_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
            r["date"], uid,
        )
        if result != "INSERT 0 0":
            n += 1
    print(f"  plans: {n}/{len(rows)}")

    # ── context_entries ───────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "context_entries")
    n = 0
    for r in rows:
        result = await pg.execute(
            """INSERT INTO context_entries (user_id, subject, body, updated_at)
               VALUES ($1,$2,$3,$4)
               ON CONFLICT DO NOTHING""",
            uid, r["subject"], r["body"], _parse_dt(r["updated_at"]),
        )
        if result != "INSERT 0 0":
            n += 1
    print(f"  context_entries: {n}/{len(rows)}")

    # Build subject → pg id lookup (needed for task_context and milestones)
    ce_rows = await pg.fetch(
        "SELECT id, subject FROM context_entries WHERE user_id = $1", uid
    )
    subject_to_pg_id: dict[str, int] = {r["subject"]: r["id"] for r in ce_rows}
    sqlite_ce_count = len(rows)  # rows still holds context_entries here
    if sqlite_ce_count > 0 and not subject_to_pg_id:
        raise RuntimeError(
            f"[{uid}] SQLite has {sqlite_ce_count} context_entries but Postgres "
            "returned 0 — RLS bypass likely failed. Re-run as superuser."
        )

    # ── context_nodes (topological sort for self-referential FK) ──────────────
    node_rows = _safe_fetch_table(sq, "context_nodes")
    sorted_nodes = _topo_sort_nodes(node_rows)
    n = 0
    for r in sorted_nodes:
        result = await pg.execute(
            """INSERT INTO context_nodes
                   (id, user_id, parent_id, name, node_type, description, archived,
                    target_date, status, status_override, color, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
               ON CONFLICT DO NOTHING""",
            _uuid.UUID(r["id"]), uid,
            _uuid.UUID(r["parent_id"]) if r["parent_id"] else None,
            r["name"], r["node_type"], r["description"],
            _to_bool(r["archived"]),
            r["target_date"], r["status"],
            _to_bool(r["status_override"]),
            r["color"], _parse_dt(r["created_at"]), _parse_dt(r["updated_at"]),
        )
        if result != "INSERT 0 0":
            n += 1
    print(f"  context_nodes: {n}/{len(node_rows)}")

    # ── node_sections ─────────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "node_sections")
    n = 0
    for r in rows:
        result = await pg.execute(
            """INSERT INTO node_sections
                   (user_id, node_id, section_type, name, body, updated_at, position)
               VALUES ($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT DO NOTHING""",
            uid, _uuid.UUID(r["node_id"]),
            r["section_type"], r["name"], r["body"],
            _parse_dt(r["updated_at"]), r["position"],
        )
        if result != "INSERT 0 0":
            n += 1
    print(f"  node_sections: {n}/{len(rows)}")

    # ── node_tasks ────────────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "node_tasks")
    n = 0
    for r in rows:
        result = await pg.execute(
            """INSERT INTO node_tasks (node_id, task_id, user_id)
               VALUES ($1,$2,$3)
               ON CONFLICT DO NOTHING""",
            r["node_id"], r["task_id"], uid,
        )
        if result != "INSERT 0 0":
            n += 1
    print(f"  node_tasks: {n}/{len(rows)}")

    # ── tasks ─────────────────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "tasks")
    n = 0
    for r in rows:
        result = await pg.execute(
            """INSERT INTO tasks
                   (uuid, user_id, plan_date, anchor_id, position, text, status,
                    followup_config, notes, description, context_subject, context_node_id)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
               ON CONFLICT DO NOTHING""",
            _uuid.UUID(r["uuid"]) if r["uuid"] else _uuid.uuid5(_uuid.NAMESPACE_OID, f"{uid}:{r['id']}"),
            uid,
            r["plan_date"],
            _uuid.UUID(r["anchor_id"]) if r["anchor_id"] else None,
            r["position"],
            r["text"], r["status"],
            _parse_json(r["followup_config"], context=f"tasks uuid={r['uuid']} followup_config"),
            r["notes"] or "",
            r["description"],
            r["context_subject"],
            _uuid.UUID(r["context_node_id"]) if r["context_node_id"] else None,
        )
        if result != "INSERT 0 0":
            n += 1
    print(f"  tasks: {n}/{len(rows)}")

    # ── task_dependencies ─────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "task_dependencies")
    n = 0
    for r in rows:
        result = await pg.execute(
            """INSERT INTO task_dependencies (task_id, blocked_by_id, user_id)
               VALUES ($1,$2,$3)
               ON CONFLICT DO NOTHING""",
            _uuid.UUID(r["task_id"]), _uuid.UUID(r["blocked_by_id"]), uid,
        )
        if result != "INSERT 0 0":
            n += 1
    print(f"  task_dependencies: {n}/{len(rows)}")

    # ── dependencies ─────────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "dependencies")
    n = 0
    for r in rows:
        result = await pg.execute(
            """INSERT INTO dependencies
                   (user_id, blocker_type, blocker_id, blocked_type, blocked_id)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT DO NOTHING""",
            uid, r["blocker_type"], r["blocker_id"], r["blocked_type"], r["blocked_id"],
        )
        if result != "INSERT 0 0":
            n += 1
    print(f"  dependencies: {n}/{len(rows)}")

    # ── subtasks ──────────────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "subtasks")
    n = 0
    for r in rows:
        result = await pg.execute(
            """INSERT INTO subtasks (user_id, task_id, text, done, position)
               VALUES ($1,$2,$3,$4,$5)
               ON CONFLICT DO NOTHING""",
            uid, r["task_id"], r["text"],
            _to_bool(r["done"]), r["position"],
        )
        if result != "INSERT 0 0":
            n += 1
    print(f"  subtasks: {n}/{len(rows)}")

    # ── links ─────────────────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "links")
    n = 0
    for r in rows:
        result = await pg.execute(
            """INSERT INTO links (user_id, parent_type, parent_id, url, label, category, created_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT DO NOTHING""",
            uid, r["parent_type"], r["parent_id"],
            r["url"], r["label"], r["category"], _parse_dt(r["created_at"]),
        )
        if result != "INSERT 0 0":
            n += 1
    print(f"  links: {n}/{len(rows)}")

    # ── milestones ────────────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "milestones")
    n = 0
    for r in rows:
        context_entry_id = subject_to_pg_id.get(r["context_subject"])
        if context_entry_id is None and r["context_subject"]:
            print(f"  WARN: milestone {r['id']} refs unknown context_subject '{r['context_subject']}'")
            null_milestone_context += 1
        result = await pg.execute(
            """INSERT INTO milestones
                   (id, user_id, context_entry_id, name, description, target_date,
                    status, status_override, color, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
               ON CONFLICT DO NOTHING""",
            _uuid.UUID(r["id"]), uid,
            context_entry_id,
            r["name"], r["description"], r["target_date"],
            r["status"], _to_bool(r["status_override"]),
            r["color"], _parse_dt(r["created_at"]), _parse_dt(r["updated_at"]),
        )
        if result != "INSERT 0 0":
            n += 1
    print(f"  milestones: {n}/{len(rows)}")

    # ── milestone_tasks ───────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "milestone_tasks")
    n = 0
    for r in rows:
        result = await pg.execute(
            """INSERT INTO milestone_tasks (milestone_id, task_id, user_id)
               VALUES ($1,$2,$3)
               ON CONFLICT DO NOTHING""",
            _uuid.UUID(r["milestone_id"]), r["task_id"], uid,
        )
        if result != "INSERT 0 0":
            n += 1
    print(f"  milestone_tasks: {n}/{len(rows)}")

    # ── task_context ──────────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "task_context")
    n = 0
    for r in rows:
        context_entry_id = subject_to_pg_id.get(r["subject"])
        if context_entry_id is None:
            print(f"  WARN: task_context ({r['task_id']}, '{r['subject']}') refs missing context entry")
            skipped_task_context += 1
            continue
        result = await pg.execute(
            """INSERT INTO task_context (task_id, user_id, context_entry_id)
               VALUES ($1,$2,$3)
               ON CONFLICT DO NOTHING""",
            r["task_id"], uid, context_entry_id,
        )
        if result != "INSERT 0 0":
            n += 1
    print(f"  task_context: {n}/{len(rows)}")

    # ── followup_state ────────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "followup_state")
    n = 0
    for r in rows:
        result = await pg.execute(
            """INSERT INTO followup_state
                   (user_id, date, anchor_id, task_id, sequence_started_at,
                    acknowledged_at, pre_ack_pings_sent, post_ack_pings_sent,
                    last_ping_at, completed)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
               ON CONFLICT DO NOTHING""",
            uid, r["date"], r["anchor_id"], r["task_id"],
            _parse_dt(r["sequence_started_at"]), _parse_dt(r["acknowledged_at"]),
            r["pre_ack_pings_sent"] or 0,
            r["post_ack_pings_sent"] or 0,
            _parse_dt(r["last_ping_at"]),
            _to_bool(r["completed"]),
        )
        if result != "INSERT 0 0":
            n += 1
    print(f"  followup_state: {n}/{len(rows)}")

    # ── acknowledgements ──────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "acknowledgements")
    n = 0
    for r in rows:
        result = await pg.execute(
            """INSERT INTO acknowledgements (plan_date, anchor_id, user_id, acknowledged_at)
               VALUES ($1,$2,$3,$4)
               ON CONFLICT DO NOTHING""",
            r["plan_date"], r["anchor_id"], uid, _parse_dt(r["acknowledged_at"]),
        )
        if result != "INSERT 0 0":
            n += 1
    print(f"  acknowledgements: {n}/{len(rows)}")

    # ── check_ins ─────────────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "check_ins")
    n = 0
    for r in rows:
        result = await pg.execute(
            """INSERT INTO check_ins
                   (user_id, plan_date, anchor_id, type, timestamp, accomplished, current_status)
               VALUES ($1,$2,$3,$4,$5,$6,$7)
               ON CONFLICT DO NOTHING""",
            uid, r["plan_date"], r["anchor_id"], r["type"],
            _parse_dt(r["timestamp"]), r["accomplished"] or "", r["current_status"] or "",
        )
        if result != "INSERT 0 0":
            n += 1
    print(f"  check_ins: {n}/{len(rows)}")

    # ── edit_history ──────────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "edit_history")
    existing = await pg.fetchval(
        "SELECT count(*) FROM edit_history WHERE user_id = $1", uid
    )
    if existing > 0:
        print(f"  edit_history: SKIPPED (PG already has {existing} rows)")
    else:
        n = 0
        for r in rows:
            result = await pg.execute(
                """INSERT INTO edit_history
                       (user_id, table_name, operation, record_id, before_json, after_json, created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)
                   ON CONFLICT DO NOTHING""",
                uid, r["table_name"], r["operation"], r["record_id"],
                _parse_json(r["before_json"], context=f"edit_history id={r['id']} before_json"),
                _parse_json(r["after_json"], context=f"edit_history id={r['id']} after_json"),
                _parse_dt(r["created_at"]),
            )
            if result != "INSERT 0 0":
                n += 1
        print(f"  edit_history: {n}/{len(rows)}")

    # ── conversation_history ──────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "conversation_history")
    existing = await pg.fetchval(
        "SELECT count(*) FROM conversation_history WHERE user_id = $1", uid
    )
    if existing > 0:
        print(f"  conversation_history: SKIPPED (PG already has {existing} rows)")
    else:
        batch = [(uid, r["role"], r["body"], _parse_dt(r["ts"])) for r in rows]
        if batch:
            await pg.executemany(
                "INSERT INTO conversation_history (user_id, role, body, ts) VALUES ($1,$2,$3,$4)",
                batch,
            )
        print(f"  conversation_history: {len(batch)}/{len(rows)}")

    # ── staging_mutations ─────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "staging_mutations")
    n = 0
    for r in rows:
        result = await pg.execute(
            """INSERT INTO staging_mutations
                   (id, user_id, session_id, type, description, params_json, created_at, updated_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               ON CONFLICT DO NOTHING""",
            r["id"], uid, r["session_id"], r["type"],
            r["description"], _parse_json(r["params_json"], context=f"staging_mutations id={r['id']} params_json") or {},
            _parse_dt(r["created_at"]), _parse_dt(r["updated_at"]),
        )
        if result != "INSERT 0 0":
            n += 1
    print(f"  staging_mutations: {n}/{len(rows)}")

    # ── orchestrator_conversation ─────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "orchestrator_conversation")
    existing = await pg.fetchval(
        "SELECT count(*) FROM orchestrator_conversation WHERE user_id = $1", uid
    )
    if existing > 0:
        print(f"  orchestrator_conversation: SKIPPED (PG already has {existing} rows)")
    else:
        batch = [(uid, r["session_id"], r["role"], r["body"], r["round_num"], _parse_dt(r["ts"]))
                 for r in rows]
        if batch:
            await pg.executemany(
                """INSERT INTO orchestrator_conversation
                       (user_id, session_id, role, body, round_num, ts)
                   VALUES ($1,$2,$3,$4,$5,$6)""",
                batch,
            )
        print(f"  orchestrator_conversation: {len(batch)}/{len(rows)}")

    # ── invocation_log ────────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "invocation_log")
    existing = await pg.fetchval(
        "SELECT count(*) FROM invocation_log WHERE user_id = $1", uid
    )
    if existing > 0:
        print(f"  invocation_log: SKIPPED (PG already has {existing} rows)")
    else:
        batch = [(uid, r["session_id"], r["stage"],
                  r["prompt"] or "", r["response"] or "", r["error"], _parse_dt(r["ts"]))
                 for r in rows]
        if batch:
            await pg.executemany(
                """INSERT INTO invocation_log
                       (user_id, session_id, stage, prompt, response, error, ts)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)""",
                batch,
            )
        print(f"  invocation_log: {len(batch)}/{len(rows)}")

    # ── state_monitor_log ─────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "state_monitor_log")
    existing = await pg.fetchval(
        "SELECT count(*) FROM state_monitor_log WHERE user_id = $1", uid
    )
    if existing > 0:
        print(f"  state_monitor_log: SKIPPED (PG already has {existing} rows)")
    else:
        batch = [(uid, r["change_type"], r["entity_id"] or "",
                  r["score"] if r["score"] is not None else 1, _to_bool(r["consumed"]), _parse_dt(r["ts"]))
                 for r in rows]
        if batch:
            await pg.executemany(
                """INSERT INTO state_monitor_log
                       (user_id, change_type, entity_id, score, consumed, ts)
                   VALUES ($1,$2,$3,$4,$5,$6)""",
                batch,
            )
        print(f"  state_monitor_log: {len(batch)}/{len(rows)}")

    # ── beacon_state (singleton → per-user row) ───────────────────────────────
    try:
        beacon = sq.execute("SELECT last_invoked_at FROM beacon_state WHERE id = 1").fetchone()
        last_invoked = beacon["last_invoked_at"] if beacon else None
    except sqlite3.OperationalError as e:
        if "no such table" in str(e):
            last_invoked = None
        else:
            raise
    result = await pg.execute(
        """INSERT INTO beacon_state (user_id, last_invoked_at)
           VALUES ($1, $2)
           ON CONFLICT DO NOTHING""",
        uid, _parse_dt(last_invoked),
    )
    print(f"  beacon_state: {'1' if result != 'INSERT 0 0' else '0'}/1")

    # ── kanban_columns ────────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "kanban_columns")
    n = 0
    for r in rows:
        result = await pg.execute(
            """INSERT INTO kanban_columns
                   (id, user_id, name, position, color, match_rules, entry_rules, created_by)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
               ON CONFLICT DO NOTHING""",
            _uuid.UUID(r["id"]), uid,
            r["name"], r["position"], r["color"],
            _parse_json(r["match_rules"], context=f"kanban_columns id={r['id']} match_rules") or {},
            _parse_json(r["entry_rules"], context=f"kanban_columns id={r['id']} entry_rules") or {},
            r["created_by"],
        )
        if result != "INSERT 0 0":
            n += 1
    print(f"  kanban_columns: {n}/{len(rows)}")

    # ── user_settings ─────────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "user_settings")
    n = 0
    for r in rows:
        result = await pg.execute(
            """INSERT INTO user_settings (user_id, key, value)
               VALUES ($1,$2,$3)
               ON CONFLICT DO NOTHING""",
            uid, r["key"], r["value"],
        )
        if result != "INSERT 0 0":
            n += 1
    print(f"  user_settings: {n}/{len(rows)}")

    # ── sessions ──────────────────────────────────────────────────────────────
    rows = _safe_fetch_table(sq, "sessions")
    n = 0
    for r in rows:
        result = await pg.execute(
            """INSERT INTO sessions
                   (id, user_id, chat_id, state, turn_count, max_turns, summary,
                    created_at, last_activity)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
               ON CONFLICT DO NOTHING""",
            _uuid.UUID(r["id"]), uid,
            r["chat_id"], r["state"],
            r["turn_count"] if r["turn_count"] is not None else 0,
            r["max_turns"] if r["max_turns"] is not None else 10,
            r["summary"], _parse_dt(r["created_at"]), _parse_dt(r["last_activity"]),
        )
        if result != "INSERT 0 0":
            n += 1
    print(f"  sessions: {n}/{len(rows)}")

    if skipped_task_context or null_milestone_context:
        print(f"  SUMMARY: {skipped_task_context} task_context rows skipped, "
              f"{null_milestone_context} milestones with NULL context_entry_id")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true",
                        help="Print row counts without writing to Postgres")
    args = parser.parse_args()
    asyncio.run(migrate(dry_run=args.dry_run))
