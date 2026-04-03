"""Shared fixtures for API tests — injects a valid JWT cookie so auth-gated routes work."""
from __future__ import annotations

import pytest
from httpx import AsyncClient, ASGITransport
from pathlib import Path

from api.auth import create_jwt, get_user_db_path
import api.auth as auth_module


TEST_USER_ID = "test-user-00000000-0000-0000-0000-000000000001"
TEST_USERNAME = "testuser"


def make_authenticated_client(app, db_path: Path):
    """Return an AsyncClient context manager with a valid JWT cookie that resolves to db_path."""
    token = create_jwt(TEST_USER_ID, TEST_USERNAME, is_admin=False)

    class _AuthClient:
        def __init__(self):
            self._original = None

        async def __aenter__(self):
            # Patch get_user_db_path so this user resolves to the test db
            self._original = auth_module.get_user_db_path

            def _patched(user_id: str) -> Path:
                if user_id == TEST_USER_ID:
                    return db_path
                return self._original(user_id)

            auth_module.get_user_db_path = _patched

            # Also patch inside auth_dependency (it calls get_user_db_path via module reference)
            import api.auth
            api.auth.get_user_db_path = _patched

            self._client = AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
                cookies={"tether_token": token},
            )
            return await self._client.__aenter__()

        async def __aexit__(self, *args):
            auth_module.get_user_db_path = self._original
            import api.auth
            api.auth.get_user_db_path = self._original
            return await self._client.__aexit__(*args)

    return _AuthClient()
