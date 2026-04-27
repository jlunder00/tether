from typing import Any


class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, list] = {}

    async def connect(self, ws, user_id: str) -> None:
        await ws.accept()
        self._connections.setdefault(user_id, []).append(ws)

    def register_only(self, ws, user_id: str) -> None:
        """Register an already-accepted websocket under an additional user_id key.

        Unlike connect(), this does NOT call ws.accept() — use it when the
        socket is already open and you only need an extra channel entry.
        """
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
