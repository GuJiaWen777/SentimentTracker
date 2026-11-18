from datetime import date

import pytest

from earlydata_weekly_publisher import sources
from earlydata_weekly_publisher.models import Article
from earlydata_weekly_publisher.sources import SourceError, SourceRequest, get_source, source_names


START = date(2026, 5, 25)
END = date(2026, 5, 31)


def test_registry_exposes_the_shipped_sources():
    assert set(source_names()) == {"redfox", "xlsx"}
    assert get_source("xlsx").info.label == "P&B Excel"
    assert get_source("redfox").info.label == "RedFox API"


def test_unknown_source_lists_available_choices():
    with pytest.raises(SourceError, match="redfox"):
        get_source("rss")


def test_redfox_reports_key_presence_but_never_the_value(monkeypatch):
    monkeypatch.setenv("REDFOX_API_KEY", "secret-key")
    assert get_source("redfox").required_config() == {"REDFOX_API_KEY": True}

    monkeypatch.delenv("REDFOX_API_KEY")
    assert get_source("redfox").required_config() == {"REDFOX_API_KEY": False}


def test_redfox_adapter_maps_the_request_to_the_collector(monkeypatch):
    calls = {}

    def fake_fetch(start, end, accounts, *, include_content=True):
        calls.update(start=start, end=end, accounts=accounts, include_content=include_content)
        return [Article(title="标题", source="来源", published_at="2026-05-30")]

    monkeypatch.setattr(sources.redfox, "fetch_redfox", fake_fetch)

    articles = get_source("redfox").fetch(
        SourceRequest(start=START, end=END, accounts=("医药魔方",), include_content=False)
    )

    assert len(articles) == 1
    assert calls == {"start": START, "end": END, "accounts": ["医药魔方"], "include_content": False}


def test_xlsx_adapter_requires_an_existing_file(tmp_path):
    with pytest.raises(SourceError, match="--xlsx"):
        get_source("xlsx").fetch(SourceRequest(start=START, end=END))

    with pytest.raises(SourceError, match="not found"):
        get_source("xlsx").fetch(SourceRequest(start=START, end=END, path=tmp_path / "missing.xlsx"))
