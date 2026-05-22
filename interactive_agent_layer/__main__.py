"""Entry point: python -m interactive_agent_layer [--host HOST] [--port PORT]"""
from __future__ import annotations

import argparse
import logging
import os

import uvicorn

from interactive_agent_layer.pool_client import PoolClient
from interactive_agent_layer.server import create_app
from interactive_agent_layer.session import Layer
from interactive_agent_layer.ws_publisher import WSPublisher

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive Agent Layer service")
    parser.add_argument("--port", type=int, default=5003)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    redis_url = os.environ.get("REDIS_URL")
    redis_client = None
    if redis_url:
        import redis.asyncio as aioredis
        redis_client = aioredis.from_url(redis_url)
        logger.info("WSPublisher: Redis dual-write enabled (%s)", redis_url)
    else:
        logger.warning(
            "WSPublisher: REDIS_URL not set — background events will not reach "
            "the API process. Set REDIS_URL=redis://localhost:6379 to enable."
        )

    publisher = WSPublisher(redis_client=redis_client)
    pool = PoolClient()
    layer = Layer(pool_client=pool, ws_publisher=publisher)
    app = create_app(layer)

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
