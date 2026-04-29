"""Shared motif vocabulary — single source of truth for valid motif values."""
from __future__ import annotations

VALID_MOTIFS: frozenset[str] = frozenset(
    {"anchor", "focus", "calm", "energy", "care", "flow", "dusk", "quiet"}
)


def validate_motif(motif: str) -> None:
    """Raise ValueError if motif is not one of the allowed values."""
    if motif not in VALID_MOTIFS:
        raise ValueError(
            f"Invalid motif: {motif!r}. Must be one of {sorted(VALID_MOTIFS)}"
        )
