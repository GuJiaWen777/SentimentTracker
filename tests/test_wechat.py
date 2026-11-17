import json

from earlydata_weekly_publisher import wechat


class FakeResponse:
    def __init__(self, payload, *, status=200, content=b"", text=""):
        self._payload = payload
        self.status_code = status
        self.content = content
        self.text = text or json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


def _html(tmp_path):
    path = tmp_path / "article.html"
    path.write_text('<section><p><span leaf="">正文</span></p></section>', encoding="utf-8")
    return path


def _no_uploads(monkeypatch):
    monkeypatch.setattr(wechat, "_upload_image", lambda *args, **kwargs: ("cover-media", "https://img.example/cover.png"))
    monkeypatch.setattr(wechat, "_rewrite_article_images", lambda html, token, base_dir, app_id: html)


def test_publish_refreshes_an_expired_access_token(tmp_path, monkeypatch):
    wechat.clear_token_cache()
    _no_uploads(monkeypatch)
    monkeypatch.setenv("WECHAT_APP_ID", "wx1234567890")
    monkeypatch.setenv("WECHAT_APP_SECRET", "secret")
    monkeypatch.setattr(wechat.time, "sleep", lambda _seconds: None)
    responses = [
        FakeResponse({"access_token": "token-1", "expires_in": 7200}),
        FakeResponse({"errcode": 40001, "errmsg": "invalid credential"}),
        FakeResponse({"access_token": "token-2", "expires_in": 7200}),
        FakeResponse({"media_id": "draft-1"}),
    ]
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url, dict(kwargs.get("params") or {})))
        return responses.pop(0)

    monkeypatch.setattr(wechat.requests, "request", fake_request)

    media_id = wechat.publish_draft(_html(tmp_path), title="标题", cover="cover.png", author="EARLY DATA")

    assert media_id == "draft-1"
    assert [(method, params.get("access_token")) for method, _url, params in calls] == [
        ("GET", None),
        ("POST", "token-1"),
        ("GET", None),
        ("POST", "token-2"),
    ]


def test_publish_updates_an_existing_draft(tmp_path, monkeypatch):
    wechat.clear_token_cache()
    _no_uploads(monkeypatch)
    monkeypatch.setenv("WECHAT_APP_ID", "wx1234567890")
    monkeypatch.setenv("WECHAT_APP_SECRET", "secret")
    monkeypatch.setattr(wechat, "get_access_token", lambda **kwargs: "token")
    captured = {}

    def fake_json(method, url, **kwargs):
        captured.update({"method": method, "url": url, **kwargs})
        return {}

    monkeypatch.setattr(wechat, "_wechat_json", fake_json)

    media_id = wechat.publish_draft(
        _html(tmp_path),
        title="标题",
        cover="cover.png",
        author="EARLY DATA",
        update_media_id="draft-0",
    )

    assert media_id == "draft-0"
    assert captured["url"] == wechat.DRAFT_UPDATE_URL
    assert captured["json_body"]["media_id"] == "draft-0"
    assert captured["json_body"]["index"] == 0


def test_image_upload_is_cached_by_content(tmp_path, monkeypatch):
    monkeypatch.setenv("EARLYDATA_WECHAT_CACHE", str(tmp_path / "cache" / "wechat_media.json"))
    image = tmp_path / "logo.png"
    image.write_bytes(b"fake-png-bytes")
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append((method, url))
        return FakeResponse({"media_id": "cover-media", "url": "https://img.example/logo.png"})

    monkeypatch.setattr(wechat.requests, "request", fake_request)

    first = wechat._upload_image("logo.png", "token", permanent=True, base_dir=tmp_path, app_id="wx123")
    second = wechat._upload_image("logo.png", "token", permanent=True, base_dir=tmp_path, app_id="wx123")

    assert first == second == ("cover-media", "https://img.example/logo.png")
    assert len(calls) == 1


def test_request_retries_a_transient_http_error(tmp_path, monkeypatch):
    monkeypatch.setenv("EARLYDATA_WECHAT_CACHE", str(tmp_path / "cache" / "wechat_media.json"))
    image = tmp_path / "logo.png"
    image.write_bytes(b"fake-png-bytes")
    responses = [
        FakeResponse({"errcode": -1, "errmsg": "system busy"}, status=503, text="busy"),
        FakeResponse({"media_id": "cover-media", "url": "https://img.example/logo.png"}),
    ]
    calls = []
    monkeypatch.setattr(wechat.time, "sleep", lambda _seconds: None)

    def fake_request(method, url, **kwargs):
        calls.append(method)
        return responses.pop(0)

    monkeypatch.setattr(wechat.requests, "request", fake_request)

    media_id, url = wechat._upload_image("logo.png", "token", permanent=True, base_dir=tmp_path, app_id="wx123")

    assert (media_id, url) == ("cover-media", "https://img.example/logo.png")
    assert len(calls) == 2


def test_access_token_is_cached_in_process(monkeypatch):
    wechat.clear_token_cache()
    calls = []

    def fake_request(method, url, **kwargs):
        calls.append(method)
        return FakeResponse({"access_token": "token", "expires_in": 7200})

    monkeypatch.setattr(wechat.requests, "request", fake_request)

    assert wechat.get_access_token(app_id="wx123", secret="secret") == "token"
    assert wechat.get_access_token(app_id="wx123", secret="secret") == "token"
    assert len(calls) == 1
