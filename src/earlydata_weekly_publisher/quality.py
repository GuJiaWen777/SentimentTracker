from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .pipeline import read_articles


NUMBER = re.compile(r"\d+(?:\.\d+)?(?:万|亿)?(?:美元|元|%|％)?")
CLAIM_TERMS = ("首款", "首个", "唯一", "最大", "最高", "首次", "百亿美元", "全球领先")


def build_review_context(report_dir: Path, brief: dict[str, Any]) -> dict[str, Any]:
    ranking_by_id = _ranking_by_id(report_dir / "ranking.json")
    article_by_id = _article_by_id(report_dir / "articles.json")
    evidence: dict[str, dict[str, Any]] = {}
    for item in brief.get("items", []):
        if not isinstance(item, dict):
            continue
        article_id = str(item.get("article_id") or "")
        ranking = ranking_by_id.get(article_id, {})
        article = article_by_id.get(article_id)
        source_text = ""
        excerpt = ""
        if article is not None:
            source_text = " ".join([article.title, article.summary, article.content])
            excerpt = _excerpt(article.summary or article.content, 1400)
        evidence[article_id] = {
            "article_id": article_id,
            "score": ranking.get("score"),
            "reason": str(ranking.get("reason") or ""),
            "ranking_category": str(ranking.get("category") or ""),
            "url": str(item.get("url") or getattr(article, "url", "") or ranking.get("url") or ""),
            "excerpt": excerpt,
            "source_available": article is not None and bool(source_text.strip()),
            "source_text": source_text,
        }
    issues = review_quality(brief, evidence)
    public_evidence = {
        article_id: {key: value for key, value in value.items() if key != "source_text"}
        for article_id, value in evidence.items()
    }
    return {
        "evidence": public_evidence,
        "quality": {
            "issues": issues,
            "error_count": sum(1 for issue in issues if issue["level"] == "error"),
            "warning_count": sum(1 for issue in issues if issue["level"] == "warning"),
        },
    }


def review_quality(brief: dict[str, Any], evidence: dict[str, dict[str, Any]]) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    seen_titles: set[str] = set()
    for index, item in enumerate(brief.get("items", [])):
        if not isinstance(item, dict):
            issues.append(_issue("error", "invalid_item", "新闻条目结构无效", f"items.{index}", ""))
            continue
        article_id = str(item.get("article_id") or "")
        path = f"items.{index}"
        title = str(item.get("title") or "").strip()
        title_key = re.sub(r"[^\w\u4e00-\u9fff]", "", title).casefold()
        if title_key and title_key in seen_titles:
            issues.append(_issue("error", "duplicate_title", "与其他入选新闻标题重复", path + ".title", article_id))
        seen_titles.add(title_key)
        if not str(item.get("source") or "").strip() or not str(item.get("date") or "").strip():
            issues.append(_issue("error", "missing_source", "来源或发布日期缺失", path, article_id))
        context = evidence.get(article_id, {})
        if not str(context.get("url") or "").strip():
            issues.append(_issue("warning", "missing_url", "缺少原文链接", path + ".url", article_id))
        if not context.get("source_available"):
            issues.append(_issue("warning", "missing_evidence", "报告目录缺少可核对的原文内容", path, article_id))
        summary = str(item.get("summary") or "").strip()
        so_what = str(item.get("so_what") or "").strip()
        if not 30 <= len(summary) <= 180:
            issues.append(_issue("warning", "summary_length", f"事实摘要长度为 {len(summary)} 字", path + ".summary", article_id))
        if not 20 <= len(so_what) <= 140:
            issues.append(_issue("warning", "impact_length", f"业务影响长度为 {len(so_what)} 字", path + ".so_what", article_id))
        source_text = str(context.get("source_text") or "")
        if source_text:
            generated = summary + " " + so_what
            unsupported = [token for token in _numbers(generated) if token not in source_text]
            if unsupported:
                values = "、".join(unsupported[:4])
                issues.append(_issue("warning", "unsupported_number", f"原文中未直接找到数字：{values}", path + ".summary", article_id))
            unsupported_claims = [term for term in CLAIM_TERMS if term in generated and term not in source_text]
            if unsupported_claims:
                values = "、".join(unsupported_claims)
                issues.append(_issue("warning", "unsupported_claim", f"原文中未直接找到表述：{values}", path + ".summary", article_id))
    return issues


def _ranking_by_id(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("items", []) if isinstance(data, dict) else []
    return {str(row.get("article_id")): row for row in rows if isinstance(row, dict) and row.get("article_id")}


def _article_by_id(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return {f"a{index:04d}": article for index, article in enumerate(read_articles(path), start=1)}


def _numbers(text: str) -> list[str]:
    ignored = {"1", "2", "3", "4", "5", "6"}
    return list(dict.fromkeys(token for token in NUMBER.findall(text) if token not in ignored))


def _excerpt(value: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(value or ""))).strip()
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _issue(level: str, code: str, message: str, path: str, article_id: str) -> dict[str, str]:
    return {"level": level, "code": code, "message": message, "path": path, "article_id": article_id}
