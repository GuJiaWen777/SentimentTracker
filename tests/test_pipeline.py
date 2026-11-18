from datetime import date

import pytest

from earlydata_weekly_publisher.articles import read_articles, write_articles
from earlydata_weekly_publisher.brief import build_brief, generate_brief, read_brief, write_brief_outputs, write_rendered_outputs
from earlydata_weekly_publisher.models import Article, ensure_article_ids
from earlydata_weekly_publisher.render import render_markdown, validate_html
from earlydata_weekly_publisher.wechat import _local_image_path


def test_build_writes_compliant_earlydata_article(tmp_path):
    articles = [
        Article(
            title="辉瑞与信达推进 ADC 全球合作",
            source="医药魔方",
            published_at="2026-05-29",
            content="ADC 与双抗管线进入全球共同开发阶段，交易结构强调利润共享。",
            url="https://example.com/pfizer-indata",
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
    assert 'href="https://example.com/pfizer-indata"' in html
    assert "查看来源" in html
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


def test_generate_brief_excludes_articles_outside_requested_window():
    inside = Article(title="信达生物与辉瑞达成 ADC 合作", source="来源", published_at="2026-05-30", content="合作 授权 ADC")
    outside = Article(title="旧闻：某药企达成合作", source="来源", published_at="2020-01-01", content="合作 授权 ADC")

    brief = generate_brief([inside, outside], date(2026, 5, 25), date(2026, 5, 31), generator="rules")

    assert [item["title"] for item in brief["items"]] == ["信达生物与辉瑞达成 ADC 合作"]
    assert brief["generation"]["excluded_outside_window"] == 1


def test_generate_brief_rejects_reversed_window():
    article = Article(title="FDA 更新审评要求", source="来源", published_at="2026-05-30")

    with pytest.raises(ValueError, match="after end"):
        generate_brief([article], date(2026, 5, 31), date(2026, 5, 25), generator="rules")


def test_article_ids_are_persisted_and_survive_reorder(tmp_path):
    path = tmp_path / "articles.json"
    articles = [
        Article(title="第一篇", source="来源", published_at="2026-05-30"),
        Article(title="第二篇", source="来源", published_at="2026-05-30"),
    ]
    ensure_article_ids(articles)
    write_articles(path, articles)

    reordered = read_articles(path)[::-1]
    ensure_article_ids(reordered)

    assert [(article.title, article.article_id) for article in reordered] == [
        ("第二篇", "a0002"),
        ("第一篇", "a0001"),
    ]


def test_article_ids_replace_duplicates_without_renaming_unique_ones():
    articles = [
        Article(title="第一篇", source="来源", published_at="2026-05-30", article_id="a0007"),
        Article(title="第二篇", source="来源", published_at="2026-05-30", article_id="a0007"),
        Article(title="第三篇", source="来源", published_at="2026-05-30"),
    ]

    ensure_article_ids(articles)

    assert [article.article_id for article in articles] == ["a0007", "a0001", "a0002"]


def test_markdown_includes_every_report_section():
    article = Article(
        title="辉瑞与信达生物达成 ADC 全球授权合作",
        source="医药魔方",
        published_at="2026-05-30",
        content="双方将推进抗体偶联药物的临床开发和商业化。",
    )
    brief = build_brief([article], date(2026, 5, 25), date(2026, 5, 31))

    markdown = render_markdown(brief)

    for heading in ("本周数据面板", "本期关键信号", "本期重点公司 / 机构", "本期重点药物 / 技术类型", "本周对你的业务意味着什么", "后续追踪", "数据来源"):
        assert heading in markdown
    assert "辉瑞" in markdown
    assert "ADC" in markdown


def test_local_article_images_cannot_escape_report_directory(tmp_path):
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    (report_dir / "ok.png").write_bytes(b"image")

    assert _local_image_path("ok.png", report_dir, restrict_to_base=True) == (report_dir / "ok.png").resolve()

    with pytest.raises(RuntimeError, match="escapes the report directory"):
        _local_image_path("../outside.png", report_dir, restrict_to_base=True)


def test_reviewed_brief_can_be_rendered_without_generation(tmp_path):
    article = Article(
        title="FDA 更新 AI 药物审评要求",
        source="来源",
        published_at="2026-05-30",
        content="监管机构要求补充模型验证材料。",
    )
    brief = build_brief([article], date(2026, 5, 25), date(2026, 5, 31))
    report_dir = tmp_path / "report"
    brief_path = write_brief_outputs(brief, report_dir)["brief"]
    reviewed = read_brief(brief_path)
    reviewed["key_signal"] = "人工确认后的本期关键信号。"

    outputs = write_rendered_outputs(reviewed, report_dir / "reviewed")
    html = outputs["html"].read_text(encoding="utf-8")

    assert "人工确认后的本期关键信号" in html
    assert outputs["markdown"].exists()
    validate_html(html)
