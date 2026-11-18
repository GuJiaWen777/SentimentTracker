from __future__ import annotations

import os
import re
from html import escape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse


DEFAULT_COVER = "https://www.earlydata.com/assets/early-data-logo.png"
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
CJK = re.compile(r"[一-鿿]")


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
    dashboard = "".join(dashboard_card(*card) for card in brief["dashboard"])
    tags = combined_tag_block(brief["companies"], brief["technologies"])
    news = "".join(news_item(item) for item in brief["items"])
    insights = "".join(leaf_line("→ " + value, margin="0 0 6px") for value in brief["insights"])
    follow_up = "".join(leaf_line("• " + value, margin="0 0 4px") for value in brief["follow_up"])
    start, end = brief["window_start"], brief["window_end"]
    source_text = " · ".join(brief["sources"])
    return f'''<section style="max-width:660px;margin:0 auto;background:#FFFFFF;color:#4A5264;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB','Microsoft YaHei',Arial,sans-serif;line-height:1.8;overflow-x:hidden;">
<section style="padding:32px 18px 24px;border-bottom:1px solid #E4E8ED;box-sizing:border-box;"><p style="margin:0 0 8px;font-size:11px;line-height:1.5;color:#8A93A2;letter-spacing:0.1em;"><span leaf="">EARLY DATA · 生物医药 CEO 舆情周报</span></p><h1 style="margin:0 0 8px;font-size:24px;line-height:1.35;color:#1C1F26;font-weight:700;"><span leaf="">{html_text(brief['title'])}</span></h1><p style="margin:0;font-size:13px;line-height:1.7;color:#8A93A2;"><span leaf="">{html_text(start)} — {html_text(end)} · 精选 5 分钟必读内容</span></p></section>
<section style="padding:18px 18px;"><section style="display:flex;flex-wrap:wrap;margin:0 -5px;">{dashboard}</section></section>
<section style="padding:8px 18px 18px;"><section style="border:1px solid #E4E8ED;border-radius:6px;background:#F8F9FA;padding:12px 14px;"><p style="margin:0;font-size:13px;line-height:1.75;color:#4A5264;"><span style="color:#0B65C2;font-weight:700;"><span leaf="">本期关键信号：</span></span><span leaf="">{html_text(brief['key_signal'])}</span></p></section></section>
{tags}
<section style="padding:22px 18px 10px;"><p style="margin:0;font-size:11px;line-height:1.6;color:#8A93A2;letter-spacing:0.08em;"><span leaf="">本周最值得 CEO 关注</span></p></section>{news}
<section style="padding:0 18px;"><section style="height:1px;background:#E4E8ED;margin:20px 0;"><span leaf=""><br></span></section></section>
<section style="padding:22px 18px 10px;"><p style="margin:0;font-size:11px;line-height:1.6;color:#8A93A2;letter-spacing:0.08em;"><span leaf="">本周对你的业务意味着什么</span></p></section>
<section style="padding:16px 18px;"><section style="background:#F8F9FA;border:1px solid #E4E8ED;border-radius:6px;padding:16px 18px;"><p style="margin:0 0 10px;font-size:12px;line-height:1.5;color:#8A93A2;letter-spacing:0.08em;"><span leaf="">EARLY DATA 视角</span></p>{insights}</section></section>
<section style="padding:10px 18px 18px;"><section style="background:#F8F9FA;border:1px solid #E4E8ED;border-radius:6px;padding:14px 16px;"><p style="margin:0 0 8px;font-size:12px;line-height:1.5;color:#8A93A2;"><span leaf="">后续追踪</span></p>{follow_up}</section></section>
<section style="padding:18px 18px 32px;border-top:1px solid #E4E8ED;"><p style="margin:0 0 6px;font-size:11px;line-height:1.7;color:#8A93A2;"><span leaf="">Early Data · Early AI · 每周发布</span></p><p style="margin:0;font-size:11px;line-height:1.7;color:#8A93A2;"><span leaf="">数据来源：{html_text(source_text)}；本期纳入 {brief['source_count']} 篇相关文章。</span></p></section>
</section>'''


def validate_html(html: str) -> None:
    for pattern, message in FORBIDDEN_HTML:
        if pattern.search(html):
            raise ValueError(f"HTML validation failed: {message}")
    checker = LeafChecker()
    checker.feed(html)
    if CJK.search(html) and not checker.leaf_count:
        raise ValueError('HTML validation failed: missing <span leaf="">.')
    if checker.unwrapped:
        raise ValueError("HTML validation failed: text outside leaf span: " + "；".join(checker.unwrapped[:3]))


def dashboard_card(label: str, value: str, color: str) -> str:
    return (
        '<section style="width:50%;box-sizing:border-box;padding:5px;">'
        '<section style="background:#F8F9FA;border:1px solid #E4E8ED;border-radius:6px;padding:12px 14px;">'
        f'<p style="margin:0 0 5px;font-size:11px;line-height:1.5;color:#8A93A2;"><span leaf="">{escape(label)}</span></p>'
        f'<p style="margin:0;font-size:15px;line-height:1.5;color:{color};font-weight:700;"><span leaf="">{escape(value)}</span></p>'
        "</section></section>"
    )


def combined_tag_block(companies: list[str], technologies: list[str]) -> str:
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
            f'<span style="display:inline-block;margin:0 6px 6px 0;background:{background};color:{color};border-radius:4px;padding:3px 8px;font-size:12px;font-weight:700;"><span leaf="">{html_text(tag)}</span></span>'
            for tag in tags
        )
        content += (
            f'<p style="margin:0 0 8px;font-size:12px;line-height:1.5;color:#8A93A2;"><span leaf="">{html_text(label)}</span></p>'
            f'<p style="margin:{margin};line-height:2;">{chips}</p>'
        )
    return f'<section style="padding:0 18px 18px;"><section style="background:#F8F9FA;border:1px solid #E4E8ED;border-radius:6px;padding:12px 14px;">{content}</section></section>'


def news_item(item: dict[str, Any]) -> str:
    source = f"{item['source']} · {item['date'][5:].replace('-', '月', 1)}日" if len(item["date"]) == 10 else item["source"]
    url = str(item.get("url") or "").strip()
    source_link = ""
    if urlparse(url).scheme in {"http", "https"}:
        source_link = f' · <a href="{escape(url, quote=True)}" style="color:#0B65C2;text-decoration:none;"><span leaf="">查看来源</span></a>'
    return (
        f'<section style="padding:14px 18px;border-top:1px solid #E4E8ED;">'
        f'<p style="margin:0 0 8px;"><span style="display:inline-block;background:{item["background"]};color:{item["color"]};border-radius:4px;padding:3px 8px;font-size:12px;font-weight:700;"><span leaf="">{html_text(item["signal"])}</span></span></p>'
        f'<h3 style="margin:0 0 6px;font-size:15px;line-height:1.6;color:#1C1F26;font-weight:700;"><span leaf="">{html_text(item["title"])}</span></h3>'
        f'<p style="margin:0 0 6px;font-size:13px;line-height:1.8;color:#8A93A2;"><span leaf="">{html_text(item["summary"])}</span></p>'
        f'<p style="margin:0 0 6px;font-size:13px;line-height:1.7;color:#0B65C2;font-weight:700;"><span leaf="">→ {html_text(item["signal"])}：{html_text(item["so_what"])}</span></p>'
        f'<p style="margin:0;font-size:11px;line-height:1.6;color:#8A93A2;text-align:right;"><span leaf="">{html_text(source)}</span>{source_link}</p>'
        "</section>"
    )


def leaf_line(value: str, *, margin: str) -> str:
    return f'<p style="margin:{margin};font-size:13px;line-height:1.8;color:#4A5264;"><span leaf="">{html_text(value)}</span></p>'


def html_text(value: object) -> str:
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


class LeafChecker(HTMLParser):
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
