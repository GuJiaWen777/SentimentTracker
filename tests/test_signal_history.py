import json
from datetime import date

from earlydata_weekly_publisher.review_app import ReviewWorkspace
from earlydata_weekly_publisher.signal_history import (
    record_report,
    trend_context_for_report,
    trend_context_for_window,
    trend_summary,
)


def _item(article_id: str, title: str, signal: str, source: str = "来源") -> dict:
    return {
        "article_id": article_id,
        "title": title,
        "source": source,
        "date": "2026-05-30",
        "summary": "这是一段用于趋势测试的事实摘要，长度足够。",
        "signal": signal,
        "background": "#EDF6E3",
        "color": "#3B6D11",
        "so_what": "管理层应复核相关合作与监管安排。",
        "url": "https://example.com/item",
    }


def _write_report(
    report_dir,
    start: date,
    end: date,
    items,
    *,
    companies=None,
    technologies=None,
    title="周报",
):
    report_dir.mkdir(parents=True, exist_ok=True)
    brief = {
        "title": title,
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "source_count": len(items),
        "key_signal": "本周关键信号。",
        "dashboard": [
            ["监管动向", "1 条", "#A32D2D"],
            ["AI 落地", "0 条", "#1C1F26"],
            ["市场并购", "1 条", "#2B72B8"],
            ["本周信号数", f"{len(items)} 条", "#1C1F26"],
        ],
        "companies": companies or [],
        "technologies": technologies or [],
        "items": items,
        "alternates": [],
        "insights": ["含义一。", "含义二。", "含义三。"],
        "follow_up": ["追踪一。", "追踪二。", "追踪三。"],
        "sources": sorted({item["source"] for item in items}),
        "generation": {"mode": "llm", "model": "test-model"},
    }
    (report_dir / "brief.json").write_text(json.dumps(brief, ensure_ascii=False), encoding="utf-8")
    (report_dir / "ranking.json").write_text(
        json.dumps(
            {
                "items": [
                    {"article_id": item["article_id"], "score": 90, "category": "交易", "reason": "影响决策"}
                    for item in items
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return brief


def test_record_report_persists_signals_and_is_idempotent(tmp_path):
    db_path = tmp_path / "history" / "signals.sqlite3"
    report = tmp_path / "20260525_20260531"
    _write_report(
        report,
        date(2026, 5, 25),
        date(2026, 5, 31),
        [_item("a0001", "辉瑞达成合作", "竞争"), _item("a0002", "FDA 发布指南", "监管")],
        companies=["辉瑞"],
        technologies=["ADC"],
    )

    first = record_report(report, db_path=db_path)
    record_report(report, db_path=db_path)
    summary = trend_summary(db_path)

    assert first["report_key"] == "20260525_20260531"
    assert first["signal_count"] == 2
    assert db_path.is_file()
    assert summary["window_count"] == 1
    assert sum(summary["weeks"][0]["signal_counts"].values()) == 2
    assert summary["weeks"][0]["category_counts"] == {"交易": 2}


def test_trend_summary_tracks_entity_streaks_and_new_entities(tmp_path):
    db_path = tmp_path / "signals.sqlite3"
    _write_report(
        tmp_path / "week1",
        date(2026, 5, 18),
        date(2026, 5, 24),
        [_item("a0001", "辉瑞合作", "竞争")],
        companies=["辉瑞"],
        technologies=["ADC"],
    )
    _write_report(
        tmp_path / "week2",
        date(2026, 5, 25),
        date(2026, 5, 31),
        [_item("a0001", "辉瑞与信达合作", "竞争"), _item("a0002", "FDA 指南", "监管")],
        companies=["辉瑞", "信达生物"],
        technologies=["ADC"],
    )
    record_report(tmp_path / "week1", db_path=db_path)
    record_report(tmp_path / "week2", db_path=db_path)

    summary = trend_summary(db_path)

    assert summary["window_count"] == 2
    persistent = {(entry["name"], entry["streak"]) for entry in summary["persistent_entities"]}
    assert ("辉瑞", 2) in persistent
    assert ("ADC", 2) in persistent
    assert all(entry["name"] != "信达生物" for entry in summary["persistent_entities"])
    assert trend_summary(db_path, until=date(2026, 5, 24))["window_count"] == 1

    current = {
        "window_start": "2026-06-01",
        "companies": ["辉瑞", "百济神州"],
        "technologies": ["ADC"],
    }
    context = trend_context_for_report(db_path, current)
    assert context["window_count"] == 2
    assert {"name": "百济神州", "kind": "company"} in context["new_entities"]
    continuing = {(entry["name"], entry["streak"]) for entry in context["continuing_entities"]}
    assert ("辉瑞", 2) in continuing
    assert ("ADC", 2) in continuing


def test_trend_context_for_window_excludes_current_window(tmp_path):
    db_path = tmp_path / "signals.sqlite3"
    _write_report(
        tmp_path / "week1",
        date(2026, 5, 18),
        date(2026, 5, 24),
        [_item("a0001", "辉瑞合作", "竞争")],
        companies=["辉瑞"],
    )
    _write_report(
        tmp_path / "week2",
        date(2026, 5, 25),
        date(2026, 5, 31),
        [_item("a0001", "辉瑞合作", "竞争")],
        companies=["辉瑞"],
    )
    record_report(tmp_path / "week1", db_path=db_path)
    record_report(tmp_path / "week2", db_path=db_path)

    context = trend_context_for_window(db_path, date(2026, 5, 25))

    assert context["window_count"] == 1
    assert context["weeks"][0]["window_start"] == "2026-05-18"


def test_review_workspace_loads_cross_week_trends(tmp_path):
    db_path = tmp_path / "signals.sqlite3"
    previous = tmp_path / "previous"
    _write_report(
        previous,
        date(2026, 5, 18),
        date(2026, 5, 24),
        [_item("a0001", "辉瑞合作", "竞争")],
        companies=["辉瑞"],
        technologies=["ADC"],
    )
    record_report(previous, db_path=db_path)
    current = tmp_path / "current"
    _write_report(
        current,
        date(2026, 5, 25),
        date(2026, 5, 31),
        [_item("a0001", "辉瑞与信达合作", "竞争")],
        companies=["辉瑞"],
        technologies=["ADC"],
    )

    loaded = ReviewWorkspace(current, history_db=db_path).load()

    assert loaded["trends"]["window_count"] == 1
    assert loaded["trends"]["persistent_entities"] == []
    assert loaded["trends"]["new_entities"] == []
    assert {(entry["name"], entry["kind"]) for entry in loaded["trends"]["current_entities"]} == {
        ("辉瑞", "company"),
        ("ADC", "technology"),
    }
