from fastapi import APIRouter, Depends, Request
import asyncpg
from api.auth import auth_dependency
from db.pg_queries import add_dependency, remove_dependency, get_dependencies_for
from db.pool_middleware import get_db_conn

router = APIRouter()


@router.post("/dependencies")
async def create_dependency(body: dict, _auth=Depends(auth_dependency),
                            conn: asyncpg.Connection = Depends(get_db_conn)):
    dep_id = await add_dependency(conn, body["blocker_type"], body["blocker_id"],
                                  body["blocked_type"], body["blocked_id"])
    return {"id": dep_id}


@router.delete("/dependencies/{dep_id}")
async def delete_dependency(dep_id: int, _auth=Depends(auth_dependency),
                            conn: asyncpg.Connection = Depends(get_db_conn)):
    await remove_dependency(conn, dep_id)
    return {"ok": True}


@router.get("/{entity_type}/{entity_id}/dependencies")
async def get_entity_dependencies(entity_type: str, entity_id: str,
                                  _auth=Depends(auth_dependency),
                                  conn: asyncpg.Connection = Depends(get_db_conn)):
    return await get_dependencies_for(conn, entity_type, entity_id)
