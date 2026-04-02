from typing import Any


class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, list] = {}

    async def connect(self, ws, user_id: str) -> None:
        await ws.accept()
        self._connections.setdefault(user_id, []).append(ws)

    def disconnect(self, ws, user_id: str) -> None:
        conns = self._connections.get(user_id, [])
        self._connections[user_id] = [c for c in conns if c is not ws]

    async def broadcast(self, data: Any, user_id: str) -> None:
        conns = self._connections.get(user_id, [])
        dead = []
        for ws in conns:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, user_id)


manager = ConnectionManager()
