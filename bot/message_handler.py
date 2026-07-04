from __future__ import annotations
import asyncio
import json
import logging
import os
import random
import re
import time
import uuid
from datetime import date as date_type
from pathlib import Path
from typing import Callable

import requests
from jinja2 import Environment, FileSystemLoader

from config.loader import config as tether_config

from bot.handler_utils import (
    get_current_anchor,
    is_anchor_active,
    parse_check_in,
    parse_update_context,
    parse_update_plan,
)
from db.pg_queries import (
    get_anchors,
    get_plan,
    get_recent_history,
    insert_check_in,
    insert_conversation_turn,
    list_plan_dates,
    log_stage,
    patch_anchor,
    upsert_plan,
    upsert_tasks,
    clear_session_state,
    insert_orchestrator_turn,
    link_milestone_task,
    patch_milestone,
    init_followup_state,
    get_active_followup_states,
    acknowledge_followup,
    record_ping,
    mark_followup_completed,
    resolve_followup_config,
    # context_nodes model
    ensure_node_path,
    get_node_by_path,
    get_section,
    upsert_section,
    append_section,
    get_children,
    get_all_node_paths,
    create_node,
)
import db.postgres as pg
from shared import notify_due
import db.pg_auth_queries as pg_auth_queries
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(os.environ.get("TETHER_CONFIG_DIR", Path.home() / ".tether-config"))
_OFFSET_PATH = _CONFIG_DIR / "telegram_offset"

# pending link codes: code -> (chat_id, timestamp) — in-memory cache; authoritative copy is auth db
_pending_links: dict[str, tuple[str, float]] = {}
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_jinja = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)), trim_blocks=True)

HISTORY_EXCHANGES = int(tether_config.get("pipeline.history_exchanges", 5))

# v2 pipeline constants
MAX_PLANNING_ROUNDS = int(tether_config.get("pipeline.max_planning_rounds", 4))
MAX_REPAIR_ATTEMPTS = int(tether_config.get("pipeline.max_repair_attempts", 3))
MAX_SATISFACTION_RETRIES = int(tether_config.get("pipeline.max_satisfaction_retries", 2))
_CLASSIFIER_TIMEOUT = 45

# Module-level log context — set once per _run_v2_planning_loop call.
# Safe because the bot is single-threaded.
_log_ctx: dict = {"pool": None, "user_id": None, "session_id": None}


def _set_log_context(pool, user_id: str, session_id: str) -> None:
    _log_ctx["pool"] = pool
    _log_ctx["user_id"] = user_id
    _log_ctx["session_id"] = session_id


async def _log_safe(stage: str, prompt: str, response: str, error: str | None = None) -> None:
    """Log a pipeline stage if log context is set. Never raises."""
    try:
        if _log_ctx["pool"] and _log_ctx["user_id"] and _log_ctx["session_id"]:
            async with pg.get_conn(_log_ctx["pool"], _log_ctx["user_id"]) as conn:
                await log_stage(conn, _log_ctx["session_id"], stage, prompt, response, error)
    except Exception as e:
        logger.debug("_log_safe failed: %s", e)


async def _resolve_user_id(pool, chat_id: str) -> str | None:
    """Look up chat_id in Postgres and return user_id UUID, or None if not found."""
    try:
        async with pg.get_conn(pool) as conn:  # no user_id — auth tables have no RLS
            user = await pg_auth_queries.get_user_by_telegram_chat_id(conn, chat_id)
            if user:
                return user["id"]
    except Exception as e:
        logger.warning("_resolve_user_id error: %s", e)
    return None


_MODEL_DEFAULTS: dict[str, str] = {
    "orchestrator":              "claude-sonnet-4-6",
    "meta_eval":                 "claude-haiku-4-5-20251001",
    "meta_eval_repair":          "claude-haiku-4-5-20251001",
    "meta_eval_repair_escalate": "claude-sonnet-4-6",
    "execution_subagent":        "claude-haiku-4-5-20251001",
    "satisfaction_eval":         "claude-haiku-4-5-20251001",
    "response_builder":          "claude-sonnet-4-6",
    "quick_classifier":          "claude-haiku-4-5-20251001",
}


_HISTORY_BODY_MAX = 500  # chars per message — prevents one long message dominating


def _format_history(history: list[dict]) -> str:
    if not history:
        return "(none)"
    lines = []
    for row in history:
        label = "User" if row["role"] == "user" else "Bot"
        ts = (row["ts"].strftime("%Y-%m-%d %H:%M") if hasattr(row["ts"], "strftime") else row["ts"][:16]) if row["ts"] else ""
        body = row["body"]
        if len(body) > _HISTORY_BODY_MAX:
            body = body[:_HISTORY_BODY_MAX] + "…"
        lines.append(f"[{ts}] {label}: {body}")
    return "\n".join(lines)


async def _fetch_requested_context(requests: list[dict], pool, user_id: str, round_num: int) -> str:
    """Resolve a list of context requests into a formatted string block."""
    today = str(date_type.today())
    sections: list[str] = [f"## Fetched context (round {round_num})"]
    async with pg.get_conn(pool, user_id) as conn:
        for req in requests:
            kind = req.get("kind")
            if kind == "context_entry":
                subject = req.get("subject", "")
                node = await get_node_by_path(conn, subject)
                if node:
                    sec = await get_section(conn, node["id"], "details")
                    body = sec["body"] if sec else "(no details section)"
                    sections.append(f"### Context: {subject}\n{body}")
                else:
                    sections.append(f"### Context: {subject}\n(not found)")
            elif kind == "plan":
                date = req.get("date", today)
                plan = await get_plan(conn, date)
                lines = [f"### Plan: {date}"]
                for anchor_id, anchor_data in plan.get("anchors", {}).items():
                    lines.append(f"**{anchor_id}**")
                    for task in anchor_data.get("tasks", []):
                        lines.append(f"- {task}")
                if not plan.get("anchors"):
                    lines.append("(no tasks)")
                sections.append("\n".join(lines))
            elif kind == "anchor_detail":
                anchor_id = req.get("anchor_id", "")
                anchors = await get_anchors(conn)
                anchor = next((a for a in anchors if a["id"] == anchor_id), None)
                if anchor:
                    sections.append(
                        f"### Anchor: {anchor_id}\n"
                        f"Name: {anchor['name']}, Time: {anchor['time']}, "
                        f"Duration: {anchor['duration_minutes']}min"
                    )
                else:
                    sections.append(f"### Anchor: {anchor_id}\n(not found)")
            elif kind == "check_in_log":
                date = req.get("date", today)
                plan = await get_plan(conn, date)
                log = plan.get("check_in_log", [])
                if log:
                    lines = [f"### Check-in log: {date}"]
                    for entry in log:
                        lines.append(
                            f"- [{entry.get('timestamp', '')}] {entry.get('anchor_id', '')}: "
                            f"{entry.get('accomplished', '')}"
                        )
                    sections.append("\n".join(lines))
                else:
                    sections.append(f"### Check-in log: {date}\n(none)")
            else:
                logger.warning("Unknown context request kind: %s", kind)
    return "\n\n".join(sections)


def get_model(role: str) -> str:
    """Return the model string for a pipeline role, reading from config with fallback."""
    try:
        return tether_config.get(f"models.{role}") or _MODEL_DEFAULTS[role]
    except Exception as e:
        logger.warning("get_model config read failed, using default: %s", e)
        return _MODEL_DEFAULTS.get(role, "claude-sonnet-4-6")


async def call_claude(prompt: str, timeout: int = 180, model_role: str | None = None,
                      stage: str = "") -> str:
    from claude_agent_sdk import query, ClaudeAgentOptions, AssistantMessage, TextBlock
    from bot.llm import _llm_env_extras

    env: dict[str, str] = {}
    extras = _llm_env_extras.get()
    if extras:
        env.update(extras)

    model = get_model(model_role) if model_role is not None else None
    opts = ClaudeAgentOptions(
        model=model,
        permission_mode="bypassPermissions",
        env=env,
    )

    async def _collect() -> str:
        parts: list[str] = []
        async for msg in query(prompt=prompt, options=opts):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        parts.append(block.text)
        return "".join(parts).strip()

    try:
        out = await asyncio.wait_for(_collect(), timeout=timeout)
    except asyncio.TimeoutError:
        if stage:
            await _log_safe(stage, prompt, "", f"timeout after {timeout}s")
        raise RuntimeError(f"Claude timed out after {timeout}s. Try a simpler request.")
    except Exception as e:
        if stage:
            await _log_safe(stage, prompt, "", str(e))
        raise

    if stage:
        await _log_safe(stage, prompt, out)
    return out


def _parse_json(raw: str) -> dict:
    """Parse JSON from Claude output, stripping markdown fences."""
    cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
    return json.loads(cleaned)


def parse_claude_response(raw: str) -> tuple[str, list[dict]]:
    """Extract message and mutations. Falls back to treating raw as message."""
    try:
        data = json.loads(raw.strip())
        return data.get("message", raw), data.get("mutations", [])
    except (json.JSONDecodeError, AttributeError):
        pass
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            return data.get("message", raw), data.get("mutations", [])
        except (json.JSONDecodeError, AttributeError):
            pass
    return raw, []


async def apply_mutations(mutations: list[dict], pool, user_id: str, today: str) -> None:
    async with pg.get_conn(pool, user_id) as conn:
        for m in mutations:
            op = m.get("op")
            try:
                if op == "update_anchor":
                    fields = {k: v for k, v in m.items() if k not in ("op", "anchor_id")}
                    await patch_anchor(conn, m["anchor_id"], **fields)
                elif op == "update_plan_tasks":
                    date = m.get("date", today)
                    async with conn.transaction():
                        await upsert_plan(conn, date)
                        await upsert_tasks(conn, date, m["anchor_id"], m["tasks"], notes="")
                elif op == "update_context":
                    node = await ensure_node_path(conn, m["subject"])
                    await upsert_section(conn, node["id"], "details", m["body"])
                elif op == "append_context":
                    node = await ensure_node_path(conn, m["subject"])
                    await append_section(conn, node["id"], "details", m["content"])
                elif op == "patch_context":
                    node = await get_node_by_path(conn, m["subject"])
                    if node:
                        sec = await get_section(conn, node["id"], "details")
                        if sec and m["old"] in sec["body"]:
                            new_body = sec["body"].replace(m["old"], m["new"], 1)
                            await upsert_section(conn, node["id"], "details", new_body)
                    else:
                        logger.warning("patch_context: subject %r not found", m["subject"])
                elif op == "insert_check_in":
                    await insert_check_in(conn, today, m["anchor_id"],
                                    m["accomplished"], m["current_status"])
                elif op == "link_milestone_tasks":
                    milestone_id = m["milestone_id"]
                    for task_id in m.get("task_ids", []):
                        await link_milestone_task(conn, milestone_id, task_id)
                elif op == "create_milestone":
                    parent = await get_node_by_path(conn, m.get("context_subject", ""))
                    parent_id = parent["id"] if parent else None
                    await create_node(
                        conn, parent_id, m["name"],
                        node_type="milestone",
                        target_date=m.get("target_date"),
                    )
                elif op == "patch_milestone":
                    fields = {k: v for k, v in m.items()
                              if k in {"name", "description", "target_date", "status"}}
                    if fields:
                        await patch_milestone(conn, m["milestone_id"], fields)
                else:
                    logger.warning("Unknown mutation op: %s", op)
            except Exception as e:
                logger.error("Failed to apply mutation %s: %s", m, e)


def _parse_ts(ts_str: str | None, *, default: "datetime") -> "datetime":
    from datetime import datetime
    if not ts_str:
        return default
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError:
        return default


def classify_followup_row(row: dict, config: dict, now: "datetime") -> tuple[str | None, "datetime | None"]:
    """Pure classification of a single followup_state row against its resolved
    config: is it due right now, and if not (or after it fires), when's the
    next candidate check time?

    Returns ``(queue, next_candidate)``:
      - ``queue`` is ``"pre"``/``"post"`` if the row is due right now for that
        ack phase, else ``None``.
      - ``next_candidate`` is the earliest ``datetime`` this row could next
        become due — ``None`` if the row has exhausted its allotted pings for
        its current phase (no further automatic check needed for it).

    No I/O — depends only on the row, its config, and the current time, so
    the next-due estimate used for Redis gating (see shared/notify_due.py)
    is independently testable without a database.
    """
    from datetime import datetime, timedelta

    def minutes_since(ts_str: str | None) -> float:
        if not ts_str:
            return float('inf')
        try:
            ts = datetime.fromisoformat(ts_str)
        except ValueError:
            return float('inf')
        return (now - ts).total_seconds() / 60

    if row["acknowledged_at"] is None:
        ref_ts = row["last_ping_at"] or row["sequence_started_at"]
        if row["pre_ack_pings_sent"] >= config["pre_ack_max_pings"]:
            return None, None
        if minutes_since(ref_ts) >= config["pre_ack_interval_min"]:
            # Due now — will be pinged this pass. The next candidate (one
            # interval after "now") is an approximation: the precise value
            # depends on the ping actually being recorded by the caller.
            return "pre", now + timedelta(minutes=config["pre_ack_interval_min"])
        return None, _parse_ts(ref_ts, default=now) + timedelta(minutes=config["pre_ack_interval_min"])
    else:
        ref_ts = row["last_ping_at"] or row["acknowledged_at"]
        if row["post_ack_pings_sent"] >= config["post_ack_pings"]:
            return None, None
        if minutes_since(ref_ts) >= config["post_ack_interval_min"]:
            return "post", now + timedelta(minutes=config["post_ack_interval_min"])
        return None, _parse_ts(ref_ts, default=now) + timedelta(minutes=config["post_ack_interval_min"])


async def check_followups(pool, user_id: str, send_fn):
    """Called every polling cycle. Sends batched pre/post-ack messages for due tasks.

    Returns the earliest ``datetime`` at which a currently-active-but-not-yet-due
    followup row could next become due (or ``None`` if there are no active rows
    at all, i.e. the followup component is entirely governed by the next anchor
    trigger). Callers use this to populate the Redis next-due gate
    (``shared.notify_due.set_component_due(user_id, "followup", ...)``) so a
    future invocation can skip this Postgres round-trip entirely when nothing
    is due yet — see shared/notify_due.py for the full gating scheme.
    """
    from datetime import datetime, date
    now = datetime.now()
    today = str(date.today())

    next_candidate: datetime | None = None

    def _consider(candidate: datetime | None) -> None:
        nonlocal next_candidate
        if candidate is None:
            return
        if next_candidate is None or candidate < next_candidate:
            next_candidate = candidate

    # Phase 1: load all data (connection held only for reads + config lookups)
    async with pg.get_conn(pool, user_id) as conn:
        rows = await get_active_followup_states(conn, today)
        if not rows:
            logger.debug("check_followups: no active followup states for %s", today)
            return None

        pre_ack_due = []
        post_ack_due = []

        all_anchors = await get_anchors(conn)
        active_anchor_ids = {a["id"] for a in all_anchors if is_anchor_active(a, now)}
        logger.debug("check_followups: %d rows, %d active anchors (%s)",
                     len(rows), len(active_anchor_ids), ", ".join(active_anchor_ids) or "none")

        for row in rows:
            if row["anchor_id"] not in active_anchor_ids:
                logger.debug("check_followups: skipping task %s — anchor %s not active",
                             row["task_id"], row["anchor_id"])
                continue
            config = await resolve_followup_config(conn, row["anchor_id"], row["task_id"])
            if config is None:
                logger.debug("check_followups: skipping task %s — no followup config",
                             row["task_id"])
                continue
            queue, candidate = classify_followup_row(row, config, now)
            _consider(candidate)
            if queue == "pre":
                pre_ack_due.append(row)
            elif queue == "post":
                post_ack_due.append(row)

        plan = await get_plan(conn, today) if (pre_ack_due or post_ack_due) else {}

    # Phase 2: send messages + record pings (connection released between HTTP calls)
    if pre_ack_due:
        from collections import defaultdict
        by_anchor: dict = defaultdict(list)
        for row in pre_ack_due:
            by_anchor[row["anchor_id"]].append(row)
        for anchor_id, anchor_rows in by_anchor.items():
            task_lines = []
            for row in anchor_rows:
                task = None
                if plan and anchor_id in plan.get("anchors", {}):
                    task = next(
                        (t for t in plan["anchors"][anchor_id]["tasks"]
                         if t["id"] == row["task_id"]), None
                    )
                task_lines.append(f"• {task['text'] if task else row['task_id']}")
            anchor_name = next((a["name"] for a in all_anchors if a["id"] == anchor_id), anchor_id)
            msg = (f"Your **{anchor_name}** block is underway. You haven't checked in yet on:\n"
                   + "\n".join(task_lines)
                   + "\n\n`/check-in` when you're on it.")
            send_fn(msg)
            async with pg.get_conn(pool, user_id) as conn:
                for row in anchor_rows:
                    await record_ping(conn, row["id"], "pre", now)

    if post_ack_due:
        from collections import defaultdict
        by_anchor: dict = defaultdict(list)
        for row in post_ack_due:
            by_anchor[row["anchor_id"]].append(row)
        for anchor_id, anchor_rows in by_anchor.items():
            task_lines = []
            for row in anchor_rows:
                task = None
                if plan and anchor_id in plan.get("anchors", {}):
                    task = next(
                        (t for t in plan["anchors"][anchor_id]["tasks"]
                         if t["id"] == row["task_id"]), None
                    )
                status = f" ({task['status']})" if task else ""
                task_lines.append(f"• {task['text'] if task else row['task_id']}{status}")
            anchor_name = next((a["name"] for a in all_anchors if a["id"] == anchor_id), anchor_id)
            msg = (f"Quick check — progress on **{anchor_name}**:\n"
                   + "\n".join(task_lines)
                   + "\n\nWhat have you knocked out?")
            send_fn(msg)
            async with pg.get_conn(pool, user_id) as conn:
                for row in anchor_rows:
                    await record_ping(conn, row["id"], "post", now)

    return next_candidate


# ---------------------------------------------------------------------------
# v2 Pipeline: helpers
# ---------------------------------------------------------------------------

def _format_plan_human_readable(plan: dict) -> str:
    if not plan.get("anchors"):
        return "(No tasks planned)"
    lines = []
    for anchor_id, anchor_data in plan["anchors"].items():
        lines.append(f"**{anchor_id}**")
        for task in anchor_data.get("tasks", []):
            lines.append(f"- {task}")
        if anchor_data.get("notes"):
            lines.append(f"  Notes: {anchor_data['notes']}")
    return "\n".join(lines)


_STATUS_SYMBOL = {
    "done": "✓", "in_progress": "▶", "skipped": "–",
    "blocked": "✗", "pending": "○",
}


def _format_plan_compact(plan: dict) -> str:
    """Compact single-line-per-anchor plan representation.

    Example: morning: ✓ Exercise | ○ Breakfast | ▶ Review notes
    Significantly fewer tokens than the verbose format for large plans.
    """
    if not plan.get("anchors"):
        return "(no plan)"
    lines = []
    for anchor_id, anchor_data in plan["anchors"].items():
        tasks = anchor_data.get("tasks", [])
        if not tasks:
            lines.append(f"{anchor_id}: (empty)")
            continue
        task_parts = []
        for t in tasks:
            sym = _STATUS_SYMBOL.get(t.get("status", "pending"), "○")
            task_parts.append(f"{sym} {t.get('text', '?')}")
        lines.append(f"{anchor_id}: {' | '.join(task_parts)}")
    return "\n".join(lines)


def _format_mutation_plan_human_readable(plan: list[dict]) -> str:
    if not plan:
        return "(Nothing staged yet)"
    return "\n".join(
        f"- [{m.get('type', '?')}] {m.get('description', m.get('id', '?'))}"
        for m in plan
    )


def _format_orchestrator_conversation(conv: list[dict]) -> str:
    if not conv:
        return "(No prior turns)"
    return "\n\n".join(
        f"[Round {t['round']}] {t['role'].replace('_', ' ').title()}: {t['body']}"
        for t in conv
    )


def _summarize_orchestrator_conv(conv: list[dict], max_chars: int = 1000) -> str:
    """Compress orchestrator turns into a briefing string for subagents."""
    if not conv:
        return "(No orchestrator reasoning available)"
    parts = [t["body"] for t in conv if t["role"] == "orchestrator"]
    combined = "\n---\n".join(parts)
    if len(combined) <= max_chars:
        return combined
    return combined[:max_chars] + "\n... (truncated)"


# ---------------------------------------------------------------------------
# v2 Pipeline: orchestrator call
# ---------------------------------------------------------------------------

async def call_orchestrator(
    user_message: str,
    plan: dict,
    subjects: list[str],
    history: list[dict],
    conversation: list[dict],
    meta_eval_summary: str,
    fetched_context: str,
    anchors: list[dict],
    stage: str = "orchestrator",
    session_notes: str | None = None,
) -> str:
    """Call the orchestrator. Returns raw plain-text reasoning (not JSON)."""
    current_anchor = get_current_anchor(anchors)
    template = _jinja.get_template("orchestrator.md")
    prompt = template.render(
        date=str(date_type.today()),
        current_anchor=current_anchor,
        plan_human_readable=_format_plan_compact(plan),
        subjects_list="\n".join(f"- {s}" for s in subjects),
        history=_format_history(history),
        meta_eval_summary=meta_eval_summary,
        fetched_context=fetched_context,
        prior_conversation=_format_orchestrator_conversation(conversation),
        user_message=user_message,
        session_notes=session_notes,
    )
    return await call_claude(prompt, timeout=60, model_role="orchestrator", stage=stage)


# ---------------------------------------------------------------------------
# v2 Pipeline: meta-eval call with repair escalation
# ---------------------------------------------------------------------------

def _build_repair_prompt(
    malformed_output: str,
    orchestrator_conv: list[dict],
    valid_subjects: list[str],
    valid_anchor_ids: list[str],
    available_dates: list[str],
) -> str:
    schema = json.dumps({
        "summary": "string",
        "context_to_fetch": [],
        "mutation_plan": [],
        "orchestrator_done": False,
    }, indent=2)
    template = _jinja.get_template("meta_eval_repair.md")
    return template.render(
        malformed_output=malformed_output,
        expected_schema=schema,
        orchestrator_conversation=_format_orchestrator_conversation(orchestrator_conv),
        valid_subjects=", ".join(valid_subjects),
        valid_anchor_ids=", ".join(valid_anchor_ids),
        available_dates=", ".join(available_dates),
    )


async def call_meta_eval(
    orchestrator_conversation: list[dict],
    current_mutation_plan: list[dict],
    fetched_context_log: list[str],
    anchors: list[dict],
    all_subjects: list[str],
    available_dates: list[str],
    today: str,
    round_num: int,
    max_rounds: int,
    force_done: bool,
) -> dict:
    """Call the meta-evaluator. Returns parsed dict or error sentinel."""
    anchor_summary = "\n".join(f"- {a['id']}: {a['name']} ({a['time']})" for a in anchors)
    # Keep only last 2 turns — mutation_plan + fetched_context_log already carry
    # the cumulative state, so older orchestrator turns are redundant context
    # that inflates the prompt and causes Haiku timeouts.
    recent_conv = orchestrator_conversation[-2:]
    template = _jinja.get_template("meta_eval.md")
    prompt = template.render(
        orchestrator_conversation=_format_orchestrator_conversation(recent_conv),
        current_mutation_plan_human_readable=_format_mutation_plan_human_readable(current_mutation_plan),
        fetched_context_log="\n\n".join(fetched_context_log) if fetched_context_log else "(none)",
        anchors=anchor_summary,
        all_subjects="\n".join(f"- {s}" for s in all_subjects),
        available_dates=", ".join(available_dates),
        date=today,
        round_num=round_num,
        max_rounds=max_rounds,
        force_done=force_done,
    )

    raw = ""
    try:
        raw = await call_claude(prompt, timeout=45, model_role="meta_eval",
                          stage=f"meta_eval_{round_num}")
        return _parse_json(raw)
    except Exception as e:
        logger.warning("meta_eval round %d initial call failed: %s", round_num, e)

    valid_anchor_ids = [a["id"] for a in anchors]
    repair_prompt = _build_repair_prompt(
        raw, recent_conv, all_subjects, valid_anchor_ids, available_dates
    )
    for attempt in range(MAX_REPAIR_ATTEMPTS):
        role = "meta_eval_repair_escalate" if attempt == MAX_REPAIR_ATTEMPTS - 1 else "meta_eval_repair"
        try:
            repaired = await call_claude(repair_prompt, timeout=45, model_role=role,
                                   stage=f"meta_eval_repair_{round_num}_{attempt}")
            return _parse_json(repaired)
        except Exception as e:
            logger.warning("meta_eval repair attempt %d failed: %s", attempt, e)
            continue

    logger.error("call_meta_eval: all repair attempts failed")
    return {
        "summary": (
            "The system had trouble interpreting the last planning step. "
            "Please restate what you want to do clearly and concisely."
        ),
        "context_to_fetch": [],
        "mutation_plan": current_mutation_plan,
        "orchestrator_done": False,
        "_parse_error": True,
    }


# ---------------------------------------------------------------------------
# v2 Pipeline: typed subagent dispatch
# ---------------------------------------------------------------------------

async def _dispatch_single_subagent(
    mutation: dict, orchestrator_briefing: str, pool, user_id: str, today: str
) -> str:
    """Dispatch one mutation to the appropriate subagent. Returns report string."""
    op_type = mutation.get("type", "")

    if op_type in ("update_plan_tasks", "update_context", "update_anchor"):
        params = {k: v for k, v in mutation.items() if k not in ("type", "id", "description")}
        template = _jinja.get_template("subagent_upsert.md")
        prompt = template.render(
            op=op_type,
            description=mutation.get("description", ""),
            params=json.dumps(params, indent=2),
            orchestrator_briefing=orchestrator_briefing,
        )
    elif op_type in ("patch_context", "append_context"):
        subject = mutation.get("subject", "")
        async with pg.get_conn(pool, user_id) as conn:
            node = await get_node_by_path(conn, subject)
            if node:
                sec = await get_section(conn, node["id"], "details")
                current_body = sec["body"] if sec else "(not found)"
            else:
                current_body = "(not found)"
        template = _jinja.get_template("subagent_patch.md")
        prompt = template.render(
            op=op_type,
            description=mutation.get("description", ""),
            subject=subject,
            old=mutation.get("old", ""),
            new=mutation.get("new", ""),
            content=mutation.get("content", ""),
            current_body=current_body,
            orchestrator_briefing=orchestrator_briefing,
        )
    else:
        logger.warning("_dispatch_single_subagent: unknown type %r", op_type)
        return f"SKIPPED: unknown type {op_type!r}"

    try:
        raw = await call_claude(prompt, timeout=120, model_role="execution_subagent",
                          stage=f"subagent_{op_type}")
        data = _parse_json(raw)
        report = data.get("report", "")
        db_mutation = {k: v for k, v in data.items() if k != "report"}
        if db_mutation.get("op"):
            await apply_mutations([db_mutation], pool, user_id, today)
        return report or f"[{op_type}] completed"
    except Exception as e:
        logger.error("Subagent dispatch failed for %r: %s", op_type, e)
        return f"FAILED [{op_type}]: {e}"


async def dispatch_typed_subagents(
    mutation_plan: list[dict],
    orchestrator_briefing: str,
    pool,
    user_id: str,
) -> tuple[list[str], list[str]]:
    """Dispatch all non-chat mutations. Returns (reports, chat_messages)."""
    today = str(date_type.today())
    reports: list[str] = []
    chat_messages: list[str] = []
    for mutation in mutation_plan:
        if mutation.get("type") == "chat":
            chat_messages.append(mutation.get("message", mutation.get("description", "")))
            continue
        reports.append(await _dispatch_single_subagent(mutation, orchestrator_briefing, pool, user_id, today))
    return reports, chat_messages


# ---------------------------------------------------------------------------
# v2 Pipeline: satisfaction eval + response builder
# ---------------------------------------------------------------------------

async def call_satisfaction_eval(
    original_intent: str,
    mutation_plan: list[dict],
    reports: list[str],
    pool,
    user_id: str,
) -> dict:
    """Verify mutations accomplished the stated intent."""
    today = str(date_type.today())
    async with pg.get_conn(pool, user_id) as conn:
        plan = await get_plan(conn, today)
    db_state = f"Today's plan:\n{_format_plan_human_readable(plan)}"
    template = _jinja.get_template("satisfaction_eval.md")
    prompt = template.render(
        original_intent=original_intent,
        mutation_plan_description=_format_mutation_plan_human_readable(mutation_plan),
        subagent_reports="\n".join(f"- {r}" for r in reports) if reports else "(none)",
        db_state=db_state,
    )
    try:
        raw = await call_claude(prompt, timeout=45, model_role="satisfaction_eval",
                          stage="satisfaction_eval")
        data = _parse_json(raw)
        return {
            "satisfied": data.get("satisfied", True),
            "issues": data.get("issues", []),
            "replan_needed": data.get("replan_needed", False),
        }
    except Exception as e:
        logger.warning("call_satisfaction_eval failed (%s), assuming satisfied", e)
        return {"satisfied": True, "issues": [], "replan_needed": False}


async def call_response_builder(
    user_message: str,
    reports: list[str],
    chat_messages: list[str],
    history: list[dict],
    pool,
    user_id: str,
    anchors: list[dict],
) -> str:
    """Build the final user-facing Telegram message."""
    today = str(date_type.today())
    current_anchor = get_current_anchor(anchors)
    async with pg.get_conn(pool, user_id) as conn:
        plan = await get_plan(conn, today)
    template = _jinja.get_template("response_builder.md")
    prompt = template.render(
        date=today,
        current_anchor=current_anchor,
        plan_human_readable=_format_plan_human_readable(plan),
        subagent_reports="\n".join(f"- {r}" for r in reports) if reports else "(none)",
        chat_messages="\n".join(chat_messages) if chat_messages else "",
        history=_format_history(history),
        user_message=user_message,
    )
    raw = ""
    try:
        raw = await call_claude(prompt, timeout=60, model_role="response_builder",
                          stage="response_builder")
        data = _parse_json(raw)
        return data.get("message", raw)
    except RuntimeError as e:
        return str(e)
    except Exception as e:
        logger.warning("response_builder parse failed, returning raw: %s", e)
        return raw


# ---------------------------------------------------------------------------
# Quick-route classifier
# ---------------------------------------------------------------------------

async def _classify_message(text: str, current_anchor: dict, today: str) -> str:
    """Return 'quick' or 'full' based on whether the message needs the orchestrator."""
    template = _jinja.get_template("quick_classifier.md")
    prompt = template.render(
        user_message=text,
        current_anchor=current_anchor,
        date=today,
    )
    try:
        _timeout = int(tether_config.get("pipeline.classifier_timeout_seconds", _CLASSIFIER_TIMEOUT))
        raw = await call_claude(prompt, timeout=_timeout, model_role="quick_classifier",
                          stage="quick_classifier")
        data = _parse_json(raw)
        route = data.get("route", "full")
        return route if route in ("quick", "full") else "full"
    except Exception as e:
        logger.warning("quick_classifier failed, defaulting to full: %s", e)
        return "full"


# ---------------------------------------------------------------------------
# Slash-command path (deterministic DB writes; pipeline continues below)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# v2 Pipeline: planning loop helper
# ---------------------------------------------------------------------------

async def _run_v2_planning_loop(
    text: str,
    anchors: list[dict],
    history: list[dict],
    pool,
    user_id: str,
    today: str,
    issues_context: str = "",
) -> tuple[list[dict], list[str], list[str], list[dict]]:
    """Run orchestrator → meta-eval loop then dispatch subagents.

    Returns (mutation_plan, reports, chat_messages, orchestrator_conv).
    Raises RuntimeError if parse errors exceed threshold.
    """
    async with pg.get_conn(pool, user_id) as conn:
        all_subjects = await get_all_node_paths(conn)
        available_dates = list(dict.fromkeys([today] + await list_plan_dates(conn)))
    session_id = str(uuid.uuid4())
    async with pg.get_conn(pool, user_id) as conn:
        await clear_session_state(conn, session_id)
    _set_log_context(pool, user_id, session_id)

    orchestrator_conv: list[dict] = []
    current_mutation_plan: list[dict] = []
    fetched_context_log: list[str] = []
    last_meta_summary = issues_context
    last_fetched = ""
    parse_error_count = 0

    for round_num in range(MAX_PLANNING_ROUNDS + 1):
        force_done = round_num == MAX_PLANNING_ROUNDS

        async with pg.get_conn(pool, user_id) as conn:
            plan = await get_plan(conn, today)

        orch_response = await call_orchestrator(
            user_message=text,
            plan=plan,
            subjects=all_subjects,
            history=history,
            conversation=orchestrator_conv,
            meta_eval_summary=last_meta_summary,
            fetched_context=last_fetched,
            anchors=anchors,
            stage=f"orchestrator_{round_num}",
        )
        orchestrator_conv.append({"role": "orchestrator", "body": orch_response, "round": round_num})
        async with pg.get_conn(pool, user_id) as conn:
            await insert_orchestrator_turn(conn, session_id, "orchestrator", orch_response, round_num)

        meta = await call_meta_eval(
            orchestrator_conversation=orchestrator_conv,
            current_mutation_plan=current_mutation_plan,
            fetched_context_log=fetched_context_log,
            anchors=anchors,
            all_subjects=all_subjects,
            available_dates=available_dates,
            today=today,
            round_num=round_num,
            max_rounds=MAX_PLANNING_ROUNDS,
            force_done=force_done,
        )

        if meta.get("_parse_error"):
            parse_error_count += 1
            if parse_error_count >= 3:
                raise RuntimeError(
                    "Something went wrong with my planning process. "
                    "Please try again or rephrase your request."
                )

        last_meta_summary = meta.get("summary", "")
        current_mutation_plan = meta.get("mutation_plan", current_mutation_plan)

        context_requests = meta.get("context_to_fetch", [])
        if context_requests:
            last_fetched = await _fetch_requested_context(context_requests, pool, user_id, round_num + 1)
            fetched_context_log.append(last_fetched)
        else:
            last_fetched = ""

        if meta.get("orchestrator_done") or force_done:
            break

    orchestrator_briefing = _summarize_orchestrator_conv(orchestrator_conv)
    reports, chat_messages = await dispatch_typed_subagents(current_mutation_plan, orchestrator_briefing, pool, user_id)
    return current_mutation_plan, reports, chat_messages, orchestrator_conv


# ---------------------------------------------------------------------------
# v3 SDK path
# ---------------------------------------------------------------------------

def _is_v3_enabled() -> bool:
    """Check if v3 SDK conversation loop is enabled in config."""
    try:
        return tether_config.get_bool("llm.use_v3", False)
    except Exception as e:
        logger.debug("_is_v3_enabled config read failed: %s", e)
        return False


def _is_v2_fallback_enabled() -> bool:
    """Check if v2 pipeline fallback is enabled when v3 fails. Default: True."""
    try:
        return tether_config.get_bool("llm.v2_fallback", True)
    except Exception as e:
        logger.debug("_is_v2_fallback_enabled config read failed: %s", e)
        return True


async def _handle_v3(text: str, pool, user_id: str, anchors: list[dict],
               current_anchor: dict,
               skill_commands: list[str] | None = None,
               conversation_id: str | None = None) -> str:
    """Run a basic v3 single-shot LLM call. Returns the response text.

    Uses AnthropicBackend directly (no LLMRouter, no conversation loop,
    no tool execution). For advanced features (sessions, tools, multi-turn),
    install tether-premium.
    """
    from bot.conversation import build_system_prompt
    from bot.llm import AnthropicBackend, PipelineBackend

    today = str(date_type.today())
    async with pg.get_conn(pool, user_id) as conn:
        plan = await get_plan(conn, today)
        subjects = await get_all_node_paths(conn)
        history = await get_recent_history(conn, HISTORY_EXCHANGES)

    plan_lines = []
    for anchor_id, data in plan.get("anchors", {}).items():
        tasks = data.get("tasks", [])
        task_strs = [f"[{t.get('status', '?')[:1]}] {t.get('text', '')}" for t in tasks]
        plan_lines.append(f"{anchor_id}: {' | '.join(task_strs) or 'empty'}")

    _quick_tokens = {"hi", "hello", "hey", "thanks", "ok", "yes", "no", "yep", "nope", "ty"}
    mode = "quick" if text.strip().lower() in _quick_tokens else "scheduler"
    system = build_system_prompt(
        anchor_name=current_anchor.get("name", "General"),
        anchor_time=current_anchor.get("time", "00:00"),
        plan_summary="\n".join(plan_lines) or "No plan data.",
        context_subjects=subjects,
        session_notes=None,
        mode=mode,
    )

    # Conversation context injection — appended to system prompt when a
    # conversation_id with a linked context_node is provided.
    if conversation_id:
        try:
            from bot.conversation_context import build_conversation_context
            ctx_block = await build_conversation_context(conversation_id, pool, user_id)
            if ctx_block:
                system = system + "\n\n" + ctx_block
        except Exception as _ctx_err:
            logger.warning("_handle_v3: context injection failed: %s", _ctx_err)

    # Skill injection (v3-basic fallback): append skill content to system prompt
    if skill_commands:
        try:
            from tether_premium.bot.skill_registry import load_skill
            skill_blocks = [load_skill(f"/{cmd}") for cmd in skill_commands]
            skill_text = "\n\n".join(b for b in skill_blocks if b)
            if skill_text:
                system = system + "\n\n" + skill_text
        except ImportError:
            pass

    conv_history = [
        {"role": "user" if h["role"] == "user" else "assistant", "content": h["body"]}
        for h in history
    ]
    conv_history.append({"role": "user", "content": text})

    backend = AnthropicBackend()
    if not backend.is_available():
        backend = PipelineBackend()

    model = tether_config.get("llm.roles.main_agent.model", "claude-sonnet-4-6")

    logger.info("v3 basic: model=%s backend=%s mode=%s", model, type(backend).__name__, mode)
    result = await backend.complete(messages=conv_history, system=system, model=model)
    return result.content


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _log_preview(text: str, n: int = 120) -> str:
    """Single-line truncated preview for log lines."""
    t = (text or "").replace("\n", " ⏎ ").strip()
    return (t[:n] + "…") if len(t) > n else t


async def _handle_message_body(text: str, send_fn: Callable[[str], None], pool, user_id: str,
                               status_fn=None, conversation_id: str | None = None) -> None:
    today = str(date_type.today())
    logger.info("handle_message: entered, text_len=%d", len(text or ""))
    async with pg.get_conn(pool, user_id) as conn:
        await upsert_plan(conn, today)
        anchors = await get_anchors(conn)
    logger.info("handle_message: DB init done")
    current_anchor = get_current_anchor(anchors)

    logger.info("msg received: len=%d preview=%r", len(text or ""), _log_preview(text))
    logger.debug("msg received full: %r", text)

    # Unified slash pre-processor: DB writes + skill command extraction
    from bot.slash_preprocessor import scan_slash_commands

    _skill_registry = None
    try:
        from tether_premium.bot.skill_registry import REGISTRY as _skill_registry
    except ImportError:
        pass

    _parsed = scan_slash_commands(text, skill_registry=_skill_registry)
    _skill_commands = _parsed.skill_commands or None

    if "check-in" in _parsed.db_commands_applied:
        accomplished, status = parse_check_in(text)
        async with pg.get_conn(pool, user_id) as conn:
            await insert_check_in(conn, today, current_anchor["id"], accomplished, status)
            from datetime import datetime as _dt
            await acknowledge_followup(conn, today, current_anchor["id"], _dt.now())

    if "tether-update-context" in _parsed.db_commands_applied:
        try:
            subject, body = parse_update_context(text)
            async with pg.get_conn(pool, user_id) as conn:
                node = await ensure_node_path(conn, subject)
                await upsert_section(conn, node["id"], "details", body)
        except ValueError:
            pass

    if "update-plan" in _parsed.db_commands_applied:
        anchor_id, tasks = parse_update_plan(text)
        async with pg.get_conn(pool, user_id) as conn:
            await upsert_plan(conn, today)
            await upsert_tasks(conn, today, anchor_id, tasks, notes="")

    # /stop: interrupt any running premium session and reply, then return early.
    if text.strip() == "/stop":
        stopped = False
        try:
            from tether_premium.register import get_premium_handler
            _handler = get_premium_handler()
            if hasattr(_handler, "_session_manager"):
                mgr = _handler._session_manager
                session = mgr.get_session("default")
                if session and session.is_active:
                    loop = mgr._loop
                    if loop and loop.is_running():
                        import asyncio as _asyncio
                        fut_interrupt = _asyncio.run_coroutine_threadsafe(session.interrupt(), loop)
                        try:
                            fut_interrupt.result(timeout=5)
                        except TimeoutError:
                            fut_interrupt.cancel()
                            logger.error("handle_message: /stop — interrupt timed out, future cancelled")
                            send_fn("Could not stop the session in time — it may be stuck. Try again or wait for it to finish.")
                            return
                        fut_mark = _asyncio.run_coroutine_threadsafe(session.mark_interrupted(), loop)
                        try:
                            fut_mark.result(timeout=5)
                        except TimeoutError:
                            fut_mark.cancel()
                            logger.error("handle_message: /stop — mark_interrupted timed out, future cancelled")
                        stopped = True
        except TimeoutError:
            pass  # already handled above
        except Exception as _e:
            logger.error("handle_message: /stop error: %s", _e, exc_info=True)
            send_fn("Stop attempt failed — the session may still be running.")
            return
        if stopped:
            send_fn("Stopped. Send your next message to continue.")
        else:
            send_fn("No active session to stop.")
        return

    # All messages (including slash commands) now continue into the pipeline below.
    # The old `if text.startswith("/")` early-return path is retired.

    # --- v3 SDK path (if enabled) ---
    if _is_v3_enabled():
        # Premium plugin hook — sessions, LLM router, role dispatch, Beacon
        try:
            from tether_premium.register import get_premium_handler
            logger.info("dispatch: premium handler")
            # Record user turn before calling the handler so it's never lost
            # even if the handler raises an exception partway through.
            async with pg.get_conn(pool, user_id) as conn:
                await insert_conversation_turn(conn, "user", text)
            # Premium handler uses send_fn for Beacon notifications;
            # it returns the main response text without sending it.
            # status_fn (async) is forwarded for WebSocket real-time status pushes.
            final = await get_premium_handler()(text, pool, user_id, anchors, current_anchor,
                                               send_fn=send_fn,
                                               skill_commands=_skill_commands,
                                               status_fn=status_fn)
            if final:
                logger.info("reply sent: len=%d preview=%r", len(final), _log_preview(final))
                logger.debug("reply full: %r", final)
                send_fn(final)
                async with pg.get_conn(pool, user_id) as conn:
                    await insert_conversation_turn(conn, "assistant", final)
            else:
                logger.info("reply sent: <empty> (premium handler returned None)")
            return
        except (ImportError, NotImplementedError):
            pass  # Premium not installed or not yet wired
        except TypeError as _te:
            import traceback
            logger.error("Premium handler raised TypeError — possible bug in handler "
                         "(not a signature mismatch): %s\n%s", _te, traceback.format_exc())
            # Fall through to v3-basic as graceful degradation

        # Basic v3 single-shot (community edition — no tools, no sessions)
        try:
            final = await _handle_v3(text, pool, user_id, anchors, current_anchor,
                               skill_commands=_skill_commands,
                               conversation_id=conversation_id)
            send_fn(final)
            async with pg.get_conn(pool, user_id) as conn:
                await insert_conversation_turn(conn, "user", text)
                await insert_conversation_turn(conn, "assistant", final)
            return
        except Exception as e:
            import traceback
            logger.error("v3 path failed (%s: %s):\n%s",
                         type(e).__name__, e, traceback.format_exc())
            if not _is_v2_fallback_enabled():
                send_fn(f"[Tether error: {type(e).__name__}: {e}]")
                async with pg.get_conn(pool, user_id) as conn:
                    await insert_conversation_turn(conn, "user", text)
                return
            logger.warning("v3 FAILED — falling back to v2 pipeline")

    # --- v2 pipeline (default / fallback) ---

    # Quick-route classifier: skip the full orchestrator pipeline for simple messages
    async with pg.get_conn(pool, user_id) as conn:
        history = await get_recent_history(conn, HISTORY_EXCHANGES)
    route = await _classify_message(text, current_anchor, today)

    if route == "quick":
        final = await call_response_builder(text, [], [], history, pool, user_id, anchors)
        send_fn(final)
        async with pg.get_conn(pool, user_id) as conn:
            await insert_conversation_turn(conn, "user", text)
            await insert_conversation_turn(conn, "assistant", final)
        return

    # Free text: v2 orchestrator pipeline
    try:
        mutation_plan, reports, chat_messages, orch_conv = await _run_v2_planning_loop(
            text, anchors, history, pool, user_id, today
        )
    except RuntimeError as e:
        send_fn(str(e))
        async with pg.get_conn(pool, user_id) as conn:
            await insert_conversation_turn(conn, "user", text)
        return

    original_intent = orch_conv[0]["body"] if orch_conv else text

    for _ in range(MAX_SATISFACTION_RETRIES):
        sat = await call_satisfaction_eval(original_intent, mutation_plan, reports, pool, user_id)
        if not sat["replan_needed"]:
            break
        issues_context = "Previous attempt had issues:\n" + "\n".join(
            f"- {i}" for i in sat["issues"]
        )
        try:
            mutation_plan, reports, chat_messages, orch_conv = await _run_v2_planning_loop(
                text, anchors, history, pool, user_id, today, issues_context=issues_context
            )
        except RuntimeError:
            break

    final = await call_response_builder(text, reports, chat_messages, history, pool, user_id, anchors)
    send_fn(final)
    async with pg.get_conn(pool, user_id) as conn:
        await insert_conversation_turn(conn, "user", text)
        await insert_conversation_turn(conn, "assistant", final)


async def handle_message(text: str, send_fn: Callable[[str], None], pool, user_id: str,
                         vault=None, status_fn=None,
                         conversation_id: str | None = None) -> None:
    """Public entry point. When a vault is provided, acquires the per-user lock
    and materialises credentials into an env dict that downstream LLM calls
    merge into the spawned claude-code subprocess.

    Vault is a duck-typed object with:
      - with_lock(user_id) -> async context manager
      - materialize(user_id) -> async context manager yielding a dict[str, str]
        of env vars (e.g. {"CLAUDE_CODE_OAUTH_TOKEN": "..."})

    status_fn is an optional async callback for real-time status pushes (WebSocket
    path only). It is threaded through to the premium handler and into the SDK
    session's in-process send_status_update MCP tool.
    """
    from bot.llm import _llm_env_extras

    if vault is not None:
        async with vault.with_lock(user_id):
            async with vault.materialize(user_id) as env_extras:
                token = _llm_env_extras.set(dict(env_extras))
                try:
                    await _handle_message_body(text, send_fn, pool, user_id, status_fn=status_fn,
                                               conversation_id=conversation_id)
                finally:
                    _llm_env_extras.reset(token)
    else:
        await _handle_message_body(text, send_fn, pool, user_id, status_fn=status_fn,
                                   conversation_id=conversation_id)


# ---------------------------------------------------------------------------
# Telegram polling
# ---------------------------------------------------------------------------

def _send_telegram(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)


def _notify_api() -> None:
    try:
        requests.post("http://localhost:8000/api/notify", timeout=2)
    except Exception as e:
        logger.debug("API notify failed: %s", e)


def _load_offset() -> int:
    try:
        return int(_OFFSET_PATH.read_text().strip())
    except Exception as e:
        logger.debug("_load_offset failed, starting from 0: %s", e)
        return 0


def _save_offset(offset: int) -> None:
    try:
        _OFFSET_PATH.write_text(str(offset))
    except Exception as e:
        logger.warning("Failed to save offset: %s", e)


async def _get_anchors_and_plan(pool, user_id: str, today: str):
    async with pg.get_conn(pool, user_id) as conn:
        anchors = await get_anchors(conn)
        plan = await get_plan(conn, today)
    return anchors, plan


async def _init_followup_states(pool, user_id: str, today: str, anchor_id: str, task_ids: list, now):
    async with pg.get_conn(pool, user_id) as conn:
        for task_id in task_ids:
            await init_followup_state(conn, today, anchor_id, task_id, now)


async def _fetch_poll_credentials(pool, fernet: Fernet) -> tuple[str, str, str] | None:
    """Look up the polling user's bot token and chat_id from the DB.

    Returns (token, chat_id, user_id) for the first user who has a
    bot_token_encrypted set, or None if no user has registered a bot token.

    Phase 1 assumption: single-user deployment. The LIMIT 1 documents this
    explicitly so multi-user Phase 5 work is immediately visible.
    """
    async with pg.get_conn(pool) as conn:  # no user_id — auth schema, no RLS
        row = await conn.fetchrow(
            """
            SELECT tc.user_id, tc.telegram_chat_id, tc.bot_token_encrypted
            FROM telegram_connections tc
            WHERE tc.bot_token_encrypted IS NOT NULL
            ORDER BY tc.user_id
            LIMIT 1
            """
        )
    if row is None:
        return None
    raw_token = fernet.decrypt(bytes(row["bot_token_encrypted"])).decode()
    return raw_token, str(row["telegram_chat_id"]) if row["telegram_chat_id"] else "", str(row["user_id"])


async def _auto_link_chat(pool, user_id: str, chat_id: str) -> bool:
    """Bind chat_id to the polling user ONLY when no real binding exists.

    Uses a guarded UPDATE (not UPSERT) so that a legitimate existing binding is
    never overwritten by a stranger's first message. Returns True if the link
    was established, False if a real chat_id was already bound.
    """
    async with pg.get_conn(pool) as conn:
        return await pg_auth_queries.auto_link_chat_id(conn, user_id, chat_id)


async def _bootstrap_last_user(pool) -> dict | None:
    """Fetch the most recently active telegram-linked user from DB for cold-start."""
    async with pg.get_conn(pool) as conn:
        return await pg_auth_queries.get_most_recent_telegram_user(conn)


def run_polling(token: str, chat_id: str, poll_user_id: str | None = None) -> None:
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    pool = loop.run_until_complete(pg.create_pool())
    offset = _load_offset()
    last_anchor_id: str | None = None
    # Persist across polling cycles so followups work even when no messages arrive.
    # These get set when a message is processed and remembered for background checks.
    last_user_id: str | None = None
    last_chat_id: str | None = None
    # Bootstrap last_user_id from DB so followup pings work immediately after restart
    try:
        _bootstrap = loop.run_until_complete(_bootstrap_last_user(pool))
        if _bootstrap:
            last_user_id = _bootstrap["id"]
            last_chat_id = _bootstrap.get("telegram_chat_id")
            logger.info("run_polling: bootstrapped user_id=%s from DB", last_user_id)
    except Exception as _be:
        logger.warning("run_polling: failed to bootstrap last_user_id from DB: %s", _be)
    logger.info("Tether bot polling started (offset=%d)", offset)
    # Start premium meeting event listener if available
    try:
        from tether_premium.bot.scheduling.events import start_meeting_event_listener
        start_meeting_event_listener(
            api_base_url=tether_config.get("api.base_url", "http://localhost:8000"),
            api_token=tether_config.get("api.bot_token", ""),
        )
        logger.info("Meeting event listener started")
    except ImportError:
        pass
    while True:
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"timeout": 30, "offset": offset},
                timeout=35,
            )
            data = resp.json()
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                _save_offset(offset)
                msg = update.get("message", {})
                text = msg.get("text", "")
                incoming_chat_id = str(msg.get("chat", {}).get("id", chat_id))
                if not text:
                    continue

                send = lambda m, cid=incoming_chat_id: _send_telegram(token, cid, m)

                # Resolve user_id from chat_id
                resolved_user_id = loop.run_until_complete(_resolve_user_id(pool, incoming_chat_id))

                if resolved_user_id is None:
                    # Auto-link: the polling user's personal bot token is what
                    # we're using, so any first message to this bot belongs to them.
                    # Guard: only link when no real chat_id is bound yet (guarded
                    # UPDATE — won't overwrite an existing legitimate binding, so a
                    # stranger discovering the bot cannot hijack Jason's account).
                    if poll_user_id is not None:
                        try:
                            linked = loop.run_until_complete(
                                _auto_link_chat(pool, poll_user_id, incoming_chat_id)
                            )
                            if linked:
                                resolved_user_id = poll_user_id
                                logger.info(
                                    "Auto-linked chat_id %s to user %s on first message",
                                    incoming_chat_id, poll_user_id,
                                )
                            else:
                                # A real binding already exists for a different chat_id.
                                # Reject silently — do not reveal account details.
                                logger.warning(
                                    "Rejected message from unrecognized chat_id %s "
                                    "(user %s already linked to a different chat)",
                                    incoming_chat_id, poll_user_id,
                                )
                                continue
                        except Exception as e:
                            logger.error("Auto-link failed for chat_id %s: %s", incoming_chat_id, e)
                            send("[Tether error: could not link your chat. Please try again.]")
                            continue
                    else:
                        send("I don't recognize you. Contact your Tether administrator to link your account.")
                        continue

                try:
                    loop.run_until_complete(handle_message(text, send, pool, resolved_user_id))
                    last_user_id = resolved_user_id
                    last_chat_id = incoming_chat_id
                    _notify_api()
                except Exception as e:
                    logger.error("Error handling message: %s", e)
                    send(f"[Tether error: {e}]")

            # Detect anchor start and run follow-ups for the user who last messaged
            from datetime import datetime as _dt, date as _date
            _today = str(_date.today())
            _active_chat = last_chat_id if last_chat_id else chat_id
            _send = lambda m, cid=_active_chat: _send_telegram(token, cid, m)

            # Meeting events are PUSH-based (arrive via the WS listener into
            # an in-process queue at unpredictable times), not time-based —
            # there's no "next_due timestamp" to precompute for them, so they
            # don't fit the Redis due-time gate below at all. drain_meeting_events
            # already self-gates for free (checks its queue is non-empty before
            # ever touching Postgres — see tether_premium docstring), so it is
            # deliberately EXEMPT from the is_due() gate and always called: if
            # it were nested inside the gate, a meeting event could arrive for
            # a user with no anchor/followup due and sit un-drained until
            # something else made that user "due" again.
            if last_user_id:
                try:
                    from tether_premium.bot.scheduling.events import drain_meeting_events
                    loop.run_until_complete(drain_meeting_events(pool=pool, user_id=last_user_id, send_fn=_send))
                except ImportError:
                    pass
                except Exception as _de:
                    logger.warning("Meeting event drain failed: %s", _de)

            # Redis next-due gate — this loop ticks every ~30s (Telegram
            # long-poll timeout) regardless of whether anything is actually
            # due; without this check every tick would hit Postgres 2-3x via
            # _get_anchors_and_plan/check_followups even when idle, defeating
            # managed-Postgres (Neon) auto-suspend. See shared/notify_due.py
            # for the full scheme. Gated ONCE per user (not per sub-check) —
            # anchor-transition can create new followup rows that
            # check_followups then needs to see in the SAME pass, so splitting
            # the gate per sub-function risks skipping just-created rows via a
            # stale followup-only cache entry.
            if last_user_id and loop.run_until_complete(notify_due.is_due(last_user_id)):
                _anchors_and_plan = loop.run_until_complete(
                    _get_anchors_and_plan(pool, last_user_id, _today)
                )
                _anchors, _plan = _anchors_and_plan
                loop.run_until_complete(notify_due.set_cached_anchors(last_user_id, _anchors))
                _current_anchor = get_current_anchor(_anchors)
                _anchor_running = _current_anchor and is_anchor_active(_current_anchor)
                if not _anchor_running:
                    last_anchor_id = None
                elif _current_anchor.get("id") != last_anchor_id:
                    last_anchor_id = _current_anchor["id"]
                    if _plan and _current_anchor["id"] in _plan.get("anchors", {}):
                        loop.run_until_complete(_init_followup_states(
                            pool, last_user_id, _today, _current_anchor["id"],
                            [t["id"] for t in _plan["anchors"][_current_anchor["id"]]["tasks"] if t.get("id")],
                            _dt.now()
                        ))

                _followup_next = loop.run_until_complete(check_followups(pool, last_user_id, _send))

                # Recompute-after-run: write fresh anchor/followup next-due
                # estimates back to Redis from data just fetched above (zero
                # extra Postgres cost). Self-perpetuating — no separate
                # background refresh job needed.
                _anchor_next = notify_due.next_anchor_boundary(_anchors, _dt.now())
                if _anchor_next is not None:
                    loop.run_until_complete(
                        notify_due.set_component_due(last_user_id, "anchor", _anchor_next.timestamp())
                    )
                if _followup_next is not None:
                    loop.run_until_complete(
                        notify_due.set_component_due(last_user_id, "followup", _followup_next.timestamp())
                    )
        except Exception as e:
            logger.error("Polling error: %s", e)
            time.sleep(5)


def main() -> None:
    level_name = os.environ.get("TETHER_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    logger.info("log level: %s", level_name)

    # Load the vault key and look up the polling user's bot token from DB.
    # Per Jason's Phase 1 override: no env-var fallback. The token lives in
    # telegram_connections.bot_token_encrypted only.
    vault_key_str = tether_config.get("vault.key")
    if not vault_key_str:
        logger.error("vault.key not configured — cannot decrypt bot token")
        import sys
        sys.exit(1)
    fernet = Fernet(vault_key_str.encode() if isinstance(vault_key_str, str) else vault_key_str)

    # Soft config: per-user token not yet in DB (migration not yet run).
    # Loop until the token appears — once the ops migration script runs, the bot
    # picks it up without supervisord intervention.
    _startup_loop = asyncio.new_event_loop()
    _pool = _startup_loop.run_until_complete(pg.create_pool())
    try:
        while True:
            credentials = _startup_loop.run_until_complete(_fetch_poll_credentials(_pool, fernet))
            if credentials is not None:
                break
            logger.warning(
                "No per-user bot token found in DB. "
                "Sleeping 30 s — run scripts/migrate_telegram_to_per_user.py to resolve."
            )
            time.sleep(30)
    finally:
        _startup_loop.run_until_complete(pg.close_pool())
        _startup_loop.close()

    token, chat_id, poll_user_id = credentials
    logger.info("Polling as user %s (chat_id=%s)", poll_user_id, chat_id or "<none yet>")
    run_polling(token, chat_id, poll_user_id=poll_user_id)


if __name__ == "__main__":
    main()
