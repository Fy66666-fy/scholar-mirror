"""摘要工坊：单篇深读 + 批量横向对比 + 任意文本粘贴。

三种用法对应三种真实场景：
    单篇深读 —— 读到一篇关键文献，想快速抓住六件事并核对原句；
    批量对比 —— 手上 5–20 篇，想横向看方法、样本、结论差在哪；
    粘贴文本 —— 手上是一篇 PDF 摘要或别人发来的段落，不在检索结果里。
"""
from __future__ import annotations

import re

import streamlit as st

from core import export, llm, schema, summarize, templates, translate
from core import text as T
from ui import state, theme

_SLOT_COLORS = {
    "question": "#1f4e5f",
    "method": "#3f7a5e",
    "data": "#6b7f9e",
    "findings": "#a8822f",
    "conclusion": "#b4623c",
    "limitation": "#8b6b8f",
}


def _highlight_numbers(text: str, numbers: list[dict]) -> str:
    if not numbers:
        return theme.esc(text)
    out, last = [], 0
    for n in numbers:
        s, e = n.get("start", -1), n.get("end", -1)
        if s < 0 or e <= s or s < last:
            continue
        out.append(theme.esc(text[last:s]))
        out.append(
            f'<span style="background:#f8f1de;border-bottom:1.5px solid #d8bd83;'
            f'padding:0 1px;">{theme.esc(text[s:e])}</span>'
        )
        last = e
    out.append(theme.esc(text[last:]))
    return "".join(out)


def _located_text(paper: dict, summ: dict) -> None:
    """原文定位：句子编号 + 槽位色标，用来核对「这句是从哪来的」。"""
    sents = T.split_sentences(paper.get("abstract") or "")
    if not sents:
        return
    used: dict[str, str] = {}
    for slot, data in summ["slots"].items():
        for item in data["sentences"]:
            used[item["text"]] = slot
    rows = []
    for i, s in enumerate(sents, 1):
        slot = used.get(s)
        if slot:
            color = _SLOT_COLORS.get(slot, "#1f4e5f")
            label = templates.SLOT_LABELS.get(slot, slot)
            tag = (f'<span style="font-size:10.5px;color:#fff;background:{color};'
                   f'padding:1px 6px;border-radius:8px;margin-right:7px;">{label}</span>')
            style = f"border-left:2px solid {color};padding-left:9px;background:#fffdf8;"
        else:
            tag, style = "", "border-left:2px solid transparent;padding-left:9px;opacity:.62;"
        rows.append(
            f'<div style="margin:5px 0;{style}font-size:13px;line-height:1.75;">'
            f'<span style="color:#a5adb2;font-variant-numeric:tabular-nums;margin-right:6px;">{i:02d}</span>'
            f'{tag}{theme.esc(s)}</div>'
        )
    st.markdown("".join(rows), unsafe_allow_html=True)


def _single(paper: dict, key_prefix: str = "") -> None:
    tpl_key = st.session_state.get(f"tpl_{key_prefix}{paper.get('sid', 'x')}") or templates.auto_template(paper)
    summ = summarize.structured(paper, tpl_key)

    theme.section(paper.get("title") or "（无标题）", "", "01")
    meta = [schema.venue_year(paper), schema.display_authors(paper)]
    if paper.get("doi"):
        meta.append(f"DOI {paper['doi']}")
    st.markdown(
        f'<div style="font-size:12.5px;color:#6b767c;margin-bottom:10px;">{theme.esc(" · ".join(meta))}</div>',
        unsafe_allow_html=True,
    )

    theme.stats([
        ("模板", summ["template_name"], ""),
        ("槽位完整度", f"{summ['coverage']}/6", ""),
        ("抽取置信度", str(summ["confidence"]), summ["confidence_label"]),
        ("关键数值", str(len(summ["numbers"])), "个"),
    ])

    if summ["one_liner"]:
        st.markdown(
            f'<div class="sm-card accent"><div style="font-size:11.5px;letter-spacing:.08em;'
            f'color:#a8822f;font-weight:600;margin-bottom:6px;">一句话结论</div>'
            f'<div style="font-size:15.5px;line-height:1.8;">{theme.esc(summ["one_liner"])}</div></div>',
            unsafe_allow_html=True,
        )

    _llm_block(paper, summ)

    if not summ["has_abstract"]:
        theme.empty("这篇没有摘要", "多数 Crossref 记录与部分预印本不含摘要。可以打开原文页看，或换一个源。")
        return

    left, right = st.columns([0.66, 0.34])
    with left:
        for slot in ("question", "method", "data", "findings", "conclusion", "limitation"):
            cell = summ["slots"][slot]
            if cell["sentences"]:
                body = "".join(
                    f'<div class="sm-quote" style="margin-bottom:6px;">{theme.esc(x["text"])}</div>'
                    for x in cell["sentences"]
                )
                note = '<span class="sm-pill warn">位置推断</span>' if cell["inferred"] else ""
                st.markdown(
                    f'<div class="sm-slot"><div class="lb">{theme.esc(cell["label"])}{note}</div>'
                    f'<div class="tx">{body}</div></div>',
                    unsafe_allow_html=True,
                )
            else:
                st.markdown(
                    f'<div class="sm-slot empty"><div class="lb">{theme.esc(cell["label"])}</div>'
                    f'<div class="tx">摘要未提及 —— 只能回全文确认</div></div>',
                    unsafe_allow_html=True,
                )
    with right:
        if summ["numbers"]:
            st.markdown('<div class="sm-hint">关键数值（原文锚点）</div>', unsafe_allow_html=True)
            st.markdown(theme.pills([n["value"] for n in summ["numbers"][:12]], "gold"),
                        unsafe_allow_html=True)
        kws = summarize.keywords(paper, 8)
        if kws:
            st.markdown('<div class="sm-hint" style="margin-top:12px;">关键词</div>', unsafe_allow_html=True)
            st.markdown(theme.pills(kws, "solid"), unsafe_allow_html=True)
        st.markdown('<div class="sm-hint" style="margin-top:12px;">模板切换</div>', unsafe_allow_html=True)
        st.selectbox(
            "模板", list(templates.TEMPLATES),
            index=list(templates.TEMPLATES).index(tpl_key),
            format_func=lambda k: templates.TEMPLATES[k]["name"],
            key=f"tpl_{key_prefix}{paper.get('sid', 'x')}",
            label_visibility="collapsed",
        )

    _translate_block(paper, summ)

    with st.expander("原文定位：每句话落在哪一栏", expanded=False):
        st.markdown(
            f'<div class="sm-abs" style="margin-bottom:8px;">{_highlight_numbers(paper.get("abstract") or "", summ["numbers"])}</div>',
            unsafe_allow_html=True,
        )
        st.markdown("<hr style='border-color:#e4ded3;margin:12px 0;'>", unsafe_allow_html=True)
        _located_text(paper, summ)

    with st.expander("导出这一篇", expanded=False):
        md = export.report_markdown([paper], topic=paper.get("title", ""),
                                    meta={"query": paper.get("title", "")})
        c1, c2 = st.columns(2)
        c1.download_button("Markdown", md.encode("utf-8"), file_name="summary.md", use_container_width=True)
        c2.download_button("BibTeX", export.to_bibtex([paper]).encode("utf-8"),
                           file_name="paper.bib", use_container_width=True)


def _translate_block(paper: dict, summ: dict) -> None:
    """中文对照：按槽位逐句翻译，原文与译文并排，方便核对术语。"""
    sid = paper.get("sid", "x")
    with st.expander("中文对照（机翻，逐句核对）", expanded=False):
        c1, c2 = st.columns([1, 3])
        c1.caption(f"引擎：{translate.engine_label()}")
        if c2.button("生成中文对照", key=f"tr_{sid}"):
            with st.spinner("逐句翻译中…"):
                out = {}
                for slot in ("question", "method", "data", "findings", "conclusion", "limitation"):
                    sents = [x["text"] for x in summ["slots"][slot]["sentences"]]
                    out[slot] = [{"src": t, **translate.translate(t, "zh")} for t in sents]
            st.session_state[f"tr_{sid}"] = out
        res = st.session_state.get(f"tr_{sid}")
        if not res:
            st.caption("点击上面的按钮再翻译。整篇摘要也可以，但逐句对照更适合核对术语。")
            return
        for slot, items in res.items():
            if not items:
                continue
            label = summ["slots"][slot]["label"]
            st.markdown(f'<div class="sm-hint" style="margin-top:10px;">{theme.esc(label)}</div>',
                        unsafe_allow_html=True)
            for it in items:
                if it.get("ok"):
                    st.markdown(
                        f'<div class="sm-slot" style="padding:10px 13px;">'
                        f'<div style="font-size:12.5px;color:#6b767c;line-height:1.6;">'
                        f'{theme.esc(it["src"])}</div>'
                        f'<div style="font-size:13.5px;line-height:1.75;margin-top:5px;">'
                        f'{theme.esc(it["text"])}</div></div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f'<div class="sm-slot empty"><div class="tx">{theme.esc(it["src"])}'
                        f'（未翻译：{theme.esc(it.get("error") or "")}）</div></div>',
                        unsafe_allow_html=True,
                    )


def _llm_block(paper: dict, summ: dict) -> None:
    """可选的 LLM 深度总结。没配就直接说明，不假装有。"""
    sid = paper.get("sid", "x")
    if not llm.is_ready():
        st.markdown(
            f'<div class="sm-card flat"><div style="font-size:12.5px;color:#6b767c;line-height:1.7;">'
            f'当前用本地抽取式摘要（不调用模型）。需要更连贯的中文段落时，可在「设置 → 模型与翻译」'
            f'配置任意 OpenAI 兼容接口；配置后这里会出现「深度总结」按钮。</div></div>',
            unsafe_allow_html=True,
        )
        return
    c1, c2 = st.columns([1, 3])
    if c1.button("LLM 深度总结", key=f"llm_{sid}"):
        slots = {summ["slots"][k]["label"]: [x["text"] for x in summ["slots"][k]["sentences"]]
                 for k in summ["slots"]}
        with st.spinner("生成中…"):
            text, err = llm.deep_summary(paper.get("title", ""), slots, summ.get("one_liner", ""))
        st.session_state[f"llmres_{sid}"] = (text, err)
    c2.caption(f"模型：{llm.model_name()}　·　只喂已抽取的原句，不允许补充事实")
    res = st.session_state.get(f"llmres_{sid}")
    if res:
        text, err = res
        if text:
            st.markdown(
                f'<div class="sm-card accent"><div style="font-size:14px;line-height:1.85;">'
                f'{theme.esc(text)}</div></div>', unsafe_allow_html=True)
        else:
            st.warning(f"生成失败：{err}")


def _pasted() -> None:
    theme.section("粘贴任意文本", "不限于检索结果：PDF 摘要、审稿意见里的文献段、自己写的草稿都能读。", "02")
    c1, c2 = st.columns([3, 1])
    title = c1.text_input("标题（可留空）", placeholder="例如：Effects of X on Y")
    tpl = c2.selectbox("模板", list(templates.TEMPLATES),
                       format_func=lambda k: templates.TEMPLATES[k]["name"])
    text = st.text_area("摘要 / 段落", height=220,
                        placeholder="把摘要粘进来。中英文都可以，带不带 Background/Methods 小标题都能识别。")
    if st.button("生成结构化摘要", type="primary"):
        if not (text or "").strip():
            st.warning("先粘贴一段文本。")
            return
        paper = schema.normalize_paper({
            "title": title or (T.split_sentences(text) or ["粘贴文本"])[0][:80],
            "abstract": text, "source": "pasted", "sid": "pasted:1",
        })
        st.session_state["pasted_paper"] = paper
        # 把用户刚选的模板写进对应控件的状态，避免下面又被自动模板覆盖
        st.session_state["tpl_paste_pasted:1"] = tpl

    paper = st.session_state.get("pasted_paper")
    if paper:
        st.markdown("<hr style='border-color:#e4ded3;margin:18px 0;'>", unsafe_allow_html=True)
        _single(paper, key_prefix="paste_")


def _batch() -> None:
    ps = state.papers()
    if not ps:
        theme.empty("还没有可对比的文献", "先在「文献检索」拿到一批结果。")
        return
    theme.section("批量横向对比", "每格都是原文原句的截取，可直接粘进综述表格，再逐条回原文改。", "03")
    n = st.slider("对比篇数", 3, min(30, len(ps)), min(8, len(ps)))
    picked = ps[:n]
    tpl = st.selectbox("统一模板", ["自动"] + list(templates.TEMPLATES),
                       format_func=lambda k: "自动（按研究设计判断）" if k == "自动" else templates.TEMPLATES[k]["name"])
    rows = summarize.compare_rows(picked, None if tpl == "自动" else tpl)

    headers = ["#", "文献", "年份", "设计", "研究问题", "方法", "样本", "主要发现", "局限"]
    table_rows = []
    for i, r in enumerate(rows, 1):
        table_rows.append([
            str(i),
            f'<b>{theme.esc(T.shorten(r["title"], 46))}</b>',
            str(r["year"] or "—"),
            theme.esc(r["design"]),
            theme.esc(T.shorten(r["question"], 90) or "—"),
            theme.esc(T.shorten(r["method"], 90) or "—"),
            T.fmt_int(r["sample"]),
            theme.esc(T.shorten(r["findings"], 120) or "—"),
            theme.esc(T.shorten(r["limitation"], 70) or "未提及"),
        ])
    theme.table(headers, table_rows)

    gaps = [r for r in rows if not r["findings"]]
    if gaps:
        st.caption(f"有 {len(gaps)} 篇没抽到「主要发现」，通常是摘要不含结果段（综述、理论文章常见）。")

    md = export.comparison_markdown(rows, st.session_state.get("query", ""))
    c1, c2 = st.columns(2)
    c1.download_button("下载对比表 Markdown", md.encode("utf-8"),
                       file_name="comparison.md", use_container_width=True)
    c2.download_button("下载对比表 XLSX", export.to_xlsx(picked), file_name="comparison.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)


def render() -> None:
    theme.hero(
        "摘要工坊",
        "按学科模板把摘要拆成六个槽位：研究问题、方法与设计、数据与样本、主要发现、结论与意义、局限与展望。"
        "每句都能点回原文核对，抽不到的槽位会明说「摘要未提及」，而不是编一句填上。",
        "STEP 02 · READ",
    )
    tab1, tab2, tab3 = st.tabs(["单篇深读", "批量对比", "粘贴文本"])
    with tab1:
        ps = state.papers()
        if not ps:
            theme.empty("还没有文献", "先在「文献检索」拿到结果，或到「粘贴文本」直接试。")
        else:
            options = {f"{i + 1:02d}. {T.shorten(p.get('title', ''), 70)}": p for i, p in enumerate(ps)}
            label = st.selectbox("选择文献", list(options), index=0)
            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
            _single(options[label])
    with tab2:
        _batch()
    with tab3:
        _pasted()
