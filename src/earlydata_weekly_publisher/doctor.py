from __future__ import annotations

import json
import os
import platform
import shutil
import socket
import sqlite3
import sys
from pathlib import Path
from typing import Any

from .artifacts import stamp as stamp_artifact
from .config import load_dotenv
from .ranking_cache import DEFAULT_RANKING_CACHE
from .signal_history import default_history_db


LLM_BACKENDS = {"api", "claude", "codex"}


def run_doctor(root: Path, *, review_port: int = 8765) -> dict[str, Any]:
    """Check local configuration without printing secret values or calling providers."""
    base = Path(root).resolve()
    load_dotenv(base)
    checks: list[dict[str, str]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    version = sys.version_info
    if version >= (3, 10):
        add("python", "ok", f"Python {platform.python_version()}")
    else:
        add("python", "error", f"Python {platform.python_version()} is too old; 3.10+ is required.")

    project_file = base / "pyproject.toml"
    if project_file.is_file() and "earlydata-weekly-publisher" in project_file.read_text(encoding="utf-8", errors="ignore"):
        add("project", "ok", "pyproject.toml found")
    else:
        add("project", "warn", "run commands from the repository root containing pyproject.toml")

    env_file = base / ".env"
    add(
        "env_file",
        "ok" if env_file.is_file() else "warn",
        ".env found" if env_file.is_file() else "no .env file; using the current environment",
    )

    backend = (os.environ.get("LLM_BACKEND") or "api").strip().lower()
    if backend not in LLM_BACKENDS:
        add("llm_backend", "error", f"LLM_BACKEND={backend!r} is not one of api, claude, codex")
    else:
        add("llm_backend", "ok", f"LLM_BACKEND={backend}")
        if backend == "api":
            key = bool(os.environ.get("LLM_API_KEY", "").strip())
            model = bool(os.environ.get("LLM_API_MODEL", "").strip())
            if key and model:
                add("llm_api", "ok", "LLM_API_KEY and LLM_API_MODEL are configured")
            else:
                missing = [
                    name
                    for name, present in (("LLM_API_KEY", key), ("LLM_API_MODEL", model))
                    if not present
                ]
                add("llm_api", "error", "missing " + ", ".join(missing))
            base_url = os.environ.get("LLM_API_BASE_URL", "https://api.openai.com/v1").strip()
            if base_url.startswith(("http://", "https://")):
                add("llm_base_url", "ok", base_url)
            else:
                add("llm_base_url", "warn", "LLM_API_BASE_URL should start with http:// or https://")
        else:
            executable = "claude" if backend == "claude" else "codex"
            found = shutil.which(executable) or shutil.which(f"{executable}.cmd") or shutil.which(f"{executable}.exe")
            add(
                "llm_cli",
                "ok" if found else "error",
                f"{executable} found on PATH" if found else f"{executable} CLI not found on PATH",
            )

    redfox = bool(os.environ.get("REDFOX_API_KEY", "").strip())
    add(
        "redfox",
        "ok" if redfox else "warn",
        "REDFOX_API_KEY is configured" if redfox else "REDFOX_API_KEY is not configured; RedFox fetch will fail",
    )

    app_id = os.environ.get("WECHAT_APP_ID", "").strip()
    secret = os.environ.get("WECHAT_APP_SECRET", "").strip()
    if app_id and secret:
        notes = ["WECHAT_APP_ID and WECHAT_APP_SECRET are configured"]
        status = "ok"
        if not app_id.startswith("wx"):
            status = "warn"
            notes.append("WECHAT_APP_ID usually starts with 'wx'")
        if len(secret) < 16:
            status = "warn"
            notes.append("WECHAT_APP_SECRET looks unusually short")
        add("wechat", status, "; ".join(notes))
    elif app_id or secret:
        add("wechat", "warn", "only one of WECHAT_APP_ID / WECHAT_APP_SECRET is configured")
    else:
        add("wechat", "warn", "WeChat credentials are not configured; publishing will fail")

    _check_writable(base / "data", "data_dir", add)

    cache_path = _resolve(base, os.environ.get("EARLYDATA_RANKING_CACHE") or str(DEFAULT_RANKING_CACHE))
    _check_readable_json(cache_path, "ranking_cache", add)

    history_path = _resolve(base, os.environ.get("EARLYDATA_HISTORY_DB") or str(default_history_db()))
    _check_history_db(history_path, add)

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", int(review_port)))
        except OSError:
            add("review_port", "warn", f"127.0.0.1:{review_port} is in use; pass --port to review")
        else:
            add("review_port", "ok", f"127.0.0.1:{review_port} is available")

    ok_count = sum(1 for check in checks if check["status"] == "ok")
    warn_count = sum(1 for check in checks if check["status"] == "warn")
    error_count = sum(1 for check in checks if check["status"] == "error")
    return stamp_artifact(
        "doctor",
        {
            "ok": error_count == 0,
            "summary": {"ok": ok_count, "warn": warn_count, "error": error_count},
            "checks": checks,
            "environment": {
                "root": str(base),
                "cwd": str(Path.cwd()),
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
        },
    )


def format_doctor(report: dict[str, Any]) -> str:
    labels = {"ok": "[ok]", "warn": "[warn]", "error": "[error]"}
    lines = [f"环境检查：{report['summary']['ok']} ok, {report['summary']['warn']} warn, {report['summary']['error']} error"]
    for check in report.get("checks", []):
        lines.append(f"{labels.get(check['status'], '[?]'):8} {check['name']}: {check['detail']}")
    return "\n".join(lines)


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _check_writable(path: Path, name: str, add: Any) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".earlydata-doctor-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        add(name, "error", f"{path} is not writable: {exc}")
    else:
        add(name, "ok", f"{path} is writable")


def _check_readable_json(path: Path, name: str, add: Any) -> None:
    if not path.is_file():
        parent = path.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
            probe = parent / ".earlydata-doctor-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            add(name, "error", f"cache directory {parent} is not writable: {exc}")
        else:
            add(name, "ok", f"{path} does not exist yet; it will be created")
        return
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        add(name, "warn", f"cache is unreadable and will be rebuilt: {type(exc).__name__}")
        return
    if isinstance(value, dict):
        add(name, "ok", f"{path} is readable")
    else:
        add(name, "warn", f"{path} is not a JSON object; it will be rebuilt")


def _check_history_db(path: Path, add: Any) -> None:
    if not path.is_file():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            add("history_db", "error", f"history directory is not writable: {exc}")
        else:
            add("history_db", "ok", f"{path} does not exist yet; it will be created")
        return
    try:
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5)
        try:
            row = connection.execute("PRAGMA quick_check").fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        add("history_db", "error", f"history database is unreadable: {exc}")
        return
    if row and str(row[0]).lower() == "ok":
        add("history_db", "ok", f"{path} passed quick_check")
    else:
        add("history_db", "warn", f"{path} reported: {row[0] if row else 'no result'}")
