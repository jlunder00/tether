from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from db.queries import (
    create_node, get_node, get_node_by_path, get_node_path,
    get_children, get_subtree, move_node, delete_node,
    patch_node_fields,
    get_sections, get_section, upsert_section, append_section, delete_section,
    list_section_files, create_section_file, rename_section_file, reorder_section_files,
    search_sections,
    link_task_to_node, unlink_task_from_node, get_node_tasks,
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
    kwargs = {"target_date": body.target_date, "color": body.color}
    if body.status is not None:
        kwargs["status"] = body.status
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
    node = get_node(request.state.db_path, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    fields = body.model_dump(exclude_unset=True)
    updated = patch_node_fields(request.state.db_path, node_id, fields)

    if fields:
        await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)

    return updated


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
    node = get_node(request.state.db_path, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return get_children(request.state.db_path, parent_id=node_id, include_archived=include_archived)


@router.get("/nodes/{node_id}/subtree")
async def get_node_subtree(
    node_id: str,
    request: Request,
    _auth=Depends(auth_dependency),
    include_archived: bool = False,
):
    node = get_node(request.state.db_path, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
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
    """List section types with file counts for a node."""
    node = get_node(request.state.db_path, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    rows = get_sections(request.state.db_path, node_id)
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["section_type"]] = counts.get(r["section_type"], 0) + 1
    return [{"section_type": t, "file_count": c} for t, c in counts.items()]


@router.get("/nodes/{node_id}/sections/{section_type}")
async def list_section_files_route(
    node_id: str,
    section_type: str,
    request: Request,
    _auth=Depends(auth_dependency),
):
    """List files within a section type [{name, size, position, updated_at}]."""
    node = get_node(request.state.db_path, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return list_section_files(request.state.db_path, node_id, section_type)


@router.post("/nodes/{node_id}/sections/{section_type}")
async def create_section_file_route(
    node_id: str,
    section_type: str,
    body: CreateSectionFileBody,
    request: Request,
    _auth=Depends(auth_dependency),
):
    """Create a new named file within a section type."""
    node = get_node(request.state.db_path, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    try:
        result = create_section_file(
            request.state.db_path, node_id, section_type, body.name, body.body,
        )
    except (ValueError, Exception) as exc:
        if "UNIQUE constraint" in str(exc) or "already exists" in str(exc).lower():
            raise HTTPException(status_code=409, detail=f"File '{body.name}' already exists in {section_type}")
        raise
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return result


@router.post("/nodes/{node_id}/sections/{section_type}/reorder")
async def reorder_section_files_route(
    node_id: str,
    section_type: str,
    body: ReorderSectionFilesBody,
    request: Request,
    _auth=Depends(auth_dependency),
):
    """Reorder files within a section type."""
    node = get_node(request.state.db_path, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    reorder_section_files(request.state.db_path, node_id, section_type, body.name_order)
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return {"ok": True}


@router.get("/nodes/{node_id}/sections/{section_type}/{name}")
async def get_section_file_route(
    node_id: str,
    section_type: str,
    name: str,
    request: Request,
    _auth=Depends(auth_dependency),
):
    """Get a specific section file body."""
    section = get_section(request.state.db_path, node_id, section_type, name=name)
    if not section:
        raise HTTPException(status_code=404, detail="Section file not found")
    return section


@router.put("/nodes/{node_id}/sections/{section_type}/{name}")
async def upsert_section_file_route(
    node_id: str,
    section_type: str,
    name: str,
    body: UpsertSectionBody,
    request: Request,
    _auth=Depends(auth_dependency),
):
    """Upsert a specific section file."""
    node = get_node(request.state.db_path, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    result = upsert_section(request.state.db_path, node_id, section_type, body.body, name=name)
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return result


@router.post("/nodes/{node_id}/sections/{section_type}/{name}/append")
async def append_section_file_route(
    node_id: str,
    section_type: str,
    name: str,
    body: AppendSectionBody,
    request: Request,
    _auth=Depends(auth_dependency),
):
    """Append to a specific section file."""
    node = get_node(request.state.db_path, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    result = append_section(request.state.db_path, node_id, section_type, body.content, name=name)
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return result


@router.post("/nodes/{node_id}/sections/{section_type}/{name}/rename")
async def rename_section_file_route(
    node_id: str,
    section_type: str,
    name: str,
    body: RenameSectionFileBody,
    request: Request,
    _auth=Depends(auth_dependency),
):
    """Rename a section file."""
    node = get_node(request.state.db_path, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    try:
        result = rename_section_file(
            request.state.db_path, node_id, section_type, name, body.new_name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        if "UNIQUE constraint" in str(exc):
            raise HTTPException(status_code=409, detail=f"File '{body.new_name}' already exists")
        raise
    await manager.broadcast({"type": "nodes_updated"}, request.state.user_id)
    return result


@router.delete("/nodes/{node_id}/sections/{section_type}/{name}")
async def delete_section_file_route(
    node_id: str,
    section_type: str,
    name: str,
    request: Request,
    _auth=Depends(auth_dependency),
):
    """Delete a specific section file."""
    delete_section(request.state.db_path, node_id, section_type, name=name)
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
    node = get_node(request.state.db_path, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return get_node_tasks(request.state.db_path, node_id)


@router.post("/nodes/{node_id}/tasks")
async def link_task_route(
    node_id: str,
    body: LinkTaskBody,
    request: Request,
    _auth=Depends(auth_dependency),
):
    node = get_node(request.state.db_path, node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
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
