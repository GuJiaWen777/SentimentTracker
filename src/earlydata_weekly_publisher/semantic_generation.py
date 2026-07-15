from __future__ import annotations

import os
import re
from datetime import date
from typing import Any, Protocol

from .llm_client import create_llm_client
from .prompts import RANKING_SYSTEM_PROMPT, SYNTHESIS_SYSTEM_PROMPT, ranking_prompt, synthesis_prompt


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
        "companies": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
        "technologies": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
        "insights": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "string"}},
        "follow_up": {"type": "array", "minItems": 3, "maxItems": 3, "items": {"type": "string"}},
    },
    "required": ["key_signal", "dashboard", "selected", "companies", "technologies", "insights", "follow_up"],
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
) -> dict[str, Any]:
    if not articles:
        raise ValueError("No articles available for the selected window.")
    llm = client or create_llm_client(backend)
    article_map = {f"a{index:04d}": article for index, article in enumerate(articles, start=1)}
    rankings = _rank_all(article_map, start, end, llm)
    unique_rankings = _dedupe_rankings(rankings)
    candidate_count = min(_env_int("LLM_SYNTHESIS_CANDIDATES", 24, minimum=6, maximum=60), len(unique_rankings))
    candidates = unique_rankings[:candidate_count]
    selection_count = min(6, len(candidates))
    synthesis_rows = [_synthesis_row(row, article_map[row["article_id"]]) for row in candidates]
    print(f"[llm] synthesizing {selection_count} signals from top {candidate_count} unique candidates", flush=True)
    synthesis = llm.complete_json(
        system_prompt=SYNTHESIS_SYSTEM_PROMPT,
        prompt=synthesis_prompt(rows=synthesis_rows, start=start, end=end, selection_count=selection_count),
        schema_name="earlydata_weekly_synthesis",
        schema=SYNTHESIS_SCHEMA,
    )
    selected = _validated_selection(synthesis, article_map, {row["article_id"] for row in candidates}, selection_count)
    dashboard = _dashboard(synthesis.get("dashboard"), selection_count)
    items = []
    for generated in selected:
        article = article_map[generated["article_id"]]
        signal = generated["signal"]
        background, color = _signal_colors(signal)
        items.append(
            {
                "article_id": generated["article_id"],
                "title": article.title,
                "source": article.source,
                "date": article.published_at,
                "summary": _required_text(generated, "summary"),
                "signal": signal,
                "background": background,
                "color": color,
                "so_what": _required_text(generated, "so_what"),
                "url": article.url,
            }
        )
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
        "insights": _text_list(synthesis, "insights", exact=3),
        "follow_up": _text_list(synthesis, "follow_up", exact=3),
        "sources": list(dict.fromkeys(item["source"] for item in items if item["source"])),
        "generation": {
            "mode": "llm",
            "model": llm.model_name,
            "ranked_article_count": len(rankings),
            "unique_article_count": len(unique_rankings),
            "candidate_count": candidate_count,
        },
        "_ranking": {
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "model": llm.model_name,
            "article_count": len(rankings),
            "items": rankings,
        },
    }


def _rank_all(article_map: dict[str, Any], start: date, end: date, client: JsonLLM) -> list[dict[str, Any]]:
    batch_size = _env_int("LLM_RANK_BATCH_SIZE", 40, minimum=5, maximum=100)
    pairs = list(article_map.items())
    batch_count = (len(pairs) + batch_size - 1) // batch_size
    results: list[dict[str, Any]] = []
    for batch_index, offset in enumerate(range(0, len(pairs), batch_size), start=1):
        batch = pairs[offset : offset + batch_size]
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
            results.append(
                {
                    "article_id": article_id,
                    "score": score,
                    "reason": _required_text(item, "reason"),
                    "category": category,
                    "title": article.title,
                    "source": article.source,
                    "published_at": article.published_at,
                    "url": article.url,
                }
            )
    return sorted(results, key=lambda row: (row["score"], article_map[row["article_id"]].score()), reverse=True)


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
        "excerpt": _excerpt(article.summary or article.content, 260),
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
        "evidence_excerpt": _excerpt(article.summary or article.content, 1200),
    }


def _validated_selection(
    synthesis: dict[str, Any],
    article_map: dict[str, Any],
    candidate_ids: set[str],
    selection_count: int,
) -> list[dict[str, Any]]:
    selected = synthesis.get("selected")
    if not isinstance(selected, list) or len(selected) != selection_count:
        raise RuntimeError(f"LLM synthesis must select exactly {selection_count} articles.")
    ids = [str(item.get("article_id") or "") for item in selected if isinstance(item, dict)]
    if len(ids) != len(set(ids)) or any(article_id not in candidate_ids or article_id not in article_map for article_id in ids):
        raise RuntimeError("LLM synthesis selected duplicate or unknown article IDs.")
    allowed_signals = {"监管", "政策", "竞争", "机会"}
    for item in selected:
        if not isinstance(item, dict) or item.get("signal") not in allowed_signals:
            raise RuntimeError("LLM synthesis returned an invalid signal category.")
    return selected


def _dashboard(value: Any, signal_count: int) -> list[list[str]]:
    if not isinstance(value, list) or len(value) != 3:
        raise RuntimeError("LLM synthesis dashboard must contain exactly three analyses.")
    expected = ["监管动向", "AI 落地", "市场并购"]
    tones = {"risk": "#A32D2D", "positive": "#3B6D11", "info": "#2B72B8", "neutral": "#1C1F26"}
    by_label = {str(item.get("label")): item for item in value if isinstance(item, dict)}
    if set(by_label) != set(expected):
        raise RuntimeError("LLM synthesis dashboard labels are incomplete.")
    rows = []
    for label in expected:
        item = by_label[label]
        tone = str(item.get("tone") or "")
        if tone not in tones:
            raise RuntimeError(f"LLM synthesis dashboard has invalid tone {tone!r}.")
        rows.append([label, _required_text(item, "value"), tones[tone]])
    rows.append(["本周信号数", f"{signal_count} 条", "#1C1F26"])
    return rows


def _signal_colors(signal: str) -> tuple[str, str]:
    return {
        "监管": ("#FCEAEA", "#A32D2D"),
        "政策": ("#EEF5FC", "#2B72B8"),
        "竞争": ("#FEF3E2", "#854F0B"),
        "机会": ("#EDF6E3", "#3B6D11"),
    }[signal]


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


def _excerpt(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(value or ""))).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}.")
    return value
