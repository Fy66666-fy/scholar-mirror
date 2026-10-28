"""缺口与方向：从可核对的文本信号里找研究不足，再翻译成可执行的研究方向。"""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from core import export, gaps, schema
from core import text as T
from ui import state, theme

SEV_TONE = {"高": "warn", "中": "gold", "低": ""}


def _stat_bar(g: dict) -> None:
    s = g.get("stats") or {}
    theme.stats([
        ("纳入文献", str(s.get("n", 0)), "篇"),
        ("中位样本量", T.fmt_int(s.get("median_n")), ""),
        ("干预性研究", f"{s.get('rct_share', 0)}", "%"),
        ("单中心占比", "—" if s.get("single_center_share") is None else f"{s['single_center_share']}", "%"),
        ("结论冲突对", str(s.get("conflicts", 0)), "对"),
        ("中位随访", "—" if not s.get("median_followup") else f"{s['median_followup']:.0f}", "月"),
    ])


def _gap_card(g: dict) -> None:
    tone = SEV_TONE.get(g["severity"], "")
    ev_html = ""
    for e in g.get("evidence") or []:
        stance = e.get("stance")
        tag = f'<span class="sm-pill warn">{stance}</span>' if stance else ""
        ev_html += (
            f'<div class="sm-ev">{tag}{theme.esc(T.shorten(e.get("quote") or "", 230))}'
            f'<div class="src">— 《{theme.esc(T.shorten(e.get("title") or "", 70))}》'
            f'{e.get("year") or ""}</div></div>'
        )
    qs = "".join(
        f'<li style="margin:3px 0;">{theme.esc(q)}</li>' for q in (g.get("questions") or [])
    )
    st.markdown(
        f'<div class="sm-card {"warn" if g["severity"] == "高" else "accent"}">'
        f'<div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start;">'
        f'<div style="font-size:15.5px;font-weight:700;line-height:1.5;">{theme.esc(g["title"])}</div>'
        f'<div>{theme.pill(g["severity"] + " 优先", tone)}{theme.pill(g["kind"])}</div></div>'
        f'<div style="font-size:13.5px;color:#4a5a63;line-height:1.8;margin-top:8px;">'
        f'{theme.esc(g["detail"])}</div>'
        f'<div style="font-size:13px;color:#4a5a63;line-height:1.8;margin-top:8px;">'
        f'<b>为什么算缺口</b>：{theme.esc(g["why"])}</div>'
        f'<div style="font-size:13px;color:#1f4e5f;line-height:1.8;margin-top:6px;">'
        f'<b>可以怎么补</b>：{theme.esc(g["suggestion"])}</div>'
        f'{ev_html}'
        f'<div style="font-size:12.5px;color:#6b767c;margin-top:8px;">推荐设计：'
        f'{theme.esc(g.get("design") or "—")}</div>'
        f'<div style="font-size:13px;line-height:1.8;margin-top:8px;"><b>可检验的问题</b>'
        f'<ul style="margin:4px 0 0 18px;padding:0;">{qs}</ul></div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _direction_card(i: int, d: dict) -> None:
    qs = "".join(f'<li style="margin:3px 0;">{theme.esc(q)}</li>' for q in d.get("questions") or [])
    st.markdown(
        f'<div class="sm-card"><div style="display:flex;gap:14px;">'
        f'<div style="min-width:34px;font-size:20px;font-weight:700;color:#a8822f;'
        f'font-variant-numeric:tabular-nums;">{i:02d}</div>'
        f'<div style="flex:1;">'
        f'<div style="font-size:15px;font-weight:700;line-height:1.55;">{theme.esc(d["title"])}</div>'
        f'<div style="font-size:12.5px;color:#6b767c;margin-top:5px;">依据：{theme.esc(d["basis"])}'
        f'　·　推荐设计：{theme.esc(d["design"])}</div>'
        f'<div style="display:flex;gap:18px;flex-wrap:wrap;margin-top:9px;">'
        f'<div style="flex:1;min-width:200px;font-size:12.8px;line-height:1.75;color:#3f7a5e;">'
        f'<b>预期贡献</b><br>{theme.esc(d["contribution"])}</div>'
        f'<div style="flex:1;min-width:200px;font-size:12.8px;line-height:1.75;color:#b4623c;">'
        f'<b>风险与替代</b><br>{theme.esc(d["risk"])}</div></div>'
        f'<ul style="font-size:13px;line-height:1.8;margin:8px 0 0 18px;padding:0;">{qs}</ul>'
        f'</div></div></div>',
        unsafe_allow_html=True,
    )


def _matrix(mat: dict) -> None:
    if not mat.get("matrix"):
        return
    fig = go.Figure(go.Heatmap(
        z=mat["matrix"], x=mat["terms"], y=mat["clusters"],
        colorscale=[[0, "#f7f5f0"], [0.4, "#cfe0d4"], [1, "#1f4e5f"]],
        showscale=True, colorbar=dict(title="命中文献数", thickness=10),
        hovertemplate="方向 %{y}<br>概念 %{x}<br>命中 %{z} 篇<extra></extra>",
    ))
    fig.update_layout(height=max(240, 46 * len(mat["clusters"]) + 80))
    fig.update_xaxes(tickangle=35, tickfont=dict(size=10))
    fig.update_yaxes(tickfont=dict(size=10.5))
    st.plotly_chart(theme.plotly_layout(fig, height=max(240, 46 * len(mat["clusters"]) + 80)),
                    use_container_width=True, config={"displayModeBar": False})


def render() -> None:
    theme.hero(
        "缺口与方向",
        "不猜「这个领域缺什么」，只报能从摘要里核对的东西：样本量、随访、单/多中心、对照、"
        "效应量、局限声明。每条缺口都附命中文献与原句，不同意可以直接反驳。",
        "STEP 06 · EXTEND",
    )
    ps = state.papers()
    if len(ps) < 3:
        theme.empty("文献太少", "缺口分析至少需要 4 篇才有统计意义。先去检索更多文献。")
        return

    res = state.analysis()
    gap_res = res["gaps"]
    _stat_bar(gap_res)

    if gap_res.get("caveat"):
        st.markdown(
            f'<div class="sm-card warn"><b>样本不足提示</b><br>'
            f'<span style="font-size:13px;line-height:1.8;">{theme.esc(gap_res["caveat"])}</span></div>',
            unsafe_allow_html=True,
        )

    theme.section("识别到的缺口", f"共 {len(gap_res['gaps'])} 条，按优先级排序。", "01")
    if not gap_res["gaps"]:
        theme.empty("没有触发任何缺口规则",
                    "这批文献在样本量、随访、设计多样性上都比较均衡，或者摘要信息太少无法判断。"
                    "换一个方向或扩大检索范围再试。")
    for g in gap_res["gaps"]:
        _gap_card(g)

    theme.section("后续研究方向", "把缺口翻译成能立项的题目。这些问题由模板生成，用于起草，需结合领域知识改写。", "02")
    for i, d in enumerate(res["directions"], 1):
        _direction_card(i, d)

    theme.section("概念覆盖矩阵", "哪个方向把哪些概念做透了、哪些概念还悬着，一眼能看出来。行=方向，列=高频概念。", "03")
    _matrix(res["matrix"])

    theme.section("导出", "整份报告包含检索条件、方向分布、精选、逐篇摘要、关联结构、缺口与方向。", "04")
    md = export.report_markdown(
        ps, topic=st.session_state.get("query", ""),
        meta={"query": st.session_state.get("query", ""),
              "discipline": st.session_state.get("discipline", ""),
              "sources": st.session_state.get("sources_used") or [],
              "raw_count": st.session_state.get("raw_count", len(ps))},
        cluster_res=res["cluster"], curated=res["curated"], gap_res=gap_res,
        directions=res["directions"], graph=res["graph"], bridges=res["bridges"],
        dup={"merged": st.session_state.get("dup_merged", 0)},
    )
    c1, c2 = st.columns(2)
    c1.download_button("下载完整报告（Markdown）", md.encode("utf-8"),
                       file_name="scholar_mirror_report.md", use_container_width=True)
    c2.download_button("下载结构化数据（XLSX）",
                       export.to_xlsx(ps, cluster_res=res["cluster"], gap_res=gap_res,
                                      curated=res["curated"]),
                       file_name="scholar_mirror.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)

    theme.method_note(
        "缺口规则只看摘要能提供的信息，因此会系统性低估「正文写了但摘要没写」的研究 —— "
        "这类会被归到「报告完整性」而不是「研究缺陷」。需要严格评价时请回全文，"
        "并按研究设计选用对应工具（RoB 2 / NOS / AMSTAR-2 / GRADE 等）。"
    )
