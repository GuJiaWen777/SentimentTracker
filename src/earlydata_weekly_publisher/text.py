from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


def strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def compact_text(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    position = max(text.rfind(mark, 0, limit + 1) for mark in "。！？；")
    return text[: position + 1] if position >= limit // 2 else text[:limit].rstrip() + "…"


def repair_title_symbols(title: str, content: str) -> str:
    if "?" not in title:
        return title
    repaired = title
    for _index in range(title.count("?")):
        position = repaired.find("?")
        left = repaired[:position]
        token_match = re.search(r"[\u4e00-\u9fffA-Za-z0-9]{2,16}$", left)
        token = token_match.group(0) if token_match else ""
        replacement = "？"
        for symbol in ("®", "™"):
            if any(token[-width:] + symbol in content for width in range(2, len(token) + 1)):
                replacement = symbol
                break
        repaired = repaired[:position] + replacement + repaired[position + 1 :]
    return repaired


def coerce_date(value: Any) -> date | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if float(value) > 1e11 else float(value)
        try:
            return datetime.fromtimestamp(seconds).date()
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def within_window(published_at: str, start: date, end: date) -> bool:
    published = coerce_date(published_at)
    return published is not None and start <= published <= end


def string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def as_int(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def cell_value(row: tuple[Any, ...], index: int) -> Any:
    return row[index - 1] if len(row) >= index else None


def unique_values(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
