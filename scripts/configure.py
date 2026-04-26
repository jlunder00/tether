#!/usr/bin/env python3
"""
Tether configuration helper.

Usage:
  python3 scripts/configure.py install                          # first-time setup
  python3 scripts/configure.py auth  [KEY=VALUE ...]            # write auth config
  python3 scripts/configure.py google [KEY=VALUE ...]           # write Google OAuth config
  python3 scripts/configure.py github [KEY=VALUE ...]           # write GitHub OAuth config
  python3 scripts/configure.py db    [KEY=VALUE ...]            # write DB passwords to .env
  python3 scripts/configure.py telegram [KEY=VALUE ...]         # write Telegram credentials

When KEY=VALUE args are provided, values are written directly (CI/make path).
When values are empty strings or omitted, the script prompts interactively (self-hoster path).

Environment variables:
  TETHER_CONFIG_DIR    Where user YAML config files live (default: ~/.tether-config)
  TETHER_COMPOSE_DIR   Where the Docker Compose .env lives (default: ~/tether)
"""

import argparse
import copy
import os
import secrets
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


# ── Category definitions ─────────────────────────────────────────────────────
#
# Each category maps ENV_VAR_NAME → dotted YAML path within the target file.
# The "db" category is special: it writes to a .env file, not a YAML file.

CATEGORIES: Dict[str, Dict] = {
    "auth": {
        "file": "auth_config.yaml",
        "keys": {
            "TETHER_JWT_SECRET": "jwt.secret",
            "TETHER_COOKIE_SECURE": "cookie.secure",
            "TETHER_ALLOWED_ORIGINS": "cors.allowed_origins",
        },
        "prompts": {
            "TETHER_JWT_SECRET": "JWT secret (leave blank to auto-generate)",
            "TETHER_COOKIE_SECURE": "Cookie secure mode [true/false] (default: true)",
            "TETHER_ALLOWED_ORIGINS": "Allowed CORS origins, comma-separated",
        },
    },
    "google": {
        "file": "auth_config.yaml",
        "keys": {
            "GOOGLE_CLIENT_ID": "oauth.google.client_id",
            "GOOGLE_CLIENT_SECRET": "oauth.google.client_secret",
            "GOOGLE_CALLBACK_URL": "oauth.google.callback_url",
            "GOOGLE_INTEGRATION_CALLBACK_URL": "oauth.google.integration_callback_url",
        },
        "prompts": {
            "GOOGLE_CLIENT_ID": "Google OAuth client ID",
            "GOOGLE_CLIENT_SECRET": "Google OAuth client secret",
            "GOOGLE_CALLBACK_URL": "Google OAuth callback URL",
            "GOOGLE_INTEGRATION_CALLBACK_URL": "Google integration callback URL",
        },
    },
    "github": {
        "file": "auth_config.yaml",
        "keys": {
            "GITHUB_CLIENT_ID": "oauth.github.client_id",
            "GITHUB_CLIENT_SECRET": "oauth.github.client_secret",
            "GITHUB_CALLBACK_URL": "oauth.github.callback_url",
        },
        "prompts": {
            "GITHUB_CLIENT_ID": "GitHub OAuth client ID",
            "GITHUB_CLIENT_SECRET": "GitHub OAuth client secret",
            "GITHUB_CALLBACK_URL": "GitHub OAuth callback URL",
        },
    },
    "db": {
        "file": ".env",  # writes to Docker Compose .env, not a YAML
        "keys": {
            "POSTGRES_PASSWORD": "POSTGRES_PASSWORD",
            "TETHER_APP_PASSWORD": "TETHER_APP_PASSWORD",
        },
        "prompts": {
            "POSTGRES_PASSWORD": "PostgreSQL superuser password",
            "TETHER_APP_PASSWORD": "tether_app role password",
        },
    },
    "telegram": {
        "file": "app_config.yaml",
        "keys": {
            "TELEGRAM_BOT_TOKEN": "telegram.bot_token",
            "TELEGRAM_CHAT_ID": "telegram.chat_id",
        },
        "prompts": {
            "TELEGRAM_BOT_TOKEN": "Telegram bot token",
            "TELEGRAM_CHAT_ID": "Telegram chat ID",
        },
    },
}


# ── Core helpers ─────────────────────────────────────────────────────────────

def deep_merge(base: dict, override: dict) -> dict:
    """
    Recursively merge override into base. Returns a new dict; neither input is mutated.
    - Nested dicts are merged recursively.
    - Lists (and scalar values) are replaced wholesale by the override.
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def set_dotted_key(d: dict, dotted_key: str, value: Any) -> None:
    """
    Set a value at a dot-notation path in a nested dict. Mutates d in place.
    Creates intermediate dicts as needed.

    Example: set_dotted_key(d, "oauth.github.client_id", "x")
    sets d["oauth"]["github"]["client_id"] = "x"
    """
    parts = dotted_key.split(".")
    node = d
    for part in parts[:-1]:
        if part not in node or not isinstance(node[part], dict):
            node[part] = {}
        node = node[part]
    node[parts[-1]] = value


def atomic_write(path: Path, content: str) -> None:
    """
    Write content to path atomically: write to a temp file in the same directory,
    then rename over the target. Guarantees the target is never partially written.
    Creates parent directories if they don't exist.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path_str = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.rename(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def load_yaml_or_empty(path: Path) -> dict:
    """Load YAML from a file. Returns {} if the file doesn't exist or is empty."""
    if not path.exists():
        return {}
    content = path.read_text().strip()
    if not content:
        return {}
    return yaml.safe_load(content) or {}


def update_env_file(path: Path, updates: Dict[str, str]) -> None:
    """
    Update key=value entries in a .env file. Preserves unrelated keys.
    Creates the file if it doesn't exist. Writes atomically.
    """
    existing: Dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                existing[k.strip()] = v
    existing.update(updates)
    lines = [f"{k}={v}" for k, v in existing.items()]
    atomic_write(path, "\n".join(lines) + "\n")


# ── Category application ─────────────────────────────────────────────────────

def apply_category(
    category: str,
    kvs: Dict[str, str],
    config_dir: Path,
    template_dir: Optional[Path],
    interactive: bool,
    compose_dir: Optional[Path] = None,
) -> None:
    """
    Apply key=value updates for a named category.

    Args:
        category:     One of the keys in CATEGORIES.
        kvs:          Dict of ENV_VAR_NAME → value.
                      An empty string means "prompt interactively" (if interactive=True)
                      or "skip" (if interactive=False).
        config_dir:   Directory where user YAML config files live (~/.tether-config).
        template_dir: Directory of baked-in template files (/app/config or repo config/).
                      Used as the base when the user's config file doesn't exist yet.
                      Pass None to start from an empty dict when no user file exists.
        interactive:  If True, prompt via stdin for keys whose value is "".
        compose_dir:  For the "db" category only — where the Docker Compose .env lives.
    """
    spec = CATEGORIES[category]
    key_map: Dict[str, str] = spec["keys"]
    prompts: Dict[str, str] = spec.get("prompts", {})

    # Resolve final values — prompt for empty strings when interactive
    resolved: Dict[str, str] = {}
    for env_var, value in kvs.items():
        if env_var not in key_map:
            continue
        if value == "" and interactive:
            prompt_text = prompts.get(env_var, env_var)
            value = input(f"{prompt_text}: ").strip()
        if value != "":
            resolved[env_var] = value

    if not resolved:
        return  # nothing to write

    # ── db: write to .env file ───────────────────────────────────────────────
    if category == "db":
        env_path = (compose_dir or Path.cwd()) / ".env"
        update_env_file(env_path, {k: v for k, v in resolved.items()})
        return

    # ── YAML categories ──────────────────────────────────────────────────────
    filename = spec["file"]
    target_path = config_dir / filename

    # Load base: prefer existing user file → template → empty dict
    if target_path.exists():
        current = load_yaml_or_empty(target_path)
    elif template_dir is not None and (template_dir / filename).exists():
        current = load_yaml_or_empty(template_dir / filename)
    else:
        current = {}

    # Build the override dict using dotted key paths
    updates: dict = {}
    for env_var, value in resolved.items():
        dotted_path = key_map[env_var]
        set_dotted_key(updates, dotted_path, value)

    merged = deep_merge(current, updates)
    atomic_write(target_path, yaml.dump(merged, default_flow_style=False, allow_unicode=True))


# ── Install subcommand ────────────────────────────────────────────────────────

def run_install(
    config_dir: Path,
    compose_dir: Path,
    template_dir: Optional[Path],
    provided_jwt: Optional[str],
) -> None:
    """
    First-time setup: scaffold the config directory and generate a JWT secret.

    Generates TETHER_JWT_SECRET via secrets.token_hex(32) if not provided.
    After this returns, the caller's interactive loop handles remaining categories.
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    jwt_secret = provided_jwt if provided_jwt else secrets.token_hex(32)
    apply_category(
        category="auth",
        kvs={"TETHER_JWT_SECRET": jwt_secret},
        config_dir=config_dir,
        template_dir=template_dir,
        interactive=False,
        compose_dir=compose_dir,
    )


# ── CLI helpers ───────────────────────────────────────────────────────────────

def parse_kvs(args: list) -> Dict[str, str]:
    """Parse ['KEY=value', 'KEY2=value2'] positional args into a dict."""
    result: Dict[str, str] = {}
    for arg in args:
        if "=" not in arg:
            print(f"Warning: ignoring malformed arg '{arg}' (expected KEY=VALUE)", file=sys.stderr)
            continue
        key, _, value = arg.partition("=")
        result[key.strip()] = value
    return result


def main() -> None:
    config_dir = Path(os.environ.get("TETHER_CONFIG_DIR", Path.home() / ".tether-config"))
    compose_dir = Path(os.environ.get("TETHER_COMPOSE_DIR", Path.home() / "tether"))
    # Baked-in template dir: config/ at the repo root (two levels up from scripts/)
    script_dir = Path(__file__).parent
    template_dir: Optional[Path] = script_dir.parent / "config"
    if not template_dir.exists():
        template_dir = None

    parser = argparse.ArgumentParser(
        description="Tether configuration helper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    subparsers.add_parser("install", help="First-time setup — scaffold config and generate JWT secret")

    for cat_name, cat_spec in CATEGORIES.items():
        sub = subparsers.add_parser(cat_name, help=f"Configure {cat_name} settings")
        sub.add_argument(
            "kvs",
            nargs="*",
            metavar="KEY=VALUE",
            help="Key=value pairs to write. Omit values to be prompted interactively.",
        )

    parsed = parser.parse_args()

    if parsed.command == "install":
        run_install(
            config_dir=config_dir,
            compose_dir=compose_dir,
            template_dir=template_dir,
            provided_jwt=os.environ.get("TETHER_JWT_SECRET"),
        )
        # Interactive loop for remaining categories
        print("\nJWT secret written. Now configuring remaining categories interactively.")
        print("Press Enter to skip any value.\n")
        for cat_name in ("google", "github", "db", "telegram"):
            spec = CATEGORIES[cat_name]
            kvs = {k: "" for k in spec["keys"]}
            apply_category(
                category=cat_name,
                kvs=kvs,
                config_dir=config_dir,
                template_dir=template_dir,
                interactive=True,
                compose_dir=compose_dir,
            )
        print("\nSetup complete. Edit ~/.tether-config/*.yaml to adjust any values.")

    elif parsed.command in CATEGORIES:
        kvs = parse_kvs(parsed.kvs)
        # Fill in any missing expected keys as empty strings
        for key in CATEGORIES[parsed.command]["keys"]:
            if key not in kvs:
                kvs[key] = ""
        interactive = any(v == "" for v in kvs.values()) and sys.stdin.isatty()
        apply_category(
            category=parsed.command,
            kvs=kvs,
            config_dir=config_dir,
            template_dir=template_dir,
            interactive=interactive,
            compose_dir=compose_dir,
        )

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
