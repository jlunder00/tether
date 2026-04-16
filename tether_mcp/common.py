from pathlib import Path


def get_db_path() -> Path:
    from tether_mcp.server import _db
    return _db()
