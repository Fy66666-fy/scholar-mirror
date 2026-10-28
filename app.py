"""文献镜像 ScholarMirror —— 跨学科文献摘要与关联分析系统。

入口只做三件事：页面配置、侧边栏导航、按路由分发。
所有业务逻辑都在 core/ 里，页面在 ui/pages/ 里，互不依赖。
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

st.set_page_config(
    page_title="文献镜像 ScholarMirror",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

from core import library  # noqa: E402
from ui import state, theme  # noqa: E402
from ui.pages import cluster_page, dedupe_page, gaps_page, graph_page, home, library_page, search_page, summary_page  # noqa: E402

PAGES = {
    "首页": ("bi-house-door", home.render),
    "文献检索": ("bi-search", search_page.render),
    "摘要工坊": ("bi-file-earmark-text", summary_page.render),
    "查重中心": ("bi-shield-check", dedupe_page.render),
    "关联图谱": ("bi-diagram-3", graph_page.render),
    "主题聚类": ("bi-grid-3x3-gap", cluster_page.render),
    "缺口与方向": ("bi-compass", gaps_page.render),
    "我的文献库": ("bi-collection", library_page.render),
}

_MENU_STYLE = {
    "container": {"padding": "0", "background-color": "transparent"},
    "icon": {"color": "#8fb0bb", "font-size": "15px"},
    "nav-link": {
        "font-size": "14px", "text-align": "left", "margin": "2px 0",
        "padding": "9px 12px", "border-radius": "9px", "color": "#dbe6ea",
        "--hover-color": "rgba(255,255,255,.07)",
    },
    "nav-link-selected": {"background-color": "#2b6577", "color": "#ffffff", "font-weight": "600"},
}


def _sidebar() -> str:
    with st.sidebar:
        st.markdown(
            """
            <div style="padding:6px 2px 14px;">
              <div style="display:flex;align-items:center;gap:9px;">
                <div style="width:30px;height:30px;border-radius:8px;background:#2b6577;
                     display:flex;align-items:center;justify-content:center;color:#fff;
                     font-size:15px;font-weight:700;">◈</div>
                <div>
                  <div style="font-size:15px;font-weight:700;color:#fff;letter-spacing:.02em;">文献镜像</div>
                  <div style="font-size:10.5px;color:#8fb0bb;letter-spacing:.14em;">SCHOLAR MIRROR</div>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        pending = st.session_state.pop("_goto", None)
        names = list(PAGES)
        if pending in names:
            st.session_state["nav"] = pending

        try:
            from streamlit_option_menu import option_menu
            page = option_menu(
                None, names,
                icons=[PAGES[n][0] for n in names],
                default_index=0,
                styles=_MENU_STYLE,
                key="nav",
                menu_icon="cast",
            )
        except Exception:  # 插件缺失时降级为原生单选，不影响功能
            page = st.radio("导航", names, key="nav", label_visibility="collapsed")

        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
        st.markdown(
            "<div style='font-size:11px;color:#8fb0bb;letter-spacing:.08em;'>当前数据池</div>",
            unsafe_allow_html=True,
        )
        ps = state.papers()
        if ps:
            years = [p["year"] for p in ps if p.get("year")]
            st.markdown(
                f"<div style='font-size:12.5px;color:#dbe6ea;line-height:1.9;'>"
                f"文献 {len(ps)} 篇<br>"
                f"年份 {min(years) if years else '—'}–{max(years) if years else '—'}<br>"
                f"主题 {state.analysis()['cluster']['k']} 个方向</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                "<div style='font-size:12.5px;color:#8fb0bb;line-height:1.9;'>"
                "还没有检索结果<br>从「文献检索」开始</div>",
                unsafe_allow_html=True,
            )

        st.markdown("<hr style='margin:16px 0 12px;'>", unsafe_allow_html=True)
        try:
            n = library.stats()["papers"]
        except Exception:
            n = 0
        st.markdown(
            f"<div style='font-size:11.5px;color:#8fb0bb;line-height:1.8;'>"
            f"本地文献库 {n} 篇<br>数据源 6 个 · 全离线算法</div>",
            unsafe_allow_html=True,
        )
    return page


def main() -> None:
    theme.inject()
    state.init()

    # ?demo=1 直接载入内置演示数据，方便第一次打开或离线时看效果
    try:
        if st.query_params.get("demo") and not st.session_state.get("_demo_loaded"):
            state.load_demo()
            st.session_state["_demo_loaded"] = True
            st.session_state["_goto"] = "文献检索"
    except Exception:
        pass

    page = _sidebar()
    render = PAGES.get(page, PAGES["首页"])[1]
    render()

    st.markdown(
        '<div class="sm-foot">文献镜像 ScholarMirror · 抽取式摘要与关联分析 · '
        "所有摘要均来自原文原句，未做生成式改写；分析结论用于辅助判断，不替代同行评议。</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
