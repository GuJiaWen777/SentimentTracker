from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

ALIAS_ENV = "EARLYDATA_ENTITY_ALIASES"
DEFAULT_ALIAS_PATH = Path("data/entities.json")
KINDS = ("company", "technology")

# Canonical names beat near-duplicates in the review UI and cross-week trends.
# Keys are matched after removing spaces, hyphens and brackets and folding case.
BUILTIN_ALIASES: dict[str, dict[str, str]] = {
    "company": {
        "pfizer": "辉瑞",
        "辉瑞制药": "辉瑞",
        "astrazeneca": "阿斯利康",
        "阿斯利康制药": "阿斯利康",
        "roche": "罗氏",
        "罗氏制药": "罗氏",
        "novartis": "诺华",
        "诺华制药": "诺华",
        "sanofi": "赛诺菲",
        "赛诺菲巴斯德": "赛诺菲",
        "eli lilly": "礼来",
        "lilly": "礼来",
        "礼来制药": "礼来",
        "johnson & johnson": "强生",
        "johnson and johnson": "强生",
        "jnj": "强生",
        "强生公司": "强生",
        "abbvie": "艾伯维",
        "艾伯维公司": "艾伯维",
        "amgen": "安进",
        "安进公司": "安进",
        "gilead": "吉利德",
        "gilead sciences": "吉利德",
        "吉利德科学": "吉利德",
        "bristol myers squibb": "百时美施贵宝",
        "bristolmyerssquibb": "百时美施贵宝",
        "bms": "百时美施贵宝",
        "百时美施贵宝公司": "百时美施贵宝",
        "merck sharp & dohme": "默沙东",
        "merck sharp and dohme": "默沙东",
        "msd": "默沙东",
        "默沙东公司": "默沙东",
        "innovent": "信达生物",
        "innovent biologics": "信达生物",
        "信达生物制药": "信达生物",
        "biocytogen": "百奥赛图",
        "百奥赛图医药": "百奥赛图",
        "beigene": "百济神州",
        "百济神州（北京）生物科技有限公司": "百济神州",
        "hengrui": "恒瑞医药",
        "jiangsu hengrui": "恒瑞医药",
        "江苏恒瑞医药": "恒瑞医药",
        "wuxi apptec": "药明康德",
        "药明康德新药开发": "药明康德",
        "cspc": "石药集团",
        "石药控股集团": "石药集团",
        "moderna": "莫德纳",
        "biontech": "拜恩泰科",
    },
    "technology": {
        "cart": "CAR-T",
        "cart细胞": "CAR-T",
        "双特异性抗体": "双抗",
        "双特异性": "双抗",
        "bispecific": "双抗",
        "bispecific antibody": "双抗",
        "单克隆抗体": "单抗",
        "monoclonal antibody": "单抗",
        "抗体偶联药物": "ADC",
        "抗体偶联": "ADC",
        "antibody drug conjugate": "ADC",
        "抗体寡核苷酸偶联物": "AOC",
        "mrna": "mRNA",
        "mrna疫苗": "mRNA",
        "sirna": "siRNA",
        "反义寡核苷酸": "ASO",
        "antisense oligonucleotide": "ASO",
        "基因治疗": "基因疗法",
        "gene therapy": "基因疗法",
        "细胞治疗": "CGT",
        "cell and gene therapy": "CGT",
        "细胞与基因治疗": "CGT",
        "ai制药": "AI制药",
        "人工智能制药": "AI制药",
        "ai drug discovery": "AI制药",
        "放射性药物": "核药",
        "radioligand": "核药",
        "radioligand therapy": "核药",
        "glp1": "GLP-1",
        "glp1受体激动剂": "GLP-1",
        "pd1": "PD-1",
        "pdl1": "PD-L1",
        "protac": "PROTAC",
        "cro": "CRO",
        "cdmo": "CDMO",
    },
}


def alias_path() -> Path:
    return Path(os.environ.get(ALIAS_ENV) or DEFAULT_ALIAS_PATH)


def load_aliases(path: Path | None = None) -> dict[str, dict[str, str]]:
    """Built-in aliases merged with an optional local dictionary.

    The local file is ``{"company": {"alias": "Canonical"}, "technology": {...}}``.
    A missing or invalid file is ignored so a typo never breaks generation.
    """
    merged = {kind: dict(values) for kind, values in BUILTIN_ALIASES.items()}
    target = Path(path) if path is not None else alias_path()
    try:
        data: Any = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return merged
    if not isinstance(data, dict):
        return merged
    for kind in KINDS:
        values = data.get(kind)
        if not isinstance(values, dict):
            continue
        for alias, canonical in values.items():
            alias, canonical = str(alias).strip(), str(canonical).strip()
            if alias and canonical:
                merged[kind][alias] = canonical
    return merged


def canonical_entity(value: str, kind: str, *, aliases: dict[str, dict[str, str]] | None = None) -> str:
    """Return the canonical spelling for one company or technology name."""
    name = _clean(value)
    if not name:
        return ""
    if kind not in KINDS:
        return name
    table = (aliases or load_aliases()).get(kind, {})
    lookup = {_key(alias): canonical for alias, canonical in table.items()}
    return _clean(lookup.get(_key(name), name))


def normalize_entities(
    values: Iterable[Any],
    kind: str,
    *,
    aliases: dict[str, dict[str, str]] | None = None,
) -> list[str]:
    """Canonicalize, trim and deduplicate a tag list while preserving order."""
    table = aliases or load_aliases()
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = canonical_entity(str(value), kind, aliases=table)
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(name)
    return result


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", str(value)).strip(" ，。；：、")


def _key(value: str) -> str:
    return re.sub(r"[\s\-_·（）()&]+", "", value).casefold()
