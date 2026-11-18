from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from .approval import load_approved_artifact, matching_publication_receipt
from .artifacts import check as check_artifact
from .artifacts import stamp as stamp_artifact
from .articles import filter_articles_by_window, read_articles
from .brief import read_brief
from .review_log import latest_quality, read_review_log


ARTIFACTS = {
    "articles": "articles.json",
    "ranking": "ranking.json",
    "brief": "brief.json",
    "reviewed_brief": "brief.reviewed.json",
    "generated_html": "wechat_article_img.html",
    "reviewed_html": "reviewed/wechat_article_img.html",
    "review_state": "review_state.json",
    "review_log": "review_log.json",
    "publication_receipt": "publication_receipt.json",
    "run_manifest": "run.json",
}
STAGE_PRIORITY = {
    "empty": 0,
    "articles_ready": 1,
    "ready_for_review": 2,
    "review_in_progress": 3,
    "approved": 4,
    "published": 5,
}


def discover_report_dir(base_dir: Path, *, start: date, end: date) -> Path:
    slug = f"{start:%Y%m%d}_{end:%Y%m%d}"
    candidates = [path for path in base_dir.glob(slug + "*") if path.is_dir()]
    if not candidates:
        return base_dir / slug
    ranked: list[tuple[int, int, int, float, Path]] = []
    for path in candidates:
        status = inspect_workflow_status(path, start=start, end=end)
        ranked.append(
            (
                STAGE_PRIORITY[status["stage"]],
                -len(status["issues"]),
                int(path.name == slug),
                path.stat().st_mtime,
                path,
            )
        )
    return max(ranked, key=lambda item: item[:-1])[-1]


def inspect_workflow_status(report_dir: Path, *, start: date | None = None, end: date | None = None) -> dict[str, Any]:
    root = report_dir.resolve()
    paths = {name: root / relative for name, relative in ARTIFACTS.items()}
    exists = {name: path.is_file() for name, path in paths.items()}
    issues: list[str] = []
    source_count = 0
    in_window_count = 0
    if exists["articles"]:
        try:
            articles = read_articles(paths["articles"])
            source_count = len(articles)
            in_window_count = source_count
            if start is not None and end is not None:
                kept, excluded = filter_articles_by_window(articles, start, end)
                in_window_count = len(kept)
                if excluded:
                    issues.append(
                        f"{excluded} articles in articles.json fall outside the requested window "
                        f"{start.isoformat()}..{end.isoformat()} and will be ignored"
                    )
        except (ValueError, json.JSONDecodeError) as exc:
            issues.append(f"articles.json is invalid: {exc}")

    brief: dict[str, Any] | None = None
    active_brief = paths["reviewed_brief"] if exists["reviewed_brief"] else paths["brief"]
    if active_brief.is_file():
        try:
            brief = read_brief(active_brief)
        except (ValueError, json.JSONDecodeError) as exc:
            issues.append(f"brief is invalid: {exc}")
    if brief is not None and start is not None and end is not None:
        actual = (str(brief.get("window_start") or ""), str(brief.get("window_end") or ""))
        expected = (start.isoformat(), end.isoformat())
        if actual != expected:
            issues.append(f"brief window {actual[0]}..{actual[1]} does not match requested {expected[0]}..{expected[1]}")

    approved = False
    published = False
    try:
        artifact = load_approved_artifact(root)
        approved = True
        published = matching_publication_receipt(artifact) is not None
    except (ValueError, json.JSONDecodeError) as exc:
        artifact = None
        if "schema_version" in str(exc):
            issues.append(str(exc))

    if published:
        stage, next_action = "published", "report_complete"
    elif approved:
        stage, next_action = "approved", "confirm_then_publish"
    elif exists["reviewed_brief"]:
        stage, next_action = "review_in_progress", "continue_review"
    elif exists["brief"] and exists["generated_html"]:
        stage, next_action = "ready_for_review", "open_review"
    elif exists["articles"] and in_window_count:
        stage, next_action = "articles_ready", "build_with_llm"
    else:
        stage, next_action = "empty", "choose_source"
        if exists["articles"] and source_count and not in_window_count:
            issues.append("articles.json contains no articles inside the requested window")

    if brief is not None and not exists["articles"]:
        issues.append("articles.json is missing; generated content can be reviewed, but source evidence is unavailable")

    review_summary: dict[str, Any] = {}
    if exists["review_log"]:
        log = read_review_log(root)
        if log.get("error"):
            issues.append(f"review_log.json is invalid: {log['error']}")
        events = log.get("events") or []
        review_summary = {
            "event_count": len(events),
            "last_event": str((events[-1] or {}).get("type") or "") if events else "",
            "latest_quality": latest_quality(root),
        }

    if exists["run_manifest"]:
        try:
            run = check_artifact("run", json.loads(paths["run_manifest"].read_text(encoding="utf-8")))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            issues.append(f"run.json is invalid: {exc}")
        else:
            if run.get("status") == "failed":
                error = run.get("error") if isinstance(run.get("error"), dict) else {}
                message = str(error.get("message") or "unknown error")
                issues.append(f"last run failed: {error.get('type') or 'Error'}: {message}")

    return stamp_artifact(
        "status",
        {
            "report_dir": str(root),
            "window_start": start.isoformat() if start else (str(brief.get("window_start")) if brief else ""),
            "window_end": end.isoformat() if end else (str(brief.get("window_end")) if brief else ""),
            "stage": stage,
            "next_action": next_action,
            "source_count": source_count or (int(brief.get("source_count") or 0) if brief else 0),
            "in_window_count": in_window_count,
            "reuse": {
                "articles": exists["articles"] and in_window_count > 0,
                "generated_report": brief is not None and exists["generated_html"],
                "reviewed_report": exists["reviewed_brief"] and exists["reviewed_html"],
            },
            "gates": {
                "approved": approved,
                "published": published,
            },
            "review_log": review_summary,
            "artifacts": {
                name: {"path": str(path), "exists": exists[name]}
                for name, path in paths.items()
            },
            "issues": issues,
        },
    )
