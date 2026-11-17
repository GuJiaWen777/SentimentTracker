from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


WECHAT_API = "https://api.weixin.qq.com"
TOKEN_URL = f"{WECHAT_API}/cgi-bin/token"
DRAFT_ADD_URL = f"{WECHAT_API}/cgi-bin/draft/add"
DRAFT_UPDATE_URL = f"{WECHAT_API}/cgi-bin/draft/update"
MATERIAL_URL = f"{WECHAT_API}/cgi-bin/material/add_material"
UPLOADIMG_URL = f"{WECHAT_API}/cgi-bin/media/uploadimg"

TOKEN_ERROR_CODES = {40001, 40014, 42001}
RETRYABLE_ERRCODES = {-1, 45009}
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
REQUEST_ATTEMPTS = 3
TOKEN_REFRESH_MARGIN_SECONDS = 300
TEMP_MEDIA_TTL = timedelta(days=7)
DEFAULT_MEDIA_CACHE = Path("data/cache/wechat_media.json")

_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_TOKEN_LOCK = threading.Lock()
_MEDIA_LOCK = threading.Lock()


class WeChatError(RuntimeError):
    """A WeChat API failure with an optional provider error code."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


def publish_draft(
    html_path: Path,
    *,
    title: str,
    cover: str,
    author: str,
    digest: str = "",
    source_url: str = "",
    update_media_id: str | None = None,
) -> str:
    """Create a WeChat draft, or update ``update_media_id`` when provided."""
    from .pipeline import validate_html

    html = Path(html_path).read_text(encoding="utf-8")
    validate_html(html)
    app_id, secret = _credentials()
    token = get_access_token(app_id=app_id, secret=secret)

    def attempt(access_token: str) -> str:
        cover_media_id = _upload_image(
            cover,
            access_token,
            permanent=True,
            base_dir=Path(html_path).parent,
            app_id=app_id,
        )[0]
        content = _rewrite_article_images(html, access_token, Path(html_path).parent, app_id)
        article = {
            "title": title,
            "author": author,
            "digest": digest,
            "content": content,
            "content_source_url": source_url,
            "thumb_media_id": cover_media_id,
            "need_open_comment": 0,
            "only_fans_can_comment": 0,
        }
        return _create_or_update(access_token, article, update_media_id)

    try:
        return attempt(token)
    except WeChatError as exc:
        if exc.code not in TOKEN_ERROR_CODES:
            raise
        refreshed = get_access_token(app_id=app_id, secret=secret, force=True)
        return attempt(refreshed)


def get_access_token(*, app_id: str | None = None, secret: str | None = None, force: bool = False) -> str:
    app_id = (app_id if app_id is not None else os.environ.get("WECHAT_APP_ID", "")).strip()
    secret = (secret if secret is not None else os.environ.get("WECHAT_APP_SECRET", "")).strip()
    if not app_id or not secret:
        raise WeChatError("WECHAT_APP_ID and WECHAT_APP_SECRET are required.")
    cache_key = f"{app_id}:{hashlib.sha256(secret.encode('utf-8')).hexdigest()[:12]}"
    now = time.monotonic()
    with _TOKEN_LOCK:
        cached = _TOKEN_CACHE.get(cache_key)
        if cached and not force and cached[1] > now:
            return cached[0]
    body = _wechat_json(
        "GET",
        TOKEN_URL,
        action="WeChat token",
        params={"grant_type": "client_credential", "appid": app_id, "secret": secret},
        timeout=20,
    )
    token = str(body.get("access_token") or "").strip()
    if not token:
        raise WeChatError("WeChat token failed: response did not contain access_token.")
    try:
        expires_in = int(body.get("expires_in") or 7200)
    except (TypeError, ValueError):
        expires_in = 7200
    ttl = max(60, expires_in - TOKEN_REFRESH_MARGIN_SECONDS)
    with _TOKEN_LOCK:
        _TOKEN_CACHE[cache_key] = (token, time.monotonic() + ttl)
    return token


def clear_token_cache() -> None:
    with _TOKEN_LOCK:
        _TOKEN_CACHE.clear()


def _credentials() -> tuple[str, str]:
    app_id = os.environ.get("WECHAT_APP_ID", "").strip()
    secret = os.environ.get("WECHAT_APP_SECRET", "").strip()
    if not app_id or not secret:
        raise WeChatError("WECHAT_APP_ID and WECHAT_APP_SECRET are required.")
    return app_id, secret


def _create_or_update(access_token: str, article: dict[str, Any], update_media_id: str | None) -> str:
    if update_media_id:
        _wechat_json(
            "POST",
            DRAFT_UPDATE_URL,
            action="WeChat draft update",
            params={"access_token": access_token},
            json_body={"media_id": update_media_id, "index": 0, "articles": article},
            timeout=30,
        )
        return str(update_media_id)
    body = _wechat_json(
        "POST",
        DRAFT_ADD_URL,
        action="WeChat draft add",
        params={"access_token": access_token},
        json_body={"articles": [article]},
        timeout=30,
    )
    media_id = str(body.get("media_id") or "").strip()
    if not media_id:
        raise WeChatError("WeChat draft add failed: response did not contain media_id.")
    return media_id


def _rewrite_article_images(html: str, token: str, base_dir: Path, app_id: str) -> str:
    import re

    def replace(match: "re.Match[str]") -> str:
        source = match.group(1)
        uploaded = _upload_image(
            source,
            token,
            permanent=False,
            base_dir=base_dir,
            restrict_to_base=True,
            app_id=app_id,
        )[1]
        return match.group(0).replace(source, uploaded)

    return re.sub(r'<img[^>]+src=["\']([^"\']+)["\']', replace, html)


def _upload_image(
    source: str,
    token: str,
    *,
    permanent: bool,
    base_dir: Path,
    restrict_to_base: bool = False,
    app_id: str = "",
) -> tuple[str, str]:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        response = _request("GET", source, timeout=30)
        if response.status_code >= 400:
            raise WeChatError(f"Image download failed with HTTP {response.status_code}: {_preview(response)}")
        content, filename = response.content, Path(parsed.path).name or "image.png"
    elif parsed.scheme:
        raise WeChatError(f"Unsupported image reference: {source}")
    else:
        path = _local_image_path(source, base_dir, restrict_to_base=restrict_to_base)
        content, filename = path.read_bytes(), path.name

    content_type = mimetypes.guess_type(filename)[0] or "image/png"
    cache_key = _media_key(app_id, permanent, content)
    cached = _media_cache_get(cache_key)
    if cached is not None:
        return cached

    if permanent:
        url, params = MATERIAL_URL, {"access_token": token, "type": "image"}
        action = "Cover upload"
    else:
        url, params = UPLOADIMG_URL, {"access_token": token}
        action = "Article image upload"
    body = _wechat_json(
        "POST",
        url,
        action=action,
        params=params,
        files={"media": (filename, content, content_type)},
        timeout=30,
    )
    media_id, image_url = str(body.get("media_id") or ""), str(body.get("url") or "")
    if permanent and not media_id:
        raise WeChatError(f"{action} failed: response did not contain media_id.")
    if not permanent and not image_url:
        raise WeChatError(f"{action} failed: response did not contain url.")
    _media_cache_put(cache_key, media_id=media_id, url=image_url, permanent=permanent)
    return media_id, image_url


def _local_image_path(source: str, base_dir: Path, *, restrict_to_base: bool) -> Path:
    path = Path(source)
    if not path.is_absolute():
        path = base_dir / path
    resolved = path.resolve()
    if restrict_to_base and not resolved.is_relative_to(base_dir.resolve()):
        raise WeChatError(f"Article image path escapes the report directory: {source}")
    if not resolved.is_file():
        raise WeChatError(f"Article image not found: {source}")
    return resolved


def _request(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    timeout: float = 30,
) -> Any:
    last_error: Exception | None = None
    for attempt in range(REQUEST_ATTEMPTS):
        try:
            response = requests.request(
                method,
                url,
                params=params,
                json=json_body,
                files=files,
                timeout=timeout,
            )
        except requests.RequestException as exc:
            last_error = exc
            if attempt < REQUEST_ATTEMPTS - 1:
                time.sleep(min(8.0, 0.5 * 2**attempt))
                continue
            raise WeChatError(f"WeChat request failed: {exc}") from exc
        if response.status_code in RETRYABLE_HTTP_STATUS and attempt < REQUEST_ATTEMPTS - 1:
            time.sleep(min(8.0, 0.5 * 2**attempt))
            continue
        return response
    raise WeChatError(f"WeChat request failed: {last_error}") from last_error


def _wechat_json(
    method: str,
    url: str,
    *,
    action: str,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
    files: dict[str, Any] | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
    for attempt in range(REQUEST_ATTEMPTS):
        response = _request(method, url, params=params, json_body=json_body, files=files, timeout=timeout)
        if response.status_code >= 400:
            raise WeChatError(f"{action} failed with HTTP {response.status_code}: {_preview(response)}")
        try:
            body = response.json()
        except (ValueError, TypeError) as exc:
            raise WeChatError(f"{action} returned malformed JSON.") from exc
        if not isinstance(body, dict):
            raise WeChatError(f"{action} returned a non-object response.")
        code = _errcode(body)
        if code in RETRYABLE_ERRCODES and attempt < REQUEST_ATTEMPTS - 1:
            time.sleep(min(8.0, 0.5 * 2**attempt))
            continue
        if code:
            raise WeChatError(_error_text(action, body), code=code)
        return body
    raise WeChatError(f"{action} failed after {REQUEST_ATTEMPTS} attempts.")


def _errcode(body: dict[str, Any]) -> int | None:
    raw = body.get("errcode")
    if raw in (None, 0, "0", ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _error_text(action: str, body: dict[str, Any]) -> str:
    message = str(body.get("errmsg") or "unknown error")
    code = _errcode(body)
    return f"{action} failed: {message} (code {code})" if code else f"{action} failed: {message}"


def _preview(response: Any) -> str:
    return str(getattr(response, "text", ""))[:200]


def _media_key(app_id: str, permanent: bool, content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()
    return f"{app_id or 'default'}:{'permanent' if permanent else 'temporary'}:{digest}"


def _media_cache_path() -> Path:
    return Path(os.environ.get("EARLYDATA_WECHAT_CACHE") or DEFAULT_MEDIA_CACHE)


def _load_media_cache() -> dict[str, Any]:
    path = _media_cache_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "entries": {}}
    if not isinstance(raw, dict) or raw.get("version") != 1 or not isinstance(raw.get("entries"), dict):
        return {"version": 1, "entries": {}}
    return raw


def _media_cache_get(key: str) -> tuple[str, str] | None:
    with _MEDIA_LOCK:
        entry = _load_media_cache()["entries"].get(key)
    if not isinstance(entry, dict):
        return None
    expires_at = str(entry.get("expires_at") or "")
    if expires_at and expires_at <= datetime.now(timezone.utc).isoformat():
        return None
    media_id, url = str(entry.get("media_id") or ""), str(entry.get("url") or "")
    if not media_id and not url:
        return None
    return media_id, url


def _media_cache_put(key: str, *, media_id: str, url: str, permanent: bool) -> None:
    now = datetime.now(timezone.utc)
    expires_at = "" if permanent else (now + TEMP_MEDIA_TTL).isoformat()
    with _MEDIA_LOCK:
        data = _load_media_cache()
        data["entries"][key] = {
            "media_id": media_id,
            "url": url,
            "cached_at": now.isoformat(),
            "expires_at": expires_at,
        }
        cutoff = now.isoformat()
        data["entries"] = {
            entry_key: entry
            for entry_key, entry in data["entries"].items()
            if not isinstance(entry, dict) or not entry.get("expires_at") or str(entry["expires_at"]) > cutoff
        }
        path = _media_cache_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(path.suffix + ".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
        except OSError:
            # The cache is an optimization; publishing must still succeed.
            pass
