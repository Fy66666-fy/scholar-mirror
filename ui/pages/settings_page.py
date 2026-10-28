"""设置：数据管理、默认值、关于。

关于页承接了 v0.1 首页的「它能做什么 / 数据从哪来 / 边界」——
用过几天的人不需要每天看功能列表，但第一次用的人需要一个地方能读到。
"""
from __future__ import annotations

import json
import shutil
import time

import streamlit as st

from core import activity, db, http, library, profile, stats
from core.sources import SOURCE_INFO
from ui import theme
import version


def _data() -> None:
    h = stats.health()
    theme.stats([
        ("库文件", f'{h["db"]["size_mb"]}', "MB"),
        ("文献", str(h["db"]["counts"].get("papers", 0)), "篇"),
        ("缓存文件", str(h["cache_files"]), "个"),
        ("缓存占用", f'{h["cache_mb"]}', "MB"),
    ])
    theme.section("数据库", "所有个人数据都在这一个文件里，拷走就是完整备份。", "01")
    theme.table(
        ["表", "行数"],
        [[theme.esc(k), str(v)] for k, v in h["db"]["counts"].items()],
    )
    st.caption(f"路径：{h['db']['path']}")

    c1, c2, c3 = st.columns(3)
    if c1.button("清理请求缓存", use_container_width=True):
        n = http.clear_cache()
        st.success(f"清掉 {n} 个缓存文件。下次检索会重新请求。")
    if c2.button("清空活动记录", use_container_width=True):
        n = activity.clear()
        st.success(f"删除 {n} 条活动记录。")
    with c3:
        if db.DB_PATH.exists():
            st.download_button("下载数据库备份", db.DB_PATH.read_bytes(),
                               file_name=f"mirror-{time.strftime('%Y%m%d')}.db",
                               use_container_width=True)

    theme.section("导入 / 导出", "", "02")
    c4, c5 = st.columns(2)
    payload = json.dumps({"interests": profile.list_interests(), "seeds": profile.seeds()},
                         ensure_ascii=False, indent=2)
    c4.download_button("导出研究画像", payload.encode("utf-8"),
                       file_name="research_profile.json", use_container_width=True)
    papers = library.list_papers()
    from core import export
    c5.download_button("导出全部文献（BibTeX）",
                       export.to_bibtex(papers).encode("utf-8"),
                       file_name="library_all.bib", use_container_width=True)


def _defaults() -> None:
    theme.section("默认值", "这些只影响界面初始状态，不改变已有数据。", "03")
    c1, c2 = st.columns(2)
    per = c1.selectbox("检索每源条数", [10, 15, 25, 40],
                       index=[10, 15, 25, 40].index(int(library.get_kv("default_per", "15") or 15))
                       if (library.get_kv("default_per", "15") or "15").isdigit() else 1)
    k = c2.slider("推荐条数", 5, 40, int(library.get_kv("default_k", "15") or 15), 5)
    if st.button("保存默认值", type="primary"):
        library.set_kv("default_per", str(per))
        library.set_kv("default_k", str(k))
        st.success("已保存")

    theme.section("数据源", "全部免注册。单源失败会自动降级，不影响其余结果。", "04")
    theme.table(
        ["数据源", "说明", "强项"],
        [[f"<b>{theme.esc(v['label'])}</b>", theme.esc(v["desc"]),
          f'<span class="sm-pill">{theme.esc(v["strength"])}</span>']
         for v in SOURCE_INFO.values()],
    )
    s = http.stats()
    if s:
        rows = []
        for host, v in list(s.items())[:10]:
            rows.append([theme.esc(host), str(v.get("ok", 0)), str(v.get("cache", 0)),
                         str(v.get("fail", 0)), theme.esc((v.get("last_error") or "")[:60])])
        theme.table(["域名", "成功", "缓存命中", "失败", "最近错误"], rows)


def _about() -> None:
    theme.section("它是什么", "", "05")
    theme.card(
        '<div style="font-size:14.5px;line-height:1.85;">'
        "文献镜像是跨学科的文献摘要与关联分析工作台：检索聚合、结构化摘要、查重、"
        "关联图谱、主题聚类、研究缺口、个性化推荐，全部在本地完成。"
        "<b>不调用大模型，不需要 API Key，不花额度。</b><br>"
        "所有摘要句都来自论文原文，系统只做「选哪一句、放在哪一栏」；"
        "分析结论用于辅助判断，不替代同行评议。</div>",
        tone="accent",
    )

    theme.section("八个能力", "", "06")
    items = [
        ("六源检索", "OpenAlex / Crossref / arXiv / PubMed / Europe PMC / Semantic Scholar，并发、去重、降级"),
        ("结构化摘要", "六套学科模板，六个统一槽位，每句可回溯原文"),
        ("三层查重", "跨源合并、近似重复（预印本↔正式版）、逐句文本查重"),
        ("关联图谱", "文本/概念/引用/元数据四信号，力导向布局，边可解释"),
        ("聚类与精选", "轮廓系数选 k，精选分五项可解释"),
        ("缺口与方向", "10 条可核对规则，每条带证据原句与可检验问题"),
        ("研究画像与推荐", "显式方向 + 种子文献，五路打分 + MMR 多样性"),
        ("项目与文献库", "书架/标签/状态/笔记，里程碑与进度，BibTeX/RIS 导入导出"),
    ]
    cols = st.columns(2)
    for i, (t, d) in enumerate(items):
        with cols[i % 2]:
            theme.card(
                f'<div style="font-size:14px;font-weight:700;">{t}</div>'
                f'<div style="font-size:12.8px;color:#4a5a63;line-height:1.7;margin-top:4px;">{d}</div>',
                tone="tight",
            )

    theme.section("边界", "", "07")
    for line in [
        "摘要是抽取式的，不会替你润色；抽不到就写「摘要未提及」，不生成。",
        "只看标题与摘要，正文里写了但摘要没写的，会被归到「报告完整性」而不是「研究缺陷」。",
        "缺口分析不评价单篇质量，只说明这批文献在哪些维度上同质或缺失。",
        "结论冲突只提示方向不一致，不裁定谁对谁错。",
        "聚类边界是人为的，轮廓系数 0.1 上下说明文献本身连续。",
        "文本查重只比对摘要与标题，不等于全文查重。",
    ]:
        st.markdown(f'<div style="font-size:13px;color:#4a5a63;line-height:1.8;">· {line}</div>',
                    unsafe_allow_html=True)

    theme.section("版本", "", "08")
    st.markdown(
        f'<div style="font-size:13px;color:#4a5a63;line-height:1.9;">'
        f'v{version.__version__}（{version.__codename__}）· {version.__release_date__}<br>'
        f'与 med-lit-system 的关系：复用其摘要与请求层思路，新增学科模板层、查重、图谱、'
        f'聚类、缺口、画像与推荐。两者互不依赖。</div>',
        unsafe_allow_html=True,
    )


def render() -> None:
    theme.hero(
        "设置",
        "数据管理、默认值与产品说明。所有数据都在本机，卸载即删除。",
        "SETTINGS · 设置",
    )
    tab1, tab2, tab3 = st.tabs(["数据与缓存", "默认值与数据源", "关于"])
    with tab1:
        _data()
    with tab2:
        _defaults()
    with tab3:
        _about()
