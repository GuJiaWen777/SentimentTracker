from datetime import date

from earlydata_weekly_publisher.pipeline import Article, build_brief, read_articles, validate_html, write_articles, write_brief_outputs


def test_build_writes_compliant_earlydata_article(tmp_path):
    articles = [
        Article(
            title="辉瑞与信达推进 ADC 全球合作",
            source="医药魔方",
            published_at="2026-05-29",
            content="ADC 与双抗管线进入全球共同开发阶段，交易结构强调利润共享。",
            entities=["辉瑞", "信达生物"],
            read_count=1000,
            like_count=80,
        ),
        Article(
            title="FDA 强化 AI 药物审评材料要求",
            source="Nature",
            published_at="2026-05-28",
            content="监管机构要求补齐人工智能辅助决策的可解释性与验证材料。",
            entities=["FDA"],
            read_count=900,
            share_count=20,
        ),
    ]
    raw_path = tmp_path / "articles.json"
    write_articles(raw_path, articles)

    brief = build_brief(articles, date(2026, 5, 25), date(2026, 5, 31))
    outputs = write_brief_outputs(brief, tmp_path / "report")
    html = outputs["html"].read_text(encoding="utf-8")

    assert raw_path.exists()
    assert outputs["markdown"].exists()
    assert outputs["html"].name == "wechat_article_img.html"
    assert "本期关键信号" in html
    assert "本期重点公司 / 机构" in html
    assert "本期重点药物 / 技术类型" in html
    assert "辉瑞" in html
    assert "ADC" in html
    assert '<span leaf="">' in html
    assert html.count("本期重点公司 / 机构") == 1
    assert html.count("本期重点药物 / 技术类型") == 1
    assert html.index("本期重点公司 / 机构") < html.index("本期重点药物 / 技术类型")
    assert '<section style="padding:0 18px 18px;"><section style="background:#F8F9FA;border:1px solid #E4E8ED;border-radius:6px;padding:12px 14px;">' in html
    validate_html(html)


def test_build_prefers_industry_signals_and_clean_entity_tags():
    articles = [
        Article(
            title="减重和运动改善健康的研究进展",
            source="泛健康",
            published_at="2026-05-29",
            content="面向普通人群的健康科普内容。",
            read_count=100_000,
            like_count=10_000,
        ),
        Article(
            title="信达生物与辉瑞达成 ADC 全球授权合作",
            source="医药魔方",
            published_at="2026-05-29",
            content="双方将推进抗体偶联药物的临床开发和商业化。",
            entities=["信达生物", "辉瑞"],
            read_count=1_000,
        ),
        Article(
            title="FDA 受理首款 AOC 的上市申请",
            source="医药笔记",
            published_at="2026-05-30",
            content="监管审评将关注临床安全性和有效性数据。",
            read_count=800,
        ),
    ]

    brief = build_brief(articles, date(2026, 5, 25), date(2026, 5, 31))

    item_titles = [item["title"] for item in brief["items"]]
    assert "减重和运动改善健康的研究进展" not in item_titles
    assert brief["companies"][:2] == ["信达生物", "辉瑞"]
    assert "FDA" in brief["companies"]
    assert "ADC" in brief["technologies"]
    assert "AOC" in brief["technologies"]


def test_build_deduplicates_repeated_titles_and_uses_headline_category():
    articles = [
        Article(
            title="辉瑞与信达生物达成 ADC 全球授权合作",
            source="来源一",
            published_at="2026-05-30",
            read_count=2_000,
        ),
        Article(
            title="辉瑞与信达生物达成 ADC 全球授权合作",
            source="来源二",
            published_at="2026-05-30",
            read_count=1_000,
        ),
        Article(
            title="FDA 受理创新药上市申请",
            source="来源三",
            published_at="2026-05-30",
            read_count=900,
        ),
    ]

    brief = build_brief(articles, date(2026, 5, 25), date(2026, 5, 31))

    assert len(brief["items"]) == 2
    assert brief["items"][0]["signal"] == "竞争"
    assert "辉瑞与信达生物" not in brief["companies"]


def test_build_excludes_promotional_agendas_when_editorial_signals_exist():
    articles = [
        Article(
            title="中国制药大会会议议程更新：出海与 BD 合作专场",
            source="大会",
            published_at="2026-05-29",
            read_count=10_000,
        ),
        Article(
            title="信达生物与辉瑞达成 ADC 全球授权合作",
            source="医药魔方",
            published_at="2026-05-29",
            read_count=1_000,
        ),
    ]

    brief = build_brief(articles, date(2026, 5, 25), date(2026, 5, 31))

    assert [item["title"] for item in brief["items"]] == ["信达生物与辉瑞达成 ADC 全球授权合作"]


def test_html_normalizes_source_quotes_without_changing_json_content(tmp_path):
    article = Article(
        title='FDA 受理“创新药”合作申请',
        source="来源",
        published_at="2026-05-30",
        content='原文标题包含 "半角引号"。',
    )

    brief = build_brief([article], date(2026, 5, 25), date(2026, 5, 31))
    html = write_brief_outputs(brief, tmp_path)["html"].read_text(encoding="utf-8")

    assert "“半角引号”" in html


def test_read_articles_repairs_registered_mark_lost_in_title(tmp_path):
    path = tmp_path / "articles.json"
    path.write_text(
        '{"articles":[{"title":"迪哲医药舒沃哲?双重磅","source":"来源","published_at":"2026-05-30","content":"舒沃哲®国际多中心III期研究"}]}',
        encoding="utf-8",
    )

    articles = read_articles(path)

    assert articles[0].title == "迪哲医药舒沃哲®双重磅"
