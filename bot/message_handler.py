from __future__ import annotations
import json
import logging
import random
import re
import subprocess
import time
import uuid
from datetime import date as date_type
from pathlib import Path
from typing import Callable

import requests
import yaml
from jinja2 import Environment, FileSystemLoader

from bot.handler_utils import (
    get_current_anchor,
    is_anchor_active,
    parse_check_in,
    parse_update_context,
    parse_update_plan,
)
from db.queries import (
    get_anchors,
    get_context_entries,
    get_plan,
    get_recent_history,
    insert_check_in,
    insert_conversation_turn,
    list_plan_dates,
    log_stage,
    patch_anchor,
    upsert_context_entry,
    upsert_plan,
    upsert_tasks,
    clear_session_state,
    insert_orchestrator_turn,
    get_orchestrator_conversation,
    upsert_staging_mutation,
    get_staging_mutations,
    link_milestone_task,
    create_milestone,
    patch_milestone,
    init_followup_state,
    get_active_followup_states,
    acknowledge_followup,
    record_ping,
    mark_followup_completed,
    resolve_followup_config,
)
from db.schema import init_db

logger = logging.getLogger(__name__)


def _resolve_db_path(chat_id: str) -> Path | None:
    """Look up chat_id in auth.db and return per-user DB path, or None if not found."""
    if not AUTH_DB_PATH.exists():
        return None
    try:
        from db.auth_queries import get_user_by_telegram_chat_id
        user = get_user_by_telegram_chat_id(AUTH_DB_PATH, chat_id)
        if user:
            return Path.home() / ".tether-config" / "users" / f"{user['id']}.db"
    except Exception as e:
        logger.warning("_resolve_db_path error: %s", e)
    return None


def verify_link_code(code: str) -> str | None:
    """Verify a /link code against auth.db. Returns chat_id if valid, else None."""
    try:
        from db.auth_queries import verify_and_consume_link_code
        return verify_and_consume_link_code(AUTH_DB_PATH, code)
    except Exception as e:
        logger.warning("verify_link_code error: %s", e)
        return None

DB_PATH = Path.home() / ".tether-config" / "tether.db"
AUTH_DB_PATH = Path.home() / ".tether-config" / "auth.db"
_CONFIG_PATH = Path.home() / ".tether-config" / "config.yaml"
_OFFSET_PATH = Path.home() / ".tether-config" / "telegram_offset"

# pending link codes: code -> (chat_id, timestamp) — in-memory cache; authoritative copy is auth.db
_pending_links: dict[str, tuple[str, float]] = {}
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_jinja = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)), trim_blocks=True)

HISTORY_EXCHANGES = 5

# v2 pipeline constants
MAX_PLANNING_ROUNDS = 4
MAX_REPAIR_ATTEMPTS = 3
MAX_SATISFACTION_RETRIES = 2

# Module-level log context — set once per _run_v2_planning_loop call.
# Safe because the bot is single-threaded.
_log_ctx: dict = {"db_path": None, "session_id": None}


def _set_log_context(db_path: Path, session_id: str) -> None:
    _log_ctx["db_path"] = db_path
    _log_ctx["session_id"] = session_id


def _log_safe(stage: str, prompt: str, response: str, error: str | None = None) -> None:
    """Log a pipeline stage if log context is set. Never raises."""
    try:
        if _log_ctx["db_path"] and _log_ctx["session_id"]:
            log_stage(_log_ctx["db_path"], _log_ctx["session_id"], stage, prompt, response, error)
    except Exception:
        pass


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
        ts = row["ts"][:16] if row["ts"] else ""
        body = row["body"]
        if len(body) > _HISTORY_BODY_MAX:
            body = body[:_HISTORY_BODY_MAX] + "…"
        lines.append(f"[{ts}] {label}: {body}")
    return "\n".join(lines)


def _fetch_requested_context(requests: list[dict], db_path: Path, round_num: int) -> str:
    """Resolve a list of context requests into a formatted string block."""
    today = str(date_type.today())
    sections: list[str] = [f"## Fetched context (round {round_num})"]
    for req in requests:
        kind = req.get("kind")
        if kind == "context_entry":
            subject = req.get("subject", "")
            entries = get_context_entries(db_path, prefix=subject)
            if entries:
                for e in entries:
                    sections.append(f"### Context: {e['subject']}\n{e['body']}")
            else:
                sections.append(f"### Context: {subject}\n(not found)")
        elif kind == "plan":
            date = req.get("date", today)
            plan = get_plan(db_path, date)
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
            anchors = get_anchors(db_path)
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
            plan = get_plan(db_path, date)
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


def load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def get_model(role: str) -> str:
    """Return the model string for a pipeline role, reading from config with fallback."""
    try:
        config = load_config()
        return config.get("models", {}).get(role) or _MODEL_DEFAULTS[role]
    except Exception:
        return _MODEL_DEFAULTS.get(role, "claude-sonnet-4-6")


def call_claude(prompt: str, timeout: int = 180, model_role: str | None = None,
                stage: str = "") -> str:
    cmd = ["claude", "-p", "--strict-mcp-config"]
    if model_role is not None:
        cmd += ["--model", get_model(model_role)]
    cmd.append(prompt)
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=True, timeout=timeout,
        )
        out = result.stdout.strip()
        if stage:
            _log_safe(stage, prompt, out)
        return out
    except subprocess.TimeoutExpired:
        if stage:
            _log_safe(stage, prompt, "", f"timeout after {timeout}s")
        raise RuntimeError(f"Claude timed out after {timeout}s. Try a simpler request.")


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


def apply_mutations(mutations: list[dict], db_path: Path, today: str) -> None:
    for m in mutations:
        op = m.get("op")
        try:
            if op == "update_anchor":
                fields = {k: v for k, v in m.items() if k not in ("op", "anchor_id")}
                patch_anchor(db_path, m["anchor_id"], **fields)
            elif op == "update_plan_tasks":
                date = m.get("date", today)
                upsert_plan(db_path, date)
                upsert_tasks(db_path, date, m["anchor_id"], m["tasks"], notes="")
            elif op == "update_context":
                upsert_context_entry(db_path, m["subject"], m["body"])
            elif op == "append_context":
                entries = get_context_entries(db_path)
                entry = next((e for e in entries if e["subject"] == m["subject"]), None)
                current = entry["body"] if entry else ""
                upsert_context_entry(db_path, m["subject"],
                                     current.rstrip() + "\n\n" + m["content"])
            elif op == "patch_context":
                entries = get_context_entries(db_path)
                entry = next((e for e in entries if e["subject"] == m["subject"]), None)
                if entry:
                    new_body = entry["body"].replace(m["old"], m["new"], 1)
                    upsert_context_entry(db_path, m["subject"], new_body)
                else:
                    logger.warning("patch_context: subject %r not found", m["subject"])
            elif op == "insert_check_in":
                insert_check_in(db_path, today, m["anchor_id"],
                                m["accomplished"], m["current_status"])
            elif op == "link_milestone_tasks":
                milestone_id = m["milestone_id"]
                for task_id in m.get("task_ids", []):
                    link_milestone_task(db_path, milestone_id, task_id)
            elif op == "create_milestone":
                create_milestone(
                    db_path,
                    m["context_subject"],
                    m["name"],
                    description=m.get("description"),
                    target_date=m.get("target_date"),
                )
            elif op == "patch_milestone":
                fields = {k: v for k, v in m.items()
                          if k in {"name", "description", "target_date", "status"}}
                if fields:
                    patch_milestone(db_path, m["milestone_id"], fields)
            else:
                logger.warning("Unknown mutation op: %s", op)
        except Exception as e:
            logger.error("Failed to apply mutation %s: %s", m, e)


def check_followups(db_path: Path, send_fn) -> None:
    """Called every polling cycle. Sends batched pre/post-ack messages for due tasks."""
    from datetime import datetime, date
    now = datetime.now()
    today = str(date.today())

    def minutes_since(ts_str: str | None) -> float:
        if not ts_str:
            return float('inf')
        try:
            ts = datetime.fromisoformat(ts_str)
        except ValueError:
            return float('inf')
        return (now - ts).total_seconds() / 60

    rows = get_active_followup_states(db_path, today)
    if not rows:
        return

    pre_ack_due = []
    post_ack_due = []

    # Only ping for anchors that are currently in their time window
    all_anchors = get_anchors(db_path)
    active_anchor_ids = {a["id"] for a in all_anchors if is_anchor_active(a, now)}

    for row in rows:
        if row["anchor_id"] not in active_anchor_ids:
            continue
        config = resolve_followup_config(db_path, row["anchor_id"], row["task_id"])
        if config is None:
            continue
        if row["acknowledged_at"] is None:
            ref_ts = row["last_ping_at"] or row["sequence_started_at"]
            if (row["pre_ack_pings_sent"] < config["pre_ack_max_pings"]
                    and minutes_since(ref_ts) >= config["pre_ack_interval_min"]):
                pre_ack_due.append(row)
        else:
            ref_ts = row["last_ping_at"] or row["acknowledged_at"]
            if (row["post_ack_pings_sent"] < config["post_ack_pings"]
                    and minutes_since(ref_ts) >= config["post_ack_interval_min"]):
                post_ack_due.append(row)

    if pre_ack_due:
        from collections import defaultdict
        by_anchor: dict = defaultdict(list)
        for row in pre_ack_due:
            by_anchor[row["anchor_id"]].append(row)
        for anchor_id, anchor_rows in by_anchor.items():
            plan = get_plan(db_path, today)
            task_lines = []
            for row in anchor_rows:
                task = None
                if plan and anchor_id in plan.get("anchors", {}):
                    task = next(
                        (t for t in plan["anchors"][anchor_id]["tasks"]
                         if t["id"] == row["task_id"]), None
                    )
                task_lines.append(f"• {task['text'] if task else row['task_id']}")
            anchors = get_anchors(db_path)
            anchor_name = next((a["name"] for a in anchors if a["id"] == anchor_id), anchor_id)
            msg = (f"Your **{anchor_name}** block is underway. You haven't checked in yet on:\n"
                   + "\n".join(task_lines)
                   + "\n\n`/check-in` when you're on it.")
            send_fn(msg)
            for row in anchor_rows:
                record_ping(db_path, row["id"], "pre", now)

    if post_ack_due:
        from collections import defaultdict
        by_anchor: dict = defaultdict(list)
        for row in post_ack_due:
            by_anchor[row["anchor_id"]].append(row)
        for anchor_id, anchor_rows in by_anchor.items():
            plan = get_plan(db_path, today)
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
            anchors = get_anchors(db_path)
            anchor_name = next((a["name"] for a in anchors if a["id"] == anchor_id), anchor_id)
            msg = (f"Quick check — progress on **{anchor_name}**:\n"
                   + "\n".join(task_lines)
                   + "\n\nWhat have you knocked out?")
            send_fn(msg)
            for row in anchor_rows:
                record_ping(db_path, row["id"], "post", now)


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

def call_orchestrator(
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
    return call_claude(prompt, timeout=60, model_role="orchestrator", stage=stage)


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


def call_meta_eval(
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
        raw = call_claude(prompt, timeout=45, model_role="meta_eval",
                          stage=f"meta_eval_{round_num}")
        return _parse_json(raw)
    except Exception:
        pass

    valid_anchor_ids = [a["id"] for a in anchors]
    repair_prompt = _build_repair_prompt(
        raw, recent_conv, all_subjects, valid_anchor_ids, available_dates
    )
    for attempt in range(MAX_REPAIR_ATTEMPTS):
        role = "meta_eval_repair_escalate" if attempt == MAX_REPAIR_ATTEMPTS - 1 else "meta_eval_repair"
        try:
            repaired = call_claude(repair_prompt, timeout=45, model_role=role,
                                   stage=f"meta_eval_repair_{round_num}_{attempt}")
            return _parse_json(repaired)
        except Exception:
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

def _dispatch_single_subagent(
    mutation: dict, orchestrator_briefing: str, db_path: Path, today: str
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
        entries = get_context_entries(db_path, prefix=subject)
        current_body = next((e["body"] for e in entries if e["subject"] == subject), "(not found)")
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
        raw = call_claude(prompt, timeout=120, model_role="execution_subagent",
                          stage=f"subagent_{op_type}")
        data = _parse_json(raw)
        report = data.get("report", "")
        db_mutation = {k: v for k, v in data.items() if k != "report"}
        if db_mutation.get("op"):
            apply_mutations([db_mutation], db_path, today)
        return report or f"[{op_type}] completed"
    except Exception as e:
        logger.error("Subagent dispatch failed for %r: %s", op_type, e)
        return f"FAILED [{op_type}]: {e}"


def dispatch_typed_subagents(
    mutation_plan: list[dict],
    orchestrator_briefing: str,
    db_path: Path,
) -> tuple[list[str], list[str]]:
    """Dispatch all non-chat mutations. Returns (reports, chat_messages)."""
    today = str(date_type.today())
    reports: list[str] = []
    chat_messages: list[str] = []
    for mutation in mutation_plan:
        if mutation.get("type") == "chat":
            chat_messages.append(mutation.get("message", mutation.get("description", "")))
            continue
        reports.append(_dispatch_single_subagent(mutation, orchestrator_briefing, db_path, today))
    return reports, chat_messages


# ---------------------------------------------------------------------------
# v2 Pipeline: satisfaction eval + response builder
# ---------------------------------------------------------------------------

def call_satisfaction_eval(
    original_intent: str,
    mutation_plan: list[dict],
    reports: list[str],
    db_path: Path,
) -> dict:
    """Verify mutations accomplished the stated intent."""
    today = str(date_type.today())
    plan = get_plan(db_path, today)
    db_state = f"Today's plan:\n{_format_plan_human_readable(plan)}"
    template = _jinja.get_template("satisfaction_eval.md")
    prompt = template.render(
        original_intent=original_intent,
        mutation_plan_description=_format_mutation_plan_human_readable(mutation_plan),
        subagent_reports="\n".join(f"- {r}" for r in reports) if reports else "(none)",
        db_state=db_state,
    )
    try:
        raw = call_claude(prompt, timeout=45, model_role="satisfaction_eval",
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


def call_response_builder(
    user_message: str,
    reports: list[str],
    chat_messages: list[str],
    history: list[dict],
    db_path: Path,
    anchors: list[dict],
) -> str:
    """Build the final user-facing Telegram message."""
    today = str(date_type.today())
    current_anchor = get_current_anchor(anchors)
    plan = get_plan(db_path, today)
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
        raw = call_claude(prompt, timeout=60, model_role="response_builder",
                          stage="response_builder")
        data = _parse_json(raw)
        return data.get("message", raw)
    except RuntimeError as e:
        return str(e)
    except Exception:
        return raw


# ---------------------------------------------------------------------------
# Quick-route classifier
# ---------------------------------------------------------------------------

def _classify_message(text: str, current_anchor: dict, today: str) -> str:
    """Return 'quick' or 'full' based on whether the message needs the orchestrator."""
    template = _jinja.get_template("quick_classifier.md")
    prompt = template.render(
        user_message=text,
        current_anchor=current_anchor,
        date=today,
    )
    try:
        raw = call_claude(prompt, timeout=15, model_role="quick_classifier",
                          stage="quick_classifier")
        data = _parse_json(raw)
        route = data.get("route", "full")
        return route if route in ("quick", "full") else "full"
    except Exception:
        return "full"  # default to full pipeline on any error


# ---------------------------------------------------------------------------
# Slash-command path (deterministic, single Claude call)
# ---------------------------------------------------------------------------

def _build_slash_prompt(user_message: str, db_path: Path) -> str:
    today = str(date_type.today())
    anchors = get_anchors(db_path)
    current_anchor = get_current_anchor(anchors)
    plan = get_plan(db_path, today)
    context_entries = get_context_entries(db_path, top_level_only=True)
    context_text = "\n\n".join(f"## {e['subject']}\n{e['body']}" for e in context_entries)
    template = _jinja.get_template("message_handler.md")
    return template.render(
        date=today,
        current_anchor=current_anchor,
        plan=plan,
        context=context_text,
        check_in_log=plan.get("check_in_log", []),
        user_message=user_message,
        ack=None,
        dispatch_focus=None,
    )


# ---------------------------------------------------------------------------
# v2 Pipeline: planning loop helper
# ---------------------------------------------------------------------------

def _run_v2_planning_loop(
    text: str,
    anchors: list[dict],
    history: list[dict],
    db_path: Path,
    today: str,
    issues_context: str = "",
) -> tuple[list[dict], list[str], list[str], list[dict]]:
    """Run orchestrator → meta-eval loop then dispatch subagents.

    Returns (mutation_plan, reports, chat_messages, orchestrator_conv).
    Raises RuntimeError if parse errors exceed threshold.
    """
    all_subjects = [e["subject"] for e in get_context_entries(db_path)]
    available_dates = list(dict.fromkeys([today] + list_plan_dates(db_path)))
    session_id = str(uuid.uuid4())
    clear_session_state(db_path, session_id)
    _set_log_context(db_path, session_id)

    orchestrator_conv: list[dict] = []
    current_mutation_plan: list[dict] = []
    fetched_context_log: list[str] = []
    last_meta_summary = issues_context
    last_fetched = ""
    parse_error_count = 0

    for round_num in range(MAX_PLANNING_ROUNDS + 1):
        force_done = round_num == MAX_PLANNING_ROUNDS

        orch_response = call_orchestrator(
            user_message=text,
            plan=get_plan(db_path, today),
            subjects=all_subjects,
            history=history,
            conversation=orchestrator_conv,
            meta_eval_summary=last_meta_summary,
            fetched_context=last_fetched,
            anchors=anchors,
            stage=f"orchestrator_{round_num}",
        )
        orchestrator_conv.append({"role": "orchestrator", "body": orch_response, "round": round_num})
        insert_orchestrator_turn(db_path, session_id, "orchestrator", orch_response, round_num)

        meta = call_meta_eval(
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
            last_fetched = _fetch_requested_context(context_requests, db_path, round_num + 1)
            fetched_context_log.append(last_fetched)
        else:
            last_fetched = ""

        if meta.get("orchestrator_done") or force_done:
            break

    orchestrator_briefing = _summarize_orchestrator_conv(orchestrator_conv)
    reports, chat_messages = dispatch_typed_subagents(current_mutation_plan, orchestrator_briefing, db_path)
    return current_mutation_plan, reports, chat_messages, orchestrator_conv


# ---------------------------------------------------------------------------
# v3 SDK path
# ---------------------------------------------------------------------------

def _is_v3_enabled() -> bool:
    """Check if v3 SDK conversation loop is enabled in config."""
    try:
        config = load_config()
        return bool(config.get("llm", {}).get("use_v3", False))
    except Exception:
        return False


def _handle_v3(text: str, db_path: Path, anchors: list[dict],
               current_anchor: dict) -> str:
    """Run the v3 SDK conversation loop. Returns the response text."""
    import asyncio
    from bot.conversation import handle_message as v3_handle
    from bot.llm import LLMRouter
    from bot.tools import load_tools, make_tool_executor
    from bot.memory import read_session_notes

    config = load_config()
    llm_config = config.get("llm", {})

    router = LLMRouter()
    tools = load_tools()
    tool_schemas = [t.to_api_schema() for t in tools]
    executor = make_tool_executor(tools, db_path=str(db_path))

    today = str(date_type.today())
    plan = get_plan(db_path, today)
    subjects = [e["subject"] for e in get_context_entries(db_path)]
    history = get_recent_history(db_path, HISTORY_EXCHANGES)

    # Compact plan for system prompt
    plan_lines = []
    for anchor_id, data in plan.get("anchors", {}).items():
        tasks = data.get("tasks", [])
        task_strs = [f"[{t.get('status', '?')[:1]}] {t.get('text', '')}" for t in tasks]
        plan_lines.append(f"{anchor_id}: {' | '.join(task_strs) or 'empty'}")

    notes_path = str(Path.home() / ".tether-config" / ".session-notes.md")
    session_notes = read_session_notes(notes_path)

    # Convert history to messages format
    conv_history = []
    for h in history:
        conv_history.append({
            "role": "user" if h["role"] == "user" else "assistant",
            "content": h["body"],
        })

    model_quick = config.get("models", {}).get("quick_classifier", "claude-haiku-4-5-20251001")
    model_full = config.get("models", {}).get("orchestrator", "claude-sonnet-4-6")

    result = asyncio.run(v3_handle(
        user_text=text,
        router=router,
        db_path=str(db_path),
        anchor_name=current_anchor.get("name", "General"),
        anchor_time=current_anchor.get("time", "00:00"),
        plan_summary="\n".join(plan_lines) or "No plan data.",
        context_subjects=subjects,
        session_notes=session_notes,
        conversation_history=conv_history,
        tools=tool_schemas,
        tool_executor=executor,
        model_quick=model_quick,
        model_full=model_full,
    ))
    return result


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def handle_message(text: str, send_fn: Callable[[str], None], db_path: Path = DB_PATH) -> None:
    today = str(date_type.today())
    init_db(db_path)
    upsert_plan(db_path, today)

    anchors = get_anchors(db_path)
    current_anchor = get_current_anchor(anchors)

    # Slash commands: deterministic DB writes then single Claude reply
    if text.startswith("/check-in"):
        accomplished, status = parse_check_in(text)
        insert_check_in(db_path, today, current_anchor["id"], accomplished, status)
        from datetime import datetime as _dt
        acknowledge_followup(db_path, today, current_anchor["id"], _dt.now())

    elif text.startswith("/tether-update-context"):
        try:
            subject, body = parse_update_context(text)
            upsert_context_entry(db_path, subject, body)
        except ValueError:
            pass

    elif text.startswith("/update-plan"):
        anchor_id, tasks = parse_update_plan(text)
        upsert_plan(db_path, today)
        upsert_tasks(db_path, today, anchor_id, tasks, notes="")

    if text.startswith("/"):
        try:
            raw = call_claude(_build_slash_prompt(text, db_path))
            message, mutations = parse_claude_response(raw)
            apply_mutations(mutations, db_path, today)
            send_fn(message)
        except RuntimeError as e:
            send_fn(str(e))
        return

    # --- v3 SDK path (if enabled) ---
    if _is_v3_enabled():
        try:
            final = _handle_v3(text, db_path, anchors, current_anchor)
            send_fn(final)
            insert_conversation_turn(db_path, "user", text)
            insert_conversation_turn(db_path, "assistant", final)
            return
        except Exception as e:
            logger.warning("v3 path failed, falling back to v2: %s", e)
            # Fall through to v2 pipeline

    # --- v2 pipeline (default / fallback) ---

    # Quick-route classifier: skip the full orchestrator pipeline for simple messages
    history = get_recent_history(db_path, HISTORY_EXCHANGES)
    route = _classify_message(text, current_anchor, today)

    if route == "quick":
        final = call_response_builder(text, [], [], history, db_path, anchors)
        send_fn(final)
        insert_conversation_turn(db_path, "user", text)
        insert_conversation_turn(db_path, "assistant", final)
        return

    # Free text: v2 orchestrator pipeline
    try:
        mutation_plan, reports, chat_messages, orch_conv = _run_v2_planning_loop(
            text, anchors, history, db_path, today
        )
    except RuntimeError as e:
        send_fn(str(e))
        insert_conversation_turn(db_path, "user", text)
        return

    original_intent = orch_conv[0]["body"] if orch_conv else text

    for _ in range(MAX_SATISFACTION_RETRIES):
        sat = call_satisfaction_eval(original_intent, mutation_plan, reports, db_path)
        if not sat["replan_needed"]:
            break
        issues_context = "Previous attempt had issues:\n" + "\n".join(
            f"- {i}" for i in sat["issues"]
        )
        try:
            mutation_plan, reports, chat_messages, orch_conv = _run_v2_planning_loop(
                text, anchors, history, db_path, today, issues_context=issues_context
            )
        except RuntimeError:
            break

    final = call_response_builder(text, reports, chat_messages, history, db_path, anchors)
    send_fn(final)
    insert_conversation_turn(db_path, "user", text)
    insert_conversation_turn(db_path, "assistant", final)


# ---------------------------------------------------------------------------
# Telegram polling
# ---------------------------------------------------------------------------

def _send_telegram(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)


def _notify_api() -> None:
    try:
        requests.post("http://localhost:8000/api/notify", timeout=2)
    except Exception:
        pass


def _load_offset() -> int:
    try:
        return int(_OFFSET_PATH.read_text().strip())
    except Exception:
        return 0


def _save_offset(offset: int) -> None:
    try:
        _OFFSET_PATH.write_text(str(offset))
    except Exception as e:
        logger.warning("Failed to save offset: %s", e)


def run_polling(token: str, chat_id: str) -> None:
    offset = _load_offset()
    last_anchor_id: str | None = None
    logger.info("Tether bot polling started (offset=%d)", offset)
    while True:
        try:
            resp = requests.get(
                f"https://api.telegram.org/bot{token}/getUpdates",
                params={"timeout": 30, "offset": offset},
                timeout=35,
            )
            data = resp.json()
            last_message_db_path: Path | None = None
            last_message_chat_id: str | None = None
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                _save_offset(offset)
                msg = update.get("message", {})
                text = msg.get("text", "")
                incoming_chat_id = str(msg.get("chat", {}).get("id", chat_id))
                if not text:
                    continue

                send = lambda m, cid=incoming_chat_id: _send_telegram(token, cid, m)

                # Handle /start and /link before auth check
                if text.strip() in ("/start", "/link"):
                    try:
                        from db.auth_queries import store_link_code
                        from db.auth_schema import init_auth_db
                        if not AUTH_DB_PATH.exists():
                            AUTH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                            init_auth_db(AUTH_DB_PATH)
                        code = f"{random.randint(0, 999999):06d}"
                        store_link_code(AUTH_DB_PATH, code, incoming_chat_id)
                        send(f"Your link code is: {code}. Enter this in Tether settings within 5 minutes.")
                    except Exception as e:
                        logger.error("Error handling /link: %s", e)
                        send("[Tether error generating link code]")
                    continue

                # Resolve per-user DB path from chat_id
                resolved_db = _resolve_db_path(incoming_chat_id)
                if resolved_db is None:
                    send(
                        "I don't recognize you. Link your Tether account at your Tether URL, "
                        "then use /link to connect."
                    )
                    continue

                try:
                    handle_message(text, send, db_path=resolved_db)
                    last_message_db_path = resolved_db
                    last_message_chat_id = incoming_chat_id
                    _notify_api()
                except Exception as e:
                    logger.error("Error handling message: %s", e)
                    send(f"[Tether error: {e}]")

            # Detect anchor start and run follow-ups for the user who last messaged
            from datetime import datetime as _dt, date as _date
            _today = str(_date.today())
            _active_db = last_message_db_path if last_message_db_path else DB_PATH
            _active_chat = last_message_chat_id if last_message_chat_id else chat_id
            _send = lambda m, cid=_active_chat: _send_telegram(token, cid, m)
            _current_anchor = get_current_anchor(get_anchors(_active_db))
            _anchor_running = _current_anchor and is_anchor_active(_current_anchor)
            if not _anchor_running:
                last_anchor_id = None
            elif _current_anchor.get("id") != last_anchor_id:
                last_anchor_id = _current_anchor["id"]
                _plan = get_plan(_active_db, _today)
                if _plan and _current_anchor["id"] in _plan.get("anchors", {}):
                    for _task in _plan["anchors"][_current_anchor["id"]]["tasks"]:
                        if _task.get("id"):
                            init_followup_state(_active_db, _today, _current_anchor["id"],
                                                _task["id"], _dt.now())
            # Run follow-up pings for the active user's DB
            check_followups(_active_db, _send)
        except Exception as e:
            logger.error("Polling error: %s", e)
            time.sleep(5)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    config = load_config()
    token = config["telegram"]["bot_token"]
    chat_id = str(config["telegram"]["chat_id"])
    run_polling(token, chat_id)


if __name__ == "__main__":
    main()
