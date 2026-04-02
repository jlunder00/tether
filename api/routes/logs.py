from fastapi import APIRouter, Depends, Request
from db.queries import get_invocation_log
from api.auth import auth_dependency
import api.config as cfg

router = APIRouter()


@router.get("/logs")
async def get_logs(request: Request, _auth=Depends(auth_dependency), n: int = 5):
    return get_invocation_log(request.state.db_path, n=n)
