#!/usr/bin/env python3
"""Cron-invoked: sends anchor transition message to Telegram."""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

import requests
import yaml

from bot.plan_reader import load_context, load_plan
from bot.prompt_builder import build_anchor_prompt

CONFIG_DIR = Path.home() / ".tether-config"
PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def load_config() -> dict:
    with open(CONFIG_DIR / "config.yaml") as f:
        return yaml.safe_load(f)


def call_claude(prompt: str) -> str:
    result = subprocess.run(
        ["claude", "-p", prompt],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def send_telegram(bot_token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    resp = requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
    resp.raise_for_status()


async def trigger_anchor(anchor_id: str) -> None:
    user_id = os.environ.get("TETHER_USER_ID")
    if not user_id:
        print("[tether] TETHER_USER_ID not set", file=sys.stderr)
        sys.exit(1)

    import db.postgres as pg
    from db.pg_queries import anchors as anchors_module

    pool = await pg.create_pool()
    try:
        async with pg.get_conn(pool, user_id) as conn:
            anchors_list = await anchors_module.get_anchors(conn)
        anchors = {a["id"]: a for a in anchors_list}

        if anchor_id not in anchors:
            print(f"[tether] unknown anchor: {anchor_id}", file=sys.stderr)
            sys.exit(1)

        anchor = anchors[anchor_id]
        plan = await load_plan(pool, user_id)
        context = await load_context(pool, user_id)
    finally:
        await pool.close()

    anchor_plan = plan.anchors.get(anchor_id)
    if anchor_plan is None:
        return  # anchor not scheduled today — skip silently

    config = load_config()
    prompt = build_anchor_prompt(
        templates_dir=PROMPTS_DIR,
        anchor_id=anchor_id,
        anchor_name=anchor["name"],
        anchor_plan=anchor_plan,
        day_plan=plan,
        context=context,
    )

    message = call_claude(prompt)
    send_telegram(
        bot_token=config["telegram"]["bot_token"],
        chat_id=config["telegram"]["chat_id"],
        text=message,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Tether anchor trigger")
    parser.add_argument("anchor_id", help="Anchor to trigger (e.g. grind_am)")
    args = parser.parse_args()
    asyncio.run(trigger_anchor(args.anchor_id))


if __name__ == "__main__":
    main()
