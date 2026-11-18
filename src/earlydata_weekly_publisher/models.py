from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Article:
    title: str
    source: str
    published_at: str
    content: str = ""
    summary: str = ""
    url: str = ""
    tags: list[str] | None = None
    entities: list[str] | None = None
    read_count: int = 0
    like_count: int = 0
    share_count: int = 0
    recommend_count: int = 0
    article_id: str = ""

    def score(self) -> float:
        return self.read_count * 0.35 + self.like_count * 8 + self.share_count * 12 + self.recommend_count * 10


def ensure_article_ids(articles: list[Article]) -> list[Article]:
    """Assign a stable, persisted article_id to every article.

    IDs already stored in articles.json are preserved, so reordering or
    removing rows no longer shifts the evidence attached to a report item.
    """
    reserved = {
        str(article.article_id).strip()
        for article in articles
        if str(article.article_id).strip()
    }
    seen: set[str] = set()
    counter = 1
    for article in articles:
        article_id = str(article.article_id or "").strip()
        if article_id and article_id not in seen:
            seen.add(article_id)
            article.article_id = article_id
            continue
        while f"a{counter:04d}" in seen or f"a{counter:04d}" in reserved:
            counter += 1
        article.article_id = f"a{counter:04d}"
        seen.add(article.article_id)
    return articles
