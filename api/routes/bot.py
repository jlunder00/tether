from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
import asyncpg, asyncio
from db.pg_queries import get_last_bot_activity
from db.pool_middleware import get_db_conn
from api.auth import auth_dependency, ws_auth_dependency
from bot.message_handler import handle_message

router = APIRouter()


@router.get("/bot/health")
async def bot_health(_auth=Depends(auth_dependency),
                     conn: asyncpg.Connection = Depends(get_db_conn)):
    activity = await get_last_bot_activity(conn)
    if not activity:
        return {"status": "unknown", "last_activity": None}
    from datetime import datetime, timezone
    try:
        ts = datetime.fromisoformat(activity["ts"])
        age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
    except (ValueError, TypeError):
        age_min = float("inf")
    status = "ok" if age_min < 5 else "stale" if age_min < 30 else "offline"
    return {"status": status, "last_activity": activity}

@router.websocket("/bot/chat")
async def bot_chat(websocket: WebSocket,
                   _auth=Depends(ws_auth_dependency)):
    pool = websocket.app.state.pool
    user_id = websocket.state.user_id
    await websocket.accept()


    try:
        while True:
            data = await websocket.receive_json()
            # expected: {"type": "user", "content": "..."}
            response_parts = []
            def send_fn(msg: str):
                response_parts.append(msg)

            #pass content into the bot pipeline
            await handle_message(data['content'], 
                                 send_fn=send_fn,
                                 pool=pool,
                                 user_id=user_id
                            )

            full_response = "".join(response_parts)
            await websocket.send_json({"type": "chunk", "content": full_response})
            await websocket.send_json({"type": "done"})
    except WebSocketDisconnect:
        # cancel heartbeat, clean up
        return


