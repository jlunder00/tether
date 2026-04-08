from fastapi import APIRouter, Depends, Request
from db.queries import get_last_bot_activity
from api.auth import auth_dependency

router = APIRouter()


@router.get("/bot/health")
async def bot_health(request: Request, _auth=Depends(auth_dependency)):
    activity = get_last_bot_activity(request.state.db_path)
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
