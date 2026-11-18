from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .artifacts import check as check_artifact
from .artifacts import stamp as stamp_artifact
from .brief import read_brief, write_rendered_outputs
from .io_utils import sha256_file, write_json_atomic
from .quality import build_review_context
from .text import dedupe_strings


@dataclass(frozen=True)
class ApprovedArtifact:
    report_dir: Path
    brief_path: Path
    html_path: Path
    title: str
    brief_sha256: str
    html_sha256: str


def approve_report(report_dir: Path, *, history_db: Path | None = None) -> dict[str, Any]:
    root = report_dir.resolve()
    brief_path = root / "brief.reviewed.json"
    state_path = root / "review_state.json"
    if not brief_path.is_file():
        raise ValueError("Save the reviewed brief before approval.")
    brief = read_brief(brief_path)
    quality = build_review_context(root, brief)["quality"]
    if quality["error_count"]:
        raise ValueError(f"Review has {quality['error_count']} blocking quality errors.")
    html_path = write_rendered_outputs(brief, root / "reviewed")["html"]
    previous = _read_json(state_path, kind="review_state")
    approved_at = datetime.now(timezone.utc).isoformat()
    state = stamp_artifact(
        "review_state",
        {
            "status": "approved",
            "updated_at": approved_at,
            "approved_at": approved_at,
            "locked_fields": dedupe_strings(previous.get("locked_fields")),
            "brief_sha256": sha256_file(brief_path),
            "html_sha256": sha256_file(html_path),
        },
    )
    write_json_atomic(state_path, state)
    if history_db is not None:
        from .signal_history import record_report

        try:
            state["history"] = record_report(root, db_path=history_db)
        except Exception as exc:  # History is advisory; never block editorial approval.
            state["history_error"] = f"{type(exc).__name__}: {exc}"
        write_json_atomic(state_path, state)
    return state


def load_approved_artifact(report_dir: Path) -> ApprovedArtifact:
    root = report_dir.resolve()
    brief_path = root / "brief.reviewed.json"
    html_path = root / "reviewed" / "wechat_article_img.html"
    state = _read_json(root / "review_state.json", kind="review_state")
    if state.get("status") != "approved":
        raise ValueError("Report must be approved in the review workbench before publishing.")
    if not brief_path.is_file() or not html_path.is_file():
        raise ValueError("Approved brief or HTML artifact is missing.")
    brief_sha256, html_sha256 = sha256_file(brief_path), sha256_file(html_path)
    if brief_sha256 != state.get("brief_sha256") or html_sha256 != state.get("html_sha256"):
        raise ValueError("Approved artifacts changed after approval; review and approve them again.")
    brief = read_brief(brief_path)
    return ApprovedArtifact(
        report_dir=root,
        brief_path=brief_path,
        html_path=html_path,
        title=str(brief["title"]),
        brief_sha256=brief_sha256,
        html_sha256=html_sha256,
    )


def read_publication_receipt(report_dir: Path) -> dict[str, Any]:
    return _read_json(Path(report_dir) / "publication_receipt.json", kind="publication_receipt")


def matching_publication_receipt(artifact: ApprovedArtifact) -> dict[str, Any] | None:
    receipt = read_publication_receipt(artifact.report_dir)
    if receipt.get("html_sha256") == artifact.html_sha256 and receipt.get("media_id"):
        return receipt
    return None


def write_publication_receipt(
    artifact: ApprovedArtifact,
    *,
    media_id: str,
    title: str,
    updated: bool = False,
) -> Path:
    path = artifact.report_dir / "publication_receipt.json"
    previous = read_publication_receipt(artifact.report_dir)
    try:
        update_count = int(previous.get("update_count") or 0)
    except (TypeError, ValueError):
        update_count = 0
    now = datetime.now(timezone.utc).isoformat()
    payload = stamp_artifact(
        "publication_receipt",
        {
            "status": "draft_updated" if updated else "draft_created",
            "media_id": media_id,
            "title": title,
            "published_at": str(previous.get("published_at") or now),
            "updated_at": now,
            "brief_sha256": artifact.brief_sha256,
            "html_sha256": artifact.html_sha256,
            "update_count": update_count + (1 if updated else 0),
        },
    )
    write_json_atomic(path, payload)
    return path


def _read_json(path: Path, *, kind: str | None = None) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        return {}
    if kind is not None:
        check_artifact(kind, value)
    return value

