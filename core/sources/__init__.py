"""数据源注册表与并发检索编排。

对外只暴露两个函数：
    search_all(...)  并发打多个源，返回合并后的结果 + 每个源的状态
    available()      各源的说明，供 UI 展示与用户勾选

编排上做三件事，都是「多源聚合」绕不开的坑：
1. 单源失败绝不拖垮整体 —— 每个适配器独立 try，失败写进 status 里，
   UI 显示「Crossref 超时，其余 3 个源正常」，而不是整页报错。
2. 并发但有界 —— 不同域名之间并行，同一域名靠 http 层的 per-host 锁串行。
3. 检索式按源翻译 —— PubMed/Europe PMC 支持布尔式，arXiv 只认 all:，
   Crossref 走书目匹配。同一句用户输入要分别改写。
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from core import schema
from core.sources import arxiv, chinaxiv, crossref, europepmc, openalex, pubmed, semantic

ADAPTERS = {
    "openalex": openalex.search,
    "crossref": crossref.search,
    "arxiv": arxiv.search,
    "pubmed": pubmed.search,
    "europepmc": europepmc.search,
    "semantic": semantic.search,
    "chinaxiv": chinaxiv.search,
}

SOURCE_INFO = {
    "openalex": {
        "label": "OpenAlex",
        "desc": "跨学科 2.5 亿条元数据，带摘要、主题标签与参考文献",
        "strength": "覆盖面 · 引用关系",
        "key": False,
    },
    "crossref": {
        "label": "Crossref",
        "desc": "DOI 注册库，期刊与会议正式出版物最全",
        "strength": "权威元数据 · 卷期页码",
        "key": False,
    },
    "arxiv": {
        "label": "arXiv",
        "desc": "预印本，计算机 / 物理 / 数学最新进展",
        "strength": "时效性 · 全文 PDF",
        "key": False,
    },
    "pubmed": {
        "label": "PubMed",
        "desc": "生物医学权威索引，含人工标引的 MeSH 主题词",
        "strength": "医学覆盖 · MeSH",
        "key": False,
    },
    "europepmc": {
        "label": "Europe PMC",
        "desc": "生命科学文献 + 开放全文标记 + 参考文献",
        "strength": "OA 全文 · 引用边",
        "key": False,
    },
    "semantic": {
        "label": "Semantic Scholar",
        "desc": "带 TLDR 一句话摘要与引用网络（匿名配额较紧）",
        "strength": "语义摘要",
        "key": False,
    },
    "chinaxiv": {
        "label": "ChinaXiv",
        "desc": "中科院中文预印本平台，免注册；正式中文期刊需靠 Crossref 或自行导入",
        "strength": "中文文献",
        "key": False,
    },
}

BOOL_SOURCES = {"pubmed", "europepmc"}


def available() -> dict:
    return SOURCE_INFO


def _split_terms(query: str) -> tuple[list[str], list[str]]:
    """把用户输入拆成（正向词, 排除词）。支持 -term / NOT term 两种排除写法。"""
    q = (query or "").strip()
    excludes: list[str] = []
    for m in re.finditer(r"(?:^|\s)(?:-|NOT\s+)(\"[^\"]+\"|\S+)", q, flags=re.I):
        excludes.append(m.group(1).strip('"'))
    q_clean = re.sub(r"(?:^|\s)(?:-|NOT\s+)(\"[^\"]+\"|\S+)", " ", q, flags=re.I)
    positives = [t.strip('"') for t in re.findall(r"\"[^\"]+\"|\S+", q_clean) if t.strip('"')]
    return positives, excludes


def build_query(query: str, source: str) -> str:
    positives, excludes = _split_terms(query)
    if not positives:
        return query
    if source in BOOL_SOURCES:
        base = " AND ".join(f'"{p}"' if " " in p else p for p in positives)
        if excludes:
            base += " NOT (" + " OR ".join(excludes) + ")"
        return base
    if source == "arxiv":
        return " ".join(positives)
    out = " ".join(positives)
    if excludes:
        out += " " + " ".join(f"-{e}" for e in excludes)
    return out


def search_all(query: str, *, sources: list[str] | None = None, limit_per_source: int = 20,
               year_from: int | None = None, oa_only: bool = False,
               lang: str | None = None, on_progress=None) -> dict:
    """并发检索。返回 {'papers': [...], 'status': [...], 'elapsed': float}。

    papers 尚未去重 —— 去重是独立的一步（core.dedupe），因为用户可能想
    先看到「各源各返回了什么」再决定要不要合并。
    """
    picked = [s for s in (sources or list(ADAPTERS)) if s in ADAPTERS]
    started = time.time()
    papers: list[dict] = []
    status: list[dict] = []

    if not picked:
        return {"papers": [], "status": [], "elapsed": 0.0}

    def run(src: str) -> tuple[str, list[dict], str, float]:
        t0 = time.time()
        try:
            res = ADAPTERS[src](
                build_query(query, src),
                limit=limit_per_source,
                year_from=year_from,
                oa_only=oa_only,
                lang=lang,
            )
            return src, res or [], "", time.time() - t0
        except Exception as exc:  # noqa: BLE001 - 适配器内部异常一律降级
            return src, [], f"{type(exc).__name__}: {exc}", time.time() - t0

    with ThreadPoolExecutor(max_workers=min(4, len(picked))) as pool:
        futures = {pool.submit(run, s): s for s in picked}
        for fut in as_completed(futures):
            src, res, err, cost = fut.result()
            papers.extend(res)
            status.append({
                "source": src,
                "label": SOURCE_INFO.get(src, {}).get("label", src),
                "ok": not err and bool(res),
                "count": len(res),
                "error": err,
                "seconds": round(cost, 2),
            })
            if on_progress:
                on_progress(src, len(res), err)

    order = {s: i for i, s in enumerate(picked)}
    status.sort(key=lambda s: order.get(s["source"], 99))
    return {"papers": papers, "status": status, "elapsed": round(time.time() - started, 2)}


def default_sources(discipline: str) -> list[str]:
    return [s for s in (schema.DISCIPLINES.get(discipline, {}).get("sources") or list(ADAPTERS))
            if s in ADAPTERS]
