from __future__ import annotations

import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from .llm_client import create_llm_client
from .prompts import (
    RANKING_PROMPT_VERSION,
    RANKING_SYSTEM_PROMPT,
    SYNTHESIS_PROMPT_VERSION,
    SYNTHESIS_SYSTEM_PROMPT,
    ranking_prompt,
    synthesis_prompt,
)
from .ranking_cache import RankingCache
from .text import excerpt as excerpt_text
from .theme import NEUTRAL_COLOR, SIGNAL_COLORS, TONE_COLORS


RANKING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "articles": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "article_id": {"type": "string"},
                    "score": {"type": "integer", "minimum": 0, "maximum": 100},
                    "reason": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": ["监管", "政策", "交易", "临床", "技术", "资本", "市场", "其他"],
                    },
                },
                "required": ["article_id", "score", "reason", "category"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["articles"],
    "additionalProperties": False,
}

SYNTHESIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "key_signal": {"type": "string"},
        "dashboard": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string", "enum": ["监管动向", "AI 落地", "市场并购"]},
                    "value": {"type": "string"},
                    "tone": {"type": "string", "enum": ["risk", "positive", "info", "neutral"]},
                },
                "required": ["label", "value", "tone"],
                "additionalProperties": False,
            },
        },
        "selected": {
            "type": "array",
            "minItems": 1,
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "article_id": {"type": "string"},
                    "signal": {"type": "string", "enum": ["监管", "政策", "竞争", "机会"]},
                    "summary": {"type": "string"},
                    "so_what": {"type": "string"},
                },
                "required": ["article_id", "signal", "summary", "so_what"],
                "additionalProperties": False,
            },
        },
        "alternates": {
            "type": "array",
            "minItems": 0,
            "maxItems": 6,
            "items": {
                "type": "object",
                "properties": {
                    "article_id": {"type": "string"},
                    "signal": {"type": "string", "enum": ["监管", "政策", "竞争", "机会"]},
                    "summary": {"type": "string"},
                    "so_what": {"type": "string"},
                },
                "required": ["article_id", "signal", "summary", "so_what"],
                "additionalProperties": False,
            },
        },
        "companies": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
        "technologies": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
        "insights": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "string"}},
        "follow_up": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "string"}},
    },
    "required": ["key_signal", "dashboard", "selected", "alternates", "companies", "technologies", "insights", "follow_up"],
    "additionalProperties": False,
}


class JsonLLM(Protocol):
    @property
    def model_name(self) -> str: ...

    def complete_json(
        self,
        *,
        system_prompt: str,
        prompt: str,
        schema_name: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]: ...


def build_semantic_brief(
    articles: list[Any],
    start: date,
    end: date,
    title: str | None = None,
    *,
    client: JsonLLM | None = None,
    backend: str | None = None,
    ranking_cache_path: Path | None = None,
    history_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not articles:
        raise ValueError("No articles available for the selected window.")
    started = time.monotonic()
    llm = client or create_llm_client(backend)
    from .models import ensure_article_ids

    article_map = {article.article_id: article for article in ensure_article_ids(articles)}
    cache = (
        RankingCache.open(ranking_cache_path, model=llm.model_name, prompt_version=RANKING_PROMPT_VERSION)
        if ranking_cache_path is not None
        else None
    )
    rankings = _rank_all(article_map, start, end, llm, cache=cache)
    unique_rankings = _dedupe_rankings(rankings)
    candidate_count = min(_env_int("LLM_SYNTHESIS_CANDIDATES", 24, minimum=6, maximum=60), len(unique_rankings))
    candidates = unique_rankings[:candidate_count]
    selection_count = min(6, len(candidates))
    synthesis_rows = [_synthesis_row(row, article_map[row["article_id"]]) for row in candidates]
    print(f"[llm] synthesizing {selection_count} signals from top {candidate_count} unique candidates", flush=True)
    synthesis = llm.complete_json(
        system_prompt=SYNTHESIS_SYSTEM_PROMPT,
        prompt=synthesis_prompt(
            rows=synthesis_rows,
            start=start,
            end=end,
            selection_count=selection_count,
            history_context=history_context,
        ),
        schema_name="earlydata_weekly_synthesis",
        schema=SYNTHESIS_SCHEMA,
    )
    candidate_ids = {row["article_id"] for row in candidates}
    selected, alternates = _validated_selection(synthesis, article_map, candidate_ids, selection_count)
    ranking_by_id = {row["article_id"]: row for row in rankings}
    dashboard = _dashboard(synthesis.get("dashboard"), selection_count)
    items = [_signal_item(article_map[entry["article_id"]], entry, ranking_by_id.get(entry["article_id"])) for entry in selected]
    alternate_items = [
        _signal_item(article_map[entry["article_id"]], entry, ranking_by_id.get(entry["article_id"]))
        for entry in alternates
    ]
    return {
        "title": title or f"AI CEO 生物医药舆情周报 {start:%Y.%m.%d}-{end:%m.%d}",
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "source_count": len(articles),
        "key_signal": _required_text(synthesis, "key_signal"),
        "dashboard": dashboard,
        "companies": _text_list(synthesis, "companies", maximum=5),
        "technologies": _text_list(synthesis, "technologies", maximum=5),
        "items": items,
        "alternates": alternate_items,
        "insights": _text_list(synthesis, "insights", exact=3),
        "follow_up": _text_list(synthesis, "follow_up", exact=3),
        "sources": list(dict.fromkeys(item["source"] for item in items if item["source"])),
        "generation": {
            "mode": "llm",
            "backend": str(getattr(llm, "backend", "") or backend or os.environ.get("LLM_BACKEND") or "custom"),
            "model": llm.model_name,
            "prompt_versions": {
                "ranking": RANKING_PROMPT_VERSION,
                "synthesis": SYNTHESIS_PROMPT_VERSION,
            },
            "ranked_article_count": len(rankings),
            "unique_article_count": len(unique_rankings),
            "candidate_count": candidate_count,
            "synthesis_candidates": _env_int("LLM_SYNTHESIS_CANDIDATES", 24, minimum=6, maximum=60),
            "rank_batch_size": _env_int("LLM_RANK_BATCH_SIZE", 40, minimum=5, maximum=100),
            "cache_hits": cache.hits if cache else 0,
            "cache_misses": cache.misses if cache else len(rankings),
            "history_weeks": int((history_context or {}).get("window_count") or 0),
            "usage": dict(getattr(llm, "usage", {}) or {}),
            "duration_seconds": round(time.monotonic() - started, 3),
        },
        "_ranking": {
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "model": llm.model_name,
            "article_count": len(rankings),
            "items": rankings,
        },
    }


def _rank_all(
    article_map: dict[str, Any],
    start: date,
    end: date,
    client: JsonLLM,
    *,
    cache: RankingCache | None = None,
) -> list[dict[str, Any]]:
    batch_size = _env_int("LLM_RANK_BATCH_SIZE", 40, minimum=5, maximum=100)
    pairs = list(article_map.items())
    results: list[dict[str, Any]] = []
    pending: list[tuple[str, Any]] = []
    for article_id, article in pairs:
        cached = cache.get(article) if cache else None
        if cached is not None:
            results.append(_ranking_result(article_id, article, cached))
        else:
            pending.append((article_id, article))
    if cache:
        print(f"[llm] ranking cache: {cache.hits} hits, {cache.misses} misses", flush=True)
    batch_count = (len(pending) + batch_size - 1) // batch_size
    for batch_index, offset in enumerate(range(0, len(pending), batch_size), start=1):
        batch = pending[offset : offset + batch_size]
        rows = [_ranking_row(article_id, article) for article_id, article in batch]
        print(f"[llm] ranking batch {batch_index}/{batch_count} ({len(batch)} articles)", flush=True)
        payload = client.complete_json(
            system_prompt=RANKING_SYSTEM_PROMPT,
            prompt=ranking_prompt(rows=rows, start=start, end=end, batch_index=batch_index, batch_count=batch_count),
            schema_name="earlydata_article_ranking",
            schema=RANKING_SCHEMA,
        )
        ranked = payload.get("articles")
        if not isinstance(ranked, list):
            raise RuntimeError("LLM ranking response must contain an articles array.")
        expected = {article_id for article_id, _article in batch}
        returned = {str(item.get("article_id") or "") for item in ranked if isinstance(item, dict)}
        if returned != expected or len(ranked) != len(expected):
            missing = sorted(expected - returned)
            extra = sorted(returned - expected)
            raise RuntimeError(f"LLM ranking batch {batch_index} has mismatched IDs; missing={missing}, extra={extra}.")
        for item in ranked:
            if not isinstance(item, dict):
                raise RuntimeError("LLM ranking item must be an object.")
            article_id = str(item["article_id"])
            score = int(item["score"])
            if not 0 <= score <= 100:
                raise RuntimeError(f"LLM ranking score for {article_id} must be between 0 and 100.")
            article = article_map[article_id]
            category = _required_text(item, "category")
            if category not in {"监管", "政策", "交易", "临床", "技术", "资本", "市场", "其他"}:
                raise RuntimeError(f"LLM ranking category for {article_id} is invalid: {category!r}.")
            reason = _required_text(item, "reason")
            if cache:
                cache.put(article, score=score, category=category, reason=reason)
            results.append(_ranking_result(article_id, article, {"score": score, "category": category, "reason": reason}))
    if cache and pending:
        try:
            cache.save()
        except OSError as exc:
            print(f"[cache] warning: could not save ranking cache: {exc}", file=sys.stderr, flush=True)
    return sorted(results, key=lambda row: (row["score"], article_map[row["article_id"]].score()), reverse=True)


def _ranking_result(article_id: str, article: Any, values: dict[str, Any]) -> dict[str, Any]:
    return {
        "article_id": article_id,
        "score": int(values["score"]),
        "reason": str(values["reason"]),
        "category": str(values["category"]),
        "title": article.title,
        "source": article.source,
        "published_at": article.published_at,
        "url": article.url,
    }


def _signal_item(article: Any, generated: dict[str, Any], ranking: dict[str, Any] | None) -> dict[str, Any]:
    signal = str(generated["signal"])
    background, color = _signal_colors(signal)
    return {
        "article_id": str(generated["article_id"]),
        "title": article.title,
        "source": article.source,
        "date": article.published_at,
        "summary": _required_text(generated, "summary"),
        "signal": signal,
        "background": background,
        "color": color,
        "so_what": _required_text(generated, "so_what"),
        "url": article.url,
        "score": int(ranking["score"]) if ranking and ranking.get("score") is not None else None,
        "category": str(ranking.get("category") or "") if ranking else "",
        "reason": str(ranking.get("reason") or "") if ranking else "",
    }


def _ranking_row(article_id: str, article: Any) -> dict[str, Any]:
    return {
        "article_id": article_id,
        "title": article.title,
        "source": article.source,
        "published_at": article.published_at,
        "tags": article.tags or [],
        "metrics": {
            "read": article.read_count,
            "like": article.like_count,
            "share": article.share_count,
            "recommend": article.recommend_count,
        },
        "excerpt": excerpt_text(article.summary or article.content, 260),
    }


def _synthesis_row(ranking: dict[str, Any], article: Any) -> dict[str, Any]:
    return {
        **ranking,
        "tags": article.tags or [],
        "entities": article.entities or [],
        "metrics": {
            "read": article.read_count,
            "like": article.like_count,
            "share": article.share_count,
            "recommend": article.recommend_count,
        },
        "evidence_excerpt": excerpt_text(article.summary or article.content, 1200),
    }


def _validated_selection(
    synthesis: dict[str, Any],
    article_map: dict[str, Any],
    candidate_ids: set[str],
    selection_count: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected = _validated_generated(
        synthesis.get("selected"),
        candidate_ids,
        article_map,
        "selected",
        exact=selection_count,
    )
    alternates = _validated_generated(
        synthesis.get("alternates"),
        candidate_ids,
        article_map,
        "alternates",
        maximum=6,
    )
    selected_ids = {str(item["article_id"]) for item in selected}
    alternate_ids = {str(item["article_id"]) for item in alternates}
    if selected_ids & alternate_ids:
        raise RuntimeError("LLM synthesis alternates overlap with selected articles.")
    return selected, alternates


def _validated_generated(
    value: Any,
    candidate_ids: set[str],
    article_map: dict[str, Any],
    label: str,
    *,
    exact: int | None = None,
    maximum: int | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise RuntimeError(f"LLM synthesis field {label!r} must be an array.")
    if exact is not None and len(value) != exact:
        raise RuntimeError(f"LLM synthesis must select exactly {exact} articles.")
    if maximum is not None and len(value) > maximum:
        raise RuntimeError(f"LLM synthesis field {label!r} must contain at most {maximum} articles.")
    allowed_signals = {"监管", "政策", "竞争", "机会"}
    ids: list[str] = []
    for item in value:
        if not isinstance(item, dict) or item.get("signal") not in allowed_signals:
            raise RuntimeError("LLM synthesis returned an invalid signal category.")
        article_id = str(item.get("article_id") or "")
        if article_id not in candidate_ids or article_id not in article_map:
            raise RuntimeError(f"LLM synthesis field {label!r} contains unknown article IDs.")
        ids.append(article_id)
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"LLM synthesis field {label!r} contains duplicate article IDs.")
    return value


def _dashboard(value: Any, signal_count: int) -> list[list[str]]:
    if not isinstance(value, list) or len(value) != 3:
        raise RuntimeError("LLM synthesis dashboard must contain exactly three analyses.")
    expected = ["监管动向", "AI 落地", "市场并购"]
    by_label = {str(item.get("label")): item for item in value if isinstance(item, dict)}
    if set(by_label) != set(expected):
        raise RuntimeError("LLM synthesis dashboard labels are incomplete.")
    rows = []
    for label in expected:
        item = by_label[label]
        tone = str(item.get("tone") or "")
        if tone not in TONE_COLORS:
            raise RuntimeError(f"LLM synthesis dashboard has invalid tone {tone!r}.")
        rows.append([label, _required_text(item, "value"), TONE_COLORS[tone]])
    rows.append(["本周信号数", f"{signal_count} 条", NEUTRAL_COLOR])
    return rows


def _signal_colors(signal: str) -> tuple[str, str]:
    return SIGNAL_COLORS[signal]


def _required_text(value: dict[str, Any], key: str) -> str:
    text = str(value.get(key) or "").strip()
    if not text:
        raise RuntimeError(f"LLM response field {key!r} must not be empty.")
    return text


def _text_list(value: dict[str, Any], key: str, *, exact: int | None = None, maximum: int | None = None) -> list[str]:
    raw = value.get(key)
    if not isinstance(raw, list):
        raise RuntimeError(f"LLM response field {key!r} must be an array.")
    items = list(dict.fromkeys(str(item).strip() for item in raw if str(item).strip()))
    if exact is not None and len(items) != exact:
        raise RuntimeError(f"LLM response field {key!r} must contain exactly {exact} non-empty items.")
    return items[:maximum] if maximum is not None else items


def _dedupe_rankings(rankings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen = set()
    for ranking in rankings:
        key = re.sub(r"[^\w\u4e00-\u9fff]", "", str(ranking.get("title") or "")).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(ranking)
    return result


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}.")
    return value
