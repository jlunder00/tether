"""Rate-limiting setup for auth endpoints.

Uses slowapi (a Starlette/FastAPI wrapper around limits).

Set the environment variable ``TETHER_DISABLE_RATE_LIMITS=1`` *before any
imports* to replace the limiter with a no-op. This is intended for test
environments where multiple requests to the same endpoint would otherwise
trip rate limits.
"""
from __future__ import annotations

import os

_DISABLED = bool(os.environ.get("TETHER_DISABLE_RATE_LIMITS"))

if _DISABLED:
    class _NoopLimiter:
        """Drop-in that accepts the same decorator calls but does nothing."""

        def limit(self, *args, **kwargs):  # noqa: D401
            def decorator(f):
                return f
            return decorator

        def exempt(self, f):
            return f

    limiter = _NoopLimiter()  # type: ignore[assignment]

else:
    from slowapi import Limiter
    from slowapi.util import get_remote_address

    limiter = Limiter(key_func=get_remote_address)
