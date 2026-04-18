from bot.slash_preprocessor import scan_slash_commands, SlashParseResult


def test_check_in_at_start_detected_as_db_command():
    result = scan_slash_commands("/check-in I finished the report")
    assert "check-in" in result.db_commands_applied
    assert result.skill_commands == []


def test_update_context_at_start_detected_as_db_command():
    result = scan_slash_commands("/tether-update-context Project :: notes here")
    assert "tether-update-context" in result.db_commands_applied


def test_update_plan_at_start_detected_as_db_command():
    result = scan_slash_commands("/update-plan morning :: task1; task2")
    assert "update-plan" in result.db_commands_applied


def test_db_command_mid_sentence_not_detected():
    # DB commands must be at line start
    result = scan_slash_commands("I used /check-in earlier")
    assert "check-in" not in result.db_commands_applied


def test_skill_command_anywhere_in_sentence():
    result = scan_slash_commands("how does /explain-beacon work?")
    assert "explain-beacon" in result.skill_commands


def test_skill_command_at_start():
    result = scan_slash_commands("/explain-anchors")
    assert "explain-anchors" in result.skill_commands


def test_multiple_skill_commands_in_message():
    result = scan_slash_commands("tell me about /explain-beacon and /explain-anchors")
    assert "explain-beacon" in result.skill_commands
    assert "explain-anchors" in result.skill_commands


def test_plain_text_returns_empty():
    result = scan_slash_commands("what are my tasks for today?")
    assert result.db_commands_applied == []
    assert result.skill_commands == []


def test_start_excluded_from_skill_commands():
    result = scan_slash_commands("/start")
    assert "start" not in result.skill_commands
    assert result.skill_commands == []


def test_link_excluded_from_skill_commands():
    result = scan_slash_commands("use /link to connect")
    assert "link" not in result.skill_commands


def test_unknown_command_no_registry_returned_as_skill():
    result = scan_slash_commands("how does /mystery-feature work?")
    assert "mystery-feature" in result.skill_commands


def test_unknown_command_filtered_when_registry_provided():
    registry = {"/explain-beacon": ("beacon.md", "what beacon does")}
    result = scan_slash_commands("how does /mystery-feature work?", skill_registry=registry)
    assert "mystery-feature" not in result.skill_commands


def test_known_command_passes_registry_filter():
    registry = {"/explain-beacon": ("beacon.md", "what beacon does")}
    result = scan_slash_commands("how does /explain-beacon work?", skill_registry=registry)
    assert "explain-beacon" in result.skill_commands


def test_mixed_db_and_skill_command():
    result = scan_slash_commands("/check-in done with tasks /explain-beacon")
    assert "check-in" in result.db_commands_applied
    assert "explain-beacon" in result.skill_commands


def test_clean_text_is_original_unchanged():
    text = "how does /explain-beacon work?"
    result = scan_slash_commands(text)
    assert result.clean_text == text


def test_db_command_at_start_of_second_line():
    text = "some preamble\n/check-in done with tasks"
    result = scan_slash_commands(text)
    assert "check-in" in result.db_commands_applied
