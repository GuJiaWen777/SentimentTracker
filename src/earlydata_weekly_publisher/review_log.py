from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifacts import check as check_artifact
from .artifacts import stamp as stamp_artifact
from .io_utils import write_json_atomic
from .locking import FileLock

REVIEW_LOG_NAME = "review_log.json"
MAX_EVENTS = 200
MAX_VALUE_CHARS = 400

SCALAR_FIELDS = ("title", "key_signal", "companies", "technologies", "insights", "follow_up", "dashboard")
ITEM_FIELDS = ("title", "source", "date", "signal", "background", "summary", "so_what", "url", "category")


def read_review_log(report_dir: Path) -> dict[str, Any]:
    """Read the audit trail; a damaged log is reported instead of breaking review."""
    path = Path(report_dir) / REVIEW_LOG_NAME
    if not path.is_file():
        return stamp_artifact("review_log", {"events": []})
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        log = check_artifact("review_log", data)
    except (OSError, ValueError) as exc:
        return stamp_artifact("review_log", {"events": [], "error": f"{type(exc).__name__}: {exc}"})
    events = log.get("events")
    return {
        **log,
        "events": [event for event in events if isinstance(event, dict)] if isinstance(events, list) else [],
    }


def append_event(report_dir: Path, event: dict[str, Any]) -> dict[str, Any]:
    """Append one audit event, keeping the newest ``MAX_EVENTS`` entries."""
    root = Path(report_dir)
    root.mkdir(parents=True, exist_ok=True)
    entry = dict(event)
    entry.setdefault("at", datetime.now(timezone.utc).isoformat())
    with FileLock(root / (REVIEW_LOG_NAME + ".lock"), description="review log update"):
        log = read_review_log(root)
        events = list(log.get("events") or [])
        events.append(entry)
        write_json_atomic(root / REVIEW_LOG_NAME, stamp_artifact("review_log", {"events": events[-MAX_EVENTS:]}))
    return entry


def diff_briefs(previous: dict[str, Any], current: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the editorial changes between two brief revisions."""
    changes: list[dict[str, Any]] = []
    previous = previous if isinstance(previous, dict) else {}
    current = current if isinstance(current, dict) else {}
    for field in SCALAR_FIELDS:
        before, after = previous.get(field), current.get(field)
        if before != after:
            changes.append({"path": field, "before": _clip(before), "after": _clip(after)})
    changes.extend(_diff_entries("items", previous.get("items"), current.get("items")))
    changes.extend(_diff_entries("alternates", previous.get("alternates"), current.get("alternates")))
    return changes


def summarize_quality(quality: dict[str, Any]) -> dict[str, Any]:
    """Reduce the review quality payload to counts and issue codes for the log."""
    if not isinstance(quality, dict):
        return {"error_count": 0, "warning_count": 0, "codes": {}}
    issues = quality.get("issues")
    if issues is None:
        # Already summarized (for example when read back from the log).
        codes = quality.get("codes") if isinstance(quality.get("codes"), dict) else {}
        return {
            "error_count": int(quality.get("error_count") or 0),
            "warning_count": int(quality.get("warning_count") or 0),
            "codes": dict(sorted((str(code), int(count)) for code, count in codes.items())),
        }
    counts = Counter(
        str(issue.get("code") or "unknown")
        for issue in issues
        if isinstance(issue, dict)
    )
    return {
        "error_count": int(quality.get("error_count") or 0),
        "warning_count": int(quality.get("warning_count") or 0),
        "codes": dict(sorted(counts.items())),
    }


def latest_quality(report_dir: Path) -> dict[str, Any] | None:
    """Quality recorded by the most recent approval, if the log has one."""
    for event in reversed(read_review_log(report_dir).get("events") or []):
        if event.get("type") != "approve":
            continue
        quality = event.get("quality")
        if isinstance(quality, dict):
            return summarize_quality(quality)
    return None


def quality_history(report_dir: Path) -> list[dict[str, Any]]:
    """Approval-time quality samples in chronological order."""
    samples: list[dict[str, Any]] = []
    for event in read_review_log(report_dir).get("events") or []:
        if event.get("type") != "approve" or not isinstance(event.get("quality"), dict):
            continue
        samples.append({"at": str(event.get("at") or ""), **summarize_quality(event["quality"])})
    return samples


def format_review_log(log: dict[str, Any], *, limit: int = 20) -> str:
    events = list(log.get("events") or [])
    if not events:
        message = "暂无审核记录。"
        if log.get("error"):
            message += f"\n审核记录读取失败：{log['error']}"
        return message
    lines = [f"审核记录共 {len(events)} 条事件"]
    for event in events[-max(1, limit) :]:
        kind = str(event.get("type") or "unknown")
        at = str(event.get("at") or "")
        if kind == "save":
            changes = [change for change in event.get("changes") or [] if isinstance(change, dict)]
            swaps = sum(1 for change in changes if change.get("kind") == "swap")
            detail = f"{len(changes)} 处修改" + (f"（换稿 {swaps}）" if swaps else "")
        elif kind == "approve":
            quality = event.get("quality") if isinstance(event.get("quality"), dict) else {}
            detail = f"错误 {quality.get('error_count', 0)} · 警告 {quality.get('warning_count', 0)}"
        elif kind == "publish":
            detail = f"{event.get('status') or 'published'} · {event.get('media_id') or ''}".strip(" ·")
        else:
            detail = ""
        lines.append(f"{at} {kind}：{detail}" if detail else f"{at} {kind}")
    return "\n".join(lines)


def _diff_entries(section: str, before: Any, after: Any) -> list[dict[str, Any]]:
    old = [row for row in before if isinstance(row, dict)] if isinstance(before, list) else []
    new = [row for row in after if isinstance(row, dict)] if isinstance(after, list) else []
    changes: list[dict[str, Any]] = []
    for index in range(max(len(old), len(new))):
        path = f"{section}.{index}"
        if index >= len(new):
            row = old[index]
            changes.append(
                {
                    "path": path,
                    "kind": "removed",
                    "article_id": _article_id(row),
                    "title": _clip(row.get("title")),
                }
            )
            continue
        if index >= len(old):
            row = new[index]
            changes.append(
                {
                    "path": path,
                    "kind": "added",
                    "article_id": _article_id(row),
                    "title": _clip(row.get("title")),
                }
            )
            continue
        old_row, new_row = old[index], new[index]
        old_id, new_id = _article_id(old_row), _article_id(new_row)
        if old_id != new_id:
            changes.append(
                {
                    "path": path,
                    "kind": "swap",
                    "before_article_id": old_id,
                    "after_article_id": new_id,
                    "before_title": _clip(old_row.get("title")),
                    "after_title": _clip(new_row.get("title")),
                }
            )
            continue
        for field in ITEM_FIELDS:
            if old_row.get(field) == new_row.get(field):
                continue
            changes.append(
                {
                    "path": f"{path}.{field}",
                    "article_id": old_id,
                    "before": _clip(old_row.get(field)),
                    "after": _clip(new_row.get(field)),
                }
            )
    return changes


def _article_id(row: dict[str, Any]) -> str:
    return str(row.get("article_id") or "")


def _clip(value: Any) -> Any:
    if isinstance(value, str):
        return value[:MAX_VALUE_CHARS]
    if isinstance(value, list):
        return value[:12]
    return value
