"""我的文献库：分组 + 标签 + 笔记 + 阅读状态，全部存在本地 SQLite。"""
from __future__ import annotations

import streamlit as st

from core import export, library, schema
from core import text as T
from ui import state, theme

STATES = ["未读", "在读", "已读", "重点"]


def _editor(p: dict) -> None:
    sid = p["sid"]
    with st.expander(f"{T.shorten(p.get('title', ''), 88)}", expanded=False):
        st.markdown(
            f'<div class="sm-meta">{theme.esc(schema.venue_year(p))} · '
            f'{theme.esc(schema.display_authors(p))} · {theme.esc(schema.DESIGN_LABELS.get(p.get("design"), ""))}</div>',
            unsafe_allow_html=True,
        )
        if p.get("abstract"):
            st.markdown(f'<div class="sm-abs">{theme.esc(T.shorten(p["abstract"], 700))}</div>',
                        unsafe_allow_html=True)
        if p.get("doi"):
            st.markdown(f'<div class="sm-meta">DOI：{theme.esc(p["doi"])}</div>', unsafe_allow_html=True)

        c1, c2 = st.columns([1, 1])
        cur_group = p.get("_group") or "未分组"
        new_group = c1.text_input("分组", value=cur_group, key=f"g_{sid}")
        new_state = c2.selectbox("状态", STATES,
                                 index=STATES.index(p.get("_state")) if p.get("_state") in STATES else 0,
                                 key=f"s_{sid}")
        new_tags = st.text_input("标签（逗号分隔）", value=",".join(p.get("_tags") or []), key=f"t_{sid}")
        new_note = st.text_area("笔记：为什么收它 / 排除理由", value=p.get("_note") or "",
                                key=f"n_{sid}", height=90)

        c3, c4, c5 = st.columns(3)
        if c3.button("保存", key=f"save_{sid}", use_container_width=True):
            library.update(sid, group=new_group or "未分组", tags=new_tags, note=new_note, state=new_state)
            st.toast("已保存")
            st.rerun()
        if c4.button("移除", key=f"del_{sid}", use_container_width=True):
            library.remove([sid])
            st.toast("已移出文献库")
            st.rerun()
        c5.download_button("BibTeX", export.to_bibtex([p]).encode("utf-8"),
                           file_name=f"{sid.replace(':', '_')}.bib", key=f"bib_{sid}",
                           use_container_width=True)


def render() -> None:
    theme.hero(
        "我的文献库",
        "分组管课题，标签管跨课题维度（研究类型 / 方法 / 结论方向），笔记记「为什么收它」。"
        "全部存在本机 data/mirror.db，不上传任何地方。",
        "STEP 07 · KEEP",
    )
    stt = library.stats()
    theme.stats([
        ("收藏文献", str(stt["papers"]), "篇"),
        ("分组", str(stt["groups"]), "个"),
        ("已读", str(stt["states"].get("已读", 0)), "篇"),
        ("重点", str(stt["states"].get("重点", 0)), "篇"),
    ])

    groups = library.groups()
    all_tags = library.tags()
    c1, c2, c3 = st.columns([1.2, 1.6, 1.2])
    group = c1.selectbox("分组", ["全部"] + [g for g, _ in groups])
    tags = c2.multiselect("标签", [t for t, _ in all_tags])
    kw = c3.text_input("关键词", placeholder="标题或笔记里搜")

    items = library.list_papers(
        group=None if group == "全部" else group,
        tag=tags[0] if tags else None,
        q=kw or "",
    )
    if len(tags) > 1:
        items = [p for p in items if set(tags) <= set(p.get("_tags") or [])]

    if not items:
        theme.empty("文献库是空的", "在「文献检索」里点「收藏」，条目会出现在这里。")
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

    theme.section("条目", "点开可以改分组、标签、状态与笔记。", "01")
    for p in items:
        _editor(p)

    if groups:
        theme.section("分组概览", "", "02")
        rows = [[theme.esc(g), str(n)] for g, n in groups]
        theme.table(["分组", "文献数"], rows)

    theme.method_note(
        "导出为 BibTeX / RIS 时，卷期页码与团体作者在检索阶段已取回，导入 Zotero 或 EndNote 一般无需补字段；"
        "缺字段的条目在导出文件里会直接省略，不会写空值。"
    )
