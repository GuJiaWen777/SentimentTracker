import json
from datetime import date

from earlydata_weekly_publisher.pipeline import Article, build_brief, write_articles
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
