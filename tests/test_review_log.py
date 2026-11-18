import sys
from datetime import date

from earlydata_weekly_publisher.approval import approve_report
from earlydata_weekly_publisher.articles import write_articles
from earlydata_weekly_publisher.brief import build_brief, write_brief_outputs
from earlydata_weekly_publisher.cli import main
from earlydata_weekly_publisher.models import Article
from earlydata_weekly_publisher.review_app import ReviewWorkspace
from earlydata_weekly_publisher.review_log import (
    diff_briefs,
    latest_quality,
    quality_history,
    read_review_log,
)
from earlydata_weekly_publisher.signal_history import record_report, trend_summary


START = date(2026, 5, 25)
END = date(2026, 5, 31)


def _report(tmp_path):
    article = Article(
        title="FDA 更新 AI 药物审评要求",
        source="来源",
        published_at="2026-05-30",
        content="监管机构要求补充模型验证材料。",
    )
    write_articles(tmp_path / "articles.json", [article])
    write_brief_outputs(build_brief([article], START, END), tmp_path)
    return ReviewWorkspace(tmp_path)


def test_diff_briefs_reports_field_edits_and_candidate_swaps():
    previous = {
        "title": "周报",
        "key_signal": "旧信号",
        "items": [
            {"article_id": "a1", "title": "一", "summary": "旧摘要"},
            {"article_id": "a2", "title": "二", "summary": "保留"},
        ],
    }
    current = {
        "title": "周报",
        "key_signal": "新信号",
        "items": [
            {"article_id": "a1", "title": "一", "summary": "新摘要"},
            {"article_id": "a3", "title": "三", "summary": "换稿"},
        ],
    }

    changes = diff_briefs(previous, current)

    by_path = {change["path"]: change for change in changes}
    assert by_path["key_signal"]["before"] == "旧信号"
    assert by_path["key_signal"]["after"] == "新信号"
    assert by_path["items.0.summary"]["before"] == "旧摘要"
    assert by_path["items.0.summary"]["after"] == "新摘要"
    swap = by_path["items.1"]
    assert swap["kind"] == "swap"
    assert swap["before_article_id"] == "a2"
    assert swap["after_article_id"] == "a3"
    assert swap["after_title"] == "三"


def test_save_records_locked_fields_and_editorial_changes(tmp_path):
    workspace = _report(tmp_path)
    brief = workspace.load()["brief"]
    brief["key_signal"] = "人工改写后的关键信号"

    result = workspace.save({"brief": brief, "locked_fields": ["key_signal"]})

    assert "review_log_error" not in result
    log = read_review_log(tmp_path)
    assert log["schema_version"] == 1
    save_event = log["events"][-1]
    assert save_event["type"] == "save"
    assert save_event["locked_fields"] == ["key_signal"]
    assert save_event["brief_sha256"]
    assert any(
        change["path"] == "key_signal" and change["after"] == "人工改写后的关键信号"
        for change in save_event["changes"]
    )


def test_approval_records_quality_and_feeds_the_quality_trend(tmp_path):
    workspace = _report(tmp_path)
    brief = workspace.load()["brief"]
    brief["companies"] = ["Pfizer", "辉瑞"]
    workspace.save({"brief": brief, "locked_fields": []})
    approve_report(tmp_path)

    events = read_review_log(tmp_path)["events"]
    assert [event["type"] for event in events] == ["save", "approve"]
    quality = events[-1]["quality"]
    assert quality["warning_count"] >= 1
    assert quality["codes"]["missing_url"] >= 1
    assert latest_quality(tmp_path)["warning_count"] == quality["warning_count"]
    assert quality_history(tmp_path)[-1]["codes"]["missing_url"] >= 1

    db_path = tmp_path / "signals.sqlite3"
    result = record_report(tmp_path, db_path=db_path)
    assert result["company_count"] == 1
    summary = trend_summary(db_path)
    week = summary["weeks"][0]
    assert week["quality"]["warning_count"] == quality["warning_count"]
    assert summary["quality_trend"][0]["report_key"] == result["report_key"]
    assert [entity["name"] for entity in summary["entities"] if entity["kind"] == "company"] == ["辉瑞"]


def test_review_log_command_prints_the_audit_trail(tmp_path, monkeypatch, capsys):
    workspace = _report(tmp_path)
    workspace.save({"brief": workspace.load()["brief"], "locked_fields": []})
    approve_report(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["earlydata-weekly", "review-log", "--report-dir", str(tmp_path)],
    )

    assert main() == 0

    output = capsys.readouterr().out
    assert "审核记录共 2 条事件" in output
    assert "approve" in output
