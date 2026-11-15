from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .pipeline import read_brief


DEFAULT_HISTORY_DB = Path("data/history/signals.sqlite3")
MAX_WEEKS = 52

SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
  report_key TEXT PRIMARY KEY,
  window_start TEXT NOT NULL,
  window_end TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  source_count INTEGER NOT NULL DEFAULT 0,
  model TEXT NOT NULL DEFAULT '',
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS signals (
  report_key TEXT NOT NULL,
  article_id TEXT NOT NULL,
  title TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT '',
  published_at TEXT NOT NULL DEFAULT '',
  signal TEXT NOT NULL DEFAULT '',
  summary TEXT NOT NULL DEFAULT '',
  so_what TEXT NOT NULL DEFAULT '',
  url TEXT NOT NULL DEFAULT '',
  score INTEGER,
  category TEXT NOT NULL DEFAULT '',
  reason TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (report_key, article_id)
);
CREATE TABLE IF NOT EXISTS entities (
  report_key TEXT NOT NULL,
  name TEXT NOT NULL,
  kind TEXT NOT NULL,
  PRIMARY KEY (report_key, name, kind)
);
CREATE INDEX IF NOT EXISTS idx_reports_window_end ON reports(window_end);
CREATE INDEX IF NOT EXISTS idx_signals_report ON signals(report_key);
CREATE INDEX IF NOT EXISTS idx_entities_report ON entities(report_key);
"""


def default_history_db() -> Path:
    return Path(os.environ.get("EARLYDATA_HISTORY_DB") or DEFAULT_HISTORY_DB)


def record_report(report_dir: Path, *, db_path: Path | None = None) -> dict[str, Any]:
    """Persist one report's selected signals and tags for cross-week trends."""
    root = Path(report_dir).resolve()
    brief_path = root / "brief.reviewed.json"
    if not brief_path.is_file():
        brief_path = root / "brief.json"
    if not brief_path.is_file():
        raise ValueError(f"No brief.json or brief.reviewed.json under {root}.")
    brief = read_brief(brief_path)
    start = date.fromisoformat(str(brief["window_start"]))
    end = date.fromisoformat(str(brief["window_end"]))
    report_key = f"{start:%Y%m%d}_{end:%Y%m%d}"
    target = Path(db_path) if db_path is not None else default_history_db()
    ranking = _ranking_map(root / "ranking.json")
    items = [item for item in brief.get("items", []) if isinstance(item, dict)]
    companies = _unique(str(value).strip() for value in brief.get("companies", []))
    technologies = _unique(str(value).strip() for value in brief.get("technologies", []))
    generation = brief.get("generation") if isinstance(brief.get("generation"), dict) else {}
    updated_at = datetime.now(timezone.utc).isoformat()

    connection = _connect(target)
    try:
        with connection:
            connection.execute("DELETE FROM signals WHERE report_key = ?", (report_key,))
            connection.execute("DELETE FROM entities WHERE report_key = ?", (report_key,))
            connection.execute(
                """
                INSERT OR REPLACE INTO reports
                  (report_key, window_start, window_end, title, source_count, model, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report_key,
                    start.isoformat(),
                    end.isoformat(),
                    str(brief.get("title") or ""),
                    int(brief.get("source_count") or 0),
                    str(generation.get("model") or generation.get("mode") or ""),
                    updated_at,
                ),
            )
            for index, item in enumerate(items, start=1):
                article_id = str(item.get("article_id") or "").strip() or f"a{index:04d}"
                rank = ranking.get(article_id, {})
                connection.execute(
                    """
                    INSERT OR REPLACE INTO signals
                      (report_key, article_id, title, source, published_at, signal,
                       summary, so_what, url, score, category, reason)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        report_key,
                        article_id,
                        str(item.get("title") or ""),
                        str(item.get("source") or ""),
                        str(item.get("date") or ""),
                        str(item.get("signal") or ""),
                        str(item.get("summary") or ""),
                        str(item.get("so_what") or ""),
                        str(item.get("url") or ""),
                        rank.get("score") if isinstance(rank.get("score"), int) else None,
                        str(rank.get("category") or ""),
                        str(rank.get("reason") or ""),
                    ),
                )
            for kind, values in (("company", companies), ("technology", technologies)):
                for name in values:
                    connection.execute(
                        "INSERT OR REPLACE INTO entities (report_key, name, kind) VALUES (?, ?, ?)",
                        (report_key, name, kind),
                    )
    finally:
        connection.close()
    return {
        "report_key": report_key,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "signal_count": len(items),
        "company_count": len(companies),
        "technology_count": len(technologies),
        "db": str(target),
    }


def trend_summary(db_path: Path | None = None, *, until: date | None = None, weeks: int = 8) -> dict[str, Any]:
    """Return signal counts and entity streaks for recent recorded reports."""
    target = Path(db_path) if db_path is not None else default_history_db()
    if not target.is_file():
        return _empty_summary()
    limit = max(1, min(int(weeks), MAX_WEEKS))
    try:
        connection = sqlite3.connect(target, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            where = ""
            params: list[Any] = []
            if until is not None:
                where = "WHERE window_end <= ?"
                params.append(until.isoformat())
            rows = connection.execute(
                f"SELECT * FROM reports {where} ORDER BY window_end DESC, window_start DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
            if not rows:
                return _empty_summary()
            keys = [str(row["report_key"]) for row in rows]
            placeholders = ",".join("?" for _ in keys)
            signal_rows = connection.execute(
                f"SELECT report_key, signal, COUNT(*) AS count FROM signals "
                f"WHERE report_key IN ({placeholders}) GROUP BY report_key, signal",
                keys,
            ).fetchall()
            category_rows = connection.execute(
                f"SELECT report_key, category, COUNT(*) AS count FROM signals "
                f"WHERE report_key IN ({placeholders}) AND category != '' GROUP BY report_key, category",
                keys,
            ).fetchall()
            entity_rows = connection.execute(
                f"SELECT report_key, name, kind FROM entities WHERE report_key IN ({placeholders})",
                keys,
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.DatabaseError as exc:
        return _empty_summary(str(exc))

    signal_counts: dict[str, dict[str, int]] = {key: {} for key in keys}
    for row in signal_rows:
        signal_counts[str(row["report_key"])][str(row["signal"] or "未分类")] = int(row["count"])
    category_counts: dict[str, dict[str, int]] = {key: {} for key in keys}
    for row in category_rows:
        category_counts[str(row["report_key"])][str(row["category"])] = int(row["count"])
    week_entities: dict[str, list[dict[str, str]]] = {key: [] for key in keys}
    entity_weeks: dict[tuple[str, str], set[str]] = {}
    for row in entity_rows:
        key, name, kind = str(row["report_key"]), str(row["name"]), str(row["kind"])
        entity_weeks.setdefault((name, kind), set()).add(key)
        week_entities[key].append({"name": name, "kind": kind})

    entities: list[dict[str, Any]] = []
    for (name, kind), present in entity_weeks.items():
        streak = 0
        for key in keys:
            if key not in present:
                break
            streak += 1
        entities.append({"name": name, "kind": kind, "streak": streak, "appearances": len(present)})
    entities.sort(key=lambda entry: (-entry["streak"], -entry["appearances"], entry["name"], entry["kind"]))

    weeks_out: list[dict[str, Any]] = []
    for row in reversed(rows):
        key = str(row["report_key"])
        weeks_out.append(
            {
                "report_key": key,
                "window_start": str(row["window_start"]),
                "window_end": str(row["window_end"]),
                "title": str(row["title"]),
                "source_count": int(row["source_count"]),
                "signal_counts": signal_counts.get(key, {}),
                "category_counts": category_counts.get(key, {}),
                "entities": sorted(week_entities.get(key, []), key=lambda entry: (entry["kind"], entry["name"])),
            }
        )
    return {
        "window_count": len(rows),
        "weeks": weeks_out,
        "entities": entities[:30],
        "persistent_entities": [entry for entry in entities if entry["streak"] >= 2][:20],
    }


def trend_context_for_window(db_path: Path | None, start: date, *, weeks: int = 8) -> dict[str, Any]:
    """History context for a report starting on ``start`` (excludes that window)."""
    return trend_summary(db_path, until=start - timedelta(days=1), weeks=weeks)


def trend_context_for_report(db_path: Path | None, brief: dict[str, Any], *, weeks: int = 8) -> dict[str, Any]:
    """History plus new/continuing entity comparisons for the review workbench."""
    start = date.fromisoformat(str(brief["window_start"]))
    summary = trend_context_for_window(db_path, start, weeks=weeks)
    current = [
        {"name": str(value).strip(), "kind": "company"}
        for value in brief.get("companies", [])
        if str(value).strip()
    ]
    current.extend(
        {"name": str(value).strip(), "kind": "technology"}
        for value in brief.get("technologies", [])
        if str(value).strip()
    )
    current_keys = {(entry["name"], entry["kind"]) for entry in current}
    weeks_data = summary.get("weeks") or []
    previous = (
        {(entry["name"], entry["kind"]) for entry in weeks_data[-1].get("entities", [])}
        if weeks_data
        else set()
    )
    persistent = {
        (entry["name"], entry["kind"]): entry
        for entry in summary.get("persistent_entities", [])
    }
    summary["current_entities"] = sorted(current, key=lambda entry: (entry["kind"], entry["name"]))
    summary["new_entities"] = (
        [{"name": name, "kind": kind} for name, kind in sorted(current_keys - previous)]
        if weeks_data
        else []
    )
    summary["continuing_entities"] = [
        persistent[key] for key in sorted(current_keys & set(persistent))
    ]
    return summary


def _empty_summary(error: str = "") -> dict[str, Any]:
    summary: dict[str, Any] = {
        "window_count": 0,
        "weeks": [],
        "entities": [],
        "persistent_entities": [],
        "current_entities": [],
        "new_entities": [],
        "continuing_entities": [],
    }
    if error:
        summary["error"] = error
    return summary


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.executescript(SCHEMA)
    return connection


def _ranking_map(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rows = data.get("items", []) if isinstance(data, dict) else []
    return {
        str(row.get("article_id")): row
        for row in rows
        if isinstance(row, dict) and row.get("article_id")
    }


def _unique(values: Any) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
