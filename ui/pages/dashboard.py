"""工作台首页：以「今天」为单位，而不是以「功能」为单位。

设计上刻意去掉了大标题和指标卡片墙 —— 那套东西第一眼好看，第二天就变成噪音。
这里只回答三个问题：
    今天该读什么（阅读队列 + 未读）
    今天能推进什么（项目里下一个没完成的里程碑）
    哪里还是空白（画像里有方向但库里没文献）
"""
from __future__ import annotations

import datetime as dt

import streamlit as st

from core import library, notes, profile, stats, workspace
from ui import state, theme

_WEEK = "一二三四五六日"


def _masthead(data: dict) -> None:
    lib = data["library"]
    today = dt.date.today()
    proj = data["project_stats"]
    st.markdown(
        f'<div style="display:flex;justify-content:space-between;align-items:baseline;'
        f'border-bottom:1px solid #e4ded3;padding-bottom:10px;margin-bottom:18px;">'
        f'<div style="font-size:13px;color:#6b767c;">'
        f'{today.year} 年 {today.month} 月 {today.day} 日　周{_WEEK[today.weekday()]}</div>'
        f'<div style="font-size:12.5px;color:#8b9499;">'
        f'库里 {lib["papers"]} 篇　·　待读 {data["reading"]["pending"]} 篇　·　'
        f'{proj["active"]} 个项目在推进　·　连续 {data["streak"]} 天有记录</div></div>',
        unsafe_allow_html=True,
    )


def _today(data: dict) -> None:
    lib = data["library"]
    proj = data["projects"]
    gaps = [c for c in data["coverage"] if c["papers"] == 0]

    items: list[tuple[str, str, str, str]] = []   # (标签, 标题, 说明, 跳转)
    pending = data["reading"]["pending"]
    if pending:
        high = data["reading"]["high"]
        items.append(("待读", f"队列里 {pending} 篇，其中 {high} 篇高优先",
                      "按优先级往下读，读完自动进「已读」", "待读"))
    next_ms = None
    for p in proj:
        ms = [m for m in workspace.milestones(p["id"]) if not m["done"]]
        if ms:
            next_ms = (p, ms[0])
            break
    if next_ms:
        p, m = next_ms
        items.append(("推进", f"{p['name']}：{m['title']}",
                      f"项目进度 {p['progress']}%，这是下一个没打勾的里程碑", "研究项目"))
    if gaps:
        names = "、".join(g["label"] for g in gaps[:2])
        items.append(("空白", f"方向「{names}」在库里还是 0 篇",
                      "要么去检索，要么把关键词写具体一点", "推荐"))
    if not items:
        items.append(("开始", "库里还没有文献",
                      "检索一次，或者把 Zotero 的 BibTeX 导进来", "文献检索"))

    theme.section("今天", "", "")
    cols = st.columns(min(len(items), 3))
    for col, (tag, title, desc, target) in zip(cols, items):
        with col:
            st.markdown(
                f'<div class="sm-card tight" style="min-height:104px;">'
                f'<div style="font-size:10.5px;letter-spacing:.12em;color:#a8822f;">{tag}</div>'
                f'<div style="font-size:14px;font-weight:650;line-height:1.5;margin:6px 0 4px;">'
                f'{theme.esc(title)}</div>'
                f'<div style="font-size:12.3px;color:#6b767c;line-height:1.65;">{theme.esc(desc)}</div>'
                f'</div>', unsafe_allow_html=True,
            )
            if st.button(f"{target} →", key=f"today_{target}_{tag}", use_container_width=True):
                st.session_state["_goto"] = target
                st.rerun()


def _queue(queue: list[dict]) -> None:
    theme.section("阅读队列", "来自待读队列，高优先在前。", "")
    if not queue:
        st.caption("队列是空的。")
        return
    for p in queue:
        meta = " · ".join(x for x in [p.get("_group"), p.get("_state")] if x)
        st.markdown(
            f'<div style="padding:9px 0;border-bottom:1px dashed #ece7dd;">'
            f'<div style="font-size:13.5px;font-weight:600;line-height:1.5;">'
            f'{theme.esc(p.get("title", ""))}</div>'
            f'<div style="font-size:11.8px;color:#8b9499;margin-top:2px;">'
            f'{theme.esc(str(p.get("year") or "—"))}　{theme.esc(meta)}</div></div>',
            unsafe_allow_html=True,
        )


def _notes_panel() -> None:
    rows = notes.list_notes(limit=5)
    theme.section("最近笔记", "", "")
    if not rows:
        st.caption("还没有笔记。读到关键处按一下「记一笔」，比事后回忆靠谱。")
        return
    for n in rows:
        when = dt.datetime.fromtimestamp(n["at"]).strftime("%m-%d")
        st.markdown(
            f'<div style="padding:7px 0;border-bottom:1px dashed #ece7dd;">'
            f'<div style="font-size:12.8px;line-height:1.65;">{theme.esc(n["text"][:90])}</div>'
            f'<div style="font-size:11px;color:#a5adb2;margin-top:2px;">'
            f'{when}　{theme.esc(n["kind"])}</div></div>',
            unsafe_allow_html=True,
        )


def _projects(projects: list[dict]) -> None:
    theme.section("在做的项目", "", "")
    if not projects:
        st.caption("还没有项目。项目把文献、里程碑和笔记绑在一个研究问题下。")
        return
    for p in projects:
        st.markdown(
            f'<div style="padding:9px 0;border-bottom:1px dashed #ece7dd;">'
            f'<div style="display:flex;justify-content:space-between;gap:10px;">'
            f'<div style="font-size:13.5px;font-weight:600;">{theme.esc(p["name"])}</div>'
            f'<div style="font-size:11.5px;color:#8b9499;">{p["progress"]}%</div></div>'
            f'<div style="font-size:12px;color:#6b767c;margin-top:2px;">'
            f'{theme.esc((p["question"] or "未填写研究问题")[:48])}</div>'
            f'<div class="sm-bar" style="margin-top:7px;"><i style="width:{p["progress"]}%"></i></div>'
            f'</div>', unsafe_allow_html=True,
        )


def _activity(rows: list[dict]) -> None:
    theme.section("最近操作", "", "")
    if not rows:
        st.caption("还没有记录。")
        return
    for r in rows:
        when = dt.datetime.fromtimestamp(r["at"]).strftime("%m-%d %H:%M")
        st.markdown(
            f'<div style="display:flex;gap:9px;padding:5px 0;font-size:12.5px;">'
            f'<span style="color:#a5adb2;min-width:74px;font-variant-numeric:tabular-nums;">{when}</span>'
            f'<span style="color:#8b9499;min-width:38px;">{theme.esc(r["kind"])}</span>'
            f'<span style="color:#3d4d56;flex:1;">{theme.esc(r["detail"][:64])}</span></div>',
            unsafe_allow_html=True,
        )


def _coverage(coverage: list[dict]) -> None:
    if not coverage:
        return
    theme.section("方向覆盖", "画像里的方向在库里的文献数，空白的地方值得先补。", "")
    for c in coverage:
        st.markdown(theme.bar(c["label"], c["share"], 100, "%"), unsafe_allow_html=True)


def render() -> None:
    data = stats.dashboard()
    lib = data["library"]

    if not profile.is_ready() and lib["papers"] == 0:
        st.markdown(
            '<div style="font-size:15px;line-height:1.9;max-width:640px;color:#3d4d56;margin-bottom:8px;">'
            '第一次用的话，先做三件事：写一个研究方向、检索或导入一批文献、把它们放进一个项目。'
            '之后这一页会变成你的日常视图。</div>',
            unsafe_allow_html=True,
        )
        c1, c2, c3 = st.columns(3)
        for col, (label, target) in zip((c1, c2, c3),
                                        [("写研究方向", "研究画像"), ("检索文献", "文献检索"),
                                         ("建项目", "研究项目")]):
            with col:
                if st.button(label, key=f"ob_{target}", use_container_width=True):
                    st.session_state["_goto"] = target
                    st.rerun()
        if st.button("先载入演示数据", key="ob_demo"):
            state.load_demo(seed_workspace=True)
            st.rerun()
        return

    _masthead(data)
    _today(data)

    left, right = st.columns([1.5, 1])
    with left:
        _queue(data["queue"])
        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
        _projects(data["projects"])
        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)
        _notes_panel()
    with right:
        _activity(data["activity"])
        _coverage(data["coverage"])
        if data["history"]:
            theme.section("最近检索", "", "")
            for h in data["history"][:3]:
                st.markdown(
                    f'<div style="font-size:12.3px;color:#4a5a63;padding:3px 0;">'
                    f'{theme.esc(h["query"])}'
                    f'<span style="color:#a5adb2;">　{h["n"]} 篇</span></div>',
                    unsafe_allow_html=True,
                )

    theme.section("", "", "")
    c1, c2, c3, c4, c5 = st.columns(5)
    for col, (label, target) in zip(
        (c1, c2, c3, c4, c5),
        [("检索", "文献检索"), ("推荐", "推荐"), ("文献库", "文献库"),
         ("缺口分析", "缺口与方向"), ("设置", "设置")],
    ):
        with col:
            if st.button(label, key=f"qa_{target}", use_container_width=True):
                st.session_state["_goto"] = target
                st.rerun()
