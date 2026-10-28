"""我的文献库：书架 + 标签 + 阅读状态 + 笔记，四维管理。

和 v0.1 的差别：那时只有「收藏列表」，现在是工作台的资产层 ——
能导入已有文献（BibTeX/RIS）、能批量整理、能给每篇写摘录与笔记、
能查重清理、能挂到项目下。
"""
from __future__ import annotations

import datetime as dt

import streamlit as st

from core import export, importer, library, notes, schema, workspace
from core import text as T
from ui import theme

STATES = ["未读", "在读", "已读", "重点"]


def _import_panel() -> None:
    with st.expander("导入已有文献（BibTeX / RIS / JSON）", expanded=False):
        st.caption("从 Zotero、EndNote、知网导出的文件可以直接拖进来；也可以把内容粘到下面。"
                   "按 DOI 或标题去重，已存在的只合并标签。")
        up = st.file_uploader("上传文件", type=["bib", "ris", "txt", "json", "nbib"],
                              label_visibility="collapsed")
        text = st.text_area("或粘贴内容", height=140, placeholder="@article{...} 或 TY  - JOUR ...")
        c1, c2 = st.columns([2, 1])
        group = c1.text_input("导入到书架", value="导入")
        if c2.button("解析并导入", type="primary", use_container_width=True):
            raw = ""
            name = ""
            if up is not None:
                raw = up.read().decode("utf-8", errors="ignore")
                name = up.name
            elif text.strip():
                raw = text
            if not raw.strip():
                st.warning("先上传文件或粘贴内容。")
                return
            papers, fmt = importer.parse_auto(raw, name)
            if not papers:
                st.error("没解析出条目。确认格式是 BibTeX / RIS / JSON。")
                return
            added = library.save(papers, group=group or "导入")
            from core import activity
            activity.log("导入", f"{fmt} 导入 {len(papers)} 条，新增 {added} 条")
            st.success(f"识别为 {fmt}：解析 {len(papers)} 条，新增 {added} 条（其余已存在）")
            st.rerun()


def _duplicates() -> None:
    dups = library.duplicates()
    with st.expander(f"库内查重（{len(dups)} 对疑似重复）", expanded=False):
        if not dups:
            st.caption("没有发现高度重复的条目。")
            return
        for d in dups[:20]:
            st.markdown(
                f'<div class="sm-card tight"><div style="display:flex;justify-content:space-between;">'
                f'<span class="sm-pill warn">{d["score"]:.2f}</span>'
                f'<span style="font-size:11.5px;color:#6b767c;">{theme.esc(d["kind"])}</span></div>'
                f'<div style="font-size:13px;margin-top:6px;">{theme.esc(T.shorten(d["a_title"], 80))}</div>'
                f'<div style="font-size:13px;color:#6b767c;">{theme.esc(T.shorten(d["b_title"], 80))}</div>'
                f'<div style="font-size:12px;color:#8b9499;margin-top:5px;">建议：{theme.esc(d["advice"])}</div>'
                f'</div>', unsafe_allow_html=True,
            )
            c1, c2 = st.columns(2)
            if c1.button("保留前者", key=f"keepA_{d['a_sid']}_{d['b_sid']}", use_container_width=True):
                library.remove([d["b_sid"]])
                st.rerun()
            if c2.button("保留后者", key=f"keepB_{d['a_sid']}_{d['b_sid']}", use_container_width=True):
                library.remove([d["a_sid"]])
                st.rerun()


def _toolbar(groups: list[tuple[str, int]], tags: list[tuple[str, int]]) -> dict:
    c1, c2, c3, c4 = st.columns([1.2, 1.4, 1, 1.4])
    group = c1.selectbox("书架", ["全部"] + [g for g, _ in groups])
    tag = c2.multiselect("标签", [t for t, _ in tags])
    state = c3.selectbox("状态", ["全部"] + STATES)
    kw = c4.text_input("关键词", placeholder="标题 / 笔记 / 标签")
    sort = st.radio("排序", ["入库时间", "发表年份", "被引次数", "标题"], horizontal=True,
                    label_visibility="collapsed")
    return {"group": group, "tags": tag, "state": state, "kw": kw, "sort": sort}


def _apply(items: list[dict], cfg: dict) -> list[dict]:
    out = library.list_papers(
        group=None if cfg["group"] == "全部" else cfg["group"],
        tag=cfg["tags"][0] if cfg["tags"] else None,
        state=None if cfg["state"] == "全部" else cfg["state"],
        q=cfg["kw"] or "",
    )
    if len(cfg["tags"]) > 1:
        out = [p for p in out if set(cfg["tags"]) <= set(p.get("_tags") or [])]
    if cfg["sort"] == "发表年份":
        out.sort(key=lambda p: -(p.get("year") or 0))
    elif cfg["sort"] == "被引次数":
        out.sort(key=lambda p: -(p.get("cited_by") or 0))
    elif cfg["sort"] == "标题":
        out.sort(key=lambda p: (p.get("title") or "").lower())
    return out


def _batch(items: list[dict], groups: list[tuple[str, int]]) -> None:
    with st.expander(f"批量整理（当前 {len(items)} 篇）", expanded=False):
        options = {p["sid"]: T.shorten(p.get("title", ""), 60) for p in items}
        picked = st.multiselect("选择文献", list(options), format_func=lambda s: options[s])
        c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
        target_group = c1.text_input("移动到书架", value=groups[0][0] if groups else "未分组")
        target_state = c2.selectbox("设为状态", STATES)
        target_tag = c3.text_input("加标签")
        if c4.button("执行", type="primary", use_container_width=True) and picked:
            if target_group:
                library.bulk_update(picked, group_name=target_group)
            if target_state:
                library.bulk_update(picked, state=target_state)
            if target_tag:
                for sid in picked:
                    cur = library.get(sid)
                    if cur:
                        merged = ",".join(list(dict.fromkeys((cur.get("_tags") or []) + [target_tag])))
                        library.update(sid, tags=merged)
            st.success(f"已更新 {len(picked)} 篇")
            st.rerun()
        c5, c6 = st.columns([1, 4])
        if c5.button("删除所选", use_container_width=True) and picked:
            library.remove(picked)
            st.rerun()
        c6.caption("删除只影响文献库，不影响检索结果。")


def _paper(p: dict, groups: list[tuple[str, int]], projects: list[dict]) -> None:
    sid = p["sid"]
    badges = list(p.get("_tags") or [])[:4]
    if p.get("_state"):
        badges.insert(0, p["_state"])
    with st.expander(f'{p.get("_state", "")} · {T.shorten(p.get("title", ""), 82)}', expanded=False):
        st.markdown(
            f'<div class="sm-meta">{theme.esc(schema.venue_year(p))} · '
            f'{theme.esc(schema.display_authors(p))} · '
            f'{theme.esc(schema.DESIGN_LABELS.get(p.get("design"), "未识别"))}'
            f'{" · 被引 " + str(p.get("cited_by")) if p.get("cited_by") else ""}</div>',
            unsafe_allow_html=True,
        )
        if p.get("abstract"):
            st.markdown(f'<div class="sm-abs">{theme.esc(T.shorten(p["abstract"], 900))}</div>',
                        unsafe_allow_html=True)
        st.markdown(theme.pills(badges, "solid"), unsafe_allow_html=True)

        c1, c2, c3, c4 = st.columns([1.4, 1, 1, 1])
        group_names = [g for g, _ in groups] or ["未分组"]
        cur_group = p.get("_group") or "未分组"
        new_group = c1.selectbox("书架", group_names,
                                 index=group_names.index(cur_group) if cur_group in group_names else 0,
                                 key=f"lg_{sid}")
        new_state = c2.selectbox("状态", STATES,
                                 index=STATES.index(p.get("_state")) if p.get("_state") in STATES else 0,
                                 key=f"ls_{sid}")
        new_tags = c3.text_input("标签", value=",".join(p.get("_tags") or []), key=f"lt_{sid}")
        if c4.button("保存", key=f"lsave_{sid}", use_container_width=True):
            library.update(sid, group=new_group, state=new_state, tags=new_tags)
            st.rerun()

        st.markdown('<div class="sm-hint" style="margin-top:6px;">笔记与摘录</div>', unsafe_allow_html=True)
        for n in notes.list_notes(sid=sid, limit=20):
            when = dt.datetime.fromtimestamp(n["at"]).strftime("%m-%d %H:%M")
            st.markdown(
                f'<div class="sm-card tight" style="margin-bottom:6px;">'
                f'<div style="display:flex;justify-content:space-between;">'
                f'<span style="font-size:11.5px;color:#a8822f;">{theme.esc(n["kind"])}</span>'
                f'<span style="font-size:11px;color:#a5adb2;">{when}</span></div>'
                f'<div style="font-size:13px;line-height:1.7;margin-top:3px;">{theme.esc(n["text"])}</div>'
                + (f'<div class="sm-quote" style="margin-top:5px;">{theme.esc(n["quote"])}</div>'
                   if n.get("quote") else "")
                + '</div>', unsafe_allow_html=True,
            )

        with st.form(f"note_{sid}"):
            c5, c6, c7 = st.columns([1, 3, 0.8])
            kind = c5.selectbox("类型", notes.KINDS, label_visibility="collapsed",
                                key=f"nk_{sid}")
            text = c6.text_input("内容", label_visibility="collapsed",
                                 placeholder="摘录原文，或写下你的判断", key=f"nt_{sid}")
            if c7.form_submit_button("记录", use_container_width=True) and text.strip():
                notes.add(text.strip(), sid=sid, kind=kind)
                st.rerun()

        c8, c9, c10, c11 = st.columns([1, 1.4, 1, 1])
        if projects and c8.button("加入项目", key=f"lproj_{sid}", use_container_width=True):
            st.session_state[f"showproj_{sid}"] = True
        if st.session_state.get(f"showproj_{sid}") and projects:
            target = c9.selectbox("项目", [x["name"] for x in projects],
                                  key=f"pj_{sid}", label_visibility="collapsed")
            pid = next(x["id"] for x in projects if x["name"] == target)
            if c10.button("确认加入", key=f"pjok_{sid}", use_container_width=True):
                workspace.add_paper(pid, sid, "核心")
                st.success("已加入项目")
        c11.download_button("BibTeX", export.to_bibtex([p]).encode("utf-8"),
                            file_name=f"{sid.replace(':', '_')}.bib", key=f"lbib_{sid}",
                            use_container_width=True)
        if st.button("移出文献库", key=f"ldel_{sid}"):
            library.remove([sid])
            st.rerun()


def render() -> None:
    theme.hero(
        "我的文献库",
        "书架管课题，标签管跨课题的维度，状态管阅读进度，笔记管你自己的想法。"
        "全部存在本机 data/mirror.db，不上传任何地方。",
        "LIBRARY · 文献库",
    )
    stt = library.stats()
    theme.stats([
        ("收藏文献", str(stt["papers"]), "篇"),
        ("书架", str(stt["groups"]), "个"),
        ("在读", str(stt["states"].get("在读", 0)), "篇"),
        ("已读", str(stt["states"].get("已读", 0)), "篇"),
        ("重点", str(stt["states"].get("重点", 0)), "篇"),
    ])

    _import_panel()

    groups = library.groups()
    tags = library.tags()
    cfg = _toolbar(groups, tags)
    items = _apply([], cfg)

    if not items:
        theme.empty("没有符合条件的文献", "换个筛选条件，或用上面的导入面板把已有文献搬进来。")
        return

    st.caption(f"共 {len(items)} 篇")
    c1, c2, c3 = st.columns(3)
    c1.download_button("导出 BibTeX", export.to_bibtex(items).encode("utf-8"),
                       file_name="library.bib", use_container_width=True)
    c2.download_button("导出 RIS", export.to_ris(items).encode("utf-8"),
                       file_name="library.ris", use_container_width=True)
    c3.download_button("导出 XLSX", export.to_xlsx(items), file_name="library.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)

    _batch(items, groups)
    _duplicates()

    theme.section("条目", "点开可以改书架/状态/标签、写笔记、加入项目。", "01")
    projects = workspace.list_projects()
    for p in items:
        _paper(p, groups, projects)

    if groups:
        theme.section("书架概览", "", "02")
        theme.table(["书架", "文献数"], [[theme.esc(g), str(n)] for g, n in groups])
