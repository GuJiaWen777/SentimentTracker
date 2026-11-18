import json
from datetime import date

from earlydata_weekly_publisher.articles import write_articles
from earlydata_weekly_publisher.brief import build_brief
from earlydata_weekly_publisher.models import Article
from earlydata_weekly_publisher.quality import build_review_context


def test_quality_context_links_rankings_evidence_and_unsupported_numbers(tmp_path):
    article = Article(
        title="辉瑞与信达达成合作",
        source="来源",
        published_at="2026-05-30",
        content="双方达成价值10亿美元的合作。",
        url="https://example.com/source",
    )
    write_articles(tmp_path / "articles.json", [article])
    (tmp_path / "ranking.json").write_text(
        json.dumps({"items": [{"article_id": "a0001", "score": 88, "reason": "影响全球合作格局", "category": "交易"}]}, ensure_ascii=False),
        encoding="utf-8",
    )
    brief = build_brief([article], date(2026, 5, 25), date(2026, 5, 31))
    brief["items"][0]["article_id"] = "a0001"
    brief["items"][0]["summary"] = "双方达成价值20亿美元的全球合作，交易将影响后续资产授权与商业化安排。"

    context = build_review_context(tmp_path, brief)

    evidence = context["evidence"]["a0001"]
    assert evidence["score"] == 88
    assert evidence["reason"] == "影响全球合作格局"
    assert "价值10亿美元" in evidence["excerpt"]
    assert any(issue["code"] == "unsupported_number" and "20亿美元" in issue["message"] for issue in context["quality"]["issues"])


def test_quality_uses_persisted_article_ids_after_articles_are_reordered(tmp_path):
    first = Article(title="第一篇", source="来源一", published_at="2026-05-30", content="第一篇的原文正文。", article_id="a0001")
    second = Article(title="第二篇", source="来源二", published_at="2026-05-30", content="第二篇的原文正文。", article_id="a0002")
    write_articles(tmp_path / "articles.json", [second, first])
    brief = {
        "items": [
            {
                "article_id": "a0002",
                "title": "第二篇",
                "source": "来源二",
                "date": "2026-05-30",
                "summary": "这段摘要用于确认证据仍然指向第二篇原文而不是其他文章。",
                "so_what": "管理层应复核第二篇原文的事实与后续动作安排。",
                "url": "https://example.com/second",
            }
        ]
    }

    context = build_review_context(tmp_path, brief)

    evidence = context["evidence"]["a0002"]
    assert evidence["source_available"] is True
    assert "第二篇的原文正文" in evidence["excerpt"]


def test_quality_context_warns_when_source_snapshot_is_missing(tmp_path):
    brief = {
        "items": [
            {
                "article_id": "a0001",
                "title": "新闻",
                "source": "来源",
                "date": "2026-05-30",
                "summary": "这是一段长度足够但当前没有保存原文快照用于核验的事实摘要内容。",
                "so_what": "管理层需要复核关键事实并确认行动安排。",
                "url": "",
            }
        ]
    }

    context = build_review_context(tmp_path, brief)
    codes = {issue["code"] for issue in context["quality"]["issues"]}

    assert {"missing_url", "missing_evidence"} <= codes
