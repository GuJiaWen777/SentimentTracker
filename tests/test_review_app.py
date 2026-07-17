import json
from datetime import date

from earlydata_weekly_publisher.pipeline import Article, build_brief, write_brief_outputs
from earlydata_weekly_publisher.review_app import REVIEW_HTML, ReviewWorkspace


def test_review_workspace_saves_separate_brief_locks_and_preview(tmp_path):
    article = Article(
        title="FDA 更新 AI 药物审评要求",
        source="来源",
        published_at="2026-05-30",
        content="监管机构要求补充模型验证材料。",
    )
    brief = build_brief([article], date(2026, 5, 25), date(2026, 5, 31))
    write_brief_outputs(brief, tmp_path)
    original = (tmp_path / "brief.json").read_text(encoding="utf-8")
    workspace = ReviewWorkspace(tmp_path)
    loaded = workspace.load()
    loaded["brief"]["key_signal"] = "人工审核后的关键信号。"

    result = workspace.save({"brief": loaded["brief"], "locked_fields": ["key_signal", "items.0.summary"]})

    assert (tmp_path / "brief.json").read_text(encoding="utf-8") == original
    reviewed = json.loads((tmp_path / "brief.reviewed.json").read_text(encoding="utf-8"))
    state = json.loads((tmp_path / "review_state.json").read_text(encoding="utf-8"))
    assert reviewed["key_signal"] == "人工审核后的关键信号。"
    assert state["locked_fields"] == ["key_signal", "items.0.summary"]
    assert "人工审核后的关键信号" in (tmp_path / "reviewed" / "wechat_article_img.html").read_text(encoding="utf-8")
    assert result["updated_at"]
    assert workspace.load()["using_reviewed_brief"] is True


def test_review_workbench_contains_editor_locking_and_preview():
    assert "EarlyData 编辑台" in REVIEW_HTML
    assert "locked_fields" in REVIEW_HTML
    assert "保存并预览" in REVIEW_HTML
    assert 'id="preview"' in REVIEW_HTML
    assert "确认发布稿" in REVIEW_HTML
