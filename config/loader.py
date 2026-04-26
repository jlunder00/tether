"""
Tether unified config loader.

Resolution chain (later layers win):
  1. Baked-in defaults  — config/*.yaml baked into the image
  2. Remote config      — Tigris/S3 (stub — NotImplementedError when enabled)
  3. Local override     — TETHER_CONFIG_DIR/*.yaml (volume mount or ~/.tether-config/)
  4. Placeholder resolve — ${VAR} and ${VAR:-default} expanded from env vars
  5. Validate           — hard fail if any REQUIRED_KEYS still contain ${...}

Secrets.json compatibility shim:
  If config_dir contains secrets.json but NOT auth_config.yaml, the shim injects
  known flat keys (e.g. TETHER_JWT_SECRET) as env vars for placeholder resolution.
  Removed in Phase 3.
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger(__name__)

# Flat secrets.json key → dotted config path.  Used by compatibility shim.
_SECRETS_JSON_MAP: dict[str, str] = {
    "TETHER_JWT_SECRET": "jwt.secret",
    "TETHER_COOKIE_SECURE": "cookie.secure",
    "TETHER_ALLOWED_ORIGINS": "cors.allowed_origins",
    "GITHUB_CLIENT_ID": "oauth.github.client_id",
    "GITHUB_CLIENT_SECRET": "oauth.github.client_secret",
    "GITHUB_CALLBACK_URL": "oauth.github.callback_url",
    "GOOGLE_CLIENT_ID": "oauth.google.client_id",
    "GOOGLE_CLIENT_SECRET": "oauth.google.client_secret",
    "GOOGLE_CALLBACK_URL": "oauth.google.callback_url",
    "GOOGLE_INTEGRATION_CALLBACK_URL": "integrations.google_calendar.callback_url",
}

_PLACEHOLDER_RE = re.compile(r"\$\{([^}]+)\}")

_UNSET = object()  # sentinel for "config_dir not supplied"


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*. Nested dicts are merged;
    lists and scalars in *override* replace those in *base*."""
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = deep_merge(result[key], val)
        else:
            result[key] = val
    return result


class TetherConfig:
    """Unified config loader.  Call load() once at startup; use get() everywhere.

    Parameters
    ----------
    baked_in_dir:
        Directory containing the baked-in YAML files.  Defaults to the
        ``config/`` directory in the repo root (sibling of this file).
    config_dir:
        Local override directory.  Defaults to
        ``TETHER_CONFIG_DIR`` env var, then ``~/.tether-config``.
        Pass ``None`` explicitly to disable the local-override layer
        (e.g. in cloud deployments with no volume mount).
    """

    REQUIRED_KEYS = ["jwt.secret"]

    def __init__(
        self,
        baked_in_dir: Path | None = None,
        config_dir: "Path | str | None" = _UNSET,
    ) -> None:
        self._baked_in_dir: Path = (
            baked_in_dir if baked_in_dir is not None
            else Path(__file__).parent
        )

        # Distinguish "caller passed None" from "caller omitted the arg"
        if config_dir is _UNSET:
            _env = os.environ.get("TETHER_CONFIG_DIR")
            self._config_dir: Path | None = (
                Path(_env) if _env else Path.home() / ".tether-config"
            )
        elif config_dir is None:
            self._config_dir = None
        else:
            self._config_dir = Path(config_dir)

        self._cfg: dict | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Execute full resolution chain."""
        cfg: dict = {}

        cfg = deep_merge(cfg, self._load_baked_in())

        if self._remote_provider() != "none":
            cfg = deep_merge(cfg, self._load_remote())

        # Apply secrets.json shim BEFORE local override so that the override
        # (when present) still wins; shim only fills env vars for resolution.
        shim_env = self._load_secrets_json_shim()

        if self._config_dir_exists():
            cfg = deep_merge(cfg, self._load_local_override())

        cfg = self._resolve_placeholders(cfg, extra_env=shim_env)
        self._validate(cfg)
        self._cfg = cfg

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """Return resolved value at *dotted_key*.  Auto-loads on first call."""
        self._ensure_loaded()
        node = self._cfg
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def get_list(self, dotted_key: str, default: list | None = None) -> list:
        """Return value as a list.  Comma-separated strings are split."""
        val = self.get(dotted_key)
        if val is None:
            return default if default is not None else []
        if isinstance(val, list):
            return val
        return [item.strip() for item in str(val).split(",") if item.strip()]

    def get_bool(self, dotted_key: str, default: bool = False) -> bool:
        """Return value as a bool.  Handles 'true'/'false'/'1'/'0' strings."""
        val = self.get(dotted_key)
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        return str(val).lower() in ("true", "1", "yes")

    # ------------------------------------------------------------------
    # Private — resolution chain
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._cfg is None:
            self.load()

    def _load_baked_in(self) -> dict:
        return self._load_yaml_dir(self._baked_in_dir)

    def _load_local_override(self) -> dict:
        assert self._config_dir is not None
        return self._load_yaml_dir(self._config_dir)

    def _load_yaml_dir(self, directory: Path) -> dict:
        """Merge all *.yaml files in *directory* into a single dict."""
        merged: dict = {}
        if not directory.exists():
            return merged
        for yaml_file in sorted(directory.glob("*.yaml")):
            try:
                data = yaml.safe_load(yaml_file.read_text()) or {}
                merged = deep_merge(merged, data)
            except Exception as exc:
                log.warning("Failed to load %s: %s", yaml_file, exc)
        return merged

    def _load_secrets_json_shim(self) -> dict[str, str]:
        """Return a flat env-var dict from secrets.json when auth_config.yaml
        is absent in config_dir.  Returns empty dict otherwise."""
        if self._config_dir is None or not self._config_dir.exists():
            return {}

        secrets_path = self._config_dir / "secrets.json"
        auth_yaml_path = self._config_dir / "auth_config.yaml"

        if not secrets_path.exists():
            return {}

        if auth_yaml_path.exists():
            # Local YAML takes full ownership — shim not needed
            return {}

        log.warning(
            "secrets.json compatibility shim active — migrate to auth_config.yaml "
            "(run `make configure-auth`)"
        )
        try:
            raw: dict = json.loads(secrets_path.read_text())
        except Exception as exc:
            log.warning("Could not read secrets.json: %s", exc)
            return {}

        return {k: v for k, v in raw.items() if k in _SECRETS_JSON_MAP}

    def _remote_provider(self) -> str:
        return os.environ.get("TETHER_REMOTE_PROVIDER", "none").lower()

    def _config_dir_exists(self) -> bool:
        return self._config_dir is not None and self._config_dir.exists()

    def _load_remote(self) -> dict:
        """Stub — raises NotImplementedError until Phase 3 (Tigris/S3)."""
        provider = self._remote_provider()
        raise NotImplementedError(
            f"Remote config provider '{provider}' is not yet implemented. "
            "Set TETHER_REMOTE_PROVIDER=none or leave unset for local deployments. "
            "Remote config (Tigris/S3) is implemented in Phase 3."
        )

    def _resolve_placeholders(self, cfg: dict, extra_env: dict[str, str] | None = None) -> dict:
        """Walk all string values and expand ${VAR} and ${VAR:-default}."""
        extra = extra_env or {}

        def _resolve_str(value: str) -> str:
            def _replace(match: re.Match) -> str:
                expr = match.group(1)
                if ":-" in expr:
                    var_name, fallback = expr.split(":-", 1)
                else:
                    var_name, fallback = expr, None

                # Real env vars win; shim fills in missing ones
                resolved = os.environ.get(var_name) or extra.get(var_name)
                if resolved is not None:
                    return resolved
                if fallback is not None:
                    return fallback
                return match.group(0)  # leave unresolved

            return _PLACEHOLDER_RE.sub(_replace, value)

        def _walk(node: Any) -> Any:
            if isinstance(node, dict):
                return {k: _walk(v) for k, v in node.items()}
            if isinstance(node, list):
                return [_walk(item) for item in node]
            if isinstance(node, str):
                return _resolve_str(node)
            return node

        return _walk(cfg)

    def _validate(self, cfg: dict) -> None:
        """Raise RuntimeError if any REQUIRED_KEYS still contain ${...}."""
        errors: list[str] = []
        for dotted_key in self.REQUIRED_KEYS:
            node: Any = cfg
            for part in dotted_key.split("."):
                if not isinstance(node, dict) or part not in node:
                    node = None
                    break
                node = node[part]
            if isinstance(node, str) and _PLACEHOLDER_RE.search(node):
                errors.append(dotted_key)

        if errors:
            raise RuntimeError(
                f"Required config key(s) are unresolved after startup: "
                f"{', '.join(errors)}. "
                "Set the corresponding environment variable(s) or provide values "
                "in your local config files."
            )


# ---------------------------------------------------------------------------
# Global singleton — lazy-loads on first get()
# ---------------------------------------------------------------------------

config = TetherConfig()
