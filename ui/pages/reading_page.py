"""待读：一个短队列，不是收藏夹。

这一页只回答「接下来读哪几篇」。读完就从队列里消失（进文献库的「已读」），
不想读的移出队列也不会动文献库。推荐、检索、图谱都可以往这里塞条目，
但队列本身不产生推荐 —— 两件事分开，才不会互相干扰。
"""
from __future__ import annotations

import datetime as dt

import streamlit as st

from core import library, reading, schema, workspace
from core import text as T
from ui import theme


def _add_from_library() -> None:
    pool = library.list_papers()
    if not pool:
        st.caption("文献库还是空的，先去检索或导入。")
        return
    existing = reading.sids()
    options = {p["sid"]: T.shorten(p.get("title", ""), 70)
               for p in pool if p["sid"] not in existing}
    if not options:
        st.caption("文献库里的条目都已经在队列里了。")
        return
    with st.form("add_reading"):
        c1, c2, c3 = st.columns([3, 1, 0.8])
        picked = c1.multiselect("从文献库挑", list(options), format_func=lambda s: options[s],
                                label_visibility="collapsed")
        prio = c2.selectbox("优先级", [1, 2, 3], index=1,
                            format_func=lambda p: reading.PRIORITIES[p],
                            label_visibility="collapsed")
        if c3.form_submit_button("加入队列", use_container_width=True) and picked:
            papers = [p for p in pool if p["sid"] in picked]
            reading.add(papers, priority=prio, source="手动")
            st.rerun()


def _row(p: dict, projects: list[dict]) -> None:
    sid = p["sid"]
    c1, c2, c3, c4 = st.columns([0.66, 0.13, 0.11, 0.10])
    with c1:
        st.markdown(
            theme.paper_row(p, abstract_chars=150,
                            badges=[f'{p["_priority_label"]}优先', p["_source"]]),
            unsafe_allow_html=True,
        )
    with c2:
        new_prio = st.selectbox("优先级", [1, 2, 3],
                                index=[1, 2, 3].index(p["_priority"]) if p["_priority"] in (1, 2, 3) else 1,
                                format_func=lambda x: reading.PRIORITIES[x],
                                key=f"rp_{sid}", label_visibility="collapsed")
        if new_prio != p["_priority"]:
            reading.set_priority(sid, new_prio)
            st.rerun()
    with c3:
        if st.button("读完", key=f"rd_{sid}", use_container_width=True):
            reading.mark_done(sid)
            st.rerun()
        if st.button("移出", key=f"rr_{sid}", use_container_width=True):
            reading.remove(sid)
            st.rerun()
    with c4:
        if projects and st.button("进项目", key=f"rpj_{sid}", use_container_width=True):
            st.session_state[f"pickproj_{sid}"] = True
    if st.session_state.get(f"pickproj_{sid}") and projects:
        c5, c6 = st.columns([2, 1])
        target = c5.selectbox("项目", [x["name"] for x in projects],
                              key=f"pjsel_{sid}", label_visibility="collapsed")
        pid = next(x["id"] for x in projects if x["name"] == target)
        if c6.button("确认加入", key=f"pjok_{sid}", use_container_width=True):
            workspace.add_paper(pid, sid, "核心")
            st.success("已加入项目")


def render() -> None:
    theme.hero(
        "待读",
        "从检索、推荐、图谱里点「设为待读」的条目会排在这里。读完自动进文献库的「已读」，"
        "移出只影响队列，不影响收藏。",
        "READING LIST · 待读",
    )
    stt = reading.stats()
    theme.stats([
        ("队列中", str(stt["pending"]), "篇"),
        ("高优先", str(stt["high"]), "篇"),
        ("本周加入", str(stt["added_week"]), "篇"),
        ("本周读完", str(stt["done_week"]), "篇"),
    ])

    if stt["pending"] == 0:
        theme.empty("队列是空的", "去「文献检索」或「推荐」把想读的条目加进来；"
                                  "也可以从下面的文献库里挑。")
        _add_from_library()
        return

    c1, c2 = st.columns([1, 3])
    prio = c1.selectbox("筛选优先级", ["全部", "高", "中", "低"])
    items = reading.list_items()
    if prio != "全部":
        key = {v: k for k, v in reading.PRIORITIES.items()}[prio]
        items = [p for p in items if p["_priority"] == key]

    theme.section("队列", f"{len(items)} 篇，按优先级和时间排序。", "01")
    projects = workspace.list_projects()
    for p in items:
        _row(p, projects)

    with st.expander("从文献库补充", expanded=False):
        _add_from_library()

    done = reading.list_items(include_done=True)
    done = [p for p in done if p["_done"]]
    if done:
        with st.expander(f"最近读完（{len(done)} 篇）", expanded=False):
            for p in done[:20]:
                when = dt.datetime.fromtimestamp(p["_added_at"]).strftime("%m-%d")
                st.markdown(
                    f'<div style="font-size:13px;padding:5px 0;border-bottom:1px dashed #ece7dd;">'
                    f'{theme.esc(T.shorten(p.get("title", ""), 80))}'
                    f'<span style="color:#a5adb2;font-size:11.5px;">　{when} 加入</span></div>',
                    unsafe_allow_html=True,
                )
            if st.button("清理 30 天前读完的记录"):
                n = reading.clear_done(30)
                st.success(f"清理 {n} 条")
                st.rerun()

    theme.method_note(
        "待读是队列，不是收藏。队列只保留「接下来要读的」，所以读完就消失；"
        "文献库才是长期资产，两者互不覆盖。推荐页的「不感兴趣」只影响推荐权重，不会动这里的队列。"
    )
