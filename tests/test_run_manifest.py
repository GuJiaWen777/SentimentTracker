import json
from datetime import date

import pytest

from earlydata_weekly_publisher.brief import build_brief, write_brief_outputs
from earlydata_weekly_publisher.models import Article
from earlydata_weekly_publisher.run_manifest import RunManifest


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


def test_run_manifest_records_provenance_and_artifact_hashes(tmp_path):
    with RunManifest(tmp_path, command="build", start=START, end=END) as manifest:
        manifest.set("counts", {"in_window_count": 1})
        manifest.set("cache", {"enabled": True, "path": "data/cache/ranking.json"})
        brief = build_brief([_article()], START, END)
        brief["generation"] = {
            "mode": "llm",
            "backend": "api",
            "model": "test-model",
            "usage": {"calls": 2, "total_tokens": 1234},
            "ranked_article_count": 3,
            "unique_article_count": 3,
            "candidate_count": 3,
            "cache_hits": 2,
            "cache_misses": 1,
            "history_weeks": 4,
            "excluded_outside_window": 0,
        }
        outputs = write_brief_outputs(brief, tmp_path)
        manifest.record(brief, outputs)

    report = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))

    assert report["schema_version"] == 1
    assert report["status"] == "completed"
    assert report["command"] == "build"
    assert report["window"] == {"start": "2026-05-25", "end": "2026-05-31"}
    assert report["llm"]["backend"] == "api"
    assert report["llm"]["model"] == "test-model"
    assert report["llm"]["usage"]["total_tokens"] == 1234
    assert set(report["llm"]["prompts"]) == {"ranking", "synthesis"}
    assert report["counts"]["selected_count"] == 1
    assert report["counts"]["in_window_count"] == 1
    assert report["cache"] == {"enabled": True, "path": "data/cache/ranking.json", "hits": 2, "misses": 1}
    assert report["history"]["weeks"] == 4
    assert report["artifacts"]["brief.json"]["sha256"]
    assert len(report["artifacts"]["brief.json"]["sha256"]) == 64
    assert report["error"] is None


def test_run_manifest_records_failures_without_masking_the_error(tmp_path):
    with pytest.raises(RuntimeError, match="boom"):
        with RunManifest(tmp_path, command="build", start=START, end=END):
            raise RuntimeError("boom")

    report = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))

    assert report["status"] == "failed"
    assert report["error"] == {"type": "RuntimeError", "message": "boom"}
    assert report["artifacts"] == {}
