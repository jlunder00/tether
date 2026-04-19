from fastapi import APIRouter, Depends
import asyncpg
from api.auth import auth_dependency
from db.pg_queries import get_links, create_link, delete_link
from db.pool_middleware import get_db_conn

router = APIRouter()


@router.get("/{parent_type}/{parent_id}/links")
async def get_entity_links(parent_type: str, parent_id: str,
                           _auth=Depends(auth_dependency),
                           conn: asyncpg.Connection = Depends(get_db_conn)):
    return await get_links(conn, parent_type, parent_id)


@router.post("/{parent_type}/{parent_id}/links")
async def create_entity_link(parent_type: str, parent_id: str, body: dict,
                             _auth=Depends(auth_dependency),
                             conn: asyncpg.Connection = Depends(get_db_conn)):
    return await create_link(conn, parent_type, parent_id,
                             body["url"], body.get("label"),
                             body.get("category", "other"))


@router.delete("/links/{link_id}")
async def delete_entity_link(link_id: int, _auth=Depends(auth_dependency),
                             conn: asyncpg.Connection = Depends(get_db_conn)):
    await delete_link(conn, link_id)
    return {"ok": True}
