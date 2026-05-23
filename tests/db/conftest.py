"""Shared setup for db tests.

Sets required config env vars before any app imports so the config loader
singleton resolves cleanly in environments without a full tether config file.
"""
import os

os.environ.setdefault("TETHER_JWT_SECRET", "dev-secret-change-in-production")
os.environ.setdefault("TETHER_DISABLE_RATE_LIMITS", "1")
os.environ.setdefault("TETHER_COOKIE_SECURE", "false")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-client-id")
os.environ.setdefault("GOOGLE_CLIENT_SECRET", "test-client-secret")
