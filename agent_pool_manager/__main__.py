"""Entry point: python -m agent_pool_manager [--port PORT] [--host HOST]."""
from __future__ import annotations

import argparse
import logging

import uvicorn

from .server import build_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent pool manager service")
    parser.add_argument("--host", default="0.0.0.0", help="Bind host")
    parser.add_argument("--port", type=int, default=5002, help="Bind port")
    args = parser.parse_args()

    app = build_app()
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
