#!/usr/bin/env python3
"""Benchmark the v3 LLM system — token usage, latency, tool calls.

Runs realistic user messages through the SDK conversation loop and reports:
  - Input/output tokens per message
  - Total tokens across a session
  - Wall-clock latency per message
  - Number of tool calls per message
  - Which tools were called

Each write operation is paired with a reversal so the DB is unchanged after the run.

Usage:
    .venv/bin/python scripts/benchmark_v3.py [--db PATH]
"""
import asyncio
import argparse
import os
import sys
import time
import yaml
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.llm import LLMRouter, LLMResponse, ToolCall
from bot.conversation import conversation_loop, build_system_prompt
from bot.tools import load_tools, make_tool_executor
from bot.oauth import get_valid_token


@dataclass
class RunResult:
    label: str
    message: str
    response: str
    input_tokens: int
    output_tokens: int
    tool_calls: list[str]
    rounds: int
    latency_s: float
    thinking: bool


@dataclass
class BenchmarkStats:
    results: list[RunResult] = field(default_factory=list)

    @property
    def total_input(self): return sum(r.input_tokens for r in self.results)
    @property
    def total_output(self): return sum(r.output_tokens for r in self.results)
    @property
    def total_tokens(self): return self.total_input + self.total_output
    @property
    def total_latency(self): return sum(r.latency_s for r in self.results)
    @property
    def total_tool_calls(self): return sum(len(r.tool_calls) for r in self.results)

    def print_report(self):
        print("\n" + "=" * 78)
        print("V3 LLM SYSTEM BENCHMARK")
        print("=" * 78)

        for i, r in enumerate(self.results, 1):
            tools_str = ", ".join(r.tool_calls) if r.tool_calls else "(none)"
            thinking_str = " +thinking" if r.thinking else ""
            print(f"\n--- [{r.label}] {r.message[:55]}{'...' if len(r.message) > 55 else ''}")
            print(f"  Response:  {r.response[:100]}{'...' if len(r.response) > 100 else ''}")
            print(f"  Tokens:    {r.input_tokens:,} in / {r.output_tokens:,} out = {r.input_tokens + r.output_tokens:,} total{thinking_str}")
            print(f"  Tools:     {len(r.tool_calls)} ({tools_str})")
            print(f"  Rounds:    {r.rounds}")
            print(f"  Latency:   {r.latency_s:.1f}s")

        print(f"\n{'=' * 78}")
        print(f"TOTALS ({len(self.results)} messages)")
        print(f"  Input tokens:   {self.total_input:,}")
        print(f"  Output tokens:  {self.total_output:,}")
        print(f"  Total tokens:   {self.total_tokens:,}")
        print(f"  Tool calls:     {self.total_tool_calls}")
        print(f"  Total latency:  {self.total_latency:.1f}s")
        print(f"  Avg latency:    {self.total_latency / len(self.results):.1f}s/msg")
        print(f"  Avg tokens/msg: {self.total_tokens // len(self.results):,}")

        # Estimate cost (Haiku: $0.80/M in, $4/M out; Sonnet: $3/M in, $15/M out)
        model_name = "unknown"
        for r in self.results:
            break
        is_haiku = "haiku" in (model_name or "")
        in_rate = 0.80 if is_haiku else 3.0
        out_rate = 4.0 if is_haiku else 15.0
        cost = (self.total_input / 1_000_000 * in_rate) + (self.total_output / 1_000_000 * out_rate)
        print(f"  Est. cost:      ${cost:.4f}")
        print(f"{'=' * 78}\n")


# Test scenarios: (label, user_message, is_full_path)
# Write operations are paired: add then remove
TEST_SCENARIOS = [
    # --- Quick path (no tools, no thinking) ---
    ("quick:greeting", "hi", False),
    ("quick:thanks", "thanks for the help", False),

    # --- Read-only (tools, with thinking) ---
    ("read:plan", "what's on my plan today?", True),
    ("read:context", "what context entries do I have?", True),
    ("read:milestones", "what milestones do I have?", True),
    ("read:anchors", "what time blocks do I have set up?", True),

    # --- Write: add task then remove it ---
    ("write:add_task", "add a task called 'benchmark test task' to the first available anchor", True),
    ("write:remove_task", "remove the task called 'benchmark test task' that I just added", True),

    # --- Write: add context then remove it ---
    ("write:add_context", "create a context entry called 'Benchmark/Test' with the body 'This is a benchmark test entry. Delete me.'", True),
    ("write:remove_context", "delete the context entry 'Benchmark/Test' — remove it completely by setting its body to empty", True),

    # --- Complex multi-tool ---
    ("complex:status", "give me a full status update — plan, milestones, and active context", True),
]


def load_config():
    """Read LLM config from config.yaml, with defaults."""
    config_path = Path.home() / ".tether-config" / "config.yaml"
    defaults = {
        "model": "claude-haiku-4-5-20251001",
        "thinking_enabled": True,
        "thinking_budget": 8000,
    }
    if config_path.exists():
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        llm = cfg.get("llm", {})
        return {
            "model": cfg.get("models", {}).get("orchestrator", defaults["model"]),
            "thinking_enabled": llm.get("thinking_enabled", defaults["thinking_enabled"]),
            "thinking_budget": llm.get("thinking_budget", defaults["thinking_budget"]),
        }
    return defaults


async def run_benchmark(db_path: str):
    token = get_valid_token()
    if not token:
        print("ERROR: No valid OAuth token. Run `claude /login` first.")
        return

    config = load_config()
    model = config["model"]
    thinking = config["thinking_enabled"]
    thinking_budget = config["thinking_budget"]

    router = LLMRouter()
    print(f"Backend:  {type(router.active_backend).__name__}")
    print(f"Model:    {model}")
    print(f"Thinking: {'on' if thinking else 'off'} (budget: {thinking_budget:,})")
    print(f"DB:       {db_path}")

    tools = load_tools()
    tool_schemas = [t.to_api_schema() for t in tools]
    executor = make_tool_executor(tools, db_path=db_path)
    print(f"Tools:    {len(tools)} loaded")

    # Build system prompt
    from db.queries import get_plan, get_context_entries, get_anchors
    from datetime import date

    today = date.today().isoformat()
    try:
        plan = get_plan(db_path, today)
    except Exception:
        plan = {}
    subjects = [e["subject"] for e in get_context_entries(db_path)]
    anchors = get_anchors(db_path)

    plan_lines = []
    for anchor_id, data in plan.get("anchors", {}).items():
        tasks = data.get("tasks", [])
        task_strs = [f"[{t.get('status', '?')[:1]}] {t.get('text', '')}" for t in tasks]
        plan_lines.append(f"{anchor_id}: {' | '.join(task_strs) or 'empty'}")

    current = anchors[0] if anchors else {"name": "General", "time": "00:00"}
    system = build_system_prompt(
        anchor_name=current.get("name", "General"),
        anchor_time=current.get("time", "00:00"),
        plan_summary="\n".join(plan_lines) or "No plan data.",
        context_subjects=subjects,
        session_notes=None,
    )

    stats = BenchmarkStats()
    conversation_history = []

    for label, msg_text, force_full in TEST_SCENARIOS:
        print(f"\n>> [{label}] {msg_text}")

        tool_call_names = []
        async def tracking_executor(tc: ToolCall) -> dict:
            tool_call_names.append(tc.name)
            return await executor(tc)

        conversation_history.append({"role": "user", "content": msg_text})
        recent = conversation_history[-4:]  # last 2 exchanges

        t0 = time.time()

        if not force_full:
            resp = await router.complete(
                messages=recent,
                system=system,
                model=model,
                thinking=False,  # quick path never uses thinking
            )
            rounds = 1
        else:
            resp = await conversation_loop(
                backend=router.active_backend,
                messages=recent,
                system=system,
                model=model,
                tools=tool_schemas,
                tool_executor=tracking_executor,
                max_rounds=6,
                thinking=thinking,
                thinking_budget=thinking_budget,
            )
            rounds = len(tool_call_names) + 1

        latency = time.time() - t0
        conversation_history.append({"role": "assistant", "content": resp.content})

        stats.results.append(RunResult(
            label=label,
            message=msg_text,
            response=resp.content,
            input_tokens=resp.input_tokens,
            output_tokens=resp.output_tokens,
            tool_calls=list(tool_call_names),
            rounds=rounds,
            latency_s=latency,
            thinking=thinking and force_full,
        ))
        tool_call_names.clear()

    stats.print_report()


def main():
    parser = argparse.ArgumentParser(description="Benchmark v3 LLM system")
    parser.add_argument("--db", default=os.path.expanduser("~/.tether-config/tether.db"))
    args = parser.parse_args()
    asyncio.run(run_benchmark(args.db))


if __name__ == "__main__":
    main()
