import pytest
import yaml
from pathlib import Path
from unittest.mock import patch
from bot.anchor_trigger import trigger_anchor


@pytest.fixture
def config_dir(tmp_path):
    config = {
        "telegram": {"bot_token": "test-token", "chat_id": "12345"},
    }
    anchors = {
        "anchors": [
            {
                "id": "grind_am",
                "name": "The Grind",
                "time": "08:00",
                "duration_minutes": 120,
                "flexibility": "locked",
            },
            {
                "id": "deep_work",
                "name": "Deep Work",
                "time": "14:00",
                "duration_minutes": 90,
                "flexibility": "soft",
            }
        ]
    }
    plan = {
        "date": "2026-03-25",
        "anchors": {
            "grind_am": {"tasks": ["Apply to 3 jobs"], "notes": "ML roles"}
        },
        "acknowledgements": {},
        "check_in_log": [],
    }
    (tmp_path / "config.yaml").write_text(yaml.dump(config))
    (tmp_path / "anchors.yaml").write_text(yaml.dump(anchors))
    (tmp_path / "plan.yaml").write_text(yaml.dump(plan))
    (tmp_path / "context.md").write_text("Job search is priority 1.")
    return tmp_path


@pytest.fixture
def prompts_dir(tmp_path):
    (tmp_path / "anchor_message.md").write_text(
        "Anchor: {{ anchor_name }}\nTasks: {% for t in tasks %}{{ t }}{% endfor %}"
    )
    return tmp_path


def test_trigger_calls_claude_with_anchor_name(config_dir, prompts_dir):
    with patch("bot.anchor_trigger.CONFIG_DIR", config_dir), \
         patch("bot.anchor_trigger.PROMPTS_DIR", prompts_dir), \
         patch("bot.anchor_trigger.call_claude", return_value="Time to grind!") as mock_claude, \
         patch("bot.anchor_trigger.send_telegram"):
        trigger_anchor("grind_am")
        mock_claude.assert_called_once()
        assert "The Grind" in mock_claude.call_args[0][0]


def test_trigger_calls_claude_with_tasks(config_dir, prompts_dir):
    with patch("bot.anchor_trigger.CONFIG_DIR", config_dir), \
         patch("bot.anchor_trigger.PROMPTS_DIR", prompts_dir), \
         patch("bot.anchor_trigger.call_claude", return_value="Go!") as mock_claude, \
         patch("bot.anchor_trigger.send_telegram"):
        trigger_anchor("grind_am")
        assert "Apply to 3 jobs" in mock_claude.call_args[0][0]


def test_trigger_sends_claude_response_to_telegram(config_dir, prompts_dir):
    with patch("bot.anchor_trigger.CONFIG_DIR", config_dir), \
         patch("bot.anchor_trigger.PROMPTS_DIR", prompts_dir), \
         patch("bot.anchor_trigger.call_claude", return_value="Time to grind!"), \
         patch("bot.anchor_trigger.send_telegram") as mock_tg:
        trigger_anchor("grind_am")
        mock_tg.assert_called_once_with(
            bot_token="test-token",
            chat_id="12345",
            text="Time to grind!",
        )


def test_trigger_skips_silently_when_anchor_not_in_plan(config_dir, prompts_dir):
    with patch("bot.anchor_trigger.CONFIG_DIR", config_dir), \
         patch("bot.anchor_trigger.PROMPTS_DIR", prompts_dir), \
         patch("bot.anchor_trigger.call_claude") as mock_claude, \
         patch("bot.anchor_trigger.send_telegram") as mock_tg:
        trigger_anchor("deep_work")  # in anchors.yaml but not in plan
        mock_claude.assert_not_called()
        mock_tg.assert_not_called()


def test_trigger_exits_nonzero_for_unknown_anchor(config_dir, prompts_dir):
    with patch("bot.anchor_trigger.CONFIG_DIR", config_dir), \
         patch("bot.anchor_trigger.PROMPTS_DIR", prompts_dir):
        with pytest.raises(SystemExit) as exc:
            trigger_anchor("not_a_real_anchor")
        assert exc.value.code != 0
