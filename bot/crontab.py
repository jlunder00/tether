from __future__ import annotations
import subprocess
from pathlib import Path

from db.queries import get_anchors

MARKER_START = "# TETHER_START"
MARKER_END = "# TETHER_END"
_VENV_PYTHON = Path.home() / "tether" / ".venv" / "bin" / "python"


def _anchor_to_cron(anchor: dict) -> str:
    h, m = map(int, anchor["time"].split(":"))
    return f"{m} {h} * * * {_VENV_PYTHON} -m bot.anchor_trigger {anchor['id']}"


def sync_crontab(db_path: Path) -> None:
    """Rewrite the tether-managed crontab section from current DB anchors."""
    anchors = get_anchors(db_path)

    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    existing = result.stdout if result.returncode == 0 else ""

    # Strip old tether section
    kept, inside = [], False
    for line in existing.splitlines():
        if line.strip() == MARKER_START:
            inside = True
        elif line.strip() == MARKER_END:
            inside = False
        elif not inside:
            kept.append(line)

    tether = [MARKER_START] + [_anchor_to_cron(a) for a in anchors] + [MARKER_END]
    new_crontab = "\n".join(kept + tether) + "\n"
    subprocess.run(["crontab", "-"], input=new_crontab, text=True, check=True)
