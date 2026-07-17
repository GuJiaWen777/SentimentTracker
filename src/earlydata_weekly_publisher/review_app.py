from __future__ import annotations

import json
import threading
import webbrowser
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .pipeline import read_brief, validate_brief_data, write_rendered_outputs


MAX_REQUEST_BYTES = 2 * 1024 * 1024


class ReviewWorkspace:
    def __init__(self, report_dir: Path) -> None:
        self.report_dir = report_dir.resolve()
        self.source_path = self.report_dir / "brief.json"
        self.reviewed_path = self.report_dir / "brief.reviewed.json"
        self.state_path = self.report_dir / "review_state.json"
        self.preview_dir = self.report_dir / "reviewed"
        if not self.source_path.is_file():
            raise FileNotFoundError(f"Missing report brief: {self.source_path}")

    def load(self) -> dict[str, Any]:
        brief_path = self.reviewed_path if self.reviewed_path.is_file() else self.source_path
        brief = read_brief(brief_path)
        state: dict[str, Any] = {}
        if self.state_path.is_file():
            raw_state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if isinstance(raw_state, dict):
                state = raw_state
        return {
            "brief": brief,
            "locked_fields": _string_list(state.get("locked_fields")),
            "status": str(state.get("status") or "editing"),
            "updated_at": str(state.get("updated_at") or ""),
            "using_reviewed_brief": brief_path == self.reviewed_path,
        }

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        brief = validate_brief_data(payload.get("brief"))
        locked_fields = _string_list(payload.get("locked_fields"))
        updated_at = datetime.now(timezone.utc).isoformat()
        state = {
            "status": "editing",
            "updated_at": updated_at,
            "locked_fields": locked_fields,
        }
        _write_json_atomic(self.reviewed_path, brief)
        _write_json_atomic(self.state_path, state)
        outputs = write_rendered_outputs(brief, self.preview_dir)
        return {
            "updated_at": updated_at,
            "locked_fields": locked_fields,
            "preview": str(outputs["html"]),
        }

    def preview_path(self) -> Path:
        reviewed = self.preview_dir / "wechat_article_img.html"
        generated = self.report_dir / "wechat_article_img.html"
        return reviewed if reviewed.is_file() else generated


def serve_review_workbench(
    report_dir: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
) -> None:
    workspace = ReviewWorkspace(report_dir)
    handler = _handler_for(workspace)
    server = ThreadingHTTPServer((host, port), handler)
    actual_port = server.server_address[1]
    url = f"http://{host}:{actual_port}/"
    print(f"Review workbench: {url}", flush=True)
    if open_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def _handler_for(workspace: ReviewWorkspace) -> type[BaseHTTPRequestHandler]:
    class ReviewHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlparse(self.path).path
            if path == "/":
                self._send(REVIEW_HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if path == "/api/review":
                self._json(workspace.load())
                return
            if path == "/api/health":
                self._json({"status": "ok"})
                return
            if path == "/preview":
                preview = workspace.preview_path()
                if not preview.is_file():
                    self.send_error(HTTPStatus.NOT_FOUND, "Preview has not been generated.")
                    return
                self._send(preview.read_bytes(), "text/html; charset=utf-8")
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_PUT(self) -> None:
            if urlparse(self.path).path != "/api/review":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_REQUEST_BYTES:
                    raise ValueError("Review payload is empty or too large.")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("Review payload must be a JSON object.")
                self._json(workspace.save(payload))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _json(self, value: Any, *, status: HTTPStatus = HTTPStatus.OK) -> None:
            self._send(json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

        def _send(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return ReviewHandler


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))


REVIEW_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>EarlyData 周报审核</title>
  <script src="https://unpkg.com/lucide@0.468.0/dist/umd/lucide.min.js"></script>
  <style>
    :root {
      --ink: #172033;
      --muted: #687284;
      --line: #dfe3e8;
      --paper: #ffffff;
      --canvas: #f3f5f6;
      --green: #28723f;
      --green-soft: #e9f5ec;
      --blue: #1d61a7;
      --red: #a83232;
      --amber: #95610a;
    }
    * { box-sizing: border-box; letter-spacing: 0; }
    html, body { margin: 0; min-height: 100%; background: var(--canvas); color: var(--ink); }
    body { font-family: "IBM Plex Sans", "Noto Sans SC", "Microsoft YaHei", sans-serif; }
    button, input, textarea, select { font: inherit; }
    button { cursor: pointer; }
    .shell { min-height: 100vh; display: grid; grid-template-rows: 56px 1fr; }
    .topbar { display: flex; align-items: center; justify-content: space-between; gap: 20px; padding: 0 20px; border-bottom: 1px solid var(--line); background: var(--paper); }
    .brand { display: flex; align-items: baseline; gap: 12px; min-width: 0; }
    .brand strong { font-family: Georgia, "Noto Serif SC", serif; font-size: 18px; }
    .brand span { overflow: hidden; color: var(--muted); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
    .actions { display: flex; align-items: center; gap: 10px; }
    .status { min-width: 110px; color: var(--muted); font-size: 12px; text-align: right; }
    .button { display: inline-flex; min-height: 34px; align-items: center; justify-content: center; gap: 7px; border: 1px solid var(--line); border-radius: 6px; background: var(--paper); padding: 7px 12px; color: var(--ink); font-size: 13px; font-weight: 650; }
    .button:hover { border-color: #aab2bd; background: #f8fafb; }
    .button.primary { border-color: var(--green); background: var(--green); color: white; }
    .button.primary:hover { background: #205f34; }
    .button:disabled { cursor: wait; opacity: .55; }
    .workspace { min-height: 0; display: grid; grid-template-columns: minmax(520px, 58%) minmax(380px, 42%); }
    .editor { min-width: 0; overflow: auto; border-right: 1px solid var(--line); background: var(--paper); }
    .editor-inner { width: min(780px, 100%); margin: 0 auto; padding: 26px 30px 80px; }
    .preview { min-width: 0; background: #e7eaed; padding: 18px; }
    .preview-frame { width: 100%; height: calc(100vh - 92px); border: 1px solid #ccd2d9; background: white; box-shadow: 0 12px 28px rgba(23,32,51,.09); }
    .section { padding: 22px 0; border-bottom: 1px solid var(--line); }
    .section:first-child { padding-top: 0; }
    .section-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
    .section-head h2 { margin: 0; font-family: Georgia, "Noto Serif SC", serif; font-size: 18px; }
    .meta { color: var(--muted); font-size: 12px; }
    .field { position: relative; margin-top: 14px; }
    .field:first-child { margin-top: 0; }
    .field-label { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 6px; color: #4e596b; font-size: 12px; font-weight: 700; }
    .control { width: 100%; border: 1px solid #cfd5dc; border-radius: 6px; background: white; padding: 9px 11px; color: var(--ink); line-height: 1.6; outline: none; }
    textarea.control { min-height: 94px; resize: vertical; }
    .control:focus { border-color: var(--blue); box-shadow: 0 0 0 2px rgba(29,97,167,.12); }
    .control:disabled { border-color: #d9dde2; background: #f1f3f4; color: #697384; }
    .lock { display: inline-flex; width: 30px; height: 28px; flex: 0 0 30px; align-items: center; justify-content: center; border: 1px solid transparent; border-radius: 5px; background: transparent; color: #8a94a2; }
    .lock:hover { border-color: var(--line); background: #f4f6f7; }
    .lock.active { background: var(--green-soft); color: var(--green); }
    .tag-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
    .signal { margin-top: 18px; border-left: 3px solid #9aa4b1; padding-left: 16px; }
    .signal:first-child { margin-top: 0; }
    .signal-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 8px; }
    .signal-index { display: inline-flex; width: 24px; height: 24px; align-items: center; justify-content: center; background: var(--ink); color: white; font-size: 11px; font-weight: 800; }
    .signal-title { flex: 1; min-width: 220px; font-size: 14px; font-weight: 750; line-height: 1.45; }
    .signal-source { color: var(--muted); font-size: 11px; }
    .signal-fields { display: grid; grid-template-columns: 118px 1fr; gap: 10px; }
    .compact textarea.control { min-height: 76px; }
    .list-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
    .notice { display: none; margin: 0 0 18px; border-left: 3px solid var(--red); background: #fff1f1; padding: 10px 12px; color: var(--red); font-size: 12px; }
    .notice.visible { display: block; }
    @media (max-width: 960px) {
      .workspace { grid-template-columns: 1fr; }
      .editor { border-right: 0; }
      .preview { min-height: 720px; }
      .preview-frame { height: 680px; }
    }
    @media (max-width: 640px) {
      .topbar { height: auto; min-height: 64px; padding: 10px 12px; }
      .brand span, .status { display: none; }
      .editor-inner { padding: 20px 16px 64px; }
      .tag-grid, .list-grid, .signal-fields { grid-template-columns: 1fr; }
      .preview { padding: 8px; }
      .button span { display: none; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <div class="brand"><strong>EarlyData 编辑台</strong><span id="report-meta">载入中</span></div>
      <div class="actions">
        <span class="status" id="save-status">未保存</span>
        <button class="button" id="refresh-preview" type="button" title="刷新预览"><i data-lucide="refresh-cw" width="16" height="16"></i><span>刷新</span></button>
        <button class="button primary" id="save-review" type="button"><i data-lucide="save" width="16" height="16"></i><span>保存并预览</span></button>
      </div>
    </header>
    <main class="workspace">
      <section class="editor">
        <div class="editor-inner">
          <p class="notice" id="notice"></p>
          <section class="section" id="overview"></section>
          <section class="section" id="signals"></section>
          <section class="section" id="analysis"></section>
        </div>
      </section>
      <aside class="preview"><iframe class="preview-frame" id="preview" title="公众号文章预览" src="/preview"></iframe></aside>
    </main>
  </div>
  <script>
    const state = { brief: null, locks: new Set(), dirty: false };
    const byId = id => document.getElementById(id);

    function icon(name, size = 15) {
      const node = document.createElement('i');
      node.setAttribute('data-lucide', name);
      node.setAttribute('width', size);
      node.setAttribute('height', size);
      return node;
    }

    function markDirty() {
      state.dirty = true;
      byId('save-status').textContent = '有未保存修改';
    }

    function getAtPath(path) {
      return path.split('.').reduce((value, key) => value[key], state.brief);
    }

    function setAtPath(path, value) {
      const keys = path.split('.');
      const finalKey = keys.pop();
      const target = keys.reduce((current, key) => current[key], state.brief);
      target[finalKey] = value;
      markDirty();
    }

    function field(label, path, options = {}) {
      const root = document.createElement('div');
      root.className = 'field' + (options.compact ? ' compact' : '');
      const heading = document.createElement('div');
      heading.className = 'field-label';
      const labelNode = document.createElement('label');
      labelNode.textContent = label;
      const lock = document.createElement('button');
      lock.type = 'button';
      lock.className = 'lock';
      lock.title = '锁定字段';
      const locked = state.locks.has(path);
      lock.classList.toggle('active', locked);
      lock.appendChild(icon(locked ? 'lock-keyhole' : 'lock-keyhole-open'));
      heading.append(labelNode, lock);
      const control = options.select ? document.createElement('select') : options.single ? document.createElement('input') : document.createElement('textarea');
      control.className = 'control';
      control.disabled = locked;
      if (options.select) {
        options.select.forEach(value => {
          const option = document.createElement('option');
          option.value = value;
          option.textContent = value;
          control.appendChild(option);
        });
      }
      const raw = getAtPath(path);
      control.value = options.list ? (raw || []).join('、') : (raw || '');
      control.addEventListener('input', () => setAtPath(path, options.list ? control.value.split(/[、,，]/).map(item => item.trim()).filter(Boolean) : control.value));
      lock.addEventListener('click', () => {
        if (state.locks.has(path)) state.locks.delete(path); else state.locks.add(path);
        markDirty();
        render();
      });
      root.append(heading, control);
      return root;
    }

    function sectionHead(title, meta = '') {
      const head = document.createElement('div');
      head.className = 'section-head';
      const heading = document.createElement('h2');
      heading.textContent = title;
      const detail = document.createElement('span');
      detail.className = 'meta';
      detail.textContent = meta;
      head.append(heading, detail);
      return head;
    }

    function renderOverview() {
      const root = byId('overview');
      root.replaceChildren(sectionHead('整期判断', `${state.brief.source_count} 篇来源`));
      root.append(field('文章标题', 'title', { single: true }));
      root.append(field('本期关键信号', 'key_signal'));
      const tags = document.createElement('div');
      tags.className = 'tag-grid';
      tags.append(field('重点公司 / 机构', 'companies', { single: true, list: true }), field('重点药物 / 技术', 'technologies', { single: true, list: true }));
      root.append(tags);
    }

    function renderSignals() {
      const root = byId('signals');
      root.replaceChildren(sectionHead('重点新闻', `${state.brief.items.length} 条`));
      state.brief.items.forEach((item, index) => {
        const signal = document.createElement('article');
        signal.className = 'signal';
        const meta = document.createElement('div');
        meta.className = 'signal-meta';
        const number = document.createElement('span');
        number.className = 'signal-index';
        number.textContent = String(index + 1).padStart(2, '0');
        const title = document.createElement('span');
        title.className = 'signal-title';
        title.textContent = item.title;
        const source = document.createElement('span');
        source.className = 'signal-source';
        source.textContent = `${item.source} · ${item.date}`;
        meta.append(number, title, source);
        const fields = document.createElement('div');
        fields.className = 'signal-fields';
        fields.append(field('分类', `items.${index}.signal`, { select: ['监管', '政策', '竞争', '机会'], compact: true }));
        const copy = document.createElement('div');
        copy.append(field('事实摘要', `items.${index}.summary`, { compact: true }), field('CEO 业务影响', `items.${index}.so_what`, { compact: true }));
        fields.append(copy);
        signal.append(meta, fields);
        root.append(signal);
      });
    }

    function renderAnalysis() {
      const root = byId('analysis');
      root.replaceChildren(sectionHead('业务判断与追踪'));
      const grid = document.createElement('div');
      grid.className = 'list-grid';
      const insights = document.createElement('div');
      const followUp = document.createElement('div');
      state.brief.insights.forEach((_, index) => insights.append(field(`管理层含义 ${index + 1}`, `insights.${index}`, { compact: true })));
      state.brief.follow_up.forEach((_, index) => followUp.append(field(`后续追踪 ${index + 1}`, `follow_up.${index}`, { compact: true })));
      grid.append(insights, followUp);
      root.append(grid);
    }

    function render() {
      renderOverview();
      renderSignals();
      renderAnalysis();
      if (window.lucide) window.lucide.createIcons();
    }

    async function loadReview() {
      try {
        const response = await fetch('/api/review');
        if (!response.ok) throw new Error(`载入失败 (${response.status})`);
        const payload = await response.json();
        state.brief = payload.brief;
        state.locks = new Set(payload.locked_fields || []);
        state.dirty = false;
        byId('report-meta').textContent = `${state.brief.window_start} — ${state.brief.window_end} · ${state.brief.generation?.model || state.brief.generation?.mode || '已生成'}`;
        byId('save-status').textContent = payload.updated_at ? '已载入人工稿' : '模型原稿';
        render();
      } catch (error) {
        showError(error.message);
      }
    }

    async function saveReview() {
      const button = byId('save-review');
      button.disabled = true;
      byId('save-status').textContent = '保存中';
      try {
        const response = await fetch('/api/review', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ brief: state.brief, locked_fields: [...state.locks] })
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.error || `保存失败 (${response.status})`);
        state.dirty = false;
        byId('save-status').textContent = '已保存';
        refreshPreview();
      } catch (error) {
        showError(error.message);
        byId('save-status').textContent = '保存失败';
      } finally {
        button.disabled = false;
      }
    }

    function refreshPreview() {
      byId('preview').src = `/preview?t=${Date.now()}`;
    }

    function showError(message) {
      const notice = byId('notice');
      notice.textContent = message;
      notice.classList.add('visible');
    }

    byId('save-review').addEventListener('click', saveReview);
    byId('refresh-preview').addEventListener('click', refreshPreview);
    window.addEventListener('beforeunload', event => { if (state.dirty) { event.preventDefault(); event.returnValue = ''; } });
    loadReview();
    if (window.lucide) window.lucide.createIcons();
  </script>
</body>
</html>
"""
