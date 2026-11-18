from __future__ import annotations

import os
from datetime import date
from typing import Any

import requests

from ..articles import validate_window
from ..models import Article
from ..text import as_int, coerce_date, within_window
from .base import SourceError, SourceInfo, SourceRequest


REDFOX_LIST_URL = "https://redfox.hk/story/api/gzhData/queryWorkList"
REDFOX_DETAIL_URL = "https://redfox.hk/story/api/gzhData/queryWork"


def fetch_redfox(start: date, end: date, accounts: list[str], *, include_content: bool = True) -> list[Article]:
    validate_window(start, end)
    api_key = os.environ.get("REDFOX_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("REDFOX_API_KEY is missing. Configure it in .env.")
    if not accounts:
        raise ValueError("At least one --account is required for RedFox fetch.")
    headers = {"REDFOX_API_KEY": api_key, "Content-Type": "application/json"}
    articles: list[Article] = []
    seen: set[str] = set()
    for account in accounts:
        for page in range(50):
            payload = {
                "source": "earlydata-weekly-publisher",
                "accountName": account,
                "uid": "",
                "offset": page * 20,
                "sortType": "default",
                "publishTimeStart": f"{start} 00:00:00",
                "publishTimeEnd": f"{end} 23:59:59",
            }
            response = requests.post(REDFOX_LIST_URL, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            body = response.json()
            if body.get("code") not in (200, 2000):
                raise RuntimeError(f"RedFox error {body.get('code')}: {body.get('msg') or body.get('message')}")
            data = body.get("data") or {}
            batch = data if isinstance(data, list) else data.get("list") or data.get("articles") or data.get("records") or []
            if not batch:
                break
            for raw in batch:
                article = redfox_article(raw, account)
                key = str(raw.get("workUuid") or article.url or article.title)
                if key in seen:
                    continue
                seen.add(key)
                if include_content and raw.get("workUuid"):
                    article.content = redfox_content(str(raw["workUuid"]), headers)
                articles.append(article)
            if len(batch) < 20:
                break
    in_window = [article for article in articles if within_window(article.published_at, start, end)]
    return sorted(in_window, key=lambda item: item.published_at, reverse=True)


def redfox_article(raw: dict[str, Any], account: str) -> Article:
    value = raw.get("publishTime") or raw.get("publicTime") or raw.get("publishDate") or ""
    published = coerce_date(value)
    return Article(
        title=str(raw.get("title") or raw.get("name") or "").strip(),
        source=account,
        published_at=published.isoformat() if published else str(value)[:10],
        url=str(raw.get("workUrl") or raw.get("url") or ""),
        read_count=as_int(raw.get("readCount") or raw.get("clicksCount")),
        like_count=as_int(raw.get("likeCount") or raw.get("likes")),
        share_count=as_int(raw.get("shareCount") or raw.get("shares")),
        recommend_count=as_int(raw.get("collectCount") or raw.get("recommendCount")),
    )


def redfox_content(work_uuid: str, headers: dict[str, str]) -> str:
    response = requests.post(
        REDFOX_DETAIL_URL,
        json={"source": "earlydata-weekly-publisher", "workUuid": work_uuid},
        headers=headers,
        timeout=30,
    ).json()
    data = response.get("data") or {}
    return str(data.get("content") or "") if isinstance(data, dict) else ""


class RedFoxSource:
    """Online collector backed by the RedFox WeChat article API."""

    info = SourceInfo("redfox", "RedFox API", "在线采集指定公众号的文章")

    def required_config(self) -> dict[str, bool]:
        return {"REDFOX_API_KEY": bool(os.environ.get("REDFOX_API_KEY", "").strip())}

    def fetch(self, request: SourceRequest) -> list[Article]:
        if not request.accounts:
            raise SourceError("At least one --account is required for RedFox fetch.")
        return fetch_redfox(
            request.start,
            request.end,
            list(request.accounts),
            include_content=request.include_content,
        )
