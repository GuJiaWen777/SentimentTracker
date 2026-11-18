"""Colour tokens shared by the rules renderer and LLM synthesis."""

from __future__ import annotations


SIGNAL_COLORS: dict[str, tuple[str, str]] = {
    "监管": ("#FCEAEA", "#A32D2D"),
    "政策": ("#EEF5FC", "#2B72B8"),
    "竞争": ("#FEF3E2", "#854F0B"),
    "机会": ("#EDF6E3", "#3B6D11"),
}
NEUTRAL_COLOR = "#1C1F26"
TONE_COLORS: dict[str, str] = {
    "risk": "#A32D2D",
    "positive": "#3B6D11",
    "info": "#2B72B8",
    "neutral": NEUTRAL_COLOR,
}
