"""Write mode engine for MCP upsert tools.

Provides three write modes for text fields:
- replace: full overwrite (default for bare strings)
- append: concatenate with newline separator
- patch: targeted find-and-replace OR line-based edits
"""

from __future__ import annotations

from typing import Any


class MixedPatchOpsError(ValueError):
    """Raised when patch operations mix find-based and line-based ops."""


def resolve_field(raw) -> tuple[str, Any] | None:
    """Normalise a raw field value into (mode, payload) or None to skip.

    Bare string  -> ("replace", str)
    Bare list    -> ("additive", list)
    Mode object  -> (mode, value/operations)
    Empty / None -> None
    """
    if raw is None:
        return None
    if isinstance(raw, str):
        if raw == "":
            return None
        return ("replace", raw)
    if isinstance(raw, list):
        return ("additive", raw)
    if isinstance(raw, dict):
        mode = raw.get("mode")
        if mode in ("replace", "append"):
            return (mode, raw["value"])
        if mode == "patch":
            return ("patch", raw["operations"])
    return None


def apply_resolved_field(raw, existing: str | None) -> tuple[str | None, list[dict] | None]:
    """Resolve a field value and apply write mode to existing content.

    Returns (new_value, patch_reports). patch_reports is None unless mode was "patch".
    Returns (None, None) if field should be skipped.
    """
    resolved = resolve_field(raw)
    if resolved is None:
        return None, None
    mode, value = resolved
    if mode in ("replace", "additive"):
        return value, None
    result = apply_text_mode(existing, mode, value)
    if isinstance(result, tuple):
        return result[0], result[1]
    return result, None


def apply_text_mode(
    existing: str | None, mode: str, value
) -> str | tuple[str, list[dict]]:
    """Apply a write mode to an existing text value.

    Returns:
        str for replace/append modes.
        (result_text, patch_reports) for patch mode.
    """
    if mode == "replace":
        return value
    if mode == "append":
        if not existing:
            return value
        return existing + "\n" + value
    if mode == "patch":
        return _apply_patch(existing or "", value)
    raise ValueError(f"Unknown text mode: {mode!r}")


# ── patch internals ──────────────────────────────────────────────


def _classify_ops(operations: list[dict]) -> str:
    """Return 'find' or 'line', or raise MixedPatchOpsError."""
    has_find = False
    has_line = False
    for op in operations:
        if "find" in op:
            has_find = True
        if "lines" in op or "after_line" in op or "before_line" in op:
            has_line = True
    if has_find and has_line:
        raise MixedPatchOpsError(
            "Patch operations must be ALL find-based or ALL line-based, not mixed."
        )
    if has_find:
        return "find"
    return "line"


def _apply_patch(text: str, operations: list[dict]) -> tuple[str, list[dict]]:
    kind = _classify_ops(operations)
    if kind == "find":
        return _apply_find_patch(text, operations)
    return _apply_line_patch(text, operations)


def _apply_find_patch(
    text: str, operations: list[dict]
) -> tuple[str, list[dict]]:
    reports: list[dict] = []
    for i, op in enumerate(operations):
        find = op["find"]
        replace = op["replace"]
        if not find:
            reports.append({"op": i, "status": "no_match", "detail": "find string is empty"})
            continue
        count = text.count(find)
        if count == 0:
            reports.append({"op": i, "status": "no_match", "detail": f"{find!r} not found"})
        else:
            text = text.replace(find, replace)
            reports.append({"op": i, "status": "applied", "matches": count})
    return text, reports


def _op_sort_key(indexed_op: tuple[int, dict]) -> int:
    """Extract the effective line number for reverse-order sorting."""
    _, op = indexed_op
    if "lines" in op:
        return max(op["lines"])
    if "after_line" in op:
        return op["after_line"]
    if "before_line" in op:
        return op["before_line"]
    return 0


def _apply_line_patch(
    text: str, operations: list[dict]
) -> tuple[str, list[dict]]:
    lines = text.split("\n")

    # Pair each op with its original index, sort by descending line number
    indexed = list(enumerate(operations))
    indexed.sort(key=_op_sort_key, reverse=True)

    reports: list[dict] = [None] * len(operations)

    for orig_idx, op in indexed:
        if "lines" in op:
            target_lines = op["lines"]  # 1-indexed
            replace_text = op["replace"]

            # Check all lines are in range
            out_of_range = [ln for ln in target_lines if ln < 1 or ln > len(lines)]
            if out_of_range:
                reports[orig_idx] = {
                    "op": orig_idx,
                    "status": "no_match",
                    "detail": f"line {out_of_range[0]} out of range (1-{len(lines)})",
                }
                continue

            # Sort target lines ascending for contiguous replacement
            sorted_lines = sorted(target_lines)
            first_idx = sorted_lines[0] - 1  # 0-indexed

            # Remove the target lines (in reverse to preserve indices)
            for ln in reversed(sorted_lines):
                del lines[ln - 1]

            # Insert replacement (if non-empty) at the position of the first removed line
            if replace_text:
                for j, new_line in enumerate(replace_text.split("\n")):
                    lines.insert(first_idx + j, new_line)

            reports[orig_idx] = {"op": orig_idx, "status": "applied", "matches": len(sorted_lines)}

        elif "after_line" in op:
            ln = op["after_line"]
            if ln < 0 or ln > len(lines):
                reports[orig_idx] = {
                    "op": orig_idx,
                    "status": "no_match",
                    "detail": f"after_line {ln} out of range (0-{len(lines)})",
                }
                continue
            insert_lines = op["insert"].split("\n")
            for j, new_line in enumerate(insert_lines):
                lines.insert(ln + j, new_line)
            reports[orig_idx] = {"op": orig_idx, "status": "applied", "matches": 1}

        elif "before_line" in op:
            ln = op["before_line"]
            if ln < 1 or ln > len(lines) + 1:
                reports[orig_idx] = {
                    "op": orig_idx,
                    "status": "no_match",
                    "detail": f"before_line {ln} out of range (1-{len(lines) + 1})",
                }
                continue
            insert_lines = op["insert"].split("\n")
            idx = ln - 1  # 0-indexed
            for j, new_line in enumerate(insert_lines):
                lines.insert(idx + j, new_line)
            reports[orig_idx] = {"op": orig_idx, "status": "applied", "matches": 1}

        else:
            reports[orig_idx] = {"op": orig_idx, "status": "error", "detail": "unrecognized line op"}

    return "\n".join(lines), reports


# ── utilities ────────────────────────────────────────────────────


def format_cat_n(text: str) -> str:
    """Format text with 1-indexed line numbers, like cat -n.

    >>> format_cat_n("hello\\nworld")
    '1\\thello\\n2\\tworld'
    """
    lines = text.split("\n")
    return "\n".join(f"{i + 1}\t{line}" for i, line in enumerate(lines))


def line_count(text: str) -> int:
    """Count lines in text."""
    return len(text.split("\n"))
