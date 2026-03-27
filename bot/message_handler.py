from __future__ import annotations
import json
import logging
import re
import subprocess
import time
from datetime import date as date_type
from pathlib import Path

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
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_jinja = Environment(loader=FileSystemLoader(str(PROMPTS_DIR)), trim_blocks=True)


def load_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)


def call_claude(prompt: str) -> str:
    result = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True, check=True)
    return result.stdout.strip()


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


def _build_prompt(user_message: str, db_path: Path) -> str:
    today = str(date_type.today())
    init_db(db_path)
    upsert_plan(db_path, today)

    anchors = get_anchors(db_path)
    current_anchor = get_current_anchor(anchors)
    plan = get_plan(db_path, today)
    context_entries = get_context_entries(db_path)
    context_text = "\n\n".join(f"## {e['subject']}\n{e['body']}" for e in context_entries)

    template = _jinja.get_template("message_handler.md")
    return template.render(
        date=today,
        current_anchor=current_anchor,
        plan=plan,
        context=context_text,
        check_in_log=plan.get("check_in_log", []),
        user_message=user_message,
    )


def handle_message(text: str) -> str:
    today = str(date_type.today())
    db_path = DB_PATH
    anchors = get_anchors(db_path)
    current_anchor = get_current_anchor(anchors)

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

    raw = call_claude(_build_prompt(text, db_path))
    message, mutations = parse_claude_response(raw)
    apply_mutations(mutations, db_path, today)
    return message


def _send_telegram(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)


def run_polling(token: str, chat_id: str) -> None:
    offset = 0
    logger.info("Tether bot polling started")
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
                msg = update.get("message", {})
                text = msg.get("text", "")
                if not text:
                    continue
                try:
                    reply = handle_message(text)
                    _send_telegram(token, chat_id, reply)
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
