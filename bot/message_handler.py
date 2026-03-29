from __future__ import annotations
import json
import logging
import re
import subprocess
import time
from datetime import date as date_type
from pathlib import Path
from typing import Callable

import requests
import yaml
from jinja2 import Environment, FileSystemLoader

from bot.handler_utils import (
    get_current_anchor,
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
    patch_anchor,
    upsert_context_entry,
    upsert_plan,
    upsert_tasks,
)
from db.schema import init_db

logger = logging.getLogger(__name__)

DB_PATH = Path.home() / ".tether-config" / "tether.db"
_CONFIG_PATH = Path.home() / ".tether-config" / "config.yaml"
_OFFSET_PATH = Path.home() / ".tether-config" / "telegram_offset"
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_jinja = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)), trim_blocks=True)

MAX_ORCHESTRATION_ROUNDS = 3
MAX_CONTEXT_ROUNDS = 4
HISTORY_EXCHANGES = 5


def _format_history(history: list[dict]) -> str:
    if not history:
        return "(none)"
    lines = []
    for row in history:
        label = "User" if row["role"] == "user" else "Bot"
        ts = row["ts"][:16] if row["ts"] else ""
        lines.append(f"[{ts}] {label}: {row['body']}")
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


def call_claude(prompt: str, timeout: int = 180) -> str:
    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True, text=True, check=True,
            timeout=timeout,
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
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
            else:
                logger.warning("Unknown mutation op: %s", op)
        except Exception as e:
            logger.error("Failed to apply mutation %s: %s", m, e)


# ---------------------------------------------------------------------------
# Phase 0: think_and_plan
# ---------------------------------------------------------------------------

def think_and_plan(user_message: str, anchors: list[dict],
                   all_subjects: list[str], db_path: Path,
                   history: list[dict] | None = None,
                   extra_context: list[str] | None = None,
                   round_num: int = 0,
                   force_dispatch: bool = False) -> dict:
    """Reason about the user's intent and produce either a dispatch plan or a context request.

    Returns a dict with a 'type' key:
      {"type": "dispatch",         "ack": ..., "dispatches": [...]}
      {"type": "request_context",  "requests": [...], "reason": "..."}
    """
    today = str(date_type.today())
    plan = get_plan(db_path, today)
    current_anchor_obj = get_current_anchor(anchors)
    anchor_summary = "\n".join(
        f"- {a['id']}: {a['name']} ({a['time']})" for a in anchors
    )
    subjects_summary = "\n".join(f"- {s}" for s in all_subjects)
    accumulated = "\n\n".join(extra_context) if extra_context else ""
    template = _jinja.get_template("think_and_plan.md")
    prompt = template.render(
        date=today,
        current_anchor=current_anchor_obj,
        anchors=anchor_summary,
        plan=plan,
        subjects=subjects_summary,
        user_message=user_message,
        history=_format_history(history or []),
        accumulated_context=accumulated,
        rounds_remaining=MAX_CONTEXT_ROUNDS - round_num,
        force_dispatch=force_dispatch,
    )
    _fallback = {"type": "dispatch", "ack": None,
                 "dispatches": [{"action": "chat", "subjects": [], "instructions": ""}]}
    try:
        raw = call_claude(prompt, timeout=60)
        data = _parse_json(raw)
        response_type = data.get("type", "dispatch")
        if response_type == "request_context" and not force_dispatch:
            return {
                "type": "request_context",
                "requests": data.get("requests", []),
                "reason": data.get("reason", ""),
            }
        return {
            "type": "dispatch",
            "ack": data.get("ack"),
            "dispatches": data.get("dispatches",
                                   [{"action": "chat", "subjects": [], "instructions": ""}]),
        }
    except Exception as e:
        logger.warning("think_and_plan failed (%s), falling back to single chat call", e)
        return _fallback


# ---------------------------------------------------------------------------
# Phase 1: dispatch execution (subagents)
# ---------------------------------------------------------------------------

def _build_dispatch_prompt(user_message: str, db_path: Path, dispatch: dict) -> str:
    today = str(date_type.today())
    anchors = get_anchors(db_path)
    anchor_summary = "\n".join(
        f"- {a['id']}: {a['name']} ({a['time']})" for a in anchors
    )

    plan_date = dispatch.get("prefetch_date") or dispatch.get("date") or today
    plan = get_plan(db_path, plan_date)

    relevant_subjects = dispatch.get("subjects") or []
    if relevant_subjects:
        all_entries = get_context_entries(db_path)
        context_entries = [e for e in all_entries if e["subject"] in relevant_subjects]
    else:
        context_entries = get_context_entries(db_path, top_level_only=True)

    context_text = "\n\n".join(f"## {e['subject']}\n{e['body']}" for e in context_entries)

    instructions = dispatch.get("instructions", "")
    action = dispatch.get("action", "chat")
    anchor_id = dispatch.get("anchor_id")
    if instructions:
        dispatch_focus = instructions
    elif action == "update_plan" and anchor_id:
        anchor_name = next((a["name"] for a in anchors if a["id"] == anchor_id), anchor_id)
        dispatch_focus = f"Update the task list for the '{anchor_name}' block ({anchor_id})."
    elif action == "update_context" and relevant_subjects:
        dispatch_focus = f"Update context entry: {', '.join(relevant_subjects)}."
    elif action == "update_anchor" and anchor_id:
        dispatch_focus = f"Modify the anchor definition for '{anchor_id}'."
    else:
        dispatch_focus = "Answer the user's question."

    template = _jinja.get_template("dispatch_handler.md")
    return template.render(
        date=plan_date,
        anchors=anchor_summary,
        plan=plan,
        context=context_text,
        user_message=user_message,
        dispatch_focus=dispatch_focus,
    )


def _execute_dispatch(dispatch: dict, user_message: str, db_path: Path) -> dict:
    """Run one subagent dispatch. Returns {report, mutations}."""
    today = str(date_type.today())
    try:
        prompt = _build_dispatch_prompt(user_message, db_path, dispatch)
        raw = call_claude(prompt, timeout=180)
        data = _parse_json(raw)
        report = data.get("report", "")
        mutations = data.get("mutations", [])
        apply_mutations(mutations, db_path, today)
        return {"report": report, "mutations": mutations}
    except RuntimeError as e:
        return {"report": f"FAILED: {e}", "mutations": []}
    except Exception as e:
        logger.error("_execute_dispatch error: %s", e)
        return {"report": f"FAILED: {e}", "mutations": []}


# ---------------------------------------------------------------------------
# Phase 2: evaluate completion
# ---------------------------------------------------------------------------

def _evaluate_completion(user_message: str, original_dispatches: list[dict],
                         all_reports: list[str], db_path: Path) -> dict:
    """Check if the original request was fulfilled. Returns {complete, remaining_dispatches}."""
    today = str(date_type.today())
    anchors = get_anchors(db_path)
    anchor_summary = "\n".join(
        f"- {a['id']}: {a['name']} ({a['time']})" for a in anchors
    )
    plan = get_plan(db_path, today)
    template = _jinja.get_template("orchestrator_evaluate.md")
    prompt = template.render(
        date=today,
        user_message=user_message,
        original_dispatches=json.dumps(original_dispatches, indent=2),
        all_reports=all_reports,
        plan=plan,
        anchors=anchor_summary,
    )
    try:
        raw = call_claude(prompt, timeout=45)
        data = _parse_json(raw)
        return {
            "complete": data.get("complete", True),
            "remaining_dispatches": data.get("remaining_dispatches", []),
            "assessment": data.get("assessment", ""),
        }
    except Exception as e:
        logger.warning("_evaluate_completion failed (%s), assuming complete", e)
        return {"complete": True, "remaining_dispatches": [], "assessment": ""}


# ---------------------------------------------------------------------------
# Phase 3: memory consolidation
# ---------------------------------------------------------------------------

def _consolidate_memory(user_message: str, all_reports: list[str],
                        db_path: Path) -> list[str]:
    """Ask orchestrator if any context entries should be updated. Executes memory dispatches.
    Returns list of memory reports."""
    today = str(date_type.today())
    top_entries = get_context_entries(db_path, top_level_only=True)
    context_summary = "\n\n".join(
        f"**{e['subject']}**: {e['body'][:300]}{'...' if len(e['body']) > 300 else ''}"
        for e in top_entries
    )
    template = _jinja.get_template("orchestrator_memory.md")
    prompt = template.render(
        date=today,
        user_message=user_message,
        reports=all_reports,
        context_summary=context_summary,
    )
    try:
        raw = call_claude(prompt, timeout=45)
        data = _parse_json(raw)
        memory_dispatches = data.get("memory_dispatches", [])
        if not memory_dispatches:
            return []
        reports = []
        for dispatch in memory_dispatches:
            result = _execute_dispatch(dispatch, user_message, db_path)
            reports.append(result["report"])
        return reports
    except Exception as e:
        logger.warning("_consolidate_memory failed (%s), skipping", e)
        return []


# ---------------------------------------------------------------------------
# Phase 4: final response
# ---------------------------------------------------------------------------

def _build_final_response(user_message: str, all_reports: list[str],
                          memory_reports: list[str], db_path: Path,
                          history: list[dict] | None = None) -> str:
    today = str(date_type.today())
    anchors = get_anchors(db_path)
    current_anchor = get_current_anchor(anchors)
    plan = get_plan(db_path, today)
    context_entries = get_context_entries(db_path, top_level_only=True)
    context_text = "\n\n".join(f"## {e['subject']}\n{e['body']}" for e in context_entries)
    template = _jinja.get_template("orchestrator_response.md")
    prompt = template.render(
        date=today,
        current_anchor=current_anchor,
        user_message=user_message,
        subagent_reports=all_reports,
        memory_reports=memory_reports,
        plan=plan,
        context=context_text,
        check_in_log=plan.get("check_in_log", []),
        history=_format_history(history or []),
    )
    try:
        raw = call_claude(prompt, timeout=60)
        message, mutations = parse_claude_response(raw)
        return message
    except RuntimeError as e:
        return str(e)


# ---------------------------------------------------------------------------
# Orchestrator: ties all phases together
# ---------------------------------------------------------------------------

def _orchestrate(user_message: str, dispatches: list[dict], ack: str | None,
                 db_path: Path, send_fn: Callable[[str], None],
                 history: list[dict] | None = None) -> None:
    today = str(date_type.today())
    original_dispatches = dispatches
    all_reports: list[str] = []

    has_mutations = any(d.get("action") != "chat" for d in dispatches)
    if ack and has_mutations:
        send_fn(ack)

    # Primary dispatch loop with evaluation retry
    for round_num in range(MAX_ORCHESTRATION_ROUNDS):
        for dispatch in dispatches:
            result = _execute_dispatch(dispatch, user_message, db_path)
            all_reports.append(result["report"])

        eval_result = _evaluate_completion(user_message, original_dispatches, all_reports, db_path)
        if eval_result["complete"] or round_num == MAX_ORCHESTRATION_ROUNDS - 1:
            break
        dispatches = eval_result["remaining_dispatches"]
        if not dispatches:
            break

    # Memory consolidation (optional, runs regardless of primary success)
    memory_reports = _consolidate_memory(user_message, all_reports, db_path)

    # Single final user-facing response
    final = _build_final_response(user_message, all_reports, memory_reports, db_path, history)
    send_fn(final)
    return final  # returned so handle_message can persist it to history


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
# Entry point
# ---------------------------------------------------------------------------

def handle_message(text: str, send_fn: Callable[[str], None]) -> None:
    today = str(date_type.today())
    db_path = DB_PATH
    init_db(db_path)
    upsert_plan(db_path, today)

    anchors = get_anchors(db_path)
    current_anchor = get_current_anchor(anchors)

    # Slash commands: deterministic DB writes then single Claude reply
    if text.startswith("/check-in"):
        accomplished, status = parse_check_in(text)
        insert_check_in(db_path, today, current_anchor["id"], accomplished, status)

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

    # Free text: full orchestrator pipeline
    history = get_recent_history(db_path, HISTORY_EXCHANGES)
    all_subjects = [e["subject"] for e in get_context_entries(db_path)]

    accumulated_context: list[str] = []
    result: dict = {}
    for round_num in range(MAX_CONTEXT_ROUNDS + 1):
        force = round_num == MAX_CONTEXT_ROUNDS
        result = think_and_plan(
            text, anchors, all_subjects, db_path,
            history=history,
            extra_context=accumulated_context,
            round_num=round_num,
            force_dispatch=force,
        )
        if result["type"] == "request_context" and not force:
            fetched = _fetch_requested_context(result["requests"], db_path, round_num + 1)
            accumulated_context.append(fetched)
        else:
            break

    final = _orchestrate(text, result["dispatches"], result.get("ack"), db_path, send_fn, history)
    insert_conversation_turn(db_path, "user", text)
    if final:
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
    logger.info("Tether bot polling started (offset=%d)", offset)
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
                if not text:
                    continue
                try:
                    send = lambda m: _send_telegram(token, chat_id, m)
                    handle_message(text, send)
                    _notify_api()
                except Exception as e:
                    logger.error("Error handling message: %s", e)
                    _send_telegram(token, chat_id, f"[Tether error: {e}]")
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
