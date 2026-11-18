"""Article sources. Each module turns one upstream into ``list[Article]``."""

from .pb_xlsx import ingest_pb_xlsx
from .redfox import fetch_redfox

__all__ = ["fetch_redfox", "ingest_pb_xlsx"]
