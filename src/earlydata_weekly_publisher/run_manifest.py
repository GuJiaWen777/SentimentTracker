from __future__ import annotations

import json
import platform
import subprocess
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .artifacts import stamp as stamp_artifact
from .io_utils import sha256_file
from .prompts import RANKING_PROMPT_VERSION, SYNTHESIS_PROMPT_VERSION


GENERATED_FILES = (
    "articles.json",
    "brief.json",
    "ranking.json",
    "wechat_article.md",
    "wechat_article_img.html",
)


class RunManifest:
    """Collect provenance for one build/run and write ``run.json``.

    The manifest is best-effort: a failure to write it must never fail the
    content pipeline itself.
    """

    def __init__(self, output_dir: Path, *, command: str, start: date, end: date) -> None:
        self.output_dir = Path(output_dir)
        self.command = command
        self.start = start
        self.end = end
        self.started_at = datetime.now(timezone.utc)
        self._started_monotonic = time.monotonic()
        self.brief: dict[str, Any] | None = None
        self.outputs: dict[str, Path] | None = None
        self.extra: dict[str, Any] = {}
        self._written = False

    def __enter__(self) -> "RunManifest":
        return self

    def __exit__(self, exc_type: Any, exc: BaseException | None, traceback: Any) -> bool:
        if not self._written:
            self.write(error=exc)
        return False

    def set(self, key: str, value: Any) -> "RunManifest":
        self.extra[key] = value
        return self

    def record(self, brief: dict[str, Any], outputs: dict[str, Path]) -> None:
        self.brief = brief
        self.outputs = outputs

    def write(self, *, error: BaseException | None = None) -> None:
        if self._written:
            return
        self._written = True
        generation = (self.brief or {}).get("generation")
        generation = generation if isinstance(generation, dict) else {}
        counts = {
            "source_count": int((self.brief or {}).get("source_count") or 0),
            "selected_count": len((self.brief or {}).get("items") or []),
            "alternate_count": len((self.brief or {}).get("alternates") or []),
            "ranked_article_count": generation.get("ranked_article_count"),
            "unique_article_count": generation.get("unique_article_count"),
            "candidate_count": generation.get("candidate_count"),
            "excluded_outside_window": generation.get("excluded_outside_window", 0),
        }
        counts.update(self.extra.get("counts") or {})
        cache = {
            "enabled": bool(generation.get("cache_hits") or generation.get("cache_misses")),
            "hits": int(generation.get("cache_hits") or 0),
            "misses": int(generation.get("cache_misses") or 0),
        }
        cache.update(self.extra.get("cache") or {})
        history = {
            "enabled": bool(generation.get("history_weeks")),
            "weeks": int(generation.get("history_weeks") or 0),
        }
        history.update(self.extra.get("history") or {})
        payload = stamp_artifact(
            "run",
            {
                "status": "failed" if error is not None else "completed",
                "command": self.command,
                "started_at": self.started_at.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "duration_seconds": round(time.monotonic() - self._started_monotonic, 3),
                "window": {"start": self.start.isoformat(), "end": self.end.isoformat()},
                "environment": {
                    "python": platform.python_version(),
                    "platform": platform.platform(),
                },
                "git": _git_info(),
                "llm": {
                    "backend": str(generation.get("backend") or ""),
                    "model": str(generation.get("model") or ""),
                    "prompts": {
                        "ranking": RANKING_PROMPT_VERSION,
                        "synthesis": SYNTHESIS_PROMPT_VERSION,
                    },
                    "usage": generation.get("usage") or {},
                },
                "generation": generation,
                "counts": counts,
                "cache": cache,
                "history": history,
                "input": self.extra.get("input", ""),
                "acquisition": self.extra.get("acquisition", {}),
                "artifacts": self._artifacts(),
                "error": (
                    {"type": type(error).__name__, "message": str(error)[:1000]}
                    if error is not None
                    else None
                ),
            },
        )
        self._write(payload)

    def _artifacts(self) -> dict[str, dict[str, Any]]:
        root = self.output_dir.resolve()
        candidates = [root / "articles.json"]
        if self.outputs:
            candidates.extend(Path(path).resolve() for path in self.outputs.values())
        else:
            candidates.extend(root / filename for filename in GENERATED_FILES)
        artifacts: dict[str, dict[str, Any]] = {}
        seen: set[Path] = set()
        for path in candidates:
            if path in seen or not path.is_file():
                continue
            seen.add(path)
            try:
                artifacts[path.name] = {
                    "path": path.name,
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
            except OSError:
                continue
        return artifacts

    def _write(self, payload: dict[str, Any]) -> None:
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            path = self.output_dir / "run.json"
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
        except (OSError, TypeError, ValueError):
            pass


def _git_info() -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        ).stdout.strip()
        if not commit:
            return {}
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        ).stdout.strip()
        return {"commit": commit, "dirty": bool(status)}
    except (OSError, subprocess.SubprocessError):
        return {}
