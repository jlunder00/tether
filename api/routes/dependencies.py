from fastapi import APIRouter, Depends, Request
from api.auth import auth_dependency
from db.queries import add_dependency, remove_dependency, get_dependencies_for

router = APIRouter()

@router.post("/dependencies")
async def create_dependency(body: dict, request: Request, _auth=Depends(auth_dependency)):
    dep_id = add_dependency(request.state.db_path, body["blocker_type"], body["blocker_id"],
                            body["blocked_type"], body["blocked_id"])
    return {"id": dep_id}

@router.delete("/dependencies/{dep_id}")
async def delete_dependency(dep_id: int, request: Request, _auth=Depends(auth_dependency)):
    remove_dependency(request.state.db_path, dep_id)
    return {"ok": True}

@router.get("/{entity_type}/{entity_id}/dependencies")
async def get_entity_dependencies(entity_type: str, entity_id: str, request: Request, _auth=Depends(auth_dependency)):
    return get_dependencies_for(request.state.db_path, entity_type, entity_id)
