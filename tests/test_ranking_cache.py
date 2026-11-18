import json
from datetime import date

from earlydata_weekly_publisher.pipeline import Article, generate_brief


class FakeLLM:
    model_name = "cache-test-model"

    def __init__(self):
        self.ranking_calls = 0
        self.ranked_ids = []

    def complete_json(self, *, system_prompt, prompt, schema_name, schema):
        if schema_name == "earlydata_article_ranking":
            self.ranking_calls += 1
            rows = json.loads(prompt.split("输入新闻：\n", 1)[1])
            self.ranked_ids.extend(row["article_id"] for row in rows)
            return {
                "articles": [
                    {
                        "article_id": row["article_id"],
                        "score": 95 - index,
                        "reason": "影响核心管线或管理层决策",
                        "category": "技术",
                    }
                    for index, row in enumerate(rows)
                ]
            }
        rows = json.loads(prompt.split("候选新闻：\n", 1)[1])
        selected = rows[:6]
        alternates = rows[6:12]
        return {
            "key_signal": "本周关键信号归纳，覆盖监管、交易与技术三条主线，并提示管理层需要复核的重点事项。",
            "dashboard": [
                {"label": "监管动向", "value": "关注", "tone": "risk"},
                {"label": "AI 落地", "value": "提速", "tone": "positive"},
                {"label": "市场并购", "value": "活跃", "tone": "info"},
            ],
            "selected": [
                {
                    "article_id": row["article_id"],
                    "signal": "竞争",
                    "summary": f"事实摘要：{row['title']}对本周竞争格局形成直接影响。",
                    "so_what": "复核自有管线、合作权益和全球开发资源配置。",
                }
                for row in selected
            ],
            "alternates": [
                {
                    "article_id": row["article_id"],
                    "signal": "机会",
                    "summary": f"备选摘要：{row['title']}可以作为替换信号。",
                    "so_what": "若需调整选题，可优先替换为该条。",
                }
                for row in alternates
            ],
            "companies": ["辉瑞"],
            "technologies": ["ADC"],
            "insights": ["合作模式正在升级。", "临床证据决定议价能力。", "合规准备需要前置。"],
            "follow_up": ["跟踪合作交割条件。", "跟踪关键临床读出。", "跟踪监管文件更新。"],
        }


def _articles(count: int = 3):
    return [
        Article(
            title=f"公司{i}推进创新药合作与临床开发",
            source=f"来源{i}",
            published_at="2026-05-29",
            content=f"第{i}条文章的事实证据与产业背景。",
            url=f"https://example.com/{i}",
        )
        for i in range(1, count + 1)
    ]


def test_ranking_cache_reuses_scores_without_calling_llm_again(tmp_path):
    cache_path = tmp_path / "cache" / "ranking.json"
    articles = _articles()
    first = FakeLLM()

    brief = generate_brief(
        articles,
        date(2026, 5, 25),
        date(2026, 5, 31),
        generator="llm",
        llm_client=first,
        ranking_cache_path=cache_path,
    )

    assert first.ranking_calls == 1
    assert brief["generation"]["cache_hits"] == 0
    assert brief["generation"]["cache_misses"] == 3

    second = FakeLLM()
    reused = generate_brief(
        articles,
        date(2026, 5, 25),
        date(2026, 5, 31),
        generator="llm",
        llm_client=second,
        ranking_cache_path=cache_path,
    )

    assert second.ranking_calls == 0
    assert second.ranked_ids == []
    assert reused["generation"]["cache_hits"] == 3
    assert reused["generation"]["cache_misses"] == 0
    assert [item["score"] for item in reused["items"]] == [item["score"] for item in brief["items"]]
    assert cache_path.is_file()


def test_ranking_cache_only_ranks_changed_articles(tmp_path):
    cache_path = tmp_path / "ranking.json"
    articles = _articles()
    generate_brief(
        articles,
        date(2026, 5, 25),
        date(2026, 5, 31),
        generator="llm",
        llm_client=FakeLLM(),
        ranking_cache_path=cache_path,
    )
    articles[2].content = "更新后的第三篇文章内容，导致缓存键变化。"

    third = FakeLLM()
    brief = generate_brief(
        articles,
        date(2026, 5, 25),
        date(2026, 5, 31),
        generator="llm",
        llm_client=third,
        ranking_cache_path=cache_path,
    )

    assert third.ranking_calls == 1
    assert third.ranked_ids == ["a0003"]
    assert brief["generation"]["cache_hits"] == 2
    assert brief["generation"]["cache_misses"] == 1
    entries = json.loads(cache_path.read_text(encoding="utf-8"))["entries"]
    assert len(entries) == 4


def _cache_article(title: str):
    from types import SimpleNamespace

    return SimpleNamespace(
        title=title,
        source="来源",
        published_at="2026-05-30",
        summary="",
        content="",
        tags=None,
        read_count=0,
        like_count=0,
        share_count=0,
        recommend_count=0,
    )


def test_ranking_cache_merges_entries_saved_by_another_process(tmp_path):
    from earlydata_weekly_publisher.ranking_cache import RankingCache

    path = tmp_path / "ranking.json"
    first = RankingCache.open(path, model="test-model")
    second = RankingCache.open(path, model="test-model")
    article_a = _cache_article("文章 A")
    article_b = _cache_article("文章 B")

    first.put(article_a, score=80, category="监管", reason="影响注册策略")
    first.save()
    second.put(article_b, score=70, category="技术", reason="影响管线评估")
    second.save()

    merged = RankingCache.open(path, model="test-model")
    assert {first._key(article_a), second._key(article_b)} <= set(merged.entries)
