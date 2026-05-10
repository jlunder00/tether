"""Shared helpers for API route modules."""
from fastapi import HTTPException
from db.pg_queries._motif import VALID_MOTIFS


def _validate_motif(body: dict) -> None:
    """Raise 422 if body contains an invalid motif value."""
    if "motif" in body and body["motif"] not in VALID_MOTIFS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid motif: {body['motif']!r}. Must be one of {sorted(VALID_MOTIFS)}",
        )
