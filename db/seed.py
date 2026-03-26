#!/usr/bin/env python3
"""
Seed tether.db from existing YAML config files.
Safe to re-run — uses INSERT OR IGNORE / upsert patterns.
Usage: python -m db.seed [--config-dir ~/.tether-config]
"""
from __future__ import annotations
import argparse
from pathlib import Path
import yaml

from db.schema import init_db
from db.queries import upsert_anchor, upsert_plan, upsert_tasks, upsert_context_entry


def seed(config_dir: Path) -> None:
    db_path = config_dir / "tether.db"
    init_db(db_path)
    print(f"[seed] DB at {db_path}")

    anchors_file = config_dir / "anchors.yaml"
    if anchors_file.exists():
        data = yaml.safe_load(anchors_file.read_text())
        for i, anchor in enumerate(data.get("anchors", [])):
            anchor["position"] = i
            anchor.setdefault("strictness", 3)
            upsert_anchor(db_path, anchor)
        print(f"[seed] Seeded {len(data['anchors'])} anchors")

    plan_file = config_dir / "plan.yaml"
    if plan_file.exists():
        plan = yaml.safe_load(plan_file.read_text())
        date = str(plan["date"])
        upsert_plan(db_path, date)
        for anchor_id, anchor_data in plan.get("anchors", {}).items():
            upsert_tasks(db_path, date, anchor_id,
                         tasks=anchor_data.get("tasks", []),
                         notes=anchor_data.get("notes", "") or "")
        print(f"[seed] Seeded plan for {date}")

    context_file = config_dir / "context.md"
    if context_file.exists():
        body = context_file.read_text()
        upsert_context_entry(db_path, "General", body)
        print("[seed] Seeded context.md as 'General' context entry")

    print("[seed] Done.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-dir", default=str(Path.home() / ".tether-config"))
    args = parser.parse_args()
    seed(Path(args.config_dir))


if __name__ == "__main__":
    main()
