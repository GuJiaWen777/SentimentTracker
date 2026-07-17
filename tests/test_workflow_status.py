from datetime import date

from earlydata_weekly_publisher.approval import approve_report, load_approved_artifact, write_publication_receipt
from earlydata_weekly_publisher.pipeline import Article, build_brief, write_articles, write_brief_outputs
from earlydata_weekly_publisher.review_app import ReviewWorkspace
from earlydata_weekly_publisher.workflow_status import inspect_workflow_status


START = date(2026, 5, 25)
END = date(2026, 5, 31)


def _article():
    return Article(
        title="FDA 更新 AI 药物审评要求",
        source="来源",
        published_at="2026-05-30",
        content="监管机构要求补充模型验证材料。",
        url="https://example.com/source",
    )


def test_status_recommends_source_for_empty_window(tmp_path):
    status = inspect_workflow_status(tmp_path, start=START, end=END)

    assert status["stage"] == "empty"
    assert status["next_action"] == "choose_source"
    assert status["reuse"]["articles"] is False


def test_status_reuses_existing_articles_instead_of_fetching(tmp_path):
    write_articles(tmp_path / "articles.json", [_article()])

    status = inspect_workflow_status(tmp_path, start=START, end=END)

    assert status["stage"] == "articles_ready"
    assert status["next_action"] == "build_with_llm"
    assert status["reuse"]["articles"] is True


def test_status_moves_from_review_to_approved_and_published(tmp_path):
    article = _article()
    write_articles(tmp_path / "articles.json", [article])
    write_brief_outputs(build_brief([article], START, END), tmp_path)
    assert inspect_workflow_status(tmp_path, start=START, end=END)["stage"] == "ready_for_review"

    workspace = ReviewWorkspace(tmp_path)
    loaded = workspace.load()
    workspace.save({"brief": loaded["brief"], "locked_fields": []})
    assert inspect_workflow_status(tmp_path, start=START, end=END)["stage"] == "review_in_progress"

    approve_report(tmp_path)
    approved = inspect_workflow_status(tmp_path, start=START, end=END)
    assert approved["stage"] == "approved"
    assert approved["gates"]["approved"] is True

    artifact = load_approved_artifact(tmp_path)
    write_publication_receipt(artifact, media_id="media-1", title=artifact.title)
    published = inspect_workflow_status(tmp_path, start=START, end=END)
    assert published["stage"] == "published"
    assert published["gates"]["published"] is True
