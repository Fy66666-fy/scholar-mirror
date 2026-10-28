"""关联图谱：把「这几篇有什么关系」画出来，并且让每条边都能解释。"""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from core import related, schema
from core import text as T
from ui import state, theme

PALETTE = ["#1f4e5f", "#b4623c", "#3f7a5e", "#a8822f", "#6b7f9e",
           "#8b6b8f", "#4f6f52", "#9e5b5b", "#5c6b73", "#c08a5a"]


def _network_figure(ps: list[dict], graph: dict, labels: list[int]) -> go.Figure:
    nodes = graph["nodes"]
    pos = related.layout(nodes, graph["edges"])
    idx = {p["sid"]: i for i, p in enumerate(nodes)}
    degree = graph.get("degree") or {}

    fig = go.Figure()
    # 边：按相对强度分两档，弱边更淡，避免视觉噪音
    for bucket, (lo, hi, color, width) in {
        "弱": (0.0, 0.5, "rgba(120,130,135,0.22)", 0.8),
        "强": (0.5, 1.01, "rgba(31,78,95,0.5)", 1.6),
    }.items():
        xs, ys = [], []
        for e in graph["edges"]:
            if not (lo <= e.get("strength", e["weight"]) < hi):
                continue
            a, b = pos[e["source"]], pos[e["target"]]
            xs += [a[0], b[0], None]
            ys += [a[1], b[1], None]
        if xs:
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="lines", line=dict(color=color, width=width),
                hoverinfo="skip", showlegend=False, name=f"{bucket}关联",
            ))

    degs = [degree.get(p["sid"], 0) for p in nodes]
    max_deg = max(degs) if degs else 1
    for cid in sorted(set(labels)):
        members = [i for i, lab in enumerate(labels) if lab == cid]
        fig.add_trace(go.Scatter(
            x=[pos[nodes[i]["sid"]][0] for i in members],
            y=[pos[nodes[i]["sid"]][1] for i in members],
            mode="markers",
            marker=dict(
                size=[9 + 13 * (degree.get(nodes[i]["sid"], 0) / max(max_deg, 1)) for i in members],
                color=PALETTE[cid % len(PALETTE)],
                line=dict(color="#fffdf8", width=1.4),
                opacity=0.92,
            ),
            name=f"方向 {cid + 1}",
            customdata=[[
                nodes[i].get("title", ""), nodes[i].get("year") or "—",
                schema.DESIGN_LABELS.get(nodes[i].get("design"), "未识别"),
                nodes[i].get("cited_by") or 0, degree.get(nodes[i]["sid"], 0),
            ] for i in members],
            hovertemplate=("<b>%{customdata[0]}</b><br>%{customdata[1]} · %{customdata[2]}"
                           "<br>被引 %{customdata[3]} · 连接 %{customdata[4]}<extra></extra>"),
        ))

    # 只给「连接最多」的节点打标签，否则几十个标签会糊成一片
    top = sorted(nodes, key=lambda p: -degree.get(p["sid"], 0))[:14]
    fig.add_trace(go.Scatter(
        x=[pos[p["sid"]][0] for p in top],
        y=[pos[p["sid"]][1] for p in top],
        mode="text",
        text=[T.shorten(p.get("title", ""), 26) for p in top],
        textposition="top center",
        textfont=dict(size=9.5, color="#4a5a63"),
        hoverinfo="skip", showlegend=False,
    ))

    fig.update_xaxes(visible=False, range=[-0.12, 1.12])
    fig.update_yaxes(visible=False, range=[-0.12, 1.12], scaleanchor="x", scaleratio=1)
    return theme.plotly_layout(fig, height=560)


def render() -> None:
    theme.hero(
        "关联图谱",
        "四条信号合成一条边：摘要主题、概念标签、引用关系、发表元数据。"
        "点节点看它和谁最像、为什么像；跨方向的「桥梁文献」往往是最值得先读的那几篇。",
        "STEP 04 · CONNECT",
    )
    ps = state.papers()
    if len(ps) < 3:
        theme.empty("文献太少", "至少需要 3 篇才能看出结构。先去检索更多文献。")
        return

    c1, c2, c3 = st.columns([1.4, 1, 1])
    keep_pct = c1.slider("只保留关联最强的前 N% 关系", 5, 60, 25, 5,
                         help="按分位数取阈值。绝对相似度在不同主题上不可比："
                              "同一课题常在 0.1–0.3，跨学科混检的中位数只有 0.03。")
    per_node = c2.slider("每篇最多连线", 2, 8, 4)
    mode = c3.selectbox("节点大小", ["连接数", "被引次数"])

    graph = related.build_graph(ps, percentile=100 - keep_pct, max_edges_per_node=per_node)
    labels_map = state.cluster_labels()
    labels = [labels_map.get(p["sid"], 0) for p in ps]

    if mode == "被引次数":
        for p in graph["nodes"]:
            graph["degree"][p["sid"]] = p.get("cited_by") or 0

    st.plotly_chart(_network_figure(ps, graph, labels), use_container_width=True,
                    config={"displayModeBar": False})

    stt = graph["stats"]
    theme.stats([
        ("节点", str(stt.get("nodes", 0)), "篇"),
        ("连线", str(stt.get("edges", 0)), "条"),
        ("平均连接", str(stt.get("avg_degree", 0)), ""),
        ("孤立节点", str(stt.get("isolated", 0)), "篇"),
        ("连通块", str(stt.get("components", 0)), "个"),
        ("最大连通块", str(stt.get("largest_component", 0)), "篇"),
    ])
    if stt.get("isolated", 0) > 0:
        st.caption(f"有 {stt['isolated']} 篇与其它文献都不够相似 —— 可能是边缘主题，也可能是摘要缺失导致算不出关系。")

    theme.section("两篇之间到底像在哪", "选一篇，看它最接近的几篇，以及每一项信号的贡献。", "01")
    options = {f"{T.shorten(p.get('title', ''), 66)}（{p.get('year') or '—'}）": p for p in ps}
    pick = st.selectbox("锚点文献", list(options))
    anchor = options[pick]
    rels = related.top_related(anchor, ps, k=6)
    if not rels:
        st.caption("没有找到足够相似的文献。")
    for r in rels:
        parts = r["parts"]
        bars = "".join([
            theme.bar("摘要主题", parts["text"] * 100),
            theme.bar("概念重叠", parts["concept"] * 100),
            theme.bar("引用关系", parts["citation"] * 100),
            theme.bar("发表元数据", parts["meta"] * 100),
        ])
        st.markdown(
            f'<div class="sm-card"><div style="display:flex;justify-content:space-between;gap:14px;">'
            f'<div style="flex:1;"><div style="font-size:14px;font-weight:650;line-height:1.5;">'
            f'{theme.esc(T.shorten(r["paper"].get("title", ""), 96))}</div>'
            f'<div class="sm-meta">{theme.esc(schema.venue_year(r["paper"]))}'
            f'　·　关联度 <b>{r["score"]:.2f}</b>（{related.level(r["score"])}）</div>'
            f'<div style="margin-top:6px;">{theme.pills(r["reasons"], "solid")}</div></div>'
            f'<div style="width:190px;">{bars}</div></div></div>',
            unsafe_allow_html=True,
        )

    theme.section("跨方向桥梁", "跨簇边占比高的节点：它们把两个研究方向连在一起，通常是最值得优先读的综述或方法迁移工作。", "02")
    bridges = state.analysis()["bridges"]
    if not bridges:
        st.caption("本次没有跨方向的桥梁文献。可能这批文献本来就集中在一个方向。")
    for b in bridges:
        st.markdown(
            f'<div class="sm-paper" style="padding:10px 0;">'
            f'<div class="sm-title">{theme.esc(b["title"])}</div>'
            f'<div class="sm-meta">{b["year"] or "—"} · 连接 {b["clusters_linked"]} 个方向 · '
            f'跨簇边占比 {b["cross_ratio"]:.0%} · 总连接 {b["edges"]}</div></div>',
            unsafe_allow_html=True,
        )

    with st.expander("关联矩阵（热力图）", expanded=False):
        import plotly.express as px
        import numpy as np

        m = graph["matrix"]
        short = [T.shorten(p.get("title", ""), 26) for p in graph["nodes"]]
        fig = px.imshow(m, x=short, y=short, color_continuous_scale="Teal",
                        zmin=0, zmax=1, aspect="auto")
        fig.update_layout(height=520, coloraxis_colorbar=dict(title="关联度"))
        fig.update_xaxes(tickfont=dict(size=8), tickangle=60)
        fig.update_yaxes(tickfont=dict(size=8))
        st.plotly_chart(theme.plotly_layout(fig, height=540), use_container_width=True,
                        config={"displayModeBar": False})

    with st.expander("导出关联边", expanded=False):
        lines = ["source,target,weight,text,concept,citation,meta"]
        for e in graph["edges"]:
            p = e["parts"]
            lines.append(f'"{e["source"]}","{e["target"]}",{e["weight"]:.3f},'
                         f'{p["text"]},{p["concept"]},{p["citation"]},{p["meta"]}')
        st.download_button("下载 CSV", "\n".join(lines).encode("utf-8"), file_name="edges.csv")

    theme.method_note(
        "关联度不是「引用强度」，也不是「质量」。它回答的是「这两篇在讲同一件事吗」，"
        "所以两篇互相批评的论文也可能高度关联。缺引用数据的源会让引用项自动降权，"
        "而不是记 0 分。"
    )
