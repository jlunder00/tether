from fastapi import APIRouter, Depends
import asyncpg
from db.pg_queries import get_last_bot_activity
from db.pool_middleware import get_db_conn
from api.auth import auth_dependency

router = APIRouter()


@router.get("/bot/health")
async def bot_health(_auth=Depends(auth_dependency),
                     conn: asyncpg.Connection = Depends(get_db_conn)):
    activity = await get_last_bot_activity(conn)
    if not activity:
        return {"status": "unknown", "last_activity": None}
    from datetime import datetime, timezone
    try:
        ts = datetime.fromisoformat(activity["ts"])
        age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
    except (ValueError, TypeError):
        age_min = float("inf")
    status = "ok" if age_min < 5 else "stale" if age_min < 30 else "offline"
    return {"status": status, "last_activity": activity}
