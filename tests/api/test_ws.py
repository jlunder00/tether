import pytest
from api.ws import ConnectionManager


@pytest.mark.asyncio
async def test_manager_broadcasts_to_all_clients():
    manager = ConnectionManager()

    class MockWS:
        def __init__(self):
            self.sent = []
        async def accept(self): pass
        async def send_json(self, data):
            self.sent.append(data)

    ws1, ws2 = MockWS(), MockWS()
    await manager.connect(ws1, "user-1")
    await manager.connect(ws2, "user-1")
    await manager.broadcast({"type": "plan_updated"}, "user-1")
    assert ws1.sent == [{"type": "plan_updated"}]
    assert ws2.sent == [{"type": "plan_updated"}]


@pytest.mark.asyncio
async def test_manager_broadcasts_only_to_correct_user():
    manager = ConnectionManager()

    class MockWS:
        def __init__(self):
            self.sent = []
        async def accept(self): pass
        async def send_json(self, data):
            self.sent.append(data)

    ws1, ws2 = MockWS(), MockWS()
    await manager.connect(ws1, "user-1")
    await manager.connect(ws2, "user-2")
    await manager.broadcast({"type": "plan_updated"}, "user-1")
    assert ws1.sent == [{"type": "plan_updated"}]
    assert ws2.sent == []


@pytest.mark.asyncio
async def test_manager_removes_dead_connections():
    manager = ConnectionManager()

    class MockWS:
        async def accept(self): pass
        async def send_json(self, data): raise RuntimeError("dead")

    ws = MockWS()
    await manager.connect(ws, "user-1")
    await manager.broadcast({"type": "ping"}, "user-1")
    assert manager._connections.get("user-1", []) == []
