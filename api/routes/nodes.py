from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
import asyncpg
from db.pg_queries import (
    create_node, get_node, get_node_by_path, get_node_path,
    get_children, get_subtree, move_node, delete_node,
    patch_node_fields,
    get_sections, get_section, upsert_section, append_section, delete_section,
    list_section_files, create_section_file, rename_section_file, reorder_section_files,
    search_sections,
    link_task_to_node, unlink_task_from_node, get_node_tasks,
    get_auto_archivable_nodes, archive_node,
    get_user_setting,
)
from db.pg_queries.nodes import list_nodes_index
from db.pool_middleware import get_db_conn
from api.ws import manager
from api.auth import auth_dependency

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic request bodies
# ---------------------------------------------------------------------------

class CreateNodeBody(BaseModel):
    parent_id: str | None = None
    name: str
    node_type: str = "context"
    target_date: str | None = None
    status: str | None = None
    color: str | None = None


class PatchNodeBody(BaseModel):
    name: str | None = None
    archived: bool | None = None
    target_date: str | None = None
    status: str | None = None
    color: str | None = None
    description: str | None = None


class UpsertSectionBody(BaseModel):
    body: str


class AppendSectionBody(BaseModel):
    content: str


class LinkTaskBody(BaseModel):
    task_id: str


class CreateSectionFileBody(BaseModel):
    name: str
    body: str = ""


class RenameSectionFileBody(BaseModel):
    new_name: str


class ReorderSectionFilesBody(BaseModel):
    name_order: list[str]


class MoveNodeBody(BaseModel):
    new_parent_id: str | None = None


# ---------------------------------------------------------------------------
# Auto-archive
# ---------------------------------------------------------------------------

@router.post("/nodes/auto-archive")
async def auto_archive_nodes(request: Request, _auth=Depends(auth_dependency),
                             conn: asyncpg.Connection = Depends(get_db_conn)):
    uid = request.state.user_id

    raw_completed = await get_user_setting(conn, uid, "auto_archive_days_completed")
    raw_inactive = await get_user_setting(conn, uid, "auto_archive_days_inactive")

    days_completed = int(raw_completed) if raw_completed else None
    days_inactive = int(raw_inactive) if raw_inactive else None

    nodes = await get_auto_archivable_nodes(conn, days_completed=days_completed,
                                             days_inactive=days_inactive)

    for n in nodes:
        await archive_node(conn, n["id"])

    if nodes:
        await manager.broadcast({"type": "nodes_updated"}, uid)

    return {
        "archived_count": len(nodes),
        "archived_nodes": [{"id": n["id"], "name": n["name"]} for n in nodes],
    }


# ---------------------------------------------------------------------------
# Node CRUD
# ---------------------------------------------------------------------------

@router.get("/nodes")
async def list_nodes(_auth=Depends(auth_dependency),
                     conn: asyncpg.Connection = Depends(get_db_conn),
                     parent_id: str | None = None, include_archived: bool = False):
    return await get_children(conn, parent_id=parent_id, include_archived=include_archived)


@router.post("/nodes")
async def create_node_route(body: CreateNodeBody, request: Request,
                            _auth=Depends(auth_dependency),
                            conn: asyncpg.Connection = Depends(get_db_conn)):
    kwargs = {"target_date": body.target_date, "color": body.color}
    if body.status is not None:
        kwargs["status"] = body.status
    result = await create_node(conn, body.parent_id, body.name,
                               node_type=body.node_type, **kwargs)
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return result


@router.get("/nodes/by-path/{path:path}")
async def resolve_node_by_path(path: str, _auth=Depends(auth_dependency),
                               conn: asyncpg.Connection = Depends(get_db_conn)):
    node = await get_node_by_path(conn, path)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found at path")
    return node


@router.get("/search/sections")
async def search_sections_route(_auth=Depends(auth_dependency),
                                conn: asyncpg.Connection = Depends(get_db_conn),
                                q: str = "", node_id: str | None = None):
    if not q.strip():
        return []
    return await search_sections(conn, q.strip(), node_id=node_id)


@router.get("/nodes/index")
async def get_nodes_index(request: Request, _auth=Depends(auth_dependency),
                          conn: asyncpg.Connection = Depends(get_db_conn)):
    """Lightweight index: id, title, parent_id, path, child_count.

    No section data. One recursive-CTE DB query. Used by the frontend to
    build the node tree without fetching full node detail for each item.

    NOTE: registered before /{node_id} so "index" is not matched as a node id.
    """
    return await list_nodes_index(conn, user_id=request.state.user_id)


@router.get("/nodes/{node_id}")
async def get_node_route(node_id: str, _auth=Depends(auth_dependency),
                         conn: asyncpg.Connection = Depends(get_db_conn)):
    node = await get_node(conn, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@router.patch("/nodes/{node_id}")
async def patch_node_route(node_id: str, body: PatchNodeBody, request: Request,
                           _auth=Depends(auth_dependency),
                           conn: asyncpg.Connection = Depends(get_db_conn)):
    node = await get_node(conn, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    fields = body.model_dump(exclude_unset=True)
    updated = await patch_node_fields(conn, node_id, fields)

    if fields:
        await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)

    return updated


@router.delete("/nodes/{node_id}")
async def delete_node_route(node_id: str, request: Request,
                            _auth=Depends(auth_dependency),
                            conn: asyncpg.Connection = Depends(get_db_conn)):
    node = await get_node(conn, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    await delete_node(conn, node_id)
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return {"ok": True}


@router.get("/nodes/{node_id}/children")
async def get_node_children(node_id: str, _auth=Depends(auth_dependency),
                            conn: asyncpg.Connection = Depends(get_db_conn),
                            include_archived: bool = False):
    node = await get_node(conn, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return await get_children(conn, parent_id=node_id, include_archived=include_archived)


@router.get("/nodes/{node_id}/subtree")
async def get_node_subtree(node_id: str, _auth=Depends(auth_dependency),
                           conn: asyncpg.Connection = Depends(get_db_conn),
                           include_archived: bool = False):
    node = await get_node(conn, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return await get_subtree(conn, node_id, include_archived=include_archived)


@router.post("/nodes/{node_id}/move")
async def move_node_route(node_id: str, body: MoveNodeBody, request: Request,
                          _auth=Depends(auth_dependency),
                          conn: asyncpg.Connection = Depends(get_db_conn)):
    node = await get_node(conn, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    await move_node(conn, node_id, body.new_parent_id)
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return {"ok": True}


@router.get("/nodes/{node_id}/path")
async def get_node_path_route(node_id: str, _auth=Depends(auth_dependency),
                              conn: asyncpg.Connection = Depends(get_db_conn)):
    node = await get_node(conn, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    path = await get_node_path(conn, node_id)
    return {"path": path}


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

@router.get("/nodes/{node_id}/sections")
async def list_sections(node_id: str, _auth=Depends(auth_dependency),
                        conn: asyncpg.Connection = Depends(get_db_conn)):
    node = await get_node(conn, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    rows = await get_sections(conn, node_id)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["section_type"]] = counts.get(r["section_type"], 0) + 1
    return [{"section_type": t, "file_count": c} for t, c in counts.items()]


@router.get("/nodes/{node_id}/sections/{section_type}")
async def list_section_files_route(node_id: str, section_type: str,
                                   _auth=Depends(auth_dependency),
                                   conn: asyncpg.Connection = Depends(get_db_conn)):
    node = await get_node(conn, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return await list_section_files(conn, node_id, section_type)


@router.post("/nodes/{node_id}/sections/{section_type}")
async def create_section_file_route(node_id: str, section_type: str,
                                    body: CreateSectionFileBody, request: Request,
                                    _auth=Depends(auth_dependency),
                                    conn: asyncpg.Connection = Depends(get_db_conn)):
    node = await get_node(conn, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    result = await create_section_file(conn, node_id, section_type, body.name, body.body)
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return result


@router.post("/nodes/{node_id}/sections/{section_type}/reorder")
async def reorder_section_files_route(node_id: str, section_type: str,
                                      body: ReorderSectionFilesBody, request: Request,
                                      _auth=Depends(auth_dependency),
                                      conn: asyncpg.Connection = Depends(get_db_conn)):
    node = await get_node(conn, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    try:
        await reorder_section_files(conn, node_id, section_type, body.name_order)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return {"ok": True}


@router.get("/nodes/{node_id}/sections/{section_type}/{name}")
async def get_section_file_route(node_id: str, section_type: str, name: str,
                                 _auth=Depends(auth_dependency),
                                 conn: asyncpg.Connection = Depends(get_db_conn)):
    section = await get_section(conn, node_id, section_type, name=name)
    if not section:
        raise HTTPException(status_code=404, detail="Section file not found")
    return section


@router.put("/nodes/{node_id}/sections/{section_type}/{name}")
async def upsert_section_file_route(node_id: str, section_type: str, name: str,
                                    body: UpsertSectionBody, request: Request,
                                    _auth=Depends(auth_dependency),
                                    conn: asyncpg.Connection = Depends(get_db_conn)):
    node = await get_node(conn, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    result = await upsert_section(conn, node_id, section_type, body.body, name=name)
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return result


@router.post("/nodes/{node_id}/sections/{section_type}/{name}/append")
async def append_section_file_route(node_id: str, section_type: str, name: str,
                                    body: AppendSectionBody, request: Request,
                                    _auth=Depends(auth_dependency),
                                    conn: asyncpg.Connection = Depends(get_db_conn)):
    node = await get_node(conn, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    result = await append_section(conn, node_id, section_type, body.content, name=name)
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return result


@router.post("/nodes/{node_id}/sections/{section_type}/{name}/rename")
async def rename_section_file_route(node_id: str, section_type: str, name: str,
                                    body: RenameSectionFileBody, request: Request,
                                    _auth=Depends(auth_dependency),
                                    conn: asyncpg.Connection = Depends(get_db_conn)):
    node = await get_node(conn, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    try:
        result = await rename_section_file(conn, node_id, section_type, name, body.new_name)
    except ValueError as exc:
        msg = str(exc)
        if "already exists" in msg:
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=404, detail=msg)
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return result


@router.delete("/nodes/{node_id}/sections/{section_type}/{name}")
async def delete_section_file_route(node_id: str, section_type: str, name: str,
                                    request: Request, _auth=Depends(auth_dependency),
                                    conn: asyncpg.Connection = Depends(get_db_conn)):
    node = await get_node(conn, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    section = await get_section(conn, node_id, section_type, name=name)
    if not section:
        raise HTTPException(status_code=404, detail="Section file not found")
    await delete_section(conn, node_id, section_type, name=name)
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Task linking
# ---------------------------------------------------------------------------

@router.get("/nodes/{node_id}/tasks")
async def list_node_tasks(node_id: str, _auth=Depends(auth_dependency),
                          conn: asyncpg.Connection = Depends(get_db_conn)):
    node = await get_node(conn, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return await get_node_tasks(conn, node_id)


@router.post("/nodes/{node_id}/tasks")
async def link_task_route(node_id: str, body: LinkTaskBody, request: Request,
                          _auth=Depends(auth_dependency),
                          conn: asyncpg.Connection = Depends(get_db_conn)):
    node = await get_node(conn, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    await link_task_to_node(conn, node_id, body.task_id)
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return {"ok": True}


@router.delete("/nodes/{node_id}/tasks/{task_id}")
async def unlink_task_route(node_id: str, task_id: str, request: Request,
                            _auth=Depends(auth_dependency),
                            conn: asyncpg.Connection = Depends(get_db_conn)):
    node = await get_node(conn, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    await unlink_task_from_node(conn, node_id, task_id)
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return {"ok": True}
