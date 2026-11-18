from __future__ import annotations

import re
from collections import Counter

from .models import Article
from .text import compact_text, strip_html, unique_values


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


def article_text(article: Article) -> str:
    return " ".join([article.title, article.summary, article.content, " ".join(article.tags or []), " ".join(article.entities or [])])


def summarize(article: Article) -> str:
    text = strip_html(article.summary or article.content or article.title)
    sentences = re.split(r"(?<=[。！？；])", text)
    while sentences and any(marker in sentences[0][:80] for marker in ("声明", "免责声明", "本文不构成", "撰稿")):
        sentences.pop(0)
    return compact_text("".join(sentences).strip() or article.title, 100)


def signal_style(article: Article) -> tuple[str, str, str]:
    headline = " ".join([article.title, " ".join(article.tags or [])])
    text = article_text(article)
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


def so_what(article: Article) -> str:
    text = article_text(article)
    if any(word in text for word in ("合作", "授权", "并购", "交易", "License", "BD")):
        return "复核交易结构、权益保留和海外执行能力。"
    if any(word in text for word in ("监管", "合规", "审评", "FDA", "GMP")):
        return "提前排查申报材料、数据完整性和质量体系缺口。"
    if "AI" in text or "人工智能" in text:
        return "选择可量化改善效率或质量的场景先验证。"
    return "将该信号纳入本周业务决策复核清单。"


def company_tags(articles: list[Article]) -> list[str]:
    found: list[str] = []
    for article in articles:
        found.extend(article.entities or [])
        title_and_tags = " ".join([article.title, " ".join(article.tags or [])])
        found.extend(
            name
            for name in KNOWN_ORGANIZATIONS
            if re.search(rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])", title_and_tags, re.I)
        )
        found.extend(title_organizations(title_and_tags))
    return unique_values(clean_entity(tag) for tag in found if is_entity_tag(tag))[:5]


def technology_tags(articles: list[Article]) -> list[str]:
    counts: Counter[str] = Counter()
    for article in articles:
        text = " ".join([article.title, " ".join(article.tags or [])])
        for label, keywords in PHARMA_TYPES.items():
            if any(keyword in text for keyword in keywords):
                counts[label] += 1
    return [label for label, _count in counts.most_common(5)]


def ranked_pool(articles: list[Article]) -> list[Article]:
    ranked = sorted(
        articles,
        key=lambda item: (biopharma_relevance(item), item.score(), item.published_at),
        reverse=True,
    )
    unique_ranked = dedupe_titles(ranked)
    editorial = [article for article in unique_ranked if not is_promotional(article)]
    pool = editorial or unique_ranked
    strategic = [article for article in pool if biopharma_relevance(article) >= 10]
    relevant = [article for article in pool if biopharma_relevance(article) >= 3]
    return strategic or relevant or pool


def biopharma_relevance(article: Article) -> int:
    title_and_tags = " ".join([article.title, " ".join(article.tags or [])])
    body = " ".join([article.summary, article.content])
    strategic = sum(8 for term in STRATEGIC_EVENT_TERMS if term.lower() in title_and_tags.lower())
    strategic += min(6, sum(1 for term in STRATEGIC_EVENT_TERMS if term.lower() in body.lower()))
    biopharma = sum(3 for term in BIOPHARMA_TERMS if term.lower() in title_and_tags.lower())
    biopharma += min(6, sum(1 for term in BIOPHARMA_TERMS if term.lower() in body.lower()))
    named_company = sum(4 for name in KNOWN_ORGANIZATIONS if name.lower() in title_and_tags.lower())
    generic_penalty = 12 if any(term.lower() in title_and_tags.lower() for term in GENERIC_HEALTH_TERMS) and strategic < 8 else 0
    return strategic + biopharma + named_company - generic_penalty


def is_promotional(article: Article) -> bool:
    return any(term in article.title for term in PROMOTIONAL_TITLE_TERMS)


def title_organizations(text: str) -> list[str]:
    matches = re.findall(
        r"[一-鿿A-Za-z0-9·]{2,18}(?:生物医药|生物科技|生物|医药|制药|药业|药企|公司|集团|研究院|大学|医院)",
        text,
    )
    return [clean_entity(match) for match in matches]


def clean_entity(value: str) -> str:
    value = value.strip()
    for marker in ENTITY_NOISE:
        if marker in value:
            value = value.rsplit(marker, 1)[-1]
    for connector in ("与", "和", "及"):
        if connector in value:
            value = value.rsplit(connector, 1)[-1]
    return value.strip(" ，。；：、()（）")[-16:]


def is_entity_tag(value: str) -> bool:
    value = clean_entity(value)
    if not 2 <= len(value) <= 24 or value[0].isdigit() or any(noise in value for noise in ENTITY_NOISE):
        return False
    return bool(re.search(r"[A-Za-z]|[一-鿿]", value))


def dedupe_titles(articles: list[Article]) -> list[Article]:
    result: list[Article] = []
    seen: set[str] = set()
    for article in articles:
        key = re.sub(r"[^\w一-鿿]", "", article.title).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(article)
    return result
