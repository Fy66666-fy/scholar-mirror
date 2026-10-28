"""主题聚类与精选：把一批文献切成「研究方向」，并在每个方向里挑出最该读的几篇。"""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from core import export, schema
from core import text as T
from ui import state, theme

PALETTE = ["#1f4e5f", "#b4623c", "#3f7a5e", "#a8822f", "#6b7f9e",
           "#8b6b8f", "#4f6f52", "#9e5b5b", "#5c6b73", "#c08a5a"]


def _year_chart(ps: list[dict], labels: list[int], clusters: list[dict]) -> go.Figure:
    years = sorted({p["year"] for p in ps if p.get("year")})
    fig = go.Figure()
    for c in clusters:
        counts = []
        for y in years:
            counts.append(sum(1 for i in c["members"] if ps[i].get("year") == y))
        fig.add_trace(go.Bar(
            x=[str(y) for y in years], y=counts, name=c["name"],
            marker_color=PALETTE[c["id"] % len(PALETTE)], marker_line_width=0,
        ))
    fig.update_layout(barmode="stack", xaxis_title="", yaxis_title="文献数",
                      legend=dict(orientation="h", y=-0.28))
    return theme.plotly_layout(fig, height=340)


def _design_chart(ps: list[dict]) -> go.Figure:
    dist: dict[str, int] = {}
    for p in ps:
        d = schema.DESIGN_LABELS.get(p.get("design"), "未识别")
        dist[d] = dist.get(d, 0) + 1
    items = sorted(dist.items(), key=lambda kv: -kv[1])
    fig = go.Figure(go.Bar(
        x=[v for _, v in items], y=[k for k, _ in items], orientation="h",
        marker_color="#1f4e5f", marker_line_width=0,
        text=[str(v) for _, v in items], textposition="outside",
    ))
    fig.update_layout(xaxis_title="", yaxis_title="", showlegend=False,
                      margin=dict(l=10, r=30, t=10, b=10))
    return theme.plotly_layout(fig, height=max(220, 34 * len(items)))


def _cluster_cards(ps: list[dict], res: dict) -> None:
    for c in res["clusters"]:
        yr = c.get("year_range")
        span = f"{yr[0]}–{yr[1]}" if yr else "—"
        designs = "、".join(f"{k} {v}" for k, v in list(c["designs"].items())[:3])
        color = PALETTE[c["id"] % len(PALETTE)]
        st.markdown(
            f'<div class="sm-card accent" style="border-left-color:{color};">'
            f'<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;">'
            f'<div><div style="font-size:16px;font-weight:700;">{theme.esc(c["name"])}</div>'
            f'<div class="sm-meta" style="margin-top:5px;">{c["size"]} 篇 · {span} · '
            f'簇内凝聚度 {c["cohesion"]:.2f} · OA {c["oa_ratio"]:.0%}</div></div>'
            f'<div style="font-size:28px;font-weight:700;color:{color};opacity:.28;'
            f'font-variant-numeric:tabular-nums;">{c["size"]:02d}</div></div>'
            f'<div style="margin-top:9px;">{theme.pills(c["terms"][:5], "solid")}</div>'
            f'<div style="font-size:12.5px;color:#6b767c;margin-top:8px;">主要设计：{theme.esc(designs or "—")}</div>'
            f'<div style="font-size:12.5px;color:#4a5a63;margin-top:8px;">代表文献：'
            f'{theme.esc(T.shorten(c["representative"].get("title", ""), 96))}</div></div>',
            unsafe_allow_html=True,
        )
        with st.expander(f"展开这 {c['size']} 篇", expanded=False):
            for sid in c["sids"]:
                p = next((x for x in ps if x["sid"] == sid), None)
                if p:
                    st.markdown(theme.paper_row(p, abstract_chars=180), unsafe_allow_html=True)


def _curation(ps: list[dict], res: dict) -> None:
    curated = state.analysis()["curated"]
    names = {c["id"]: c["name"] for c in res["clusters"]}
    sid_cluster = {p["sid"]: res["labels"][i] for i, p in enumerate(ps)}
    c1, c2 = st.columns([2, 1])
    with c1:
        only = st.multiselect("只看某些方向", list(names.values()))
    with c2:
        upper = min(30, len(curated))
        if upper > 5:
            top_n = st.slider("显示条数", 5, upper, min(12, upper))
        else:
            top_n = upper
            st.caption(f"共 {upper} 条")

    rows = []
    for r in curated:
        p = r["paper"]
        cname = names.get(sid_cluster.get(p.get("sid"), 0), "")
        if only and cname not in only:
            continue
        rows.append((r, cname))
    rows = rows[:top_n]

    for r, cname in rows:
        p = r["paper"]
        parts = r["parts"]
        bars = "".join(theme.bar(k, v) for k, v in parts.items())
        st.markdown(
            f'<div class="sm-card">'
            f'<div style="display:flex;gap:16px;">'
            f'<div style="min-width:46px;text-align:center;">'
            f'<div style="font-size:22px;font-weight:700;color:#a8822f;font-variant-numeric:tabular-nums;">'
            f'{r["rank"]:02d}</div><div style="font-size:10.5px;color:#8b9499;">精选分 {r["score"]}</div></div>'
            f'<div style="flex:1;min-width:0;">'
            f'<div style="font-size:14.5px;font-weight:650;line-height:1.5;">'
            f'<a href="{theme.esc(p.get("url") or "#")}" target="_blank" style="color:#1b2a33;'
            f'text-decoration:none;border-bottom:1px solid #d8d2c6;">{theme.esc(p.get("title", ""))}</a></div>'
            f'<div class="sm-meta" style="margin-top:5px;">{theme.esc(schema.venue_year(p))} · '
            f'{theme.esc(schema.display_authors(p))} · {theme.esc(cname)}</div>'
            f'<div style="margin-top:6px;">{theme.pills(r["tags"], "gold")}</div>'
            f'<div style="font-size:13px;color:#4a5a63;line-height:1.7;margin-top:6px;">{theme.esc(r["why"])}</div>'
            f'</div><div style="width:200px;">{bars}</div></div></div>',
            unsafe_allow_html=True,
        )

    md = export.report_markdown(ps, topic=st.session_state.get("query", ""),
                                meta={"query": st.session_state.get("query", ""),
                                      "discipline": st.session_state.get("discipline", ""),
                                      "sources": st.session_state.get("sources_used") or [],
                                      "raw_count": st.session_state.get("raw_count", len(ps))},
                                cluster_res=res, curated=state.analysis()["curated"],
                                gap_res=state.analysis()["gaps"],
                                directions=state.analysis()["directions"],
                                graph=state.analysis()["graph"],
                                bridges=state.analysis()["bridges"])
    st.download_button("下载完整分析报告（Markdown）", md.encode("utf-8"),
                       file_name="scholar_mirror_report.md", use_container_width=True)


def render() -> None:
    theme.hero(
        "主题聚类与精选",
        "自动切分研究方向，用「区别于全局的词」给每个方向命名；精选分拆成影响力、新近度、相关度、"
        "完整度、可获得性五项，每项都能看到分数 —— 不认可排序时，你知道该改哪个权重。",
        "STEP 05 · ORGANIZE",
    )
    ps = state.papers()
    if len(ps) < 3:
        theme.empty("文献太少", "至少 3 篇才能聚类。先去检索更多文献。")
        return

    res = state.analysis()["cluster"]
    theme.stats([
        ("研究方向", str(res["k"]), "个"),
        ("最大方向", str(max((c["size"] for c in res["clusters"]), default=0)), "篇"),
        ("聚类质量", f"{res['silhouette']:.2f}", "轮廓系数"),
        ("开放获取", f"{round(sum(1 for p in ps if p.get('is_oa')) / len(ps) * 100)}", "%"),
    ])
    st.caption(f"聚类方法：{res['method']}。轮廓系数越接近 1 说明分得越干净；0.1 上下说明这批文献本身就是连续的，"
               "方向边界是人为划的，别把它当客观事实。")

    theme.section("方向概览", "", "01")
    _cluster_cards(ps, res)

    theme.section("时间与设计分布", "看一个方向是刚起步还是在收尾，也看这批文献的证据类型是否单一。", "02")
    c1, c2 = st.columns([1.3, 1])
    with c1:
        st.plotly_chart(_year_chart(ps, res["labels"], res["clusters"]), use_container_width=True,
                        config={"displayModeBar": False})
    with c2:
        st.plotly_chart(_design_chart(ps), use_container_width=True, config={"displayModeBar": False})

    theme.section("精选清单", "同一方向里优先读哪几篇。分数只用于排序，不评价研究本身的价值。", "03")
    _curation(ps, res)

    theme.method_note(
        "簇名来自「簇内 tf-idf 均值 − 全局均值」，优先使用作者关键词与主题标签；"
        "抽不到合适的词时退回高频实词。名字只是入口，点开看成员才是准确判断。"
    )
