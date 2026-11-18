from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol, runtime_checkable

from ..models import Article


class SourceError(ValueError):
    """A user-facing problem with a source request or its configuration."""


@dataclass(frozen=True)
class SourceInfo:
    name: str
    label: str
    description: str


@dataclass(frozen=True)
class SourceRequest:
    """Everything a source may need for one acquisition window."""

    start: date
    end: date
    accounts: tuple[str, ...] = ()
    path: Path | None = None
    include_content: bool = True


@runtime_checkable
class SourceAdapter(Protocol):
    """One upstream that can turn a request into ``Article`` rows.

    Adding a source means writing one module with an adapter class and
    registering it in ``sources.SOURCES``; the CLI and doctor pick it up
    automatically.
    """

    info: SourceInfo

    def required_config(self) -> dict[str, bool]:
        """Environment requirements, as ``label -> present``.

        Only presence is reported; values must never be returned.
        """

    def fetch(self, request: SourceRequest) -> list[Article]:
        ...
