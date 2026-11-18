from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from .artifacts import check as check_artifact
from .artifacts import stamp as stamp_artifact
from .articles import filter_articles_by_window, validate_window
from .heuristics import (
    article_text,
    company_tags,
    ranked_pool,
    signal_style,
    so_what,
    summarize,
    technology_tags,
)
from .models import Article, ensure_article_ids
from .render import render_html, render_markdown, validate_html
from .text import compact_text
from .theme import NEUTRAL_COLOR, TONE_COLORS


def read_brief(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    check_artifact("brief", data)
    return validate_brief_data(data)


def validate_brief_data(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("brief.json must contain a JSON object.")
    required = {
        "title",
        "window_start",
        "window_end",
        "source_count",
        "key_signal",
        "dashboard",
        "companies",
        "technologies",
        "items",
        "insights",
        "follow_up",
        "sources",
    }
    missing = sorted(required - set(data))
    if missing:
        raise ValueError("brief.json is missing required fields: " + ", ".join(missing))
    if not isinstance(data.get("items"), list):
        raise ValueError("brief.json field 'items' must be an array.")
    if "alternates" in data and not isinstance(data["alternates"], list):
        raise ValueError("brief.json field 'alternates' must be an array.")
    return data


def build_brief(articles: list[Article], start: date, end: date, title: str | None = None) -> dict[str, Any]:
    validate_window(start, end)
    if not articles:
        raise ValueError("No articles available for the selected window.")
    ensure_article_ids(articles)
    pool = ranked_pool(articles)
    selected = pool[:6]
    alternates = pool[6:12]
    rows = [brief_item(article) for article in selected]
    alternate_rows = [brief_item(article) for article in alternates]
    companies = company_tags(selected)
    technologies = technology_tags(selected)
    risk_count = sum(1 for article in selected if signal_style(article)[0] == "监管")
    ai_count = sum(1 for article in selected if "AI" in article_text(article) or "人工智能" in article_text(article))
    deal_count = sum(
        1
        for article in selected
        if any(word in article_text(article) for word in ("BD", "合作", "授权", "并购", "交易", "License"))
    )
    summary = compact_text("；".join(item["summary"] for item in rows[:3]), 210)
    return {
        "title": title or f"AI CEO 生物医药舆情周报 {start:%Y.%m.%d}-{end:%m.%d}",
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "source_count": len(articles),
        "key_signal": summary,
        "dashboard": [
            ["监管动向", f"{risk_count} 条", TONE_COLORS["risk"] if risk_count else NEUTRAL_COLOR],
            ["AI 落地", f"{ai_count} 条", TONE_COLORS["positive"] if ai_count else NEUTRAL_COLOR],
            ["市场并购", f"{deal_count} 条", TONE_COLORS["info"] if deal_count else NEUTRAL_COLOR],
            ["本周信号数", f"{len(selected)} 条", NEUTRAL_COLOR],
        ],
        "companies": companies,
        "technologies": technologies,
        "items": rows,
        "alternates": alternate_rows,
        "insights": [so_what(article) for article in selected[:3]],
        "follow_up": [article.title for article in selected[3:6]],
        "sources": list(dict.fromkeys(article.source for article in selected if article.source)),
        "generation": {"mode": "rules"},
    }


def brief_item(article: Article) -> dict[str, Any]:
    label, background, color = signal_style(article)
    return {
        "article_id": article.article_id,
        "title": article.title,
        "source": article.source,
        "date": article.published_at,
        "summary": summarize(article),
        "signal": label,
        "background": background,
        "color": color,
        "so_what": so_what(article),
        "url": article.url,
        "score": None,
        "category": "",
        "reason": "规则模式：按启发式重要性排序",
    }


def generate_brief(
    articles: list[Article],
    start: date,
    end: date,
    title: str | None = None,
    *,
    generator: str = "llm",
    llm_client: Any | None = None,
    llm_backend: str | None = None,
    ranking_cache_path: Path | None = None,
    history_db: Path | None = None,
) -> dict[str, Any]:
    mode = generator.strip().lower()
    if mode not in {"llm", "rules"}:
        raise ValueError("generator must be 'llm' or 'rules'.")
    validate_window(start, end)
    articles = ensure_article_ids(articles)
    articles, excluded = filter_articles_by_window(articles, start, end)
    if not articles:
        raise ValueError(f"No articles available in window {start.isoformat()}..{end.isoformat()}.")
    history_context = None
    if history_db is not None:
        from .signal_history import trend_context_for_window

        history_context = trend_context_for_window(history_db, start)
    if mode == "rules":
        brief = build_brief(articles, start, end, title)
    else:
        from .semantic_generation import build_semantic_brief

        brief = build_semantic_brief(
            articles,
            start,
            end,
            title,
            client=llm_client,
            backend=llm_backend,
            ranking_cache_path=ranking_cache_path,
            history_context=history_context,
        )
    brief["generation"]["excluded_outside_window"] = excluded
    brief["generation"]["history_weeks"] = int((history_context or {}).get("window_count") or 0)
    return brief


def write_brief_outputs(brief: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    brief_path = output_dir / "brief.json"
    public_brief = stamp_artifact("brief", {key: value for key, value in brief.items() if not key.startswith("_")})
    brief_path.write_text(json.dumps(public_brief, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs = {"brief": brief_path, **write_rendered_outputs(brief, output_dir)}
    ranking = brief.get("_ranking")
    if isinstance(ranking, dict):
        ranking_path = output_dir / "ranking.json"
        ranking_path.write_text(
            json.dumps(stamp_artifact("ranking", ranking), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        outputs["ranking"] = ranking_path
    return outputs


def write_rendered_outputs(brief: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "wechat_article.md"
    html_path = output_dir / "wechat_article_img.html"
    markdown = render_markdown(brief)
    html = render_html(brief)
    validate_html(html)
    md_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")
    return {"markdown": md_path, "html": html_path}
