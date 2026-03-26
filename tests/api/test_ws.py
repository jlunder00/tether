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
    await manager.connect(ws1)
    await manager.connect(ws2)
    await manager.broadcast({"type": "plan_updated"})
    assert ws1.sent == [{"type": "plan_updated"}]
    assert ws2.sent == [{"type": "plan_updated"}]


@pytest.mark.asyncio
async def test_manager_removes_dead_connections():
    manager = ConnectionManager()

    class MockWS:
        async def accept(self): pass
        async def send_json(self, data): raise RuntimeError("dead")

    ws = MockWS()
    await manager.connect(ws)
    await manager.broadcast({"type": "ping"})
    assert len(manager._connections) == 0
