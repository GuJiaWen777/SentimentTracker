from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from .approval import load_approved_artifact, matching_publication_receipt
from .pipeline import read_articles, read_brief


ARTIFACTS = {
    "articles": "articles.json",
    "ranking": "ranking.json",
    "brief": "brief.json",
    "reviewed_brief": "brief.reviewed.json",
    "generated_html": "wechat_article_img.html",
    "reviewed_html": "reviewed/wechat_article_img.html",
    "review_state": "review_state.json",
    "publication_receipt": "publication_receipt.json",
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
    if exists["articles"]:
        try:
            source_count = len(read_articles(paths["articles"]))
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
    except (ValueError, json.JSONDecodeError):
        artifact = None

    if published:
        stage, next_action = "published", "report_complete"
    elif approved:
        stage, next_action = "approved", "confirm_then_publish"
    elif exists["reviewed_brief"]:
        stage, next_action = "review_in_progress", "continue_review"
    elif exists["brief"] and exists["generated_html"]:
        stage, next_action = "ready_for_review", "open_review"
    elif exists["articles"] and source_count:
        stage, next_action = "articles_ready", "build_with_llm"
    else:
        stage, next_action = "empty", "choose_source"

    if brief is not None and not exists["articles"]:
        issues.append("articles.json is missing; generated content can be reviewed, but source evidence is unavailable")

    return {
        "report_dir": str(root),
        "window_start": start.isoformat() if start else (str(brief.get("window_start")) if brief else ""),
        "window_end": end.isoformat() if end else (str(brief.get("window_end")) if brief else ""),
        "stage": stage,
        "next_action": next_action,
        "source_count": source_count or (int(brief.get("source_count") or 0) if brief else 0),
        "reuse": {
            "articles": exists["articles"] and source_count > 0,
            "generated_report": brief is not None and exists["generated_html"],
            "reviewed_report": exists["reviewed_brief"] and exists["reviewed_html"],
        },
        "gates": {
            "can_review": brief is not None and (exists["generated_html"] or exists["reviewed_html"]),
            "approved": approved,
            "published": published,
        },
        "artifacts": {
            name: {"path": str(path), "exists": exists[name]}
            for name, path in paths.items()
        },
        "issues": issues,
    }
