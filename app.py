"""文献镜像 ScholarMirror —— 跨学科文献研究工作台。

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

from core import library, profile  # noqa: E402
from ui import state, theme  # noqa: E402
from ui.pages import (  # noqa: E402
    changelog_page, cluster_page, dashboard, dedupe_page, gaps_page,
    graph_page, library_page, profile_page, projects_page, recommend_page,
    search_page, settings_page, summary_page,
)
import version  # noqa: E402

# 分组只是为了「找得到」，路由仍是扁平字典
GROUPS: list[tuple[str, list[str]]] = [
    ("研究", ["工作台", "文献检索", "摘要工坊", "文献库", "研究项目", "推荐", "研究画像"]),
    ("分析", ["查重中心", "关联图谱", "主题聚类", "缺口与方向"]),
    ("系统", ["更新日志", "设置"]),
]

PAGES = {
    "工作台": dashboard.render,
    "文献检索": search_page.render,
    "摘要工坊": summary_page.render,
    "文献库": library_page.render,
    "研究项目": projects_page.render,
    "推荐": recommend_page.render,
    "研究画像": profile_page.render,
    "查重中心": dedupe_page.render,
    "关联图谱": graph_page.render,
    "主题聚类": cluster_page.render,
    "缺口与方向": gaps_page.render,
    "更新日志": changelog_page.render,
    "设置": settings_page.render,
}

DEFAULT_PAGE = "工作台"


def _sidebar() -> str:
    with st.sidebar:
        st.markdown(
            """
            <div style="padding:4px 2px 12px;">
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
        if pending in PAGES:
            st.session_state["nav"] = pending
        current = st.session_state.get("nav", DEFAULT_PAGE)
        if current not in PAGES:
            current = DEFAULT_PAGE

        for group, items in GROUPS:
            st.markdown(
                f'<div style="font-size:10.5px;letter-spacing:.14em;color:#7fa3b0;'
                f'margin:12px 0 3px 4px;">{group.upper()}</div>',
                unsafe_allow_html=True,
            )
            for name in items:
                if st.button(name, key=f"nav_{name}", use_container_width=True,
                             type="primary" if name == current else "secondary"):
                    st.session_state["nav"] = name
                    st.rerun()

        st.markdown("<hr style='margin:14px 0 10px;'>", unsafe_allow_html=True)
        ps = state.papers()
        n_lib = library.stats()["papers"]
        n_int = len(profile.list_interests())
        st.markdown(
            f"<div style='font-size:11.5px;color:#8fb0bb;line-height:1.9;'>"
            f"文献池 {len(ps)} 篇<br>文献库 {n_lib} 篇 · 方向 {n_int} 个<br>"
            f"v{version.__version__} · 全离线算法</div>",
            unsafe_allow_html=True,
        )
    return current


def main() -> None:
    theme.inject()
    state.init()

    # ?demo=1 只载入演示文献池；?demo=full 额外写入示例文献库/画像/项目
    try:
        demo_mode = str(st.query_params.get("demo") or "").lower()
        if demo_mode and not st.session_state.get("_demo_loaded"):
            state.load_demo(seed_workspace=demo_mode == "full")
            st.session_state["_demo_loaded"] = True
            st.session_state["_goto"] = "工作台" if demo_mode == "full" else "文献检索"
    except Exception:
        pass

    page = _sidebar()
    PAGES.get(page, PAGES[DEFAULT_PAGE])()

    st.markdown(
        '<div class="sm-foot">文献镜像 ScholarMirror · 抽取式摘要与关联分析 · '
        "所有摘要均来自原文原句，未做生成式改写；分析结论用于辅助判断，不替代同行评议。</div>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
