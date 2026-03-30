from fastapi import APIRouter
from db.queries import get_invocation_log
import api.config as cfg

router = APIRouter()


@router.get("/logs")
async def get_logs(n: int = 5):
    return get_invocation_log(cfg.DB_PATH, n=n)
