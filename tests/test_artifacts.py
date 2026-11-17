import json

import pytest

from earlydata_weekly_publisher.artifacts import ArtifactSchemaError, check, current_version, stamp
from earlydata_weekly_publisher.pipeline import Article, read_articles, read_brief, write_articles


def _article():
    return Article(title="FDA 更新审评要求", source="来源", published_at="2026-05-30", content="监管要求补充材料。")


def test_stamp_adds_the_current_schema_version():
    payload = stamp("brief", {"title": "周报"})

    assert payload["schema_version"] == current_version("brief")
    assert payload["title"] == "周报"


def test_check_accepts_legacy_artifacts_without_a_version():
    assert check("brief", {"title": "周报"}) == {"title": "周报"}


def test_check_rejects_a_newer_schema_version():
    with pytest.raises(ArtifactSchemaError, match="newer than supported"):
        check("brief", {"schema_version": current_version("brief") + 1})


def test_check_rejects_an_invalid_schema_version():
    with pytest.raises(ArtifactSchemaError, match="invalid schema_version"):
        check("brief", {"schema_version": "one"})


def test_articles_round_trip_and_legacy_input(tmp_path):
    path = tmp_path / "articles.json"
    write_articles(path, [_article()])
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["schema_version"] == current_version("articles")
    assert read_articles(path)[0].title == "FDA 更新审评要求"

    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"articles": [{"title": "旧格式", "source": "来源", "published_at": "2026-05-30"}]}), encoding="utf-8")
    assert read_articles(legacy)[0].title == "旧格式"


def test_read_brief_rejects_a_newer_artifact(tmp_path):
    path = tmp_path / "brief.json"
    path.write_text(json.dumps({"schema_version": current_version("brief") + 1}), encoding="utf-8")

    with pytest.raises(ArtifactSchemaError, match="newer than supported"):
        read_brief(path)
