"""可选的大模型接入（OpenAI 兼容接口）。

这个项目的默认路线是「不配置也能用」：摘要、查重、聚类、缺口全部本地算。
LLM 只做三件本地做不好的事，而且都能关掉：

    深度总结   把六个槽位串成一段可读的中文摘要（仍是基于已抽出的原句，不允许编造）
    翻译       术语与长句质量明显好于免费机翻
    缺口审阅   对规则找出的缺口做一次「是否成立、还漏了什么」的复核

配置存在本地 kv 表里，key 只在请求头里出现，不写日志、不进导出。
"""
from __future__ import annotations

import json
import time

from core import http, library

DEFAULTS = {
    "llm_base": "https://api.openai.com/v1",
    "llm_model": "gpt-4o-mini",
    "llm_on": "0",
}

_SYSTEM = (
    "你是严谨的学术写作助手。你只使用用户提供的材料，不得引入材料之外的事实、"
    "数字或引用。材料没写的，就写「材料未提及」。不要编造参考文献。"
)


def base_url() -> str:
    return (library.get_kv("llm_base", DEFAULTS["llm_base"]) or "").rstrip("/")


def model_name() -> str:
    return library.get_kv("llm_model", DEFAULTS["llm_model"]) or DEFAULTS["llm_model"]


def api_key() -> str:
    return library.get_kv("llm_key", "")


def is_ready() -> bool:
    return bool(api_key()) and library.get_kv("llm_on", "0") == "1"


def mask_key(key: str | None = None) -> str:
    k = key if key is not None else api_key()
    if not k:
        return "未设置"
    return f"{k[:3]}…{k[-4:]}" if len(k) > 8 else "已设置"


def save(base: str, key: str, model: str, on: bool = True) -> None:
    library.set_kv("llm_base", (base or DEFAULTS["llm_base"]).strip())
    library.set_kv("llm_model", (model or DEFAULTS["llm_model"]).strip())
    if key is not None and key.strip():
        library.set_kv("llm_key", key.strip())
    library.set_kv("llm_on", "1" if on else "0")


def clear() -> None:
    for k in ("llm_base", "llm_model", "llm_key", "llm_on"):
        library.set_kv(k, "" if k != "llm_on" else "0")


def chat(messages: list[dict], *, temperature: float = 0.2, max_tokens: int = 1200,
         timeout: float = 90.0) -> tuple[str | None, str]:
    """返回 (文本, 错误)。任何异常都转成可展示的中文错误。"""
    if not api_key():
        return None, "还没有配置 API Key"
    url = f"{base_url()}/chat/completions"
    payload = {
        "model": model_name(),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    data = http.post_json(url, payload, ttl_kind="record", timeout=timeout, retries=0,
                          headers={"Authorization": f"Bearer {api_key()}"})
    if not data:
        return None, "请求失败：接口无响应或地址不对（检查 Base URL 是否以 /v1 结尾）"
    if "error" in data:
        msg = data["error"].get("message") if isinstance(data["error"], dict) else str(data["error"])
        return None, f"接口返回错误：{msg}"
    try:
        return data["choices"][0]["message"]["content"].strip(), ""
    except (KeyError, IndexError, TypeError):
        return None, "返回格式不是 OpenAI 兼容格式"


def test() -> tuple[bool, str]:
    text, err = chat([{"role": "user", "content": "回复两个字：可用"}], max_tokens=16, timeout=30)
    if text:
        return True, f"连接成功，模型 {model_name()} 返回：{text[:30]}"
    return False, err


# --------------------------------------------------------------------------
# 三个具体用法
# --------------------------------------------------------------------------
def deep_summary(title: str, slots: dict, one_liner: str = "") -> tuple[str | None, str]:
    """把已抽取的槽位串成一段话。输入只有原句，模型不允许补充事实。"""
    lines = [f"标题：{title}"]
    if one_liner:
        lines.append(f"一句话结论（原文）：{one_liner}")
    for label, sents in slots.items():
        if sents:
            lines.append(f"{label}：{' '.join(sents)}")
    prompt = (
        "下面是一篇论文摘要里按结构抽出的原句。请用中文写一段 150–220 字的连贯摘要，"
        "要求：只使用这些原句的信息；保留关键数字；不要添加任何原文没有的内容；"
        "不要写「本文」以外的评价。\n\n" + "\n".join(lines)
    )
    return chat([{"role": "system", "content": _SYSTEM},
                 {"role": "user", "content": prompt}], max_tokens=700)


def translate(text: str, target: str = "zh") -> tuple[str | None, str]:
    direction = "英文翻译成简体中文" if target == "zh" else "简体中文翻译成英文"
    prompt = (
        f"把下面的学术文本{direction}。保留专业术语、基因/药物名称、数字与统计符号原样；"
        "不要解释、不要总结、不要加引号。\n\n" + text[:6000]
    )
    return chat([{"role": "user", "content": prompt}], temperature=0.1, max_tokens=2000)


def review_gaps(gaps: list[dict], stats: dict) -> tuple[str | None, str]:
    """让模型复核规则找出的缺口：哪些成立、哪些是摘要信息缺失造成的误判。"""
    brief = "\n".join(
        f"- [{g.get('severity')}] {g.get('title')}：{g.get('detail')}" for g in gaps[:8]
    )
    prompt = (
        "以下是一个文献集合的统计与规则引擎找出的研究缺口。请逐条判断："
        "①这条缺口是否被数据支持；②是否只是「摘要没写」而非「研究没做」；③还漏了什么。"
        "输出中文，分点，不超过 400 字。不要引入材料之外的信息。\n\n"
        f"统计：{json.dumps(stats, ensure_ascii=False)}\n\n缺口：\n{brief}"
    )
    return chat([{"role": "system", "content": _SYSTEM},
                 {"role": "user", "content": prompt}], max_tokens=900)


def status() -> dict:
    return {
        "ready": is_ready(),
        "base": base_url(),
        "model": model_name(),
        "key": mask_key(),
        "on": library.get_kv("llm_on", "0") == "1",
    }
