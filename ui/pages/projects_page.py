"""研究项目：一个课题 = 研究问题 + 文献 + 里程碑 + 笔记。

这是工作台和「文献管理工具」的分界线：文献库回答「我有什么」，
项目回答「我在做什么、做到哪一步了」。
"""
from __future__ import annotations

import datetime as dt

import streamlit as st

from core import library, notes, schema, workspace
from core import text as T
from ui import theme


def _create() -> None:
    with st.expander("新建项目", expanded=not workspace.list_projects()):
        with st.form("new_project", clear_on_submit=True):
            c1, c2 = st.columns([2, 1])
            name = c1.text_input("项目名称", placeholder="例：血浆 p-tau217 在基层筛查中的价值")
            status = c2.selectbox("状态", workspace.STATUSES)
            question = st.text_input("研究问题（一句话）",
                                     placeholder="例：p-tau217 能否替代 PET 作为一线筛查工具？")
            desc = st.text_area("背景与目标（可选）", height=80)
            if st.form_submit_button("创建项目", type="primary"):
                if not (name or "").strip():
                    st.warning("先填项目名称。")
                else:
                    pid = workspace.create(name.strip(), question.strip(), desc.strip(), status)
                    st.session_state["pid"] = pid
                    st.rerun()


def _list() -> None:
    projects = workspace.list_projects()
    if not projects:
        theme.empty("还没有项目", "项目用来把「一个课题的文献、里程碑、笔记」放在一起。上面建一个。")
        return
    theme.section("我的项目", f"共 {len(projects)} 个。", "01")
    options = {f'{p["name"]}（{p["status"]} · {p["papers"]} 篇）': p["id"] for p in projects}
    current = st.session_state.get("pid")
    labels = list(options)
    idx = next((i for i, l in enumerate(labels) if options[l] == current), 0)
    pick = st.selectbox("选择项目", labels, index=idx, label_visibility="collapsed")
    st.session_state["pid"] = options[pick]

    for p in projects:
        tone = "accent" if p["id"] == st.session_state["pid"] else "tight"
        st.markdown(
            f'<div class="sm-card {tone}">'
            f'<div style="display:flex;justify-content:space-between;gap:12px;">'
            f'<div style="font-size:14.5px;font-weight:700;">{theme.esc(p["name"])}</div>'
            f'<div style="font-size:11.5px;color:#6b767c;">{theme.esc(p["status"])}</div></div>'
            f'<div style="font-size:12.5px;color:#6b767c;margin-top:3px;">'
            f'{theme.esc(p["question"] or "未填写研究问题")}</div>'
            f'<div class="sm-bar" style="margin-top:8px;"><i style="width:{p["progress"]}%"></i></div>'
            f'<div style="display:flex;gap:16px;font-size:11.5px;color:#8b9499;margin-top:5px;">'
            f'<span>进度 {p["progress"]}%</span><span>里程碑 {p["done"]}/{p["milestones"]}</span>'
            f'<span>文献 {p["papers"]}</span><span>笔记 {p["notes"]}</span></div></div>',
            unsafe_allow_html=True,
        )


def _milestones(pid: int) -> None:
    theme.section("里程碑", "把「做到哪一步」拆成可勾选的项。进度条按完成比例算。", "02")
    items = workspace.milestones(pid)
    if not items:
        st.caption("还没有里程碑。建议从「完成文献综述」「确定方法」「收集数据」开始。")
    for m in items:
        c1, c2, c3 = st.columns([0.08, 0.72, 0.2])
        done = c1.checkbox("", value=m["done"], key=f"ms_{m['id']}", label_visibility="collapsed")
        if done != m["done"]:
            workspace.toggle_milestone(m["id"], done)
            st.rerun()
        style = "text-decoration:line-through;color:#a5adb2;" if m["done"] else ""
        due = f'　<span style="color:#8b9499;">截止 {theme.esc(m["due"])}</span>' if m["due"] else ""
        c2.markdown(f'<div style="font-size:13.5px;{style}">{theme.esc(m["title"])}{due}</div>',
                    unsafe_allow_html=True)
        if c3.button("删除", key=f"msdel_{m['id']}", use_container_width=True):
            workspace.remove_milestone(m["id"])
            st.rerun()

    with st.form(f"add_ms_{pid}", clear_on_submit=True):
        c1, c2, c3 = st.columns([2.4, 1, 0.7])
        title = c1.text_input("新里程碑", placeholder="例：完成 30 篇文献的结构化摘要",
                              label_visibility="collapsed")
        due = c2.text_input("截止日期", placeholder="2026-12-01", label_visibility="collapsed")
        if c3.form_submit_button("添加", use_container_width=True) and title.strip():
            workspace.add_milestone(pid, title.strip(), due.strip())
            st.rerun()


def _papers(pid: int) -> None:
    theme.section("项目文献", "同一篇文献在不同课题里的作用不同：综述里是背景，在项目里可能是核心证据。", "03")
    items = workspace.papers(pid)
    if items:
        for p in items:
            c1, c2, c3 = st.columns([0.68, 0.2, 0.12])
            with c1:
                st.markdown(
                    theme.paper_row(p, abstract_chars=140, badges=[p.get("_role") or "核心"]),
                    unsafe_allow_html=True,
                )
            with c2:
                role = st.selectbox("角色", workspace.ROLES,
                                    index=workspace.ROLES.index(p["_role"])
                                    if p.get("_role") in workspace.ROLES else 0,
                                    key=f"role_{p['sid']}", label_visibility="collapsed")
                if role != p.get("_role"):
                    workspace.add_paper(pid, p["sid"], role)
                    st.rerun()
            with c3:
                if st.button("移除", key=f"prem_{p['sid']}", use_container_width=True):
                    workspace.remove_paper(pid, p["sid"])
                    st.rerun()
    else:
        st.caption("还没有关联文献。从下面把文献库里的条目加进来。")

    pool = library.list_papers()
    if not pool:
        st.caption("文献库为空，先去检索或导入。")
        return
    options = {p["sid"]: f'{T.shorten(p.get("title", ""), 68)}（{p.get("year") or "—"}）'
               for p in pool}
    existing = {p["sid"] for p in items}
    with st.form(f"add_papers_{pid}"):
        c1, c2, c3 = st.columns([3, 1, 0.8])
        picked = c1.multiselect("从文献库添加", [s for s in options if s not in existing],
                                format_func=lambda s: options[s], label_visibility="collapsed")
        role = c2.selectbox("角色", workspace.ROLES, index=0, label_visibility="collapsed")
        if c3.form_submit_button("加入", use_container_width=True) and picked:
            for sid in picked:
                workspace.add_paper(pid, sid, role)
            st.rerun()


def _notes(pid: int) -> None:
    theme.section("项目笔记", "跨文献的想法、阶段性结论、待验证的假设都放这里。", "04")
    rows = notes.list_notes(project_id=pid, limit=50)
    for n in rows:
        st.markdown(
            f'<div class="sm-card tight"><div style="display:flex;justify-content:space-between;">'
            f'<div style="font-size:11.5px;color:#a8822f;">{theme.esc(n["kind"])}</div>'
            f'<div style="font-size:11px;color:#a5adb2;">'
            f'{dt.datetime.fromtimestamp(n["at"]).strftime("%m-%d %H:%M")}</div></div>'
            f'<div style="font-size:13.5px;line-height:1.7;margin-top:4px;">{theme.esc(n["text"])}</div></div>',
            unsafe_allow_html=True,
        )
    with st.form(f"add_note_{pid}", clear_on_submit=True):
        c1, c2, c3 = st.columns([1, 3, 0.7])
        kind = c1.selectbox("类型", notes.KINDS, label_visibility="collapsed")
        text = c2.text_input("笔记内容", label_visibility="collapsed",
                             placeholder="例：三篇队列研究的随访都在 24 个月内，长期证据仍缺")
        if c3.form_submit_button("记录", use_container_width=True) and text.strip():
            notes.add(text.strip(), project_id=pid, kind=kind)
            st.rerun()


def _detail(pid: int) -> None:
    p = workspace.get(pid)
    if not p:
        return
    theme.section(p["name"], p.get("question") or "", "00")
    c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
    new_status = c1.selectbox("状态", workspace.STATUSES,
                              index=workspace.STATUSES.index(p["status"])
                              if p["status"] in workspace.STATUSES else 0)
    if new_status != p["status"]:
        workspace.update(pid, status=new_status)
        st.rerun()
    c2.metric("进度", f'{p["progress"]}%')
    c3.metric("文献", p["papers"])
    c4.metric("笔记", p["notes"])

    with st.expander("编辑项目信息", expanded=False):
        name = st.text_input("名称", value=p["name"], key=f"pn_{pid}")
        question = st.text_input("研究问题", value=p["question"], key=f"pq_{pid}")
        desc = st.text_area("背景与目标", value=p["description"], key=f"pd_{pid}", height=90)
        c5, c6 = st.columns([1, 1])
        if c5.button("保存", key=f"psave_{pid}", use_container_width=True):
            workspace.update(pid, name=name, question=question, description=desc)
            st.rerun()
        if c6.button("删除项目", key=f"pdel_{pid}", use_container_width=True):
            workspace.delete(pid)
            st.session_state.pop("pid", None)
            st.rerun()

    _milestones(pid)
    _papers(pid)
    _notes(pid)

    st.download_button("导出项目快照（JSON）", workspace.export(pid).encode("utf-8"),
                       file_name=f"project_{pid}.json")


def render() -> None:
    theme.hero(
        "研究项目",
        "一个课题 = 一个研究问题 + 一批带角色的文献 + 一组里程碑 + 若干笔记。"
        "首页的项目进度条就是从这里算出来的。",
        "PROJECTS · 项目",
    )
    ov = workspace.overview()
    theme.stats([
        ("项目总数", str(ov["total"]), "个"),
        ("进行中", str(ov["active"]), "个"),
        ("关联文献", str(ov["papers"]), "篇"),
        ("里程碑完成", f'{ov["done"]}/{ov["milestones"]}', ""),
    ])

    _create()
    _list()
    pid = st.session_state.get("pid")
    if pid and workspace.get(pid):
        _detail(pid)
