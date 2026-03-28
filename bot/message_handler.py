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
    insert_check_in,
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


def load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def call_claude(prompt: str, timeout: int = 120) -> str:
    try:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True, text=True, check=True,
            timeout=timeout,
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        raise RuntimeError("Claude took too long to respond (>120s). Try a simpler request.")


def parse_claude_response(raw: str) -> tuple[str, list[dict]]:
    """Extract message and mutations from Claude's JSON response.
    Falls back to treating raw output as the message with no mutations."""
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
            elif op == "insert_check_in":
                insert_check_in(db_path, today, m["anchor_id"],
                                m["accomplished"], m["current_status"])
            else:
                logger.warning("Unknown mutation op: %s", op)
        except Exception as e:
            logger.error("Failed to apply mutation %s: %s", m, e)


def think_and_plan(user_message: str, anchors: list[dict],
                   all_subjects: list[str], db_path: Path) -> dict:
    """Phase 0/1: reads today's plan + subjects, reasons about intent, produces ack + dispatch plan.

    Returns dict with keys:
        ack: str | None  -- message to send immediately (None for chat-only)
        dispatches: list[dict]  -- [{action, anchor_id?, date?, subjects[], instructions, prefetch_date?}]
    """
    today = str(date_type.today())
    plan = get_plan(db_path, today)
    current_anchor_obj = get_current_anchor(anchors)
    anchor_summary = "\n".join(
        f"- {a['id']}: {a['name']} ({a['time']})" for a in anchors
    )
    subjects_summary = "\n".join(f"- {s}" for s in all_subjects)
    template = _jinja.get_template("think_and_plan.md")
    prompt = template.render(
        date=today,
        current_anchor=current_anchor_obj,
        anchors=anchor_summary,
        plan=plan,
        subjects=subjects_summary,
        user_message=user_message,
    )
    try:
        raw = call_claude(prompt, timeout=45)
        cleaned = re.sub(r"```(?:json)?\s*|\s*```", "", raw).strip()
        data = json.loads(cleaned)
        return {
            "ack": data.get("ack"),
            "dispatches": data.get("dispatches", [{"action": "chat", "subjects": [], "instructions": ""}]),
        }
    except Exception as e:
        logger.warning("think_and_plan failed (%s), falling back to single chat call", e)
        return {"ack": None, "dispatches": [{"action": "chat", "subjects": [], "instructions": ""}]}


def _build_dispatch_prompt(user_message: str, db_path: Path,
                           dispatch: dict, ack: str | None) -> str:
    today = str(date_type.today())
    anchors = get_anchors(db_path)
    current_anchor = get_current_anchor(anchors)

    # Load the plan for this dispatch's target date, or today by default.
    # If the thinker flagged a prefetch_date (e.g. Sunday), load that instead.
    plan_date = dispatch.get("prefetch_date") or dispatch.get("date") or today
    plan = get_plan(db_path, plan_date)

    relevant_subjects = dispatch.get("subjects") or []
    if relevant_subjects:
        all_entries = get_context_entries(db_path)
        context_entries = [e for e in all_entries if e["subject"] in relevant_subjects]
    else:
        context_entries = get_context_entries(db_path, top_level_only=True)

    context_text = "\n\n".join(f"## {e['subject']}\n{e['body']}" for e in context_entries)

    # Build dispatch_focus from thinker's instructions if present, else derive from action
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
        dispatch_focus = None

    template = _jinja.get_template("message_handler.md")
    return template.render(
        date=plan_date,
        current_anchor=current_anchor,
        plan=plan,
        context=context_text,
        check_in_log=plan.get("check_in_log", []),
        user_message=user_message,
        ack=ack,
        dispatch_focus=dispatch_focus,
    )


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


def handle_message(text: str, send_fn: Callable[[str], None]) -> None:
    today = str(date_type.today())
    db_path = DB_PATH
    init_db(db_path)
    upsert_plan(db_path, today)

    anchors = get_anchors(db_path)
    current_anchor = get_current_anchor(anchors)

    # Slash commands: deterministic DB writes, then single Claude call for the reply
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

    # Free-text: think-and-plan phase (reads today's plan, produces ack + dispatch instructions)
    all_subjects = [e["subject"] for e in get_context_entries(db_path)]
    result = think_and_plan(text, anchors, all_subjects, db_path)
    ack = result["ack"]
    dispatches = result["dispatches"]

    has_mutations = any(d.get("action") != "chat" for d in dispatches)
    if ack and has_mutations:
        send_fn(ack)

    for dispatch in dispatches:
        try:
            prompt = _build_dispatch_prompt(text, db_path, dispatch, ack)
            raw = call_claude(prompt)
            message, mutations = parse_claude_response(raw)
            apply_mutations(mutations, db_path, today)
            if message:
                send_fn(message)
        except RuntimeError as e:
            send_fn(str(e))
            return


def _send_telegram(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)


def _notify_api() -> None:
    """Ping the local API to broadcast a WebSocket update after bot mutations."""
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
