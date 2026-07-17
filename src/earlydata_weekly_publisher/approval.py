from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .pipeline import read_brief, write_rendered_outputs
from .quality import build_review_context


@dataclass(frozen=True)
class ApprovedArtifact:
    report_dir: Path
    brief_path: Path
    html_path: Path
    title: str
    brief_sha256: str
    html_sha256: str


def approve_report(report_dir: Path) -> dict[str, Any]:
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
    previous = _read_json(state_path)
    approved_at = datetime.now(timezone.utc).isoformat()
    state = {
        "status": "approved",
        "updated_at": approved_at,
        "approved_at": approved_at,
        "locked_fields": _string_list(previous.get("locked_fields")),
        "brief_sha256": _sha256(brief_path),
        "html_sha256": _sha256(html_path),
        "quality_warning_count": quality["warning_count"],
    }
    _write_json_atomic(state_path, state)
    return state


def load_approved_artifact(report_dir: Path) -> ApprovedArtifact:
    root = report_dir.resolve()
    brief_path = root / "brief.reviewed.json"
    html_path = root / "reviewed" / "wechat_article_img.html"
    state = _read_json(root / "review_state.json")
    if state.get("status") != "approved":
        raise ValueError("Report must be approved in the review workbench before publishing.")
    if not brief_path.is_file() or not html_path.is_file():
        raise ValueError("Approved brief or HTML artifact is missing.")
    brief_sha256, html_sha256 = _sha256(brief_path), _sha256(html_path)
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


def matching_publication_receipt(artifact: ApprovedArtifact) -> dict[str, Any] | None:
    receipt = _read_json(artifact.report_dir / "publication_receipt.json")
    if receipt.get("html_sha256") == artifact.html_sha256 and receipt.get("media_id"):
        return receipt
    return None


def write_publication_receipt(artifact: ApprovedArtifact, *, media_id: str, title: str) -> Path:
    path = artifact.report_dir / "publication_receipt.json"
    _write_json_atomic(
        path,
        {
            "status": "draft_created",
            "media_id": media_id,
            "title": title,
            "published_at": datetime.now(timezone.utc).isoformat(),
            "brief_sha256": artifact.brief_sha256,
            "html_sha256": artifact.html_sha256,
        },
    )
    return path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))
