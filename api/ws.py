from typing import Any


class ConnectionManager:
    def __init__(self):
        self._connections: list = []

    async def connect(self, ws) -> None:
        await ws.accept()
        self._connections.append(ws)

    def disconnect(self, ws) -> None:
        self._connections = [c for c in self._connections if c is not ws]

    async def broadcast(self, data: Any) -> None:
        dead = []
        for ws in self._connections:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()
