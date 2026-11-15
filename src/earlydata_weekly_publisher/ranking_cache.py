from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .prompts import RANKING_PROMPT_VERSION


DEFAULT_RANKING_CACHE = Path("data/cache/ranking.json")
CACHE_VERSION = 1
MAX_ENTRIES = 5000
CATEGORIES = {"监管", "政策", "交易", "临床", "技术", "资本", "市场", "其他"}


@dataclass
class RankingCache:
    """Content-addressed ranking cache shared across report runs."""

    path: Path
    model: str
    prompt_version: str = RANKING_PROMPT_VERSION
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    @classmethod
    def open(cls, path: Path, *, model: str, prompt_version: str = RANKING_PROMPT_VERSION) -> "RankingCache":
        target = Path(path)
        entries: dict[str, dict[str, Any]] = {}
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        if isinstance(raw, dict) and raw.get("version") == CACHE_VERSION and isinstance(raw.get("entries"), dict):
            entries = {str(key): value for key, value in raw["entries"].items() if isinstance(value, dict)}
        return cls(path=target, model=model, prompt_version=prompt_version, entries=entries)

    def get(self, article: Any) -> dict[str, Any] | None:
        entry = self.entries.get(self._key(article))
        if not entry:
            self.misses += 1
            return None
        score = entry.get("score")
        category = str(entry.get("category") or "")
        reason = str(entry.get("reason") or "").strip()
        if (
            isinstance(score, bool)
            or not isinstance(score, int)
            or not 0 <= score <= 100
            or category not in CATEGORIES
            or not reason
        ):
            self.misses += 1
            return None
        self.hits += 1
        return {"score": score, "category": category, "reason": reason}

    def put(self, article: Any, *, score: int, category: str, reason: str) -> None:
        self.entries[self._key(article)] = {
            "score": int(score),
            "category": category,
            "reason": reason,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

    def save(self) -> None:
        ordered = sorted(
            self.entries.items(),
            key=lambda item: str(item[1].get("updated_at") or ""),
            reverse=True,
        )[:MAX_ENTRIES]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(
                {"version": CACHE_VERSION, "entries": dict(ordered)},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    def _key(self, article: Any) -> str:
        payload = {
            "model": self.model,
            "prompt_version": self.prompt_version,
            "title": str(getattr(article, "title", "")),
            "source": str(getattr(article, "source", "")),
            "published_at": str(getattr(article, "published_at", "")),
            "text": str(getattr(article, "summary", "") or getattr(article, "content", "")),
            "tags": list(getattr(article, "tags", None) or []),
            "read": int(getattr(article, "read_count", 0) or 0),
            "like": int(getattr(article, "like_count", 0) or 0),
            "share": int(getattr(article, "share_count", 0) or 0),
            "recommend": int(getattr(article, "recommend_count", 0) or 0),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()
