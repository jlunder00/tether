"""FastAPI integration for the async Postgres connection pool.

Usage in api/main.py:
    from db.pool_middleware import lifespan, get_db_conn
    app = FastAPI(lifespan=lifespan)

Usage in routes:
    @router.get("/tasks")
    async def list_tasks(conn=Depends(get_db_conn)):
        rows = await conn.fetch("SELECT * FROM tasks")
"""

from contextlib import asynccontextmanager

from fastapi import Request

import db.postgres as pg


@asynccontextmanager
async def lifespan(app):
    app.state.pool = await pg.create_pool()
    yield
    await pg.close_pool()


async def get_db_conn(request: Request):
    """FastAPI dependency: user-scoped Postgres connection via RLS.

    Reads user_id from request.state (set by auth_dependency).
    Auth routes pass no user_id — get an unscoped connection.
    """
    pool = request.app.state.pool
    user_id = getattr(request.state, "user_id", None)
    async with pg.get_conn(pool, user_id=user_id) as conn:
        yield conn
