from fastapi import APIRouter, Depends
import asyncpg
from db.pg_queries import get_invocation_log
from db.pool_middleware import get_db_conn
from api.auth import auth_dependency

router = APIRouter()


@router.get("/logs")
async def get_logs(_auth=Depends(auth_dependency),
                   conn: asyncpg.Connection = Depends(get_db_conn),
                   n: int = 5):
    return await get_invocation_log(conn, n=n)
