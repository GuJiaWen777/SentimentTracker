from __future__ import annotations

import json
import mimetypes
import os
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


DEFAULT_COVER = "https://www.earlydata.com/assets/early-data-logo.png"
REDFOX_LIST_URL = "https://redfox.hk/story/api/gzhData/queryWorkList"
REDFOX_DETAIL_URL = "https://redfox.hk/story/api/gzhData/queryWork"
PHARMA_TYPES = {
    "ADC": ("ADC", "抗体偶联"),
    "AOC": ("AOC", "抗体寡核苷酸偶联物"),
    "双抗": ("双抗", "双特异性"),
    "单抗": ("单抗", "单克隆抗体"),
    "小分子": ("小分子",),
    "抗体发现": ("抗体发现", "抗体库", "全人抗体"),
    "大分子生物药": ("大分子", "生物药", "生物制剂"),
    "预防性疫苗": ("疫苗",),
    "CAR-T": ("CAR-T", "CART"),
    "CGT": ("CGT", "细胞治疗", "基因治疗"),
    "ASO": ("ASO", "反义寡核苷酸"),
    "核药": ("核药", "放射性药物"),
    "AI制药": ("AI制药", "AI 制药", "人工智能制药"),
    "基因疗法": ("基因疗法", "基因治疗"),
}
BIOPHARMA_TERMS = (
    "药", "医药", "生物", "biotech", "制药", "临床", "疗法", "治疗", "FDA", "NMPA",
    "EMA", "ADC", "双抗", "单抗", "抗体", "疫苗", "肿瘤", "靶点", "管线", "细胞",
    "基因", "核酸", "蛋白", "免疫", "CRO", "CDMO", "器械", "诊断", "ASCO",
)
STRATEGIC_EVENT_TERMS = (
    "合作", "授权", "并购", "交易", "License", "BD", "融资", "申报", "获批", "批准",
    "审评", "监管", "合规", "政策", "法案", "GMP", "上市", "商业化", "出海", "支付",
)
GENERIC_HEALTH_TERMS = (
    "减重", "运动", "长寿", "衰老", "记忆", "睡眠", "饮食", "辣椒", "养生", "BMI", "血脂",
)
PROMOTIONAL_TITLE_TERMS = ("会议议程", "活动预告", "大会日程", "圆满落幕", "报名参会", "直播预告", "会议通知", "征文", "招聘")
KNOWN_ORGANIZATIONS = (
    "FDA", "NMPA", "EMA", "BMS", "Pfizer", "Roche", "Merck", "AstraZeneca", "ASCO",
    "信达生物", "百奥赛图", "默沙东", "辉瑞", "阿斯利康", "罗氏", "礼来", "百时美施贵宝",
)
ENTITY_NOISE = ("来自", "前往", "查询", "更多", "转让", "持有", "唯一", "市属", "国有", "这家", "一家")
FORBIDDEN_HTML = (
    (re.compile(r"<style[\s>]", re.I), "<style> 不支持"),
    (re.compile(r"<script[\s>]", re.I), "<script> 不支持"),
    (re.compile(r"</?div[\s>]", re.I), "<div> 不支持，请使用 <section>"),
    (re.compile(r"\sclass\s*=", re.I), "class 属性不支持"),
    (re.compile(r"\sid\s*=", re.I), "id 属性不支持"),
    (re.compile(r"position\s*:\s*(fixed|absolute|sticky)", re.I), "固定定位不支持"),
    (re.compile(r"float\s*:", re.I), "float 不支持"),
    (re.compile(r"display\s*:\s*grid", re.I), "display:grid 不支持"),
)
CJK = re.compile(r"[一-鿿㐀-䶿]")


@dataclass
class Article:
    title: str
    source: str
    published_at: str
    content: str = ""
    summary: str = ""
    url: str = ""
    tags: list[str] | None = None
    entities: list[str] | None = None
    read_count: int = 0
    like_count: int = 0
    share_count: int = 0
    recommend_count: int = 0
    article_id: str = ""

    def score(self) -> float:
        return self.read_count * 0.35 + self.like_count * 8 + self.share_count * 12 + self.recommend_count * 10


def load_dotenv(root: Path) -> None:
    path = root / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def parse_day(value: str) -> date:
    return date.fromisoformat(value)


def validate_window(start: date, end: date) -> None:
    if start > end:
        raise ValueError(f"Window start {start.isoformat()} is after end {end.isoformat()}.")


def window_slug(start: date, end: date) -> str:
    return f"{start:%Y%m%d}_{end:%Y%m%d}"


def ensure_article_ids(articles: list[Article]) -> list[Article]:
    """Assign a stable, persisted article_id to every article.

    IDs already stored in articles.json are preserved, so reordering or
    removing rows no longer shifts the evidence attached to a report item.
    """
    reserved = {
        str(article.article_id).strip()
        for article in articles
        if str(article.article_id).strip()
    }
    seen: set[str] = set()
    counter = 1
    for article in articles:
        article_id = str(article.article_id or "").strip()
        if article_id and article_id not in seen:
            seen.add(article_id)
            article.article_id = article_id
            continue
        while f"a{counter:04d}" in seen or f"a{counter:04d}" in reserved:
            counter += 1
        article.article_id = f"a{counter:04d}"
        seen.add(article.article_id)
    return articles


def filter_articles_by_window(articles: list[Article], start: date, end: date) -> tuple[list[Article], int]:
    kept: list[Article] = []
    excluded = 0
    for article in articles:
        published = _coerce_date(article.published_at)
        if published is not None and start <= published <= end:
            kept.append(article)
        else:
            excluded += 1
    return kept, excluded


def write_articles(path: Path, articles: list[Article]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"articles": [asdict(article) for article in articles]}, ensure_ascii=False, indent=2), encoding="utf-8")


def read_articles(path: Path) -> list[Article]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("articles", data) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError("articles.json must contain an articles array.")
    articles: list[Article] = []
    for raw in rows:
        if not isinstance(raw, dict) or not str(raw.get("title") or "").strip():
            continue
        content = str(raw.get("content") or "")
        articles.append(
            Article(
                title=_repair_title_symbols(str(raw.get("title") or "").strip(), content),
                source=str(raw.get("source") or raw.get("account") or "来源").strip(),
                published_at=str(raw.get("published_at") or "")[:10],
                content=content,
                summary=str(raw.get("summary") or ""),
                url=str(raw.get("url") or ""),
                tags=_string_list(raw.get("tags")),
                entities=_string_list(raw.get("entities")),
                read_count=_number(raw.get("read_count")),
                like_count=_number(raw.get("like_count")),
                share_count=_number(raw.get("share_count")),
                recommend_count=_number(raw.get("recommend_count")),
                article_id=str(raw.get("article_id") or "").strip(),
            )
        )
    return articles


def read_brief(path: Path) -> dict[str, Any]:
    return validate_brief_data(json.loads(path.read_text(encoding="utf-8")))


def validate_brief_data(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("brief.json must contain a JSON object.")
    required = {
        "title",
        "window_start",
        "window_end",
        "source_count",
        "key_signal",
        "dashboard",
        "companies",
        "technologies",
        "items",
        "insights",
        "follow_up",
        "sources",
    }
    missing = sorted(required - set(data))
    if missing:
        raise ValueError("brief.json is missing required fields: " + ", ".join(missing))
    if not isinstance(data.get("items"), list):
        raise ValueError("brief.json field 'items' must be an array.")
    if "alternates" in data and not isinstance(data["alternates"], list):
        raise ValueError("brief.json field 'alternates' must be an array.")
    return data


def fetch_redfox(start: date, end: date, accounts: list[str], *, include_content: bool = True) -> list[Article]:
    validate_window(start, end)
    api_key = os.environ.get("REDFOX_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("REDFOX_API_KEY is missing. Configure it in .env.")
    if not accounts:
        raise ValueError("At least one --account is required for RedFox fetch.")
    headers = {"REDFOX_API_KEY": api_key, "Content-Type": "application/json"}
    articles: list[Article] = []
    seen: set[str] = set()
    for account in accounts:
        for page in range(50):
            payload = {
                "source": "earlydata-weekly-publisher",
                "accountName": account,
                "uid": "",
                "offset": page * 20,
                "sortType": "default",
                "publishTimeStart": f"{start} 00:00:00",
                "publishTimeEnd": f"{end} 23:59:59",
            }
            response = requests.post(REDFOX_LIST_URL, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            body = response.json()
            if body.get("code") not in (200, 2000):
                raise RuntimeError(f"RedFox error {body.get('code')}: {body.get('msg') or body.get('message')}")
            data = body.get("data") or {}
            batch = data if isinstance(data, list) else data.get("list") or data.get("articles") or data.get("records") or []
            if not batch:
                break
            for raw in batch:
                article = _redfox_article(raw, account)
                key = str(raw.get("workUuid") or article.url or article.title)
                if key in seen:
                    continue
                seen.add(key)
                if include_content and raw.get("workUuid"):
                    article.content = _redfox_content(str(raw["workUuid"]), headers)
                articles.append(article)
            if len(batch) < 20:
                break
    in_window = [article for article in articles if _within_window(article.published_at, start, end)]
    return sorted(in_window, key=lambda item: item.published_at, reverse=True)


def ingest_pb_xlsx(path: Path, start: date, end: date) -> list[Article]:
    validate_window(start, end)
    from openpyxl import load_workbook

    book = load_workbook(path, read_only=True, data_only=True)
    sheet = book.active
    articles: list[Article] = []
    for row in sheet.iter_rows(min_row=2, values_only=True):
        title = str(_cell(row, 3) or "").strip()
        content = str(_cell(row, 17) or "").strip()
        if not title and not content:
            continue
        published = _coerce_date(_cell(row, 7))
        if not published or not start <= published <= end:
            continue
        tags = [str(_cell(row, index)).strip() for index in (8, 9, 10, 11) if _cell(row, index)]
        articles.append(
            Article(
                title=_repair_title_symbols(title or content[:30], content),
                source=str(_cell(row, 5) or "来源").strip(),
                published_at=published.isoformat(),
                content=content,
                url=str(_cell(row, 12) or "").strip(),
                tags=tags,
                read_count=_number(_cell(row, 13)),
                like_count=_number(_cell(row, 14)),
                share_count=_number(_cell(row, 15)),
                recommend_count=_number(_cell(row, 16)),
            )
        )
    book.close()
    return articles


def build_brief(articles: list[Article], start: date, end: date, title: str | None = None) -> dict[str, Any]:
    validate_window(start, end)
    if not articles:
        raise ValueError("No articles available for the selected window.")
    ensure_article_ids(articles)
    pool = _ranked_pool(articles)
    selected = pool[:6]
    alternates = pool[6:12]
    rows = [_brief_item(article) for article in selected]
    alternate_rows = [_brief_item(article) for article in alternates]
    companies = _company_tags(selected)
    technologies = _technology_tags(selected)
    risk_count = sum(1 for article in selected if _signal_style(article)[0] == "监管")
    ai_count = sum(1 for article in selected if "AI" in _article_text(article) or "人工智能" in _article_text(article))
    deal_count = sum(1 for article in selected if any(word in _article_text(article) for word in ("BD", "合作", "授权", "并购", "交易", "License")))
    summary = _compact("；".join(item["summary"] for item in rows[:3]), 210)
    return {
        "title": title or f"AI CEO 生物医药舆情周报 {start:%Y.%m.%d}-{end:%m.%d}",
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "source_count": len(articles),
        "key_signal": summary,
        "dashboard": [
            ["监管动向", f"{risk_count} 条", "#A32D2D" if risk_count else "#1C1F26"],
            ["AI 落地", f"{ai_count} 条", "#3B6D11" if ai_count else "#1C1F26"],
            ["市场并购", f"{deal_count} 条", "#2B72B8" if deal_count else "#1C1F26"],
            ["本周信号数", f"{len(selected)} 条", "#1C1F26"],
        ],
        "companies": companies,
        "technologies": technologies,
        "items": rows,
        "alternates": alternate_rows,
        "insights": [_so_what(article) for article in selected[:3]],
        "follow_up": [article.title for article in selected[3:6]],
        "sources": list(dict.fromkeys(article.source for article in selected if article.source)),
        "generation": {"mode": "rules"},
    }


def _brief_item(article: Article) -> dict[str, Any]:
    label, background, color = _signal_style(article)
    return {
        "article_id": article.article_id,
        "title": article.title,
        "source": article.source,
        "date": article.published_at,
        "summary": _summary(article),
        "signal": label,
        "background": background,
        "color": color,
        "so_what": _so_what(article),
        "url": article.url,
        "score": None,
        "category": "",
        "reason": "规则模式：按启发式重要性排序",
    }


def generate_brief(
    articles: list[Article],
    start: date,
    end: date,
    title: str | None = None,
    *,
    generator: str = "llm",
    llm_client: Any | None = None,
    llm_backend: str | None = None,
    ranking_cache_path: Path | None = None,
    history_db: Path | None = None,
) -> dict[str, Any]:
    mode = generator.strip().lower()
    if mode not in {"llm", "rules"}:
        raise ValueError("generator must be 'llm' or 'rules'.")
    validate_window(start, end)
    articles = ensure_article_ids(articles)
    articles, excluded = filter_articles_by_window(articles, start, end)
    if not articles:
        raise ValueError(f"No articles available in window {start.isoformat()}..{end.isoformat()}.")
    history_context = None
    if history_db is not None:
        from .signal_history import trend_context_for_window

        history_context = trend_context_for_window(history_db, start)
    if mode == "rules":
        brief = build_brief(articles, start, end, title)
    else:
        from .semantic_generation import build_semantic_brief

        brief = build_semantic_brief(
            articles,
            start,
            end,
            title,
            client=llm_client,
            backend=llm_backend,
            ranking_cache_path=ranking_cache_path,
            history_context=history_context,
        )
    brief["generation"]["excluded_outside_window"] = excluded
    brief["generation"]["history_weeks"] = int((history_context or {}).get("window_count") or 0)
    return brief


def write_brief_outputs(brief: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    brief_path = output_dir / "brief.json"
    public_brief = {key: value for key, value in brief.items() if not key.startswith("_")}
    brief_path.write_text(json.dumps(public_brief, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs = {"brief": brief_path, **write_rendered_outputs(brief, output_dir)}
    ranking = brief.get("_ranking")
    if isinstance(ranking, dict):
        ranking_path = output_dir / "ranking.json"
        ranking_path.write_text(json.dumps(ranking, ensure_ascii=False, indent=2), encoding="utf-8")
        outputs["ranking"] = ranking_path
    return outputs


def write_rendered_outputs(brief: dict[str, Any], output_dir: Path) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    md_path = output_dir / "wechat_article.md"
    html_path = output_dir / "wechat_article_img.html"
    markdown = render_markdown(brief)
    html = render_html(brief)
    validate_html(html)
    md_path.write_text(markdown, encoding="utf-8")
    html_path.write_text(html, encoding="utf-8")
    return {"markdown": md_path, "html": html_path}


def render_markdown(brief: dict[str, Any]) -> str:
    lines = [
        "---",
        f'title: "{brief["title"]}"',
        "author: " + os.environ.get("WECHAT_AUTHOR", "EARLY DATA"),
        f"cover: {DEFAULT_COVER}",
        "---",
        "",
        f"# {brief['title']}",
        "",
        f"{brief['window_start']} — {brief['window_end']}",
        "",
        "## 本周数据面板",
        "",
    ]
    for label, value, _color in brief["dashboard"]:
        lines.append(f"- **{label}**：{value}")
    lines.extend(["", "## 本期关键信号", "", brief["key_signal"], ""])
    if brief["companies"]:
        lines.extend(["## 本期重点公司 / 机构", "", "、".join(brief["companies"]), ""])
    if brief["technologies"]:
        lines.extend(["## 本期重点药物 / 技术类型", "", "、".join(brief["technologies"]), ""])
    lines.extend(["## 本周最值得 CEO 关注", ""])
    for item in brief["items"]:
        lines.extend(
            [
                f"### {item['title']}",
                "",
                f"- 来源：{item['source']} · {item['date']}",
                f"- 分类：{item['signal']}",
                "",
                item["summary"],
                "",
                f"**业务影响**：{item['so_what']}",
                "",
            ]
        )
    lines.extend(["## 本周对你的业务意味着什么", ""])
    lines.extend(f"- {value}" for value in brief["insights"])
    lines.extend(["", "## 后续追踪", ""])
    lines.extend(f"- {value}" for value in brief["follow_up"])
    source_text = " · ".join(brief["sources"])
    lines.extend(["", "## 数据来源", "", f"{source_text}；本期纳入 {brief['source_count']} 篇相关文章。", ""])
    return "\n".join(lines)


def render_html(brief: dict[str, Any]) -> str:
    dashboard = "".join(_dashboard_card(*card) for card in brief["dashboard"])
    tags = _combined_tag_block(brief["companies"], brief["technologies"])
    news = "".join(_news_item(item) for item in brief["items"])
    insights = "".join(_leaf_line("→ " + value, margin="0 0 6px") for value in brief["insights"])
    follow_up = "".join(_leaf_line("• " + value, margin="0 0 4px") for value in brief["follow_up"])
    start, end = brief["window_start"], brief["window_end"]
    source_text = " · ".join(brief["sources"])
    return f'''<section style="max-width:660px;margin:0 auto;background:#FFFFFF;color:#4A5264;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB','Microsoft YaHei',Arial,sans-serif;line-height:1.8;overflow-x:hidden;">
<section style="padding:32px 18px 24px;border-bottom:1px solid #E4E8ED;box-sizing:border-box;"><p style="margin:0 0 8px;font-size:11px;line-height:1.5;color:#8A93A2;letter-spacing:0.1em;"><span leaf="">EARLY DATA · 生物医药 CEO 舆情周报</span></p><h1 style="margin:0 0 8px;font-size:24px;line-height:1.35;color:#1C1F26;font-weight:700;"><span leaf="">{_html_text(brief['title'])}</span></h1><p style="margin:0;font-size:13px;line-height:1.7;color:#8A93A2;"><span leaf="">{_html_text(start)} — {_html_text(end)} · 精选 5 分钟必读内容</span></p></section>
<section style="padding:18px 18px;"><section style="display:flex;flex-wrap:wrap;margin:0 -5px;">{dashboard}</section></section>
<section style="padding:8px 18px 18px;"><section style="border:1px solid #E4E8ED;border-radius:6px;background:#F8F9FA;padding:12px 14px;"><p style="margin:0;font-size:13px;line-height:1.75;color:#4A5264;"><span style="color:#0B65C2;font-weight:700;"><span leaf="">本期关键信号：</span></span><span leaf="">{_html_text(brief['key_signal'])}</span></p></section></section>
{tags}
<section style="padding:22px 18px 10px;"><p style="margin:0;font-size:11px;line-height:1.6;color:#8A93A2;letter-spacing:0.08em;"><span leaf="">本周最值得 CEO 关注</span></p></section>{news}
<section style="padding:0 18px;"><section style="height:1px;background:#E4E8ED;margin:20px 0;"><span leaf=""><br></span></section></section>
<section style="padding:22px 18px 10px;"><p style="margin:0;font-size:11px;line-height:1.6;color:#8A93A2;letter-spacing:0.08em;"><span leaf="">本周对你的业务意味着什么</span></p></section>
<section style="padding:16px 18px;"><section style="background:#F8F9FA;border:1px solid #E4E8ED;border-radius:6px;padding:16px 18px;"><p style="margin:0 0 10px;font-size:12px;line-height:1.5;color:#8A93A2;letter-spacing:0.08em;"><span leaf="">EARLY DATA 视角</span></p>{insights}</section></section>
<section style="padding:10px 18px 18px;"><section style="background:#F8F9FA;border:1px solid #E4E8ED;border-radius:6px;padding:14px 16px;"><p style="margin:0 0 8px;font-size:12px;line-height:1.5;color:#8A93A2;"><span leaf="">后续追踪</span></p>{follow_up}</section></section>
<section style="padding:18px 18px 32px;border-top:1px solid #E4E8ED;"><p style="margin:0 0 6px;font-size:11px;line-height:1.7;color:#8A93A2;"><span leaf="">Early Data · Early AI · 每周发布</span></p><p style="margin:0;font-size:11px;line-height:1.7;color:#8A93A2;"><span leaf="">数据来源：{_html_text(source_text)}；本期纳入 {brief['source_count']} 篇相关文章。</span></p></section>
</section>'''


def validate_html(html: str) -> None:
    for pattern, message in FORBIDDEN_HTML:
        if pattern.search(html):
            raise ValueError(f"HTML validation failed: {message}")
    checker = _LeafChecker()
    checker.feed(html)
    if CJK.search(html) and not checker.leaf_count:
        raise ValueError('HTML validation failed: missing <span leaf="">.')
    if checker.unwrapped:
        raise ValueError("HTML validation failed: text outside leaf span: " + "；".join(checker.unwrapped[:3]))


def publish_draft(html_path: Path, *, title: str, cover: str, author: str, digest: str = "", source_url: str = "") -> str:
    html = html_path.read_text(encoding="utf-8")
    validate_html(html)
    app_id, secret = os.environ.get("WECHAT_APP_ID", ""), os.environ.get("WECHAT_APP_SECRET", "")
    if not app_id or not secret:
        raise RuntimeError("WECHAT_APP_ID and WECHAT_APP_SECRET are required.")
    token_response = requests.get("https://api.weixin.qq.com/cgi-bin/token", params={"grant_type": "client_credential", "appid": app_id, "secret": secret}, timeout=20).json()
    token = token_response.get("access_token")
    if not token:
        raise RuntimeError(f"WeChat token failed: {token_response.get('errmsg', 'unknown error')}")
    cover_media_id = _upload_image(cover, token, permanent=True, base_dir=html_path.parent)[0]
    html = re.sub(
        r'<img[^>]+src=["\']([^"\']+)["\']',
        lambda match: match.group(0).replace(
            match.group(1),
            _upload_image(match.group(1), token, permanent=False, base_dir=html_path.parent, restrict_to_base=True)[1],
        ),
        html,
    )
    payload = {"articles": [{"title": title, "author": author, "digest": digest, "content": html, "content_source_url": source_url, "thumb_media_id": cover_media_id, "need_open_comment": 0, "only_fans_can_comment": 0}]}
    response = requests.post("https://api.weixin.qq.com/cgi-bin/draft/add", params={"access_token": token}, json=payload, timeout=30).json()
    media_id = response.get("media_id")
    if not media_id:
        raise RuntimeError(f"WeChat draft failed: {response.get('errmsg', response)}")
    return str(media_id)


def _redfox_article(raw: dict[str, Any], account: str) -> Article:
    value = raw.get("publishTime") or raw.get("publicTime") or raw.get("publishDate") or ""
    published = _coerce_date(value)
    return Article(
        title=str(raw.get("title") or raw.get("name") or "").strip(),
        source=account,
        published_at=published.isoformat() if published else str(value)[:10],
        url=str(raw.get("workUrl") or raw.get("url") or ""),
        read_count=_number(raw.get("readCount") or raw.get("clicksCount")),
        like_count=_number(raw.get("likeCount") or raw.get("likes")),
        share_count=_number(raw.get("shareCount") or raw.get("shares")),
        recommend_count=_number(raw.get("collectCount") or raw.get("recommendCount")),
    )


def _redfox_content(work_uuid: str, headers: dict[str, str]) -> str:
    response = requests.post(REDFOX_DETAIL_URL, json={"source": "earlydata-weekly-publisher", "workUuid": work_uuid}, headers=headers, timeout=30).json()
    data = response.get("data") or {}
    return str(data.get("content") or "") if isinstance(data, dict) else ""


def _upload_image(
    source: str,
    token: str,
    *,
    permanent: bool,
    base_dir: Path,
    restrict_to_base: bool = False,
) -> tuple[str, str]:
    parsed = urlparse(source)
    if parsed.scheme in {"http", "https"}:
        response = requests.get(source, timeout=30)
        response.raise_for_status()
        content, filename = response.content, Path(parsed.path).name or "image.png"
    elif parsed.scheme:
        raise RuntimeError(f"Unsupported image reference: {source}")
    else:
        path = _local_image_path(source, base_dir, restrict_to_base=restrict_to_base)
        content, filename = path.read_bytes(), path.name
    content_type = mimetypes.guess_type(filename)[0] or "image/png"
    if permanent:
        url, params = "https://api.weixin.qq.com/cgi-bin/material/add_material", {"access_token": token, "type": "image"}
    else:
        url, params = "https://api.weixin.qq.com/cgi-bin/media/uploadimg", {"access_token": token}
    response = requests.post(url, params=params, files={"media": (filename, content, content_type)}, timeout=30).json()
    media_id, image_url = str(response.get("media_id") or ""), str(response.get("url") or "")
    if permanent and not media_id:
        raise RuntimeError(f"Cover upload failed: {response.get('errmsg', response)}")
    if not permanent and not image_url:
        raise RuntimeError(f"Article image upload failed: {response.get('errmsg', response)}")
    return media_id, image_url


def _local_image_path(source: str, base_dir: Path, *, restrict_to_base: bool) -> Path:
    path = Path(source)
    if not path.is_absolute():
        path = base_dir / path
    resolved = path.resolve()
    if restrict_to_base and not resolved.is_relative_to(base_dir.resolve()):
        raise RuntimeError(f"Article image path escapes the report directory: {source}")
    if not resolved.is_file():
        raise RuntimeError(f"Article image not found: {source}")
    return resolved


def _dashboard_card(label: str, value: str, color: str) -> str:
    return f'<section style="width:50%;box-sizing:border-box;padding:5px;"><section style="background:#F8F9FA;border:1px solid #E4E8ED;border-radius:6px;padding:12px 14px;"><p style="margin:0 0 5px;font-size:11px;line-height:1.5;color:#8A93A2;"><span leaf="">{escape(label)}</span></p><p style="margin:0;font-size:15px;line-height:1.5;color:{color};font-weight:700;"><span leaf="">{escape(value)}</span></p></section></section>'


def _combined_tag_block(companies: list[str], technologies: list[str]) -> str:
    groups = []
    if companies:
        groups.append(("本期重点公司 / 机构", companies, "#EEF5FC", "#2B72B8"))
    if technologies:
        groups.append(("本期重点药物 / 技术类型", technologies, "#EDF6E3", "#3B6D11"))
    if not groups:
        return ""
    content = ""
    for index, (label, tags, background, color) in enumerate(groups):
        margin = "0" if index == len(groups) - 1 else "0 0 10px"
        chips = "".join(
            f'<span style="display:inline-block;margin:0 6px 6px 0;background:{background};color:{color};border-radius:4px;padding:3px 8px;font-size:12px;font-weight:700;"><span leaf="">{_html_text(tag)}</span></span>'
            for tag in tags
        )
        content += (
            f'<p style="margin:0 0 8px;font-size:12px;line-height:1.5;color:#8A93A2;"><span leaf="">{_html_text(label)}</span></p>'
            f'<p style="margin:{margin};line-height:2;">{chips}</p>'
        )
    return f'<section style="padding:0 18px 18px;"><section style="background:#F8F9FA;border:1px solid #E4E8ED;border-radius:6px;padding:12px 14px;">{content}</section></section>'


def _news_item(item: dict[str, Any]) -> str:
    source = f"{item['source']} · {item['date'][5:].replace('-', '月', 1)}日" if len(item["date"]) == 10 else item["source"]
    url = str(item.get("url") or "").strip()
    source_link = ""
    if urlparse(url).scheme in {"http", "https"}:
        source_link = f' · <a href="{escape(url, quote=True)}" style="color:#0B65C2;text-decoration:none;"><span leaf="">查看来源</span></a>'
    return f'<section style="padding:14px 18px;border-top:1px solid #E4E8ED;"><p style="margin:0 0 8px;"><span style="display:inline-block;background:{item["background"]};color:{item["color"]};border-radius:4px;padding:3px 8px;font-size:12px;font-weight:700;"><span leaf="">{_html_text(item["signal"])}</span></span></p><h3 style="margin:0 0 6px;font-size:15px;line-height:1.6;color:#1C1F26;font-weight:700;"><span leaf="">{_html_text(item["title"])}</span></h3><p style="margin:0 0 6px;font-size:13px;line-height:1.8;color:#8A93A2;"><span leaf="">{_html_text(item["summary"])}</span></p><p style="margin:0 0 6px;font-size:13px;line-height:1.7;color:#0B65C2;font-weight:700;"><span leaf="">→ {_html_text(item["signal"])}：{_html_text(item["so_what"])}</span></p><p style="margin:0;font-size:11px;line-height:1.6;color:#8A93A2;text-align:right;"><span leaf="">{_html_text(source)}</span>{source_link}</p></section>'


def _leaf_line(value: str, *, margin: str) -> str:
    return f'<p style="margin:{margin};font-size:13px;line-height:1.8;color:#4A5264;"><span leaf="">{_html_text(value)}</span></p>'


def _signal_style(article: Article) -> tuple[str, str, str]:
    headline = " ".join([article.title, " ".join(article.tags or [])])
    text = _article_text(article)
    if any(word in headline for word in ("合作", "授权", "并购", "交易", "竞品", "商业化", "BD", "融资")):
        return "竞争", "#FEF3E2", "#854F0B"
    if any(word in headline for word in ("政策", "法案", "医保", "支付", "准入")):
        return "政策", "#EEF5FC", "#2B72B8"
    if any(word in headline for word in ("监管", "合规", "审评", "FDA", "警告信", "GMP", "获批", "批准", "申报")):
        return "监管", "#FCEAEA", "#A32D2D"
    if "出海" in headline:
        return "竞争", "#FEF3E2", "#854F0B"
    if "AI" in headline or "人工智能" in headline:
        return "机会", "#EDF6E3", "#3B6D11"
    if any(word in text for word in ("监管", "合规", "审评", "FDA", "警告信", "GMP")):
        return "监管", "#FCEAEA", "#A32D2D"
    if any(word in text for word in ("政策", "法案", "医保", "支付", "准入")):
        return "政策", "#EEF5FC", "#2B72B8"
    if any(word in text for word in ("合作", "授权", "并购", "交易", "竞品", "商业化")):
        return "竞争", "#FEF3E2", "#854F0B"
    return "机会", "#EDF6E3", "#3B6D11"


def _so_what(article: Article) -> str:
    text = _article_text(article)
    if any(word in text for word in ("合作", "授权", "并购", "交易", "License", "BD")):
        return "复核交易结构、权益保留和海外执行能力。"
    if any(word in text for word in ("监管", "合规", "审评", "FDA", "GMP")):
        return "提前排查申报材料、数据完整性和质量体系缺口。"
    if "AI" in text or "人工智能" in text:
        return "选择可量化改善效率或质量的场景先验证。"
    return "将该信号纳入本周业务决策复核清单。"


def _summary(article: Article) -> str:
    text = _strip_html(article.summary or article.content or article.title)
    sentences = re.split(r"(?<=[。！？；])", text)
    while sentences and any(marker in sentences[0][:80] for marker in ("声明", "免责声明", "本文不构成", "撰稿")):
        sentences.pop(0)
    return _compact("".join(sentences).strip() or article.title, 100)


def _html_text(value: object) -> str:
    text = str(value)
    quote_is_open = True
    converted: list[str] = []
    for character in text:
        if character == '"':
            converted.append("“" if quote_is_open else "”")
            quote_is_open = not quote_is_open
        elif character == "'":
            converted.append("’")
        else:
            converted.append(character)
    return escape("".join(converted))


def _company_tags(articles: list[Article]) -> list[str]:
    found: list[str] = []
    for article in articles:
        found.extend(article.entities or [])
        title_and_tags = " ".join([article.title, " ".join(article.tags or [])])
        found.extend(name for name in KNOWN_ORGANIZATIONS if re.search(rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])", title_and_tags, re.I))
        found.extend(_title_organizations(title_and_tags))
    return _unique(_clean_entity(tag) for tag in found if _is_entity_tag(tag))[:5]


def _technology_tags(articles: list[Article]) -> list[str]:
    counts: Counter[str] = Counter()
    for article in articles:
        text = " ".join([article.title, " ".join(article.tags or [])])
        for label, keywords in PHARMA_TYPES.items():
            if any(keyword in text for keyword in keywords):
                counts[label] += 1
    return [label for label, _count in counts.most_common(5)]


def _ranked_pool(articles: list[Article]) -> list[Article]:
    ranked = sorted(articles, key=lambda item: (_biopharma_relevance(item), item.score(), item.published_at), reverse=True)
    unique_ranked = _dedupe_titles(ranked)
    editorial = [article for article in unique_ranked if not _is_promotional(article)]
    pool = editorial or unique_ranked
    strategic = [article for article in pool if _biopharma_relevance(article) >= 10]
    relevant = [article for article in pool if _biopharma_relevance(article) >= 3]
    return strategic or relevant or pool


def _biopharma_relevance(article: Article) -> int:
    title_and_tags = " ".join([article.title, " ".join(article.tags or [])])
    body = " ".join([article.summary, article.content])
    strategic = sum(8 for term in STRATEGIC_EVENT_TERMS if term.lower() in title_and_tags.lower())
    strategic += min(6, sum(1 for term in STRATEGIC_EVENT_TERMS if term.lower() in body.lower()))
    biopharma = sum(3 for term in BIOPHARMA_TERMS if term.lower() in title_and_tags.lower())
    biopharma += min(6, sum(1 for term in BIOPHARMA_TERMS if term.lower() in body.lower()))
    named_company = sum(4 for name in KNOWN_ORGANIZATIONS if name.lower() in title_and_tags.lower())
    generic_penalty = 12 if any(term.lower() in title_and_tags.lower() for term in GENERIC_HEALTH_TERMS) and strategic < 8 else 0
    return strategic + biopharma + named_company - generic_penalty


def _is_promotional(article: Article) -> bool:
    return any(term in article.title for term in PROMOTIONAL_TITLE_TERMS)


def _title_organizations(text: str) -> list[str]:
    matches = re.findall(r"[\u4e00-\u9fffA-Za-z0-9·]{2,18}(?:生物医药|生物科技|生物|医药|制药|药业|药企|公司|集团|研究院|大学|医院)", text)
    return [_clean_entity(match) for match in matches]


def _clean_entity(value: str) -> str:
    value = value.strip()
    for marker in ENTITY_NOISE:
        if marker in value:
            value = value.rsplit(marker, 1)[-1]
    for connector in ("与", "和", "及"):
        if connector in value:
            value = value.rsplit(connector, 1)[-1]
    return value.strip(" ，。；：、()（）")[-16:]


def _is_entity_tag(value: str) -> bool:
    value = _clean_entity(value)
    if not 2 <= len(value) <= 24 or value[0].isdigit() or any(noise in value for noise in ENTITY_NOISE):
        return False
    return bool(re.search(r"[A-Za-z]|[\u4e00-\u9fff]", value))


def _dedupe_titles(articles: list[Article]) -> list[Article]:
    result: list[Article] = []
    seen: set[str] = set()
    for article in articles:
        key = re.sub(r"[^\w\u4e00-\u9fff]", "", article.title).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(article)
    return result


def _article_text(article: Article) -> str:
    return " ".join([article.title, article.summary, article.content, " ".join(article.tags or []), " ".join(article.entities or [])])


def _strip_html(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()


def _compact(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    position = max(text.rfind(mark, 0, limit + 1) for mark in "。！？；")
    return text[: position + 1] if position >= limit // 2 else text[:limit].rstrip() + "…"


def _repair_title_symbols(title: str, content: str) -> str:
    if "?" not in title:
        return title
    repaired = title
    for _index in range(title.count("?")):
        position = repaired.find("?")
        left = repaired[:position]
        token_match = re.search(r"[\u4e00-\u9fffA-Za-z0-9]{2,16}$", left)
        token = token_match.group(0) if token_match else ""
        replacement = "？"
        for symbol in ("®", "™"):
            if any(token[-width:] + symbol in content for width in range(2, len(token) + 1)):
                replacement = symbol
                break
        repaired = repaired[:position] + replacement + repaired[position + 1 :]
    return repaired


def _coerce_date(value: Any) -> date | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)):
        seconds = float(value) / 1000 if float(value) > 1e11 else float(value)
        try:
            return datetime.fromtimestamp(seconds).date()
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _within_window(published_at: str, start: date, end: date) -> bool:
    published = _coerce_date(published_at)
    return published is not None and start <= published <= end


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _number(value: Any) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _cell(row: tuple[Any, ...], index: int) -> Any:
    return row[index - 1] if len(row) >= index else None


def _unique(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


class _LeafChecker(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, bool]] = []
        self.leaf_depth = 0
        self.leaf_count = 0
        self.unwrapped: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        leaf = tag == "span" and any(name == "leaf" for name, _ in attrs)
        self.stack.append((tag, leaf))
        if leaf:
            self.leaf_depth += 1
            self.leaf_count += 1

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                for _, leaf in self.stack[index:]:
                    if leaf:
                        self.leaf_depth -= 1
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if data.strip() and CJK.search(data) and self.leaf_depth == 0:
            self.unwrapped.append(data.strip()[:40])
