"""工作台首页：一屏看完「我在做什么、做到哪、下一步做什么」。

和 v0.1 的「首页」不同：那个是产品介绍页，这个是驾驶舱。
介绍页挪到「设置 · 关于」，因为用过三天的人不需要再看一遍功能列表，
但每天都需要知道：还有几篇没读、哪个项目卡住了、画像覆盖到哪。
"""
from __future__ import annotations

import datetime as dt
import time

import streamlit as st

from core import activity, library, notes, profile, stats, workspace
from ui import state, theme


def _greeting() -> str:
    h = dt.datetime.now().hour
    if h < 6:
        return "还在实验室"
    if h < 11:
        return "早上好"
    if h < 14:
        return "中午好"
    if h < 19:
        return "下午好"
    return "晚上好"


def _onboarding() -> None:
    theme.section("三步开始", "工作台需要先知道你在研究什么，后面所有推荐与统计才有意义。", "00")
    c1, c2, c3 = st.columns(3)
    with c1:
        theme.card(
            '<div style="font-size:12px;color:#a8822f;font-weight:600;letter-spacing:.08em;">STEP 1</div>'
            '<div style="font-size:15px;font-weight:700;margin:6px 0;">建一个研究方向</div>'
            '<div style="font-size:13px;line-height:1.7;color:#4a5a63;">'
            '一句话标签 + 几个关键词。关键词决定推荐召回，写具体一点效果差别很大。</div>',
            tone="tight",
        )
        if st.button("去建画像 →", use_container_width=True, key="ob_profile"):
            st.session_state["_goto"] = "研究画像"
            st.rerun()
    with c2:
        theme.card(
            '<div style="font-size:12px;color:#a8822f;font-weight:600;letter-spacing:.08em;">STEP 2</div>'
            '<div style="font-size:15px;font-weight:700;margin:6px 0;">检索或导入文献</div>'
            '<div style="font-size:13px;line-height:1.7;color:#4a5a63;">'
            '从六个数据源检索，或把 Zotero 里已有的 BibTeX 导进来，收藏即入库。</div>',
            tone="tight",
        )
        if st.button("去检索 →", use_container_width=True, key="ob_search"):
            st.session_state["_goto"] = "文献检索"
            st.rerun()
    with c3:
        theme.card(
            '<div style="font-size:12px;color:#a8822f;font-weight:600;letter-spacing:.08em;">STEP 3</div>'
            '<div style="font-size:15px;font-weight:700;margin:6px 0;">开一个研究项目</div>'
            '<div style="font-size:13px;line-height:1.7;color:#4a5a63;">'
            '把文献挂到项目下，设里程碑，进度会自动出现在这一页。</div>',
            tone="tight",
        )
        if st.button("去建项目 →", use_container_width=True, key="ob_project"):
            st.session_state["_goto"] = "研究项目"
            st.rerun()

    if st.button("先载入演示数据看看", key="ob_demo"):
        state.load_demo(seed_workspace=True)
        st.session_state["_goto"] = "工作台"
        st.rerun()


def _queue(lib: dict, queue: list[dict]) -> None:
    theme.section("阅读队列", "标为「在读」的会排在最前；没标过就按入库时间给最近几篇。", "01")
    if not queue:
        theme.empty("队列是空的", "去文献库把几篇标成「在读」，它们会出现在这里。")
        return
    for p in queue:
        badges = []
        if p.get("_state"):
            badges.append(p["_state"])
        if p.get("_group"):
            badges.append(p["_group"])
        st.markdown(
            theme.paper_row(p, abstract_chars=110, badges=badges),
            unsafe_allow_html=True,
        )


def _activity_panel(rows: list[dict]) -> None:
    theme.section("最近活动", "", "02")
    if not rows:
        st.caption("还没有记录。检索、收藏、写笔记都会出现在这里。")
        return
    for r in rows:
        when = dt.datetime.fromtimestamp(r["at"]).strftime("%m-%d %H:%M")
        tone = {"收藏": "ok", "笔记": "gold", "项目": "solid", "推荐": "solid"}.get(r["kind"], "")
        st.markdown(
            f'<div style="display:flex;gap:10px;align-items:flex-start;padding:6px 0;'
            f'border-bottom:1px dashed #ece7dd;">'
            f'<div style="min-width:52px;font-size:11px;color:#a5adb2;'
            f'font-variant-numeric:tabular-nums;padding-top:2px;">{when}</div>'
            f'<div style="flex:1;font-size:13px;line-height:1.6;">{theme.pill(r["kind"], tone)}'
            f'<span style="color:#3d4d56;">{theme.esc(r["detail"])}</span></div></div>',
            unsafe_allow_html=True,
        )


def _projects_panel(projects: list[dict]) -> None:
    theme.section("研究项目", "", "03")
    if not projects:
        st.caption("还没有项目。项目把文献、里程碑和笔记绑在一个研究问题下。")
        if st.button("新建第一个项目", key="dash_new_proj"):
            st.session_state["_goto"] = "研究项目"
            st.rerun()
        return
    for p in projects:
        pct = p["progress"]
        st.markdown(
            f'<div class="sm-card tight">'
            f'<div style="display:flex;justify-content:space-between;gap:10px;">'
            f'<div style="font-size:14px;font-weight:650;">{theme.esc(p["name"])}</div>'
            f'<div style="font-size:11.5px;color:#6b767c;">{theme.esc(p["status"])}</div></div>'
            f'<div style="font-size:12.5px;color:#6b767c;margin-top:3px;">'
            f'{theme.esc(p["question"][:60]) if p["question"] else "未填写研究问题"}</div>'
            f'<div class="sm-bar" style="margin-top:9px;"><i style="width:{pct}%"></i></div>'
            f'<div style="display:flex;justify-content:space-between;font-size:11.5px;'
            f'color:#8b9499;margin-top:5px;"><span>里程碑 {p["done"]}/{p["milestones"]}</span>'
            f'<span>文献 {p["papers"]} · 笔记 {p["notes"]}</span></div></div>',
            unsafe_allow_html=True,
        )


def _coverage(coverage: list[dict]) -> None:
    theme.section("方向覆盖", "画像里每个方向在文献库中有多少篇 —— 哪个方向读得多，哪个还是空白。", "04")
    if not coverage:
        st.caption("建立研究画像后，这里会显示每个方向的文献覆盖度。")
        return
    for c in coverage:
        st.markdown(theme.bar(c["label"], c["share"], 100, "%"), unsafe_allow_html=True)
        st.markdown(
            f'<div style="font-size:11.5px;color:#8b9499;margin:-6px 0 10px;">{c["papers"]} 篇</div>',
            unsafe_allow_html=True,
        )


def _trend(days: list[tuple[str, int]]) -> None:
    import plotly.graph_objects as go

    labels = [d[5:] for d, _ in days]
    values = [c for _, c in days]
    fig = go.Figure(go.Bar(x=labels, y=values, marker_color="#1f4e5f", marker_line_width=0))
    fig.update_layout(height=150, margin=dict(l=0, r=0, t=6, b=0), showlegend=False,
                      xaxis=dict(tickfont=dict(size=9)), yaxis=dict(showgrid=False, visible=False))
    st.plotly_chart(theme.plotly_layout(fig, height=150), use_container_width=True,
                    config={"displayModeBar": False})


def render() -> None:
    data = stats.dashboard()
    lib = data["library"]
    prof = data["profile"]

    theme.hero(
        f'{_greeting()}，这是你的研究工作台',
        "左边是你要读的，中间是你在做的，右边是系统建议你关注的。"
        "所有数字都来自本机文献库，不上传任何数据。",
        "WORKBENCH · 工作台",
    )

    theme.stats([
        ("文献库", str(lib["papers"]), "篇"),
        ("在读", str(lib["reading"]), "篇"),
        ("研究项目", str(data["project_stats"]["active"]), "个进行中"),
        ("笔记", str(lib["notes"]), "条"),
        ("连续使用", str(data["streak"]), "天"),
    ])

    if not profile.is_ready() and lib["papers"] == 0:
        _onboarding()
        theme.section("最近活动", "", "05")
        _activity_panel(data["activity"])
        return

    left, right = st.columns([1.55, 1])
    with left:
        _queue(lib, data["queue"])
        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        _projects_panel(data["projects"])
    with right:
        theme.section("研究画像", "", "A")
        if prof["count"]:
            st.markdown(theme.pills([i for i in prof["keywords"]][:10], "solid"),
                        unsafe_allow_html=True)
            st.markdown(
                f'<div style="font-size:12.5px;color:#6b767c;margin:-2px 0 10px;">'
                f'{prof["count"]} 个方向 · {prof["seeds"]} 篇种子文献</div>',
                unsafe_allow_html=True,
            )
            if st.button("查看推荐 →", use_container_width=True, key="dash_rec"):
                st.session_state["_goto"] = "推荐"
                st.rerun()
        else:
            st.caption("还没有研究方向。建一个之后才能做个性化推荐。")
            if st.button("去建画像", use_container_width=True, key="dash_profile"):
                st.session_state["_goto"] = "研究画像"
                st.rerun()

        _coverage(data["coverage"])

        theme.section("活跃度", "最近 14 天的操作次数。", "B")
        _trend(data["activity_days"])

        theme.section("最近活动", "", "C")
        _activity_panel(data["activity"][:6])

    theme.section("快捷入口", "", "05")
    c1, c2, c3, c4, c5 = st.columns(5)
    for col, (label, target) in zip(
        (c1, c2, c3, c4, c5),
        [("文献检索", "文献检索"), ("文献库", "文献库"), ("研究项目", "研究项目"),
         ("缺口分析", "缺口与方向"), ("更新日志", "更新日志")],
    ):
        with col:
            if st.button(label, use_container_width=True, key=f"qa_{target}"):
                st.session_state["_goto"] = target
                st.rerun()

    if data["venues"]:
        theme.section("常读来源", "", "06")
        st.markdown(
            theme.pills([f"{v} {n}" for v, n in data["venues"]], ""),
            unsafe_allow_html=True,
        )
