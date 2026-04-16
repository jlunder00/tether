import pytest
from tether_mcp.write_modes import (
    resolve_field,
    apply_text_mode,
    format_cat_n,
    line_count,
    MixedPatchOpsError,
)


# ── resolve_field ────────────────────────────────────────────────

class TestResolveField:
    def test_bare_string(self):
        assert resolve_field("hello") == ("replace", "hello")

    def test_bare_list(self):
        assert resolve_field(["a", "b"]) == ("additive", ["a", "b"])

    def test_mode_replace(self):
        assert resolve_field({"mode": "replace", "value": "new"}) == ("replace", "new")

    def test_mode_append(self):
        assert resolve_field({"mode": "append", "value": "extra"}) == ("append", "extra")

    def test_mode_patch(self):
        ops = [{"find": "old", "replace": "new"}]
        assert resolve_field({"mode": "patch", "operations": ops}) == ("patch", ops)

    def test_empty_string_returns_none(self):
        assert resolve_field("") is None

    def test_none_returns_none(self):
        assert resolve_field(None) is None


# ── apply_text_mode: replace ─────────────────────────────────────

class TestApplyReplace:
    def test_overwrites_existing(self):
        assert apply_text_mode("old text", "replace", "new text") == "new text"

    def test_works_on_none(self):
        assert apply_text_mode(None, "replace", "value") == "value"

    def test_works_on_empty(self):
        assert apply_text_mode("", "replace", "value") == "value"


# ── apply_text_mode: append ──────────────────────────────────────

class TestApplyAppend:
    def test_concatenates(self):
        assert apply_text_mode("line1", "append", "line2") == "line1\nline2"

    def test_works_on_none(self):
        assert apply_text_mode(None, "append", "first") == "first"

    def test_works_on_empty(self):
        assert apply_text_mode("", "append", "added") == "added"


# ── apply_text_mode: patch (find-based) ─────────────────────────

class TestPatchFindBased:
    def test_single_find_replace(self):
        ops = [{"find": "world", "replace": "earth"}]
        result, reports = apply_text_mode("hello world", "patch", ops)
        assert result == "hello earth"
        assert reports == [{"op": 0, "status": "applied", "matches": 1}]

    def test_find_replace_multiple_occurrences(self):
        ops = [{"find": "a", "replace": "b"}]
        result, reports = apply_text_mode("banana", "patch", ops)
        assert result == "bbnbnb"
        assert reports[0]["matches"] == 3

    def test_find_delete_empty_replace(self):
        ops = [{"find": "remove_me", "replace": ""}]
        result, reports = apply_text_mode("keep remove_me keep", "patch", ops)
        assert result == "keep  keep"
        assert reports[0]["status"] == "applied"

    def test_no_match_reports(self):
        ops = [{"find": "missing", "replace": "x"}]
        result, reports = apply_text_mode("hello", "patch", ops)
        assert result == "hello"
        assert reports[0]["status"] == "no_match"

    def test_multiple_find_ops(self):
        ops = [
            {"find": "aaa", "replace": "AAA"},
            {"find": "bbb", "replace": "BBB"},
        ]
        result, reports = apply_text_mode("aaa bbb ccc", "patch", ops)
        assert result == "AAA BBB ccc"
        assert all(r["status"] == "applied" for r in reports)

    def test_empty_find_string_does_not_corrupt(self):
        ops = [{"find": "", "replace": "X"}]
        result, reports = apply_text_mode("hello", "patch", ops)
        assert result == "hello"
        assert reports[0]["status"] == "no_match"

    def test_empty_operations_list(self):
        result, reports = apply_text_mode("text", "patch", [])
        assert result == "text"
        assert reports == []


# ── apply_text_mode: patch (line-based) ─────────────────────────

class TestPatchLineBased:
    def test_line_replace(self):
        text = "line1\nline2\nline3"
        ops = [{"lines": [2], "replace": "replaced"}]
        result, reports = apply_text_mode(text, "patch", ops)
        assert result == "line1\nreplaced\nline3"
        assert reports[0]["status"] == "applied"

    def test_line_delete(self):
        text = "line1\nline2\nline3"
        ops = [{"lines": [2], "replace": ""}]
        result, reports = apply_text_mode(text, "patch", ops)
        assert result == "line1\nline3"
        assert reports[0]["status"] == "applied"

    def test_multi_line_replace(self):
        text = "a\nb\nc\nd"
        ops = [{"lines": [2, 3], "replace": "X"}]
        result, reports = apply_text_mode(text, "patch", ops)
        assert result == "a\nX\nd"
        assert reports[0]["status"] == "applied"

    def test_after_line_insert(self):
        text = "line1\nline2\nline3"
        ops = [{"after_line": 1, "insert": "inserted"}]
        result, reports = apply_text_mode(text, "patch", ops)
        assert result == "line1\ninserted\nline2\nline3"
        assert reports[0]["status"] == "applied"

    def test_before_line_insert(self):
        text = "line1\nline2\nline3"
        ops = [{"before_line": 1, "insert": "prepended"}]
        result, reports = apply_text_mode(text, "patch", ops)
        assert result == "prepended\nline1\nline2\nline3"
        assert reports[0]["status"] == "applied"

    def test_out_of_range_line(self):
        text = "line1\nline2"
        ops = [{"lines": [99], "replace": "nope"}]
        result, reports = apply_text_mode(text, "patch", ops)
        assert result == text
        assert reports[0]["status"] == "no_match"

    def test_multiple_line_ops_reverse_order(self):
        """Multiple ops execute correctly because they run in reverse line order."""
        text = "a\nb\nc\nd\ne"
        ops = [
            {"lines": [2], "replace": "B"},
            {"lines": [4], "replace": "D"},
        ]
        result, reports = apply_text_mode(text, "patch", ops)
        assert result == "a\nB\nc\nD\ne"
        assert all(r["status"] == "applied" for r in reports)

    def test_insert_and_replace_mixed_line_ops(self):
        """after_line insert + line replace in same batch."""
        text = "a\nb\nc"
        ops = [
            {"after_line": 3, "insert": "d"},
            {"lines": [1], "replace": "A"},
        ]
        result, reports = apply_text_mode(text, "patch", ops)
        assert result == "A\nb\nc\nd"
        assert all(r["status"] == "applied" for r in reports)

    def test_malformed_line_op(self):
        ops = [{"insert": "orphan"}]  # missing after_line/before_line
        result, reports = apply_text_mode("text", "patch", ops)
        assert reports[0]["status"] == "error"


# ── mixed ops error ──────────────────────────────────────────────

class TestMixedOpsError:
    def test_raises_on_mixed(self):
        ops = [
            {"find": "x", "replace": "y"},
            {"lines": [1], "replace": "z"},
        ]
        with pytest.raises(MixedPatchOpsError):
            apply_text_mode("x stuff", "patch", ops)


# ── format_cat_n ─────────────────────────────────────────────────

class TestFormatCatN:
    def test_basic(self):
        assert format_cat_n("hello\nworld") == "1\thello\n2\tworld"

    def test_empty(self):
        assert format_cat_n("") == "1\t"

    def test_single_line(self):
        assert format_cat_n("only") == "1\tonly"


# ── line_count ───────────────────────────────────────────────────

class TestLineCount:
    def test_multi_line(self):
        assert line_count("a\nb\nc") == 3

    def test_single_line(self):
        assert line_count("hello") == 1
