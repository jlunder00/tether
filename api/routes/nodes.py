from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from db.queries import (
    create_node, get_node, get_node_by_path, get_node_path,
    get_children, get_subtree, move_node, rename_node, delete_node,
    archive_node, unarchive_node,
    get_sections, get_section, upsert_section, append_section, delete_section,
    search_sections,
    link_task_to_node, unlink_task_from_node, get_node_tasks, get_task_nodes,
    get_milestone_nodes,
)
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


class UpsertSectionBody(BaseModel):
    body: str


class AppendSectionBody(BaseModel):
    content: str


class LinkTaskBody(BaseModel):
    task_id: str


class MoveNodeBody(BaseModel):
    new_parent_id: str | None = None


# ---------------------------------------------------------------------------
# Node CRUD
# ---------------------------------------------------------------------------

@router.get("/nodes")
async def list_nodes(
    request: Request,
    _auth=Depends(auth_dependency),
    parent_id: str | None = None,
    include_archived: bool = False,
):
    return get_children(request.state.db_path, parent_id=parent_id, include_archived=include_archived)


@router.post("/nodes")
async def create_node_route(
    body: CreateNodeBody,
    request: Request,
    _auth=Depends(auth_dependency),
):
    kwargs = {}
    if body.target_date is not None:
        kwargs["target_date"] = body.target_date
    if body.status is not None:
        kwargs["status"] = body.status
    if body.color is not None:
        kwargs["color"] = body.color
    result = create_node(
        request.state.db_path, body.parent_id, body.name,
        node_type=body.node_type, **kwargs,
    )
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return result


@router.get("/nodes/by-path/{path:path}")
async def resolve_node_by_path(
    path: str,
    request: Request,
    _auth=Depends(auth_dependency),
):
    node = get_node_by_path(request.state.db_path, path)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found at path")
    return node


@router.get("/search/sections")
async def search_sections_route(
    request: Request,
    _auth=Depends(auth_dependency),
    q: str = "",
    node_id: str | None = None,
):
    if not q.strip():
        return []
    return search_sections(request.state.db_path, q.strip(), node_id=node_id)


@router.get("/nodes/{node_id}")
async def get_node_route(
    node_id: str,
    request: Request,
    _auth=Depends(auth_dependency),
):
    node = get_node(request.state.db_path, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@router.patch("/nodes/{node_id}")
async def patch_node_route(
    node_id: str,
    body: PatchNodeBody,
    request: Request,
    _auth=Depends(auth_dependency),
):
    # Verify node exists
    node = get_node(request.state.db_path, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    changed = False

    if body.name is not None:
        rename_node(request.state.db_path, node_id, body.name)
        changed = True

    if body.archived is True:
        archive_node(request.state.db_path, node_id)
        changed = True
    elif body.archived is False:
        unarchive_node(request.state.db_path, node_id)
        changed = True

    # Handle fields that need direct SQL (target_date, status, color)
    direct_updates: dict[str, str | None] = {}
    if body.target_date is not None:
        direct_updates["target_date"] = body.target_date
    if body.status is not None:
        direct_updates["status"] = body.status
        direct_updates["status_override"] = "1"
    if body.color is not None:
        direct_updates["color"] = body.color

    if direct_updates:
        from db.schema import get_db
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        direct_updates["updated_at"] = now
        set_clause = ", ".join(f"{k}=?" for k in direct_updates)
        with get_db(request.state.db_path) as conn:
            conn.execute(
                f"UPDATE context_nodes SET {set_clause} WHERE id=?",
                (*direct_updates.values(), node_id),
            )
        changed = True

    if changed:
        await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)

    return get_node(request.state.db_path, node_id)


@router.delete("/nodes/{node_id}")
async def delete_node_route(
    node_id: str,
    request: Request,
    _auth=Depends(auth_dependency),
):
    node = get_node(request.state.db_path, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    delete_node(request.state.db_path, node_id)
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return {"ok": True}


@router.get("/nodes/{node_id}/children")
async def get_node_children(
    node_id: str,
    request: Request,
    _auth=Depends(auth_dependency),
    include_archived: bool = False,
):
    return get_children(request.state.db_path, parent_id=node_id, include_archived=include_archived)


@router.get("/nodes/{node_id}/subtree")
async def get_node_subtree(
    node_id: str,
    request: Request,
    _auth=Depends(auth_dependency),
    include_archived: bool = False,
):
    return get_subtree(request.state.db_path, node_id, include_archived=include_archived)


@router.post("/nodes/{node_id}/move")
async def move_node_route(
    node_id: str,
    body: MoveNodeBody,
    request: Request,
    _auth=Depends(auth_dependency),
):
    node = get_node(request.state.db_path, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    move_node(request.state.db_path, node_id, body.new_parent_id)
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return {"ok": True}


@router.get("/nodes/{node_id}/path")
async def get_node_path_route(
    node_id: str,
    request: Request,
    _auth=Depends(auth_dependency),
):
    node = get_node(request.state.db_path, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    path = get_node_path(request.state.db_path, node_id)
    return {"path": path}


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

@router.get("/nodes/{node_id}/sections")
async def list_sections(
    node_id: str,
    request: Request,
    _auth=Depends(auth_dependency),
):
    return get_sections(request.state.db_path, node_id)


@router.get("/nodes/{node_id}/sections/{section_type}")
async def get_section_route(
    node_id: str,
    section_type: str,
    request: Request,
    _auth=Depends(auth_dependency),
):
    section = get_section(request.state.db_path, node_id, section_type)
    if not section:
        raise HTTPException(status_code=404, detail="Section not found")
    return section


@router.put("/nodes/{node_id}/sections/{section_type}")
async def upsert_section_route(
    node_id: str,
    section_type: str,
    body: UpsertSectionBody,
    request: Request,
    _auth=Depends(auth_dependency),
):
    result = upsert_section(request.state.db_path, node_id, section_type, body.body)
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return result


@router.post("/nodes/{node_id}/sections/{section_type}/append")
async def append_section_route(
    node_id: str,
    section_type: str,
    body: AppendSectionBody,
    request: Request,
    _auth=Depends(auth_dependency),
):
    result = append_section(request.state.db_path, node_id, section_type, body.content)
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return result


@router.delete("/nodes/{node_id}/sections/{section_type}")
async def delete_section_route(
    node_id: str,
    section_type: str,
    request: Request,
    _auth=Depends(auth_dependency),
):
    delete_section(request.state.db_path, node_id, section_type)
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Task linking
# ---------------------------------------------------------------------------

@router.get("/nodes/{node_id}/tasks")
async def list_node_tasks(
    node_id: str,
    request: Request,
    _auth=Depends(auth_dependency),
):
    return get_node_tasks(request.state.db_path, node_id)


@router.post("/nodes/{node_id}/tasks")
async def link_task_route(
    node_id: str,
    body: LinkTaskBody,
    request: Request,
    _auth=Depends(auth_dependency),
):
    link_task_to_node(request.state.db_path, node_id, body.task_id)
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return {"ok": True}


@router.delete("/nodes/{node_id}/tasks/{task_id}")
async def unlink_task_route(
    node_id: str,
    task_id: str,
    request: Request,
    _auth=Depends(auth_dependency),
):
    unlink_task_from_node(request.state.db_path, node_id, task_id)
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return {"ok": True}
