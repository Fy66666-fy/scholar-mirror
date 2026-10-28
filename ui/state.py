"""会话状态与分析流水线。

Streamlit 每次交互都从头跑一遍脚本，所以「一次检索 → 多次分析」必须把
中间结果缓存住，否则每点一次按钮就重新算聚类和缺口（几十毫秒到几百毫秒，
看起来像卡顿）。

这里用 session_state 存三样东西：
    papers     去重后的文献（页面之间共享的唯一数据源）
    analysis   聚类 / 图谱 / 缺口 / 精选的计算结果，用文献签名判断是否失效
    meta       检索条件与源状态

失效判断用「文献 sid 列表的哈希」，而不是对象身份 —— 用户改了筛选条件后
papers 变了，签名就变，分析自动重算。
"""
from __future__ import annotations

import hashlib

import streamlit as st

from core import cluster as C
from core import dedupe as D
from core import gaps as G
from core import library, related


def init() -> None:
    defaults = {
        "papers": [],
        "raw_count": 0,
        "status": [],
        "query": "",
        "discipline": "通用 / 跨学科",
        "dup_groups": [],
        "dup_merged": 0,
        "analysis": None,
        "analysis_sig": "",
        "pasted_text": "",
        "sources_used": [],
        "year_from": None,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


def set_results(*, query: str, discipline: str, papers: list[dict], status: list[dict],
                raw_count: int, dup_groups: list[dict], merged: int,
                sources_used: list[str], year_from: int | None) -> None:
    st.session_state["query"] = query
    st.session_state["discipline"] = discipline
    st.session_state["papers"] = papers
    st.session_state["status"] = status
    st.session_state["raw_count"] = raw_count
    st.session_state["dup_groups"] = dup_groups
    st.session_state["dup_merged"] = merged
    st.session_state["sources_used"] = sources_used
    st.session_state["year_from"] = year_from
    st.session_state["analysis"] = None
    st.session_state["analysis_sig"] = ""
    library.add_history(query, discipline, sources_used, len(papers))


def papers() -> list[dict]:
    return st.session_state.get("papers") or []


def has_papers() -> bool:
    return bool(papers())


def signature(ps: list[dict] | None = None) -> str:
    ps = ps if ps is not None else papers()
    raw = "|".join(sorted(p.get("sid", "") for p in ps))
    return hashlib.blake2b(raw.encode("utf-8"), digest_size=8).hexdigest()


def analysis(force: bool = False) -> dict:
    """惰性计算整条分析链。同一批文献只算一次。"""
    ps = papers()
    sig = signature(ps)
    cached = st.session_state.get("analysis")
    if cached and st.session_state.get("analysis_sig") == sig and not force:
        return cached

    if not ps:
        empty = {"cluster": {"labels": [], "clusters": [], "k": 0, "silhouette": 0, "method": ""},
                 "graph": {"nodes": [], "edges": [], "stats": {}, "matrix": None},
                 "gaps": {"gaps": [], "signals": [], "caveat": "", "stats": {}},
                 "curated": [], "bridges": [], "directions": [], "matrix": {}}
        st.session_state["analysis"] = empty
        st.session_state["analysis_sig"] = sig
        return empty

    res = C.cluster(ps)
    graph = related.build_graph(ps)
    labels = res["labels"]
    gap_res = G.detect(ps, labels)
    curated = C.curate(ps, st.session_state.get("query", ""), labels)
    bridges = related.bridge_papers(graph, {p["sid"]: labels[i] for i, p in enumerate(ps)})
    dirs = G.directions(ps, gap_res, labels)
    mat = G.concept_matrix(ps, labels, res)

    out = {
        "cluster": res,
        "graph": graph,
        "gaps": gap_res,
        "curated": curated,
        "bridges": bridges,
        "directions": dirs,
        "matrix": mat,
    }
    st.session_state["analysis"] = out
    st.session_state["analysis_sig"] = sig
    return out


def cluster_labels() -> dict[str, int]:
    res = analysis()["cluster"]
    return {p["sid"]: res["labels"][i] for i, p in enumerate(papers())} if papers() else {}


def filter_papers(ps: list[dict], *, year_range: tuple | None = None, designs: list[str] | None = None,
                  oa_only: bool = False, min_cites: int = 0) -> list[dict]:
    out = []
    for p in ps:
        if year_range and p.get("year") and not (year_range[0] <= p["year"] <= year_range[1]):
            continue
        if designs and p.get("design") not in designs:
            continue
        if oa_only and not p.get("is_oa"):
            continue
        if (p.get("cited_by") or 0) < min_cites:
            continue
        out.append(p)
    return out


def save_to_library(ps: list[dict], group: str = "未分组", tags: str = "") -> int:
    return library.save(ps, group=group, tags=tags)


def reset() -> None:
    st.session_state["papers"] = []
    st.session_state["analysis"] = None
    st.session_state["analysis_sig"] = ""
    st.session_state["status"] = []
    st.session_state["dup_groups"] = []
    st.session_state["query"] = ""


def load_demo() -> dict:
    """载入内置演示数据（离线可用），走和真实检索一样的去重与分析链路。"""
    from core import demo

    raw = demo.papers()
    d = D.dedupe_papers(raw)
    m = demo.meta()
    set_results(
        query=m["query"], discipline=m["discipline"], papers=d["papers"],
        status=[{"source": "demo", "label": "内置演示数据", "ok": True,
                 "count": len(raw), "error": "", "seconds": 0.0}],
        raw_count=len(raw), dup_groups=d["groups"], merged=d["merged"],
        sources_used=m["sources"], year_from=m["year_from"],
    )
    return {"raw": len(raw), "unique": len(d["papers"]), "merged": d["merged"]}


def run_search(query: str, discipline: str, sources: list[str], per_source: int = 15,
               year_from: int | None = None, oa_only: bool = False) -> dict:
    """检索 + 跨源去重 + 落状态。返回结果摘要，供页面提示用。"""
    from core.sources import search_all

    result = search_all(query, sources=sources, limit_per_source=per_source,
                        year_from=year_from, oa_only=oa_only)
    dedup = D.dedupe_papers(result["papers"])
    set_results(
        query=query, discipline=discipline, papers=dedup["papers"],
        status=result["status"], raw_count=len(result["papers"]),
        dup_groups=dedup["groups"], merged=dedup["merged"],
        sources_used=sources, year_from=year_from,
    )
    return {
        "raw": len(result["papers"]),
        "unique": len(dedup["papers"]),
        "merged": dedup["merged"],
        "elapsed": result["elapsed"],
        "failed": [s["label"] for s in result["status"] if not s["ok"]],
    }
