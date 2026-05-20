"""Entry point: python -m interactive_agent_layer [--host HOST] [--port PORT]"""
from __future__ import annotations

import argparse

import uvicorn

from interactive_agent_layer.pool_client import StubPoolClient
from interactive_agent_layer.server import create_app
from interactive_agent_layer.session import Layer
from interactive_agent_layer.ws_publisher import WSPublisher


def main() -> None:
    parser = argparse.ArgumentParser(description="Interactive Agent Layer service")
    parser.add_argument("--port", type=int, default=5003)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    publisher = WSPublisher()
    pool = StubPoolClient()  # replaced with real pool client in follow-up PR
    layer = Layer(pool_client=pool, ws_publisher=publisher)
    app = create_app(layer)

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
