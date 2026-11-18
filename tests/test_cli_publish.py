import json
import sys
from datetime import date

import pytest

from earlydata_weekly_publisher import cli
from earlydata_weekly_publisher.approval import (
    approve_report,
    load_approved_artifact,
    read_publication_receipt,
    write_publication_receipt,
)
from earlydata_weekly_publisher.pipeline import Article, build_brief, write_articles, write_brief_outputs
from earlydata_weekly_publisher.review_app import ReviewWorkspace


START = date(2026, 5, 25)
END = date(2026, 5, 31)


def _approved_report(report_dir):
    article = Article(
        title="FDA 更新 AI 药物审评要求",
        source="来源",
        published_at="2026-05-30",
        content="监管机构要求补充模型验证材料。",
        url="https://example.com/source",
    )
    write_articles(report_dir / "articles.json", [article])
    write_brief_outputs(build_brief([article], START, END), report_dir)
    workspace = ReviewWorkspace(report_dir)
    loaded = workspace.load()
    workspace.save({"brief": loaded["brief"], "locked_fields": []})
    approve_report(report_dir)
    return load_approved_artifact(report_dir)


def test_publish_update_draft_updates_the_existing_receipt(tmp_path, monkeypatch, capsys):
    artifact = _approved_report(tmp_path)
    write_publication_receipt(artifact, media_id="old-media", title=artifact.title)

    # Simulate a correction that was saved and approved again: the receipt now
    # points at an older HTML hash, so publish must take the update path.
    reviewed_path = tmp_path / "brief.reviewed.json"
    reviewed = json.loads(reviewed_path.read_text(encoding="utf-8"))
    reviewed["key_signal"] += "（更新）"
    reviewed_path.write_text(json.dumps(reviewed, ensure_ascii=False, indent=2), encoding="utf-8")
    approve_report(tmp_path)
    artifact = load_approved_artifact(tmp_path)

    calls = {}

    def fake_publish(html_path, **kwargs):
        calls["html_path"] = html_path
        calls.update(kwargs)
        return "old-media"

    monkeypatch.setattr(cli, "publish_draft", fake_publish)
    monkeypatch.setattr(
        sys,
        "argv",
        ["earlydata-weekly", "publish", "--report-dir", str(tmp_path), "--update-draft", "--confirm"],
    )

    assert cli.main() == 0

    receipt = read_publication_receipt(tmp_path)
    assert calls["html_path"] == artifact.html_path
    assert calls["update_media_id"] == "old-media"
    assert receipt["status"] == "draft_updated"
    assert receipt["update_count"] == 1
    assert "draft_updated" in capsys.readouterr().out


def test_publish_rejects_the_removed_file_path(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["earlydata-weekly", "publish", "--file", "report.html", "--allow-unreviewed", "--confirm"],
    )

    with pytest.raises(SystemExit) as excinfo:
        cli.main()

    assert excinfo.value.code == 2
