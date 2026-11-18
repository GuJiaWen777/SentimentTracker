from __future__ import annotations

from typing import Any


"""Schema versions for persisted artifacts and machine-readable output.

Version 0 means a file written before versioning was introduced. It is read
as legacy data with the current shape. A file written by a newer release is
rejected instead of being silently misinterpreted.
"""

SCHEMA_VERSIONS: dict[str, int] = {
    "articles": 1,
    "brief": 1,
    "ranking": 1,
    "review_state": 1,
    "review_log": 1,
    "publication_receipt": 1,
    "run": 1,
    "status": 1,
    "history": 1,
    "doctor": 1,
}


class ArtifactSchemaError(ValueError):
    """Raised when an artifact was written by an incompatible release."""


def current_version(kind: str) -> int:
    try:
        return SCHEMA_VERSIONS[kind]
    except KeyError as exc:
        raise ValueError(f"Unknown artifact kind: {kind!r}.") from exc


def stamp(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``payload`` carrying the current schema version."""
    version = current_version(kind)
    stamped = dict(payload)
    stamped["schema_version"] = version
    return stamped


def check(kind: str, payload: Any) -> dict[str, Any]:
    """Validate the schema version of a persisted artifact.

    Missing ``schema_version`` is treated as legacy version 0. The payload's
    concrete fields are still validated by the caller.
    """
    if not isinstance(payload, dict):
        raise ArtifactSchemaError(f"{kind} must contain a JSON object.")
    supported = current_version(kind)
    raw = payload.get("schema_version", 0)
    if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
        raise ArtifactSchemaError(f"{kind} has an invalid schema_version: {raw!r}.")
    if raw > supported:
        raise ArtifactSchemaError(
            f"{kind} schema_version {raw} is newer than supported version {supported}; "
            "upgrade earlydata-weekly-publisher before reading this file."
        )
    return payload
