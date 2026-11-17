import json
from datetime import date

import pytest

from earlydata_weekly_publisher.approval import (
    approve_report,
    load_approved_artifact,
    matching_publication_receipt,
    write_publication_receipt,
)
from earlydata_weekly_publisher.pipeline import Article, build_brief, write_brief_outputs
from earlydata_weekly_publisher.review_app import ReviewWorkspace


def _workspace(tmp_path):
    article = Article(
        title="FDA 更新 AI 药物审评要求",
        source="来源",
        published_at="2026-05-30",
        content="监管机构要求补充模型验证材料。",
        url="https://example.com/source",
    )
    brief = build_brief([article], date(2026, 5, 25), date(2026, 5, 31))
    write_brief_outputs(brief, tmp_path)
    workspace = ReviewWorkspace(tmp_path)
    loaded = workspace.load()
    workspace.save({"brief": loaded["brief"], "locked_fields": ["key_signal"]})
    return workspace


def test_approval_hashes_reviewed_brief_and_html(tmp_path):
    _workspace(tmp_path)

    state = approve_report(tmp_path)
    artifact = load_approved_artifact(tmp_path)

    assert state["status"] == "approved"
    assert state["brief_sha256"] == artifact.brief_sha256
    assert state["html_sha256"] == artifact.html_sha256
    assert state["locked_fields"] == ["key_signal"]


def test_approval_is_invalidated_when_html_changes(tmp_path):
    _workspace(tmp_path)
    approve_report(tmp_path)
    html_path = tmp_path / "reviewed" / "wechat_article_img.html"
    html_path.write_text(html_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="changed after approval"):
        load_approved_artifact(tmp_path)


def test_approval_records_signal_history_when_configured(tmp_path):
    _workspace(tmp_path)
    db_path = tmp_path / "history" / "signals.sqlite3"

    state = approve_report(tmp_path, history_db=db_path)

    assert state["status"] == "approved"
    assert state["history"]["signal_count"] == 1
    assert state["history"]["db"] == str(db_path)
    assert db_path.is_file()


def test_publication_receipt_prevents_duplicate_draft_for_same_html(tmp_path):
    _workspace(tmp_path)
    approve_report(tmp_path)
    artifact = load_approved_artifact(tmp_path)

    receipt_path = write_publication_receipt(artifact, media_id="draft-media-1", title=artifact.title)
    receipt = matching_publication_receipt(artifact)

    assert receipt_path.name == "publication_receipt.json"
    assert receipt["media_id"] == "draft-media-1"
    assert receipt["schema_version"] == 1
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["html_sha256"] == artifact.html_sha256


def test_publication_receipt_tracks_draft_updates(tmp_path):
    _workspace(tmp_path)
    approve_report(tmp_path)
    artifact = load_approved_artifact(tmp_path)
    write_publication_receipt(artifact, media_id="draft-media-1", title=artifact.title)
    first = matching_publication_receipt(artifact)

    write_publication_receipt(artifact, media_id="draft-media-1", title=artifact.title, updated=True)
    updated = matching_publication_receipt(artifact)

    assert updated["status"] == "draft_updated"
    assert updated["update_count"] == 1
    assert updated["published_at"] == first["published_at"]
    assert updated["updated_at"] >= first["updated_at"]
