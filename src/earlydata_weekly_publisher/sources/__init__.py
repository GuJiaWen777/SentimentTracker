"""Article sources.

Each module exposes an adapter class registered in ``SOURCES``; the CLI and
``doctor`` discover sources through this registry instead of hard-coding names.
"""

from __future__ import annotations

from .base import SourceAdapter, SourceError, SourceInfo, SourceRequest
from .pb_xlsx import XlsxSource, ingest_pb_xlsx
from .redfox import RedFoxSource, fetch_redfox


SOURCES: dict[str, SourceAdapter] = {source.info.name: source for source in (RedFoxSource(), XlsxSource())}


def source_names() -> tuple[str, ...]:
    return tuple(SOURCES)


def get_source(name: str) -> SourceAdapter:
    try:
        return SOURCES[name]
    except KeyError:
        choices = ", ".join(SOURCES)
        raise SourceError(f"Unknown source {name!r}; choose from {choices}.") from None


__all__ = [
    "SOURCES",
    "SourceAdapter",
    "SourceError",
    "SourceInfo",
    "SourceRequest",
    "XlsxSource",
    "RedFoxSource",
    "fetch_redfox",
    "get_source",
    "ingest_pb_xlsx",
    "source_names",
]
