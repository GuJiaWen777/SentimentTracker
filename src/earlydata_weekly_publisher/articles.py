from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .artifacts import check as check_artifact
from .artifacts import stamp as stamp_artifact
from .models import Article
from .text import as_int, coerce_date, repair_title_symbols, string_list


def parse_day(value: str) -> date:
    return date.fromisoformat(value)


def validate_window(start: date, end: date) -> None:
    if start > end:
        raise ValueError(f"Window start {start.isoformat()} is after end {end.isoformat()}.")


def window_slug(start: date, end: date) -> str:
    return f"{start:%Y%m%d}_{end:%Y%m%d}"


def filter_articles_by_window(articles: list[Article], start: date, end: date) -> tuple[list[Article], int]:
    kept: list[Article] = []
    excluded = 0
    for article in articles:
        published = coerce_date(article.published_at)
        if published is not None and start <= published <= end:
            kept.append(article)
        else:
            excluded += 1
    return kept, excluded


def write_articles(path: Path, articles: list[Article]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = stamp_artifact("articles", {"articles": [asdict(article) for article in articles]})
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def read_articles(path: Path) -> list[Article]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        check_artifact("articles", data)
    rows = data.get("articles", data) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError("articles.json must contain an articles array.")
    articles: list[Article] = []
    for raw in rows:
        if not isinstance(raw, dict) or not str(raw.get("title") or "").strip():
            continue
        content = str(raw.get("content") or "")
        articles.append(
            Article(
                title=repair_title_symbols(str(raw.get("title") or "").strip(), content),
                source=str(raw.get("source") or raw.get("account") or "来源").strip(),
                published_at=str(raw.get("published_at") or "")[:10],
                content=content,
                summary=str(raw.get("summary") or ""),
                url=str(raw.get("url") or ""),
                tags=string_list(raw.get("tags")),
                entities=string_list(raw.get("entities")),
                read_count=as_int(raw.get("read_count")),
                like_count=as_int(raw.get("like_count")),
                share_count=as_int(raw.get("share_count")),
                recommend_count=as_int(raw.get("recommend_count")),
                article_id=str(raw.get("article_id") or "").strip(),
            )
        )
    return articles
