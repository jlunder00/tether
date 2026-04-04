"""API routes for LLM configuration — model roles, backend preference, thinking budget."""
import yaml
from pathlib import Path
from fastapi import APIRouter, Depends, Request

from api.auth import auth_dependency

router = APIRouter(prefix="/llm-config", tags=["llm-config"])

_CONFIG_PATH = Path.home() / ".tether-config" / "config.yaml"

# All configurable model roles in the pipeline
_MODEL_ROLES = [
    "orchestrator", "meta_eval", "meta_eval_repair",
    "meta_eval_repair_escalate", "execution_subagent",
    "satisfaction_eval", "response_builder", "quick_classifier",
]

# v3 defaults
_DEFAULTS = {
    "models": {
        "orchestrator": "claude-sonnet-4-6",
        "meta_eval": "claude-haiku-4-5-20251001",
        "meta_eval_repair": "claude-haiku-4-5-20251001",
        "meta_eval_repair_escalate": "claude-sonnet-4-6",
        "execution_subagent": "claude-haiku-4-5-20251001",
        "satisfaction_eval": "claude-haiku-4-5-20251001",
        "response_builder": "claude-sonnet-4-6",
        "quick_classifier": "claude-haiku-4-5-20251001",
    },
    "llm": {
        "use_v3": False,
        "v2_fallback": True,
        "preferred_backend": "anthropic",
        "thinking_enabled": True,
        "thinking_budget": 8000,
        "beacon_score_threshold": 15,
        "beacon_cooldown_minutes": 30,
    },
}


def _read_config() -> dict:
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH) as f:
            return yaml.safe_load(f) or {}
    return {}


def _write_config(config: dict) -> None:
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_CONFIG_PATH, "w") as f:
        yaml.safe_dump(config, f, default_flow_style=False)


@router.get("")
async def get_llm_config(request: Request, _auth=Depends(auth_dependency)):
    config = _read_config()
    models = {**_DEFAULTS["models"], **config.get("models", {})}
    llm = {**_DEFAULTS["llm"], **config.get("llm", {})}
    return {
        "models": models,
        "llm": llm,
        "model_roles": _MODEL_ROLES,
        "defaults": _DEFAULTS,
    }


@router.put("")
async def put_llm_config(request: Request, _auth=Depends(auth_dependency)):
    body = await request.json()
    config = _read_config()
    if "models" in body:
        config["models"] = {
            role: body["models"].get(role, _DEFAULTS["models"].get(role))
            for role in _MODEL_ROLES
            if body["models"].get(role)
        }
    _LLM_KEYS = {"use_v3", "v2_fallback", "preferred_backend", "thinking_enabled",
                  "thinking_budget", "beacon_score_threshold", "beacon_cooldown_minutes"}
    if "llm" in body:
        config["llm"] = {
            **config.get("llm", {}),
            **{k: v for k, v in body["llm"].items() if k in _LLM_KEYS},
        }
    _write_config(config)
    return {"ok": True}
