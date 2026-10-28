"""文献检索页：多源并发检索 → 跨源去重 → 筛选 → 进入下游分析。"""
from __future__ import annotations

import streamlit as st

from core import export, library, schema, summarize
from core import text as T
from core.sources import SOURCE_INFO, default_sources
from ui import state, theme


def _search_form() -> None:
    with st.form("search_form"):
        c1, c2 = st.columns([3.2, 1])
        query = c1.text_input("检索式", value=st.session_state.get("query", ""),
                              placeholder="支持空格分词、\"精确短语\"、-排除词，例如：gut microbiome -review")
        discipline = c2.selectbox("学科方向", list(schema.DISCIPLINES),
                                  index=list(schema.DISCIPLINES).index(st.session_state.get("discipline", "通用 / 跨学科")))
        c3, c4, c5, c6 = st.columns([2.2, 1, 1, 1])
        sources = c3.multiselect("数据源", list(SOURCE_INFO),
                                 default=default_sources(discipline),
                                 format_func=lambda k: SOURCE_INFO[k]["label"])
        per = c4.selectbox("每源条数", [10, 15, 25, 40], index=1)
        year_from = c5.number_input("起始年份", min_value=1950, max_value=2030, value=2015, step=1)
        oa_only = c6.checkbox("仅开放获取", value=False)
        c7, c8 = st.columns([1, 3])
        zh_mode = c7.checkbox("中文文献", value=False,
                              help="给 PubMed / Europe PMC 加语言过滤，并同时查 ChinaXiv 中文预印本")
        hint = schema.DISCIPLINES.get(discipline, {}).get("hint", "")
        if zh_mode:
            st.caption("中文模式：PubMed 限 chinese[la]，Europe PMC 限 LANG:chi，并启用 ChinaXiv。"
                       "正式中文期刊（知网/万方）没有开放接口，请用文献库的导入通道。")
        elif hint:
            st.caption(f"该学科建议：{hint}")
        submitted = st.form_submit_button("检索并合并", type="primary")

    if submitted:
        q = (query or "").strip()
        if not q:
            st.warning("请输入检索主题。")
            return
        if not sources:
            st.warning("至少选择一个数据源。")
            return
        if zh_mode and "chinaxiv" not in sources:
            sources = sources + ["chinaxiv"]
        with st.spinner("并发检索中…（arXiv 有 3 秒/次的硬限速，稍等）"):
            info = state.run_search(q, discipline, sources, per_source=per,
                                    year_from=int(year_from) if year_from else None,
                                    oa_only=oa_only, lang="zh" if zh_mode else None)
        if info["unique"] == 0:
            st.error("没有结果。可以试试更通用的关键词，或勾选更多数据源。")
        else:
            st.success(
                f"原始 {info['raw']} 条 → 合并去重后 {info['unique']} 条"
                f"（合并 {info['merged']} 条重复，耗时 {info['elapsed']}s）"
            )
        st.rerun()


def _filters(ps: list[dict]) -> list[dict]:
    years = sorted({p["year"] for p in ps if p.get("year")})
    designs = sorted({p.get("design") for p in ps if p.get("design")})
    c1, c2, c3, c4 = st.columns([1.6, 1.6, 1, 1.2])
    with c1:
        if years and len(years) > 1:
            yr = st.slider("年份", min_value=years[0], max_value=years[-1],
                           value=(years[0], years[-1]))
        else:
            yr = None
    with c2:
        picked = st.multiselect("研究设计", designs,
                                format_func=lambda d: schema.DESIGN_LABELS.get(d, d))
    with c3:
        oa = st.checkbox("仅 OA", value=False)
    with c4:
        order = st.selectbox("排序", ["相关度（原始）", "被引次数", "发表年份", "完整度"])

    out = state.filter_papers(ps, year_range=yr, designs=picked or None, oa_only=oa)
    if order == "被引次数":
        out = sorted(out, key=lambda p: -(p.get("cited_by") or 0))
    elif order == "发表年份":
        out = sorted(out, key=lambda p: -(p.get("year") or 0))
    elif order == "完整度":
        out = sorted(out, key=lambda p: -len(p.get("abstract") or ""))
    return out


def _paper_block(p: dict, idx: int) -> None:
    sid = p.get("sid", str(idx))
    badges = []
    if p.get("dup_count", 1) > 1:
        badges.append(f"跨 {p['dup_count']} 源合并")
    if p.get("is_oa"):
        badges.append("开放获取")
    if p.get("arxiv_id"):
        badges.append("预印本")

    c1, c2 = st.columns([0.86, 0.14])
    with c1:
        st.markdown(theme.paper_row(p, abstract_chars=300, badges=badges), unsafe_allow_html=True)
    with c2:
        saved = library.has(sid)
        if st.button("已收藏" if saved else "收藏", key=f"fav_{sid}_{idx}", use_container_width=True):
            if not saved:
                library.save([p], group=st.session_state.get("query", "未分组")[:24] or "未分组")
                st.toast("已加入文献库")
            else:
                st.toast("已在文献库中")
        if st.button("摘要", key=f"sum_{sid}_{idx}", use_container_width=True):
            k = f"open_{sid}_{idx}"
            st.session_state[k] = not st.session_state.get(k, False)

    if st.session_state.get(f"open_{sid}_{idx}"):
        s = summarize.structured(p)
        cols = st.columns(2)
        for i, slot in enumerate(("question", "method", "findings", "conclusion")):
            cell = s["slots"][slot]
            txt = cell["sentences"][0]["text"] if cell["sentences"] else "摘要未提及"
            cls = "" if cell["sentences"] else "empty"
            with cols[i % 2]:
                st.markdown(
                    f'<div class="sm-slot {cls}"><div class="lb">{theme.esc(cell["label"])}</div>'
                    f'<div class="tx">{theme.esc(T.shorten(txt, 320))}</div></div>',
                    unsafe_allow_html=True,
                )
        if s["numbers"]:
            st.markdown(theme.pills([n["value"] for n in s["numbers"][:10]], "gold"), unsafe_allow_html=True)
        st.caption(f"模板 {s['template_name']} · 完整度 {s['coverage']}/6 · 置信度 {s['confidence']}（{s['confidence_label']}）")


def render() -> None:
    theme.hero(
        "文献检索",
        "一次查询，同时打多个源；重复条目自动合并，并把「合并了哪几个源」记下来。"
        "检索式支持空格分词、引号精确匹配、-排除词。",
        "STEP 01 · DISCOVER",
    )
    _search_form()

    ps = state.papers()
    if not ps:
        theme.empty("还没有检索结果", "在上面输入一个研究主题，或回首页用「直接开始」快速体验。")
        return

    theme.source_status(st.session_state.get("status") or [])

    years = [p["year"] for p in ps if p.get("year")]
    cites = [p.get("cited_by") or 0 for p in ps]
    theme.stats([
        ("合并后文献", str(len(ps)), "篇"),
        ("原始命中", str(st.session_state.get("raw_count", len(ps))), "条"),
        ("跨源重复", str(st.session_state.get("dup_merged", 0)), "条"),
        ("开放获取", f"{round(sum(1 for p in ps if p.get('is_oa')) / len(ps) * 100)}", "%"),
        ("最高被引", str(max(cites) if cites else 0), "次"),
    ])

    theme.section("筛选", f"当前检索式：{st.session_state.get('query', '')}", "02")
    shown = _filters(ps)
    st.caption(f"符合条件 {len(shown)} 篇")

    theme.section("结果", "点「摘要」就地看结构化抽取；点「收藏」进文献库。", "03")

    top = st.columns([1, 1, 1, 1])
    if top[0].button("全选当前结果", use_container_width=True):
        st.session_state["_sel"] = [p["sid"] for p in shown]
    if top[1].button("收藏所选", use_container_width=True):
        sel = st.session_state.get("_sel") or []
        n = library.save([p for p in shown if p["sid"] in sel],
                         group=st.session_state.get("query", "未分组")[:24] or "未分组")
        st.toast(f"新增 {n} 篇到文献库")
    with top[2]:
        st.download_button("导出 BibTeX", export.to_bibtex(shown).encode("utf-8"),
                           file_name="scholar_mirror.bib", use_container_width=True)
    with top[3]:
        st.download_button("导出 XLSX", export.to_xlsx(shown), file_name="scholar_mirror.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           use_container_width=True)

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    for i, p in enumerate(shown[:60]):
        _paper_block(p, i)
    if len(shown) > 60:
        st.caption(f"仅显示前 60 篇，共 {len(shown)} 篇。可用筛选收窄范围。")

    theme.section("下一步", "", "04")
    c1, c2, c3, c4 = st.columns(4)
    if c1.button("去摘要工坊 →", use_container_width=True):
        st.session_state["_goto"] = "摘要工坊"
        st.rerun()
    if c2.button("看关联图谱 →", use_container_width=True):
        st.session_state["_goto"] = "关联图谱"
        st.rerun()
    if c3.button("做主题聚类 →", use_container_width=True):
        st.session_state["_goto"] = "主题聚类"
        st.rerun()
    if c4.button("找研究缺口 →", use_container_width=True):
        st.session_state["_goto"] = "缺口与方向"
        st.rerun()
