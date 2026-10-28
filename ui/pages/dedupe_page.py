"""查重中心：跨源合并 / 结果集近似重复 / 任意文本查重。"""
from __future__ import annotations

import streamlit as st

from core import dedupe, schema
from core import text as T
from ui import state, theme


def _merge_tab(ps: list[dict]) -> None:
    groups = st.session_state.get("dup_groups") or []
    merged = st.session_state.get("dup_merged", 0)
    raw = st.session_state.get("raw_count", len(ps))
    theme.stats([
        ("原始记录", str(raw), "条"),
        ("合并后", str(len(ps)), "条"),
        ("合并重复", str(merged), "条"),
        ("多源命中", str(len([p for p in ps if len(p.get("merged_sources") or p.get("sources") or []) > 1])), "篇"),
    ])
    if not groups:
        st.caption("本次没有发现跨源重复。单一数据源检索时，这一层通常是空的。")
        return
    theme.section("合并明细", "同一篇文献在多个源各有一条记录时，保留信息最全的一条，其余字段并进来。", "01")
    rows = []
    for g in groups[:40]:
        srcs = " + ".join(sorted({s for group in g["sources"] for s in group}))
        rows.append([
            f'<b>{theme.esc(T.shorten(g["kept"], 60))}</b>',
            str(g["count"]),
            theme.esc(srcs),
            theme.esc(g.get("doi") or "—"),
        ])
    theme.table(["保留条目", "合并条数", "命中数据源", "DOI"], rows)


def _pairs_tab(ps: list[dict]) -> None:
    theme.section("结果集内的近似重复", "同一项工作可能以预印本、会议版、期刊版出现三次。这里给「疑似」，判定留给人。", "02")
    threshold = st.slider("相似度阈值", 0.60, 0.98, 0.72, 0.01,
                          help="阈值越低越敏感，误报也越多。0.90 以上基本可以确认是同一项工作。")
    pairs = dedupe.near_duplicates(ps, threshold=threshold)
    if not pairs:
        theme.empty("没有超过阈值的相似对", "把阈值调低一点可以看到更多「主题接近」的文献对。")
        return

    kinds: dict[str, int] = {}
    for p in pairs:
        kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
    st.markdown(theme.pills([f"{k} {v}" for k, v in kinds.items()], "warn"), unsafe_allow_html=True)

    rows = []
    for p in pairs[:30]:
        tone = "warn" if p["score"] >= 0.9 else ""
        rows.append([
            f'<span class="sm-pill {tone}">{p["score"]:.2f}</span>',
            theme.esc(p["kind"]),
            f'{theme.esc(T.shorten(p["a_title"], 52))}<br><span style="color:#8b9499;font-size:11.5px;">'
            f'{theme.esc(p["a_source"])} · {p["a_year"] or "—"}</span>',
            f'{theme.esc(T.shorten(p["b_title"], 52))}<br><span style="color:#8b9499;font-size:11.5px;">'
            f'{theme.esc(p["b_source"])} · {p["b_year"] or "—"}</span>',
            theme.esc(p["advice"]),
        ])
    theme.table(["相似度", "类型", "文献 A", "文献 B", "建议处置"], rows)

    theme.section("逐项拆解", "一条边的分数由四个信号合成，点开看是哪一项在起作用。", "03")
    labels = {f'{i + 1}. {T.shorten(p["a_title"], 40)} ⟷ {T.shorten(p["b_title"], 40)}': p
              for i, p in enumerate(pairs[:30])}
    pick = st.selectbox("选择一对", list(labels))
    p = labels[pick]
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(theme.bar("标题词重叠", p["title_sim"] * 100, 100, "%"), unsafe_allow_html=True)
        st.markdown(theme.bar("摘要余弦", p["abstract_cos"] * 100, 100, "%"), unsafe_allow_html=True)
    with c2:
        st.markdown(theme.bar("连续片段覆盖", p["overlap"] * 100, 100, "%"), unsafe_allow_html=True)
        st.markdown(theme.bar("SimHash 指纹", p["fingerprint"] * 100, 100, "%"), unsafe_allow_html=True)
    with c3:
        st.markdown(
            f'<div class="sm-card tight"><div style="font-size:12px;color:#6b767c;">综合相似度</div>'
            f'<div style="font-size:30px;font-weight:700;font-variant-numeric:tabular-nums;">{p["score"]:.2f}</div>'
            f'<div style="font-size:12.5px;color:#b4623c;margin-top:4px;">{theme.esc(p["kind"])} · '
            f'汉明距离 {p["hamming"]}</div></div>',
            unsafe_allow_html=True,
        )
    a = next((x for x in ps if x.get("sid") == p["a_sid"]), None)
    b = next((x for x in ps if x.get("sid") == p["b_sid"]), None)
    if a and b:
        col1, col2 = st.columns(2)
        for col, item in ((col1, a), (col2, b)):
            with col:
                st.markdown(
                    f'<div class="sm-card"><div style="font-weight:650;font-size:14px;line-height:1.5;">'
                    f'{theme.esc(item.get("title", ""))}</div>'
                    f'<div class="sm-meta" style="margin-top:6px;">{theme.esc(schema.venue_year(item))}</div>'
                    f'<div class="sm-abs">{theme.esc(T.shorten(item.get("abstract") or "（无摘要）", 420))}</div></div>',
                    unsafe_allow_html=True,
                )


def _text_tab(ps: list[dict]) -> None:
    theme.section("文本查重", "粘一段自己写的稿子，逐句比对当前文献池，给出重复率与命中出处。", "04")
    if not ps:
        theme.empty("文献池为空", "查重需要语料。先在「文献检索」拿到一批文献，或换到文献库语料（下一步支持）。")
        return

    c1, c2 = st.columns([3, 1])
    text = c1.text_area("待检文本", height=200, key="dup_text",
                        placeholder="粘贴要检查的段落。建议至少 3 句，太短的结果不稳定。")
    thr = c2.slider("命中阈值", 0.40, 0.85, 0.52, 0.01,
                    help="句子级余弦相似度。0.52 左右适合判断「改写过的抄袭」，0.75 以上只抓近似照抄。")

    if st.button("开始查重", type="primary"):
        if not (text or "").strip():
            st.warning("先粘贴文本。")
            return
        st.session_state["dup_report"] = dedupe.text_similarity(text, ps, threshold=thr)

    rep = st.session_state.get("dup_report")
    if not rep:
        st.caption("提示：语料是当前文献池的标题与摘要，不含全文。全文查重需要先拿到 PDF。")
        return

    rate = rep["rate"]
    tone = "#b4623c" if rate >= 30 else ("#a8822f" if rate >= 12 else "#3f7a5e")
    verdict = "偏高，建议逐句核对" if rate >= 30 else ("存在片段重合" if rate >= 12 else "基本无重合")
    st.markdown(
        f'<div class="sm-card accent" style="display:flex;align-items:center;gap:22px;">'
        f'<div><div style="font-size:11.5px;letter-spacing:.1em;color:#6b767c;">重复率</div>'
        f'<div style="font-size:44px;font-weight:700;line-height:1.1;color:{tone};'
        f'font-variant-numeric:tabular-nums;">{rate:.1f}<span style="font-size:18px;">%</span></div></div>'
        f'<div style="font-size:13.5px;line-height:1.9;color:#4a5a63;">'
        f'{verdict}<br>命中 {rep["hit_sentences"]} / {rep["total"]} 句 · '
        f'涉及 {len(rep["matched_papers"])} 篇来源 · 阈值 {rep["threshold"]}</div></div>',
        unsafe_allow_html=True,
    )

    if rep["flagged"]:
        theme.section("命中明细", "按相似度降序。左边是你写的句子，右边是语料里的原句。", "05")
        rows = []
        for f in rep["flagged"]:
            rows.append([
                f'<span class="sm-pill warn">{f["score"]:.2f}</span>',
                theme.esc(T.shorten(f["sentence"], 110)),
                theme.esc(T.shorten(f["match"], 130)),
                f'{theme.esc(T.shorten(f["title"], 46))}<br>'
                f'<span style="color:#8b9499;font-size:11.5px;">{f["year"] or "—"}</span>',
            ])
        theme.table(["相似度", "待检句", "语料原句", "来源文献"], rows)

    if rep["matched_papers"]:
        theme.section("来源汇总", "", "06")
        rows = [[
            theme.esc(T.shorten(m["title"], 70)), str(m["year"] or "—"),
            str(m["hits"]), f'{m["best"]:.2f}',
        ] for m in rep["matched_papers"]]
        theme.table(["文献", "年份", "命中句数", "最高相似度"], rows)

    md = [f"# 查重报告", "", f"- 重复率：{rate:.1f}%",
          f"- 命中句：{rep['hit_sentences']}/{rep['total']}",
          f"- 阈值：{rep['threshold']}", "", "## 命中明细", ""]
    for f in rep["flagged"]:
        md += [f"### {f['score']:.2f} · {T.shorten(f['title'], 70)}", "",
               f"- 待检：{f['sentence']}", f"- 原文：{f['match']}", ""]
    st.download_button("下载查重报告", "\n".join(md).encode("utf-8"),
                       file_name="plagiarism_report.md")


def render() -> None:
    theme.hero(
        "查重中心",
        "三层查重解决三种重复：同一篇在多源重复、同一项工作的不同版本、你的稿子与已有文献重合。"
        "全部是本地计算，文本不会离开这台机器。",
        "STEP 03 · VERIFY",
    )
    ps = state.papers()
    if not ps:
        theme.empty("还没有文献", "查重需要语料。先去「文献检索」拿一批结果。")
        return
    tab1, tab2, tab3 = st.tabs(["跨源合并", "近似重复", "文本查重"])
    with tab1:
        _merge_tab(ps)
    with tab2:
        _pairs_tab(ps)
    with tab3:
        _text_tab(ps)
