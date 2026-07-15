import json
from datetime import date

import pytest

from earlydata_weekly_publisher.pipeline import Article, generate_brief, write_brief_outputs


class FakeSemanticLLM:
    model_name = "semantic-test-model"

    def __init__(self):
        self.ranked_ids = []
        self.calls = []

    def complete_json(self, *, system_prompt, prompt, schema_name, schema):
        self.calls.append(schema_name)
        rows = json.loads(prompt.split("输入新闻：\n", 1)[1] if schema_name == "earlydata_article_ranking" else prompt.split("候选新闻：\n", 1)[1])
        if schema_name == "earlydata_article_ranking":
            self.ranked_ids.extend(row["article_id"] for row in rows)
            return {
                "articles": [
                    {
                        "article_id": row["article_id"],
                        "score": 100 - int(row["article_id"][1:]),
                        "reason": "影响核心管线或管理层决策",
                        "category": "交易" if "合作" in row["title"] else "技术",
                    }
                    for row in rows
                ]
            }
        selected = rows[:6]
        return {
            "key_signal": "本周主线是全球合作深化、监管证据要求提高与技术平台竞争加速，管理层需要同步复核权益结构、临床差异化和合规准备。",
            "dashboard": [
                {"label": "监管动向", "value": "高关注", "tone": "risk"},
                {"label": "AI 落地", "value": "提速", "tone": "positive"},
                {"label": "市场并购", "value": "活跃", "tone": "info"},
            ],
            "selected": [
                {
                    "article_id": row["article_id"],
                    "signal": "竞争",
                    "summary": f"语义摘要：{row['title']}对本周产业竞争形成直接影响。",
                    "so_what": "复核自有管线、合作权益和全球开发资源配置。",
                }
                for row in selected
            ],
            "companies": ["辉瑞", "信达生物"],
            "technologies": ["ADC", "AI 制药"],
            "insights": ["合作模式正在升级。", "临床证据决定议价能力。", "合规准备需要前置。"],
            "follow_up": ["跟踪合作交割条件。", "跟踪关键临床读出。", "跟踪监管文件更新。"],
        }


def test_llm_generator_ranks_every_article_and_writes_audit_file(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_RANK_BATCH_SIZE", "5")
    articles = [
        Article(
            title=f"公司{i}推进创新药合作与临床开发",
            source=f"来源{i}",
            published_at="2026-05-29",
            content=f"第{i}条文章的事实证据与产业背景。",
            read_count=1_000 - i,
        )
        for i in range(1, 8)
    ]
    articles[-1].title = articles[0].title
    llm = FakeSemanticLLM()

    brief = generate_brief(
        articles,
        date(2026, 5, 25),
        date(2026, 5, 31),
        generator="llm",
        llm_client=llm,
    )
    outputs = write_brief_outputs(brief, tmp_path)
    public_brief = json.loads(outputs["brief"].read_text(encoding="utf-8"))
    ranking = json.loads(outputs["ranking"].read_text(encoding="utf-8"))

    assert set(llm.ranked_ids) == {f"a{i:04d}" for i in range(1, 8)}
    assert llm.calls.count("earlydata_article_ranking") == 2
    assert llm.calls[-1] == "earlydata_weekly_synthesis"
    assert len(brief["items"]) == 6
    assert all(item["summary"].startswith("语义摘要") for item in brief["items"])
    assert public_brief["generation"]["mode"] == "llm"
    assert public_brief["generation"]["ranked_article_count"] == 7
    assert public_brief["generation"]["unique_article_count"] == 6
    assert "_ranking" not in public_brief
    assert ranking["article_count"] == 7
    assert len(ranking["items"]) == 7
    assert outputs["html"].exists()


def test_default_generator_fails_without_llm_config_instead_of_using_rules(monkeypatch):
    for name in ("LLM_BACKEND", "LLM_API_KEY", "LLM_API_MODEL"):
        monkeypatch.delenv(name, raising=False)
    article = Article(title="创新药合作", source="来源", published_at="2026-05-30")

    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        generate_brief([article], date(2026, 5, 25), date(2026, 5, 31))
