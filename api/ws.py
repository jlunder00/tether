from typing import Any


class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, list] = {}
        # bot_id -> (ws, delegated_user_ids)
        # Keyed by bot identity so update_bot_delegation can find the ws by id.
        # PR 4 will populate delegation sets via the key-claim flow; until then
        # each bot registers with whatever set get_delegated_user_ids returns.
        self._bot_connections: dict[str, tuple[Any, set[str]]] = {}

    async def connect(self, ws, user_id: str) -> None:
        await ws.accept()
        self._connections.setdefault(user_id, []).append(ws)

    def register_only(self, ws, user_id: str) -> None:
        """Register an already-accepted websocket under an additional user_id key.

        Unlike connect(), this does NOT call ws.accept() — use it when the
        socket is already open and you only need an extra channel entry.
        """
        self._connections.setdefault(user_id, []).append(ws)

    def register_bot(self, ws, bot_id: str, delegated_user_ids: set[str]) -> None:
        """Register a bot WS connection with an initial delegation set.

        The websocket must already be accepted. Events are delivered to this
        connection only for user_ids present in delegated_user_ids.
        """
        self._bot_connections[bot_id] = (ws, set(delegated_user_ids))

    def disconnect(self, ws, user_id: str) -> None:
        conns = self._connections.get(user_id, [])
        self._connections[user_id] = [c for c in conns if c is not ws]

    def disconnect_bot(self, bot_id: str) -> None:
        """Remove a bot connection registration by bot_id."""
        self._bot_connections.pop(bot_id, None)

    def update_bot_delegation(self, bot_id: str, delegated_user_ids: set[str]) -> None:
        """Update the delegation set for an active bot connection.

        Called when a new key is claimed (PR 4) or revoked. The bot connection
        stays open — only the filter set changes. No-op if bot_id is not
        currently connected.
        """
        if bot_id in self._bot_connections:
            ws, _ = self._bot_connections[bot_id]
            self._bot_connections[bot_id] = (ws, set(delegated_user_ids))

    async def broadcast(self, data: Any, user_id: str) -> None:
        # Deliver to regular per-user connections.
        conns = self._connections.get(user_id, [])
        dead = []
        for ws in conns:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, user_id)

        # Deliver to bot connections delegated for this user.
        # Inject for_user_id so the bot can demultiplex events across users.
        dead_bots = []
        for bot_id, (bot_ws, delegated_set) in self._bot_connections.items():
            if user_id in delegated_set:
                try:
                    await bot_ws.send_json({**data, "for_user_id": str(user_id)})
                except Exception:
                    dead_bots.append(bot_id)
        for bot_id in dead_bots:
            self.disconnect_bot(bot_id)


manager = ConnectionManager()
