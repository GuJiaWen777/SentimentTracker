"""Backward-compatible facade over the split pipeline modules.

Historically this module held the whole pipeline. The implementation now
lives in focused modules (``models``, ``articles``, ``heuristics``, ``brief``,
``render``, ``sources``); this file re-exports the public names so existing
imports keep working.
"""

from __future__ import annotations

from .articles import (
    filter_articles_by_window,
    parse_day,
    read_articles,
    validate_window,
    window_slug,
    write_articles,
)
from .brief import (
    build_brief,
    generate_brief,
    read_brief,
    validate_brief_data,
    write_brief_outputs,
    write_rendered_outputs,
)
from .config import load_dotenv
from .models import Article, ensure_article_ids
from .render import DEFAULT_COVER, render_html, render_markdown, validate_html
from .sources import fetch_redfox, ingest_pb_xlsx
from .wechat import _local_image_path, publish_draft

__all__ = [
    "Article",
    "DEFAULT_COVER",
    "build_brief",
    "ensure_article_ids",
    "fetch_redfox",
    "filter_articles_by_window",
    "generate_brief",
    "ingest_pb_xlsx",
    "load_dotenv",
    "parse_day",
    "publish_draft",
    "read_articles",
    "read_brief",
    "render_html",
    "render_markdown",
    "validate_brief_data",
    "validate_html",
    "validate_window",
    "window_slug",
    "write_articles",
    "write_brief_outputs",
    "write_rendered_outputs",
    "_local_image_path",
]
