"""首页：说明这个工具做什么、怎么做，以及一个能直接开始的入口。"""
from __future__ import annotations

import time

import streamlit as st

from core import library, schema
from core.sources import SOURCE_INFO, default_sources
from ui import state, theme

EXAMPLES = [
    "microplastics soil microbial community",
    "large language model reasoning chain-of-thought",
    "minimum wage employment effects",
    "gut microbiome short-chain fatty acids obesity",
    "perovskite solar cell stability",
]


def _quick_start() -> None:
    theme.section("直接开始", "输入一个研究主题，系统会同时查 4–6 个数据源，合并重复条目后进入分析。", "01")
    with st.form("quick_start", clear_on_submit=False):
        c1, c2, c3 = st.columns([3, 1.1, 1])
        query = c1.text_input("研究主题 / 关键词", placeholder="例如：microplastics soil microbial community",
                              label_visibility="collapsed")
        discipline = c2.selectbox("学科", list(schema.DISCIPLINES), label_visibility="collapsed")
        per = c3.selectbox("每源条数", [10, 15, 25, 40], index=1, label_visibility="collapsed")
        go = st.form_submit_button("开始检索", type="primary", use_container_width=True)

    st.markdown(
        "<div style='font-size:12px;color:#8b9499;margin:-6px 0 8px;'>示例："
        + "　".join(f"<span class='sm-pill'>{e}</span>" for e in EXAMPLES[:3])
        + "</div>",
        unsafe_allow_html=True,
    )

    c1, c2 = st.columns([1, 3.2])
    if c1.button("先看演示数据", use_container_width=True):
        state.load_demo()
        st.session_state["_goto"] = "文献检索"
        st.rerun()
    c2.caption("12 篇跨学科示例文献，离线可用，用来先摸清每个页面在做什么。")

    if go:
        q = (query or "").strip()
        if not q:
            st.warning("先输入一个主题词。")
            return
        with st.spinner("正在并发检索并跨源去重…"):
            info = state.run_search(q, discipline, default_sources(discipline), per_source=per)
        if info["unique"] == 0:
            st.error("没有拿到结果。可能是网络受限或该主题在各源都没有命中，换个更通用的关键词试试。")
            return
        st.session_state["_goto"] = "文献检索"
        st.rerun()


def _features() -> None:
    theme.section("它能做什么", "六个能力，前三个解决「读得完」，后三个解决「看得懂关系」。", "02")
    items = [
        ("结构化摘要", "按学科模板抽槽位：研究问题 / 方法 / 数据 / 发现 / 结论 / 局限。每句可回溯原文。",
         "IMRaD · 计算机 · 经济 · 社科 · 人文 · 综述"),
        ("三层查重", "跨源合并同一篇；识别预印本与正式版；粘贴文本逐句比对给出重复率与出处。",
         "DOI · 标题指纹 · SimHash"),
        ("关联图谱", "文本、概念、引用、元数据四路信号合成关联度，力导向布局，每条边都能解释。",
         "共被引 · 概念重叠"),
        ("主题聚类与精选", "自动切分研究方向并命名；精选分拆成五项，能看清「为什么排前面」。",
         "轮廓系数选 k"),
        ("缺口识别", "从样本量、随访、设计、报告规范里找可核对的缺口，每条带证据原句。",
         "10 条规则 · 证据可查"),
        ("方向建议", "把缺口翻译成可检验的研究问题与推荐设计，附风险与替代方案。",
         "可起草，不可直接照抄"),
    ]
    cols = st.columns(3)
    for i, (title, desc, tag) in enumerate(items):
        with cols[i % 3]:
            theme.card(
                f'<div style="font-size:14.5px;font-weight:700;margin-bottom:6px;">{title}</div>'
                f'<div style="font-size:13px;line-height:1.75;color:#4a5a63;">{desc}</div>'
                f'<div style="margin-top:10px;">{theme.pill(tag, "gold")}</div>',
                tone="tight",
            )


def _sources() -> None:
    theme.section("数据从哪来", "六个公开数据源，无需注册、无需 API Key。单源失败不影响整体。", "03")
    rows = []
    for key, info in SOURCE_INFO.items():
        rows.append([
            f"<b>{theme.esc(info['label'])}</b>",
            theme.esc(info["desc"]),
            f'<span class="sm-pill">{theme.esc(info["strength"])}</span>',
        ])
    theme.table(["数据源", "覆盖与特点", "强项"], rows)


def _history() -> None:
    hist = library.history(6)
    if not hist:
        return
    theme.section("最近的检索", "", "04")
    for h in hist:
        when = time.strftime("%m-%d %H:%M", time.localtime(h["at"]))
        st.markdown(
            f'<div class="sm-paper" style="padding:9px 0;">'
            f'<span style="font-size:13.5px;">{theme.esc(h["query"])}</span>'
            f'<span style="font-size:12px;color:#8b9499;margin-left:10px;">'
            f'{theme.esc(h["discipline"])} · {h["n"]} 篇 · {when}</span></div>',
            unsafe_allow_html=True,
        )


def render() -> None:
    theme.hero(
        '把一批论文读成<span class="thin">一张可以核对的结构图</span>',
        "跨学科文献摘要与关联分析。检索聚合、结构化摘要、查重、关联图谱、主题聚类、研究缺口，"
        "全部在本地完成 —— 不调用大模型，不需要 API Key，每一条结论都能点回原文。",
        "SCHOLAR MIRROR · 文献镜像",
    )
    if not state.has_papers():
        theme.stats([
            ("数据源", "6", "个"),
            ("学科模板", "6", "套"),
            ("摘要槽位", "6", "项"),
            ("生成式调用", "0", "次"),
        ])
    else:
        ps = state.papers()
        years = [p["year"] for p in ps if p.get("year")]
        theme.stats([
            ("当前文献池", str(len(ps)), "篇"),
            ("年份跨度", f"{min(years)}–{max(years)}" if years else "—", ""),
            ("识别方向", str(state.analysis()["cluster"]["k"]), "个"),
            ("跨源合并", str(st.session_state.get("dup_merged", 0)), "条"),
        ])

    _quick_start()
    _features()
    _sources()
    _history()

    theme.method_note(
        "抽取式而非生成式：所有摘要句都来自论文原文，系统只做「选哪一句、放在哪一栏」。"
        "好处是不会编造，代价是摘要读起来不如人写的顺 —— 需要润色时请以原文为准。"
    )
