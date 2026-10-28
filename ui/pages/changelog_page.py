"""更新日志：把 CHANGELOG.md 渲染成时间线，顺便把路线图也放进来。"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from core import changelog
from ui import theme
import version

ROADMAP = Path(__file__).resolve().parent.parent.parent / "ROADMAP.md"


def _release(rel: dict, latest: bool) -> None:
    tag = theme.pill("当前版本", "ok") if latest else ""
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:10px;margin:22px 0 6px;">'
        f'<span style="font-size:22px;font-weight:700;letter-spacing:-.02em;">v{theme.esc(rel["version"])}</span>'
        f'<span style="font-size:12.5px;color:#8b9499;">{theme.esc(rel["date"])}</span>{tag}</div>',
        unsafe_allow_html=True,
    )
    for sec in rel["sections"]:
        tone = changelog.tone(sec["title"])
        st.markdown(
            f'<div style="margin:12px 0 4px;">{theme.pill(sec["title"], tone)}</div>',
            unsafe_allow_html=True,
        )
        for item in sec["items"]:
            title = f'<b>{theme.esc(item["title"])}</b>：' if item["title"] else ""
            st.markdown(
                f'<div style="display:flex;gap:9px;padding:4px 0 4px 4px;'
                f'border-left:2px solid #ece7dd;margin-left:2px;">'
                f'<div style="flex:1;font-size:13.2px;line-height:1.75;color:#3d4d56;">'
                f'{title}{theme.esc(item["text"])}</div></div>',
                unsafe_allow_html=True,
            )


def render() -> None:
    theme.hero(
        "更新日志",
        "每个版本改了什么、为什么改。路线图在第二个标签页，按 P0–P4 分阶段。",
        "CHANGELOG · 版本",
    )
    rels = changelog.parse()
    stt = changelog.stats()
    theme.stats([
        ("当前版本", f'v{version.__version__}', ""),
        ("代号", version.__codename__, ""),
        ("发布次数", str(stt["releases"]), "次"),
        ("变更条目", str(stt["items"]), "条"),
    ])

    tab1, tab2 = st.tabs(["更新日志", "路线图"])
    with tab1:
        if not rels:
            theme.empty("还没有记录", "CHANGELOG.md 为空或格式不符。")
        for i, rel in enumerate(rels):
            _release(rel, latest=(i == 0))
        theme.method_note(
            "版本语义：0.x 阶段每个次版本号对应一个可用里程碑，不表示不兼容。"
            "破坏性变更会在条目里单独标注。"
        )
    with tab2:
        if ROADMAP.exists():
            st.markdown(ROADMAP.read_text(encoding="utf-8"))
        else:
            theme.empty("还没有路线图", "在项目根目录放一个 ROADMAP.md 即可在这里显示。")
