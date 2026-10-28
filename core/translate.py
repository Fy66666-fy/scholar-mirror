"""翻译：默认走 MyMemory 免费接口，配了 LLM 可以切到模型翻译。

为什么不是「一键翻译整篇」：机翻对学术句式的伤害主要在术语与长句结构上，
整篇翻完基本没法用。这里的做法是**按句翻译 + 保留原文对照**，
让用户逐句核对；术语（基因名、药物名、缩写）原样保留，不参与翻译。

缓存 7 天：同一篇摘要反复打开不会重复请求，也避免把免费额度耗在重复内容上。
"""
from __future__ import annotations

import re
import time

from core import http
from core import text as T

MYMEMORY = "https://api.mymemory.translated.net/get"

# 不翻译的词：全大写缩写、带数字的代号（p-tau217、IL-6、BRCA1）、拉丁学名
_KEEP_RE = re.compile(r"^[A-Z][A-Za-z0-9\-]{1,12}$|^[A-Za-z]+-\d+[A-Za-z0-9\-]*$")

_GLOSSARY = {
    "abstract": "摘要", "systematic review": "系统评价", "meta-analysis": "Meta 分析",
    "randomized controlled trial": "随机对照试验", "cohort": "队列", "baseline": "基线",
    "follow-up": "随访", "outcome": "结局", "effect size": "效应量",
    "confidence interval": "置信区间", "hazard ratio": "风险比", "odds ratio": "比值比",
    "sensitivity": "灵敏度", "specificity": "特异度", "prevalence": "患病率",
    "microplastics": "微塑料", "soil microbial community": "土壤微生物群落",
    "large language model": "大语言模型", "benchmark": "基准", "ablation": "消融实验",
    "limitation": "局限", "future work": "未来工作", "sample size": "样本量",
}


def _split_for_api(text: str, limit: int = 450) -> list[str]:
    """MyMemory 单次请求有长度上限，按句聚合到 limit 以内。"""
    sentences = T.split_sentences(text) or [text]
    chunks, cur = [], ""
    for s in sentences:
        if len(s) > limit:
            if cur:
                chunks.append(cur)
                cur = ""
            for i in range(0, len(s), limit):
                chunks.append(s[i: i + limit])
            continue
        if len(cur) + len(s) + 1 > limit and cur:
            chunks.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        chunks.append(cur)
    return chunks


def _mymemory(text: str, source: str, target: str) -> tuple[str | None, str]:
    data = http.get_json(MYMEMORY, params={"q": text, "langpair": f"{source}|{target}"},
                         ttl_kind="static", timeout=20, retries=1)
    if not data:
        return None, "翻译接口无响应"
    if str(data.get("responseStatus")) not in ("200", "0"):
        return None, str(data.get("responseDetails") or "翻译失败")[:120]
    out = (data.get("responseData") or {}).get("translatedText") or ""
    if not out or out.strip().upper() == text.strip().upper():
        return None, "没有拿到译文"
    return out, ""


def translate(text: str, target: str = "zh", engine: str = "auto") -> dict:
    """单段翻译。target: zh / en。engine: auto / mymemory / llm / off。"""
    text = T.clean_text(text or "")
    if not text:
        return {"ok": False, "text": "", "engine": "", "error": "空文本"}

    from core import library
    mode = engine
    if mode == "auto":
        stored = library.get_kv("translate_engine", "auto")
        if stored != "auto":
            mode = stored
    if mode == "off":
        return {"ok": False, "text": "", "engine": "", "error": "翻译已在设置里关闭"}

    if mode in ("auto", "llm"):
        from core import llm
        if llm.is_ready():
            out, err = llm.translate(text, target)
            if out:
                return {"ok": True, "text": out, "engine": f"LLM（{llm.model_name()}）", "error": ""}
            if mode == "llm":
                return {"ok": False, "text": "", "engine": "LLM", "error": err}

    src, dst = ("en", "zh-CN") if target == "zh" else ("zh-CN", "en")
    parts, errs = [], []
    for chunk in _split_for_api(text):
        out, err = _mymemory(chunk, src, dst)
        if out:
            parts.append(out)
        else:
            errs.append(err)
        time.sleep(0.15)
    if not parts:
        return {"ok": False, "text": "", "engine": "MyMemory",
                "error": errs[0] if errs else "翻译失败"}
    result = " ".join(parts)
    if target == "zh":
        result = _apply_glossary(result)
    return {"ok": True, "text": result, "engine": "MyMemory（免费）", "error": ""}


def _apply_glossary(text: str) -> str:
    """机翻常把术语整段留在英文里。只在英文原词仍出现在译文时替换，避免过度改写。"""
    out = text
    for en, zh in _GLOSSARY.items():
        pattern = re.compile(rf"\b{re.escape(en)}\b", re.I)
        if pattern.search(out) and zh not in out:
            out = pattern.sub(zh, out, count=1)
    return out


def translate_sentences(sentences: list[str], target: str = "zh", engine: str = "auto") -> list[dict]:
    out = []
    for s in sentences:
        out.append({"original": s, **translate(s, target, engine)})
    return out


def engine_label() -> str:
    from core import llm, library
    mode = library.get_kv("translate_engine", "auto")
    if mode == "off":
        return "已关闭"
    if mode == "llm" and llm.is_ready():
        return f"LLM（{llm.model_name()}）"
    if mode == "mymemory":
        return "MyMemory（免费）"
    return "自动（有 LLM 用 LLM，否则 MyMemory）"


def enabled() -> bool:
    from core import library
    return library.get_kv("translate_engine", "auto") != "off"
