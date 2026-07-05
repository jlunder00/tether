# tether/sync — dispatch layer for integration sync (see sync/dispatch.py).
# The standalone LISTEN-loop worker was removed 2026-07 (not run in prod;
# see PR #474); dispatch_sync() is called inline from api/routes/integrations.py.
