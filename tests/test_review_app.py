import json
import threading
from datetime import date

import requests

from earlydata_weekly_publisher.pipeline import Article, build_brief, write_brief_outputs
from earlydata_weekly_publisher.review_app import REVIEW_HTML, ReviewWorkspace, create_review_server


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
    assert "__REVIEW_TOKEN__" in REVIEW_HTML
    assert "X-Review-Token" in REVIEW_HTML
    assert "候选池" in REVIEW_HTML
    assert "跨周趋势" in REVIEW_HTML
    assert "swapCandidate" in REVIEW_HTML


def test_review_save_recomputes_sources_and_preserves_alternates(tmp_path):
    articles = [
        Article(
            title=f"公司{i}与辉瑞达成 ADC 全球授权合作",
            source=f"来源{i}",
            published_at="2026-05-30",
            content="双方将推进抗体偶联药物的临床开发和商业化。",
            read_count=1000 - i,
        )
        for i in range(1, 9)
    ]
    brief = build_brief(articles, date(2026, 5, 25), date(2026, 5, 31))
    assert len(brief["items"]) == 6
    assert len(brief["alternates"]) == 2
    write_brief_outputs(brief, tmp_path)

    workspace = ReviewWorkspace(tmp_path)
    loaded = workspace.load()
    loaded["brief"]["items"][0]["source"] = "新来源"
    workspace.save({"brief": loaded["brief"], "locked_fields": []})

    saved = json.loads((tmp_path / "brief.reviewed.json").read_text(encoding="utf-8"))
    expected_sources = list(
        dict.fromkeys(item["source"] for item in saved["items"] if item["source"])
    )
    assert saved["sources"] == expected_sources
    assert "新来源" in saved["sources"]
    assert len(saved["alternates"]) == 2


def test_review_server_requires_token_and_rejects_dns_hosts(tmp_path):
    article = Article(
        title="FDA 更新 AI 药物审评要求",
        source="来源",
        published_at="2026-05-30",
        content="监管机构要求补充模型验证材料。",
        url="https://example.com/source",
    )
    write_brief_outputs(build_brief([article], date(2026, 5, 25), date(2026, 5, 31)), tmp_path)
    server, token = create_review_server(tmp_path, port=0, token="test-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        assert requests.get(f"{base}/api/review", timeout=5).status_code == 403
        assert requests.get(f"{base}/api/review", headers={"X-Review-Token": "wrong"}, timeout=5).status_code == 403
        assert requests.post(f"{base}/api/approve", timeout=5).status_code == 403
        assert requests.get(f"{base}/api/health", headers={"Host": "evil.example"}, timeout=5).status_code == 403

        loaded = requests.get(f"{base}/api/review", headers={"X-Review-Token": token}, timeout=5)
        assert loaded.status_code == 200
        brief = loaded.json()["brief"]

        page = requests.get(f"{base}/", timeout=5)
        assert page.status_code == 200
        assert "__REVIEW_TOKEN__" not in page.text
        assert f'content="{token}"' in page.text

        saved = requests.put(
            f"{base}/api/review",
            json={"brief": brief, "locked_fields": []},
            headers={"X-Review-Token": token},
            timeout=5,
        )
        assert saved.status_code == 200

        approved = requests.post(f"{base}/api/approve", headers={"X-Review-Token": token}, timeout=5)
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
