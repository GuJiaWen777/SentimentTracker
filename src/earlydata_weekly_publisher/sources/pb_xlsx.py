from __future__ import annotations

from datetime import date
from pathlib import Path

from ..articles import validate_window
from ..models import Article
from ..text import as_int, cell_value, coerce_date, repair_title_symbols


def ingest_pb_xlsx(path: Path, start: date, end: date) -> list[Article]:
    validate_window(start, end)
    from openpyxl import load_workbook

    book = load_workbook(path, read_only=True, data_only=True)
    sheet = book.active
    articles: list[Article] = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        title = str(cell_value(row, 3) or "").strip()
        content = str(cell_value(row, 17) or "").strip()
        if not title and not content:
            continue
        published = coerce_date(cell_value(row, 7))
        if not published or not start <= published <= end:
            continue
        tags = [str(cell_value(row, index)).strip() for index in (8, 9, 10, 11) if cell_value(row, index)]
        articles.append(
            Article(
                title=repair_title_symbols(title or content[:30], content),
                source=str(cell_value(row, 5) or "来源").strip(),
                published_at=published.isoformat(),
                content=content,
                url=str(cell_value(row, 12) or "").strip(),
                tags=tags,
                read_count=as_int(cell_value(row, 13)),
                like_count=as_int(cell_value(row, 14)),
                share_count=as_int(cell_value(row, 15)),
                recommend_count=as_int(cell_value(row, 16)),
            )
        )
    book.close()
    return articles
