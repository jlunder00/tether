from fastapi import APIRouter, Depends, Request
from api.auth import auth_dependency
from db.queries import get_links, create_link, delete_link

router = APIRouter()

@router.get("/{parent_type}/{parent_id}/links")
async def get_entity_links(parent_type: str, parent_id: str, request: Request, _auth=Depends(auth_dependency)):
    return get_links(request.state.db_path, parent_type, parent_id)

@router.post("/{parent_type}/{parent_id}/links")
async def create_entity_link(parent_type: str, parent_id: str, body: dict, request: Request, _auth=Depends(auth_dependency)):
    return create_link(request.state.db_path, parent_type, parent_id, body["url"], body.get("label"), body.get("category", "other"))

@router.delete("/links/{link_id}")
async def delete_entity_link(link_id: int, request: Request, _auth=Depends(auth_dependency)):
    delete_link(request.state.db_path, link_id)
    return {"ok": True}
