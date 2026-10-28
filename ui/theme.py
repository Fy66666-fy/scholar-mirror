"""界面主题与通用组件。

设计取向：纸感、克制、信息密度高。
- 底色是暖白（#f7f5f0），卡片是更亮的米白，边界用细线而不是阴影；
- 主色深海蓝绿（#1f4e5f）用于结构与强调，砖红（#b4623c）只用于「需要注意」；
- 数字用等宽字体，表格与分项分数对齐后更容易横向比较。

所有组件都返回 HTML 字符串，由页面用 st.markdown(..., unsafe_allow_html=True) 渲染。
Streamlit 原生组件负责交互（按钮、选择、下载），HTML 只负责「看起来像一份报告」。
"""
from __future__ import annotations

import html as _html
import re

import streamlit as st

INK = "#1b2a33"
MUTED = "#6b767c"
LINE = "#e4ded3"
ACCENT = "#1f4e5f"
ACCENT_SOFT = "#e8eff1"
WARN = "#b4623c"
GOLD = "#a8822f"
OK = "#3f7a5e"

CSS = """
<style>
:root{
  --ink:#1b2a33; --muted:#6b767c; --line:#e4ded3; --paper:#f7f5f0;
  --surface:#fffdf8; --accent:#1f4e5f; --accent-soft:#e8eff1;
  --warn:#b4623c; --gold:#a8822f; --ok:#3f7a5e;
}
.stApp{background:
  radial-gradient(1200px 600px at 12% -10%, #eef2f0 0%, transparent 60%),
  radial-gradient(900px 500px at 92% 0%, #f6efe6 0%, transparent 55%),
  var(--paper);
}
html, body, [class*="css"]{
  font-family: "Inter","Helvetica Neue","PingFang SC","Microsoft YaHei",sans-serif;
  color: var(--ink);
}
.block-container{padding-top: 2.2rem; padding-bottom: 4rem; max-width: 1240px;}
#MainMenu, footer, header[data-testid="stHeader"]{visibility:hidden;}

/* 侧边栏 */
section[data-testid="stSidebar"]{
  background: linear-gradient(180deg,#12333f 0%, #173f4d 55%, #1b4756 100%);
  border-right: 1px solid #0e2a34;
}
section[data-testid="stSidebar"] *{color:#e9eef0 !important;}
section[data-testid="stSidebar"] .stRadio label, 
section[data-testid="stSidebar"] .stSelectbox label{color:#b9c9cf !important;}
section[data-testid="stSidebar"] hr{border-color:#2c5867;}

/* 侧边栏导航按钮：做成「导航链接」而不是按钮 */
section[data-testid="stSidebar"] .stButton>button{
  background:transparent; border:1px solid transparent; color:#c9d8de !important;
  text-align:left; justify-content:flex-start; font-weight:500; font-size:13.5px;
  padding:7px 11px; border-radius:8px; min-height:0;
}
section[data-testid="stSidebar"] .stButton>button:hover{
  background:rgba(255,255,255,.07); border-color:transparent; color:#fff !important;
}
section[data-testid="stSidebar"] .stButton>button[kind="primary"]{
  background:#2b6577; border-color:#2b6577; color:#fff !important; font-weight:650;
}
section[data-testid="stSidebar"] .stButton>button p{font-size:13.5px;}

/* 标题 */
.sm-hero{padding: 6px 0 18px 0; border-bottom:1px solid var(--line); margin-bottom:22px;}
.sm-kicker{font-size:12px; letter-spacing:.18em; text-transform:uppercase; color:var(--gold); font-weight:600;}
.sm-h1{font-size:34px; line-height:1.22; font-weight:700; letter-spacing:-.02em; margin:8px 0 6px;}
.sm-h1 .thin{font-weight:300; color:var(--muted);}
.sm-sub{font-size:14.5px; color:var(--muted); max-width:820px; line-height:1.7;}
.sm-h2{font-size:19px; font-weight:700; margin:26px 0 4px; letter-spacing:-.01em;}
.sm-h2 .idx{color:var(--gold); font-weight:600; margin-right:8px; font-variant-numeric:tabular-nums;}
.sm-hint{font-size:12.5px; color:var(--muted); margin-bottom:12px; line-height:1.6;}

/* 卡片 */
.sm-card{background:var(--surface); border:1px solid var(--line); border-radius:14px;
  padding:16px 18px; margin-bottom:12px;}
.sm-card.tight{padding:12px 14px;}
.sm-card.accent{border-left:3px solid var(--accent);}
.sm-card.warn{border-left:3px solid var(--warn); background:#fdf8f4;}
.sm-card.flat{background:transparent; border-style:dashed;}

/* 统计 */
.sm-stats{display:flex; gap:10px; flex-wrap:wrap; margin:6px 0 18px;}
.sm-stat{flex:1 1 130px; background:var(--surface); border:1px solid var(--line);
  border-radius:12px; padding:12px 14px;}
.sm-stat .k{font-size:11.5px; color:var(--muted); letter-spacing:.04em;}
.sm-stat .v{font-size:24px; font-weight:700; font-variant-numeric:tabular-nums; margin-top:2px;}
.sm-stat .u{font-size:12px; color:var(--muted); font-weight:500; margin-left:2px;}

/* 标签 */
.sm-pill{display:inline-block; font-size:11.5px; padding:2px 9px; border-radius:999px;
  border:1px solid var(--line); background:#faf8f3; color:var(--muted); margin:0 5px 5px 0;
  white-space:nowrap;}
.sm-pill.solid{background:var(--accent-soft); color:var(--accent); border-color:#cfdde1;}
.sm-pill.warn{background:#fbeee7; color:var(--warn); border-color:#eed7c9;}
.sm-pill.ok{background:#eaf2ec; color:var(--ok); border-color:#cfe0d4;}
.sm-pill.gold{background:#f8f1de; color:var(--gold); border-color:#ecdfbd;}

/* 文献条目 */
.sm-paper{padding:13px 0; border-bottom:1px dashed var(--line);}
.sm-paper:last-child{border-bottom:none;}
.sm-title{font-size:15px; font-weight:650; line-height:1.45; margin-bottom:4px;}
.sm-title a{color:var(--ink); text-decoration:none; border-bottom:1px solid #d8d2c6;}
.sm-title a:hover{color:var(--accent); border-color:var(--accent);}
.sm-meta{font-size:12.5px; color:var(--muted); margin-bottom:6px;}
.sm-abs{font-size:13.5px; line-height:1.75; color:#33454f;}

/* 槽位 */
.sm-slot{background:var(--surface); border:1px solid var(--line); border-radius:12px;
  padding:13px 15px; margin-bottom:10px;}
.sm-slot .lb{font-size:11.5px; letter-spacing:.08em; color:var(--gold); font-weight:600;
  text-transform:uppercase; margin-bottom:6px;}
.sm-slot .tx{font-size:14px; line-height:1.78;}
.sm-slot.empty{background:transparent; border-style:dashed;}
.sm-slot.empty .tx{color:#9aa3a8; font-size:13px;}
.sm-quote{border-left:2px solid #d9d2c5; padding-left:10px; color:#4a5a63; font-size:13px;}

/* 分数条 */
.sm-bar{height:6px; border-radius:3px; background:#ece7dd; overflow:hidden; margin-top:5px;}
.sm-bar > i{display:block; height:100%; background:var(--accent); border-radius:3px;}

/* 证据 */
.sm-ev{border-left:2px solid #e0d8c8; padding:6px 0 6px 12px; margin:8px 0; font-size:13px;
  line-height:1.7; color:#3d4d56;}
.sm-ev .src{color:var(--muted); font-size:12px;}

/* 空状态 */
.sm-empty{border:1px dashed #d9d2c5; border-radius:14px; padding:38px 22px; text-align:center;
  background:rgba(255,253,248,.6);}
.sm-empty .t{font-size:16px; font-weight:650; margin-bottom:6px;}
.sm-empty .d{font-size:13px; color:var(--muted); line-height:1.7; max-width:520px; margin:0 auto;}

/* 表格 */
.sm-table{width:100%; border-collapse:collapse; font-size:12.8px; background:var(--surface);}
.sm-table th{background:#f0ece3; color:#4c5a62; font-weight:600; text-align:left;
  padding:8px 10px; border-bottom:1px solid var(--line); white-space:nowrap;}
.sm-table td{padding:8px 10px; border-bottom:1px solid #efeae1; vertical-align:top; line-height:1.6;}
.sm-table tr:hover td{background:#fbf8f1;}

/* 原生组件微调 */
.stButton>button{border-radius:9px; border:1px solid var(--line); background:var(--surface);
  color:var(--ink); font-weight:600; padding:.42rem .9rem; transition:all .15s;}
.stButton>button:hover{border-color:var(--accent); color:var(--accent); background:#f4f8f9;}
.stButton>button[kind="primary"]{background:var(--accent); border-color:var(--accent); color:#fff;}
.stButton>button[kind="primary"]:hover{background:#173f4d; color:#fff;}
.stDownloadButton>button{border-radius:9px; border:1px solid var(--line); background:var(--surface);}
div[data-testid="stExpander"]{border:1px solid var(--line); border-radius:12px; background:var(--surface);}
div[data-testid="stExpander"] summary{font-size:13.5px; font-weight:600;}
.stTabs [data-baseweb="tab-list"]{gap:4px; border-bottom:1px solid var(--line);}
.stTabs [data-baseweb="tab"]{height:38px; font-size:13.5px; padding:0 14px;}
.stTabs [aria-selected="true"]{color:var(--accent); font-weight:700;}
div[data-testid="stMetricValue"]{font-size:26px;}
.stSlider label, .stSelectbox label, .stTextInput label, .stTextArea label,
.stMultiSelect label, .stNumberInput label, .stRadio label{font-size:12.5px; color:var(--muted);}
.sm-foot{margin-top:36px; padding-top:14px; border-top:1px solid var(--line);
  font-size:12px; color:var(--muted); line-height:1.8;}
</style>
"""


def inject() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def esc(text: str) -> str:
    return _html.escape(str(text or ""))


def hero(title: str, subtitle: str, kicker: str = "SCHOLAR MIRROR") -> None:
    st.markdown(
        f"""<div class="sm-hero">
        <div class="sm-kicker">{esc(kicker)}</div>
        <div class="sm-h1">{title}</div>
        <div class="sm-sub">{subtitle}</div>
        </div>""",
        unsafe_allow_html=True,
    )


def section(title: str, hint: str = "", idx: str = "") -> None:
    num = f'<span class="idx">{esc(idx)}</span>' if idx else ""
    h = f'<div class="sm-h2">{num}{esc(title)}</div>'
    if hint:
        h += f'<div class="sm-hint">{esc(hint)}</div>'
    st.markdown(h, unsafe_allow_html=True)


def stats(items: list[tuple[str, str, str]]) -> None:
    """items: [(标签, 值, 单位)]"""
    cells = "".join(
        f'<div class="sm-stat"><div class="k">{esc(k)}</div>'
        f'<div class="v">{esc(v)}<span class="u">{esc(u)}</span></div></div>'
        for k, v, u in items
    )
    st.markdown(f'<div class="sm-stats">{cells}</div>', unsafe_allow_html=True)


def pill(text: str, tone: str = "") -> str:
    cls = f"sm-pill {tone}".strip()
    return f'<span class="{cls}">{esc(text)}</span>'


def pills(items: list[str], tone: str = "") -> str:
    return "".join(pill(i, tone) for i in items if i)


def card(html: str, tone: str = "") -> None:
    cls = f"sm-card {tone}".strip()
    st.markdown(f'<div class="{cls}">{html}</div>', unsafe_allow_html=True)


def empty(title: str, desc: str) -> None:
    st.markdown(
        f'<div class="sm-empty"><div class="t">{esc(title)}</div>'
        f'<div class="d">{desc}</div></div>',
        unsafe_allow_html=True,
    )


def method_note(text: str) -> None:
    st.markdown(
        f'<div class="sm-foot">{text}</div>',
        unsafe_allow_html=True,
    )


def bar(label: str, value: float, max_value: float = 100.0, suffix: str = "") -> str:
    pct = 0 if max_value <= 0 else max(0.0, min(100.0, value / max_value * 100))
    return (
        f'<div style="margin-bottom:9px;">'
        f'<div style="display:flex;justify-content:space-between;font-size:12.5px;color:#4a5a63;">'
        f'<span>{esc(label)}</span><span style="font-variant-numeric:tabular-nums;">'
        f'{value:.0f}{esc(suffix)}</span></div>'
        f'<div class="sm-bar"><i style="width:{pct:.1f}%"></i></div></div>'
    )


def paper_row(p: dict, *, show_abstract: bool = True, abstract_chars: int = 260,
              extra: str = "", badges: list[str] | None = None) -> str:
    from core import schema
    from core import text as T

    title = esc(p.get("title") or "（无标题）")
    url = p.get("url") or (f"https://doi.org/{p['doi']}" if p.get("doi") else "")
    title_html = f'<a href="{esc(url)}" target="_blank">{title}</a>' if url else title
    meta = [schema.venue_year(p), schema.display_authors(p)]
    if p.get("cited_by"):
        meta.append(f"被引 {p['cited_by']}")
    design = schema.DESIGN_LABELS.get(p.get("design"), "")
    if design and design != "未识别":
        meta.append(design)
    badge_html = pills(badges or [], "solid")
    abs_html = ""
    if show_abstract and p.get("abstract"):
        abs_html = f'<div class="sm-abs">{esc(T.shorten(p["abstract"], abstract_chars))}</div>'
    return (
        f'<div class="sm-paper"><div class="sm-title">{title_html}</div>'
        f'<div class="sm-meta">{esc(" · ".join(m for m in meta if m))}</div>'
        f'{badge_html}{abs_html}{extra}</div>'
    )


def table(headers: list[str], rows: list[list[str]], max_width: str = "") -> None:
    style = f' style="max-width:{max_width}"' if max_width else ""
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = ""
    for r in rows:
        body += "<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>"
    st.markdown(
        f'<div style="overflow-x:auto"><table class="sm-table"{style}>'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>",
        unsafe_allow_html=True,
    )


def source_status(status: list[dict]) -> None:
    """检索源状态条：成功绿点、失败红点，附条数与耗时。"""
    if not status:
        return
    parts = []
    for s in status:
        color = OK if s.get("ok") else (WARN if s.get("error") else "#9aa3a8")
        label = esc(s.get("label", ""))
        info = f"{s.get('count', 0)} 条 · {s.get('seconds', 0)}s" if s.get("ok") else (
            "限流/不可用" if not s.get("error") else "请求失败")
        parts.append(
            f'<span style="display:inline-flex;align-items:center;gap:6px;margin-right:16px;'
            f'font-size:12.5px;color:#4a5a63;">'
            f'<i style="width:7px;height:7px;border-radius:50%;background:{color};display:inline-block"></i>'
            f'{label}<span style="color:#8b9499">{esc(info)}</span></span>'
        )
    st.markdown(f'<div style="margin:2px 0 14px;">{"".join(parts)}</div>', unsafe_allow_html=True)


def plotly_layout(fig, height: int = 420, title: str = ""):
    fig.update_layout(
        height=height,
        title=dict(text=title, font=dict(size=14, color=INK)) if title else None,
        margin=dict(l=10, r=10, t=30 if title else 10, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, PingFang SC, Microsoft YaHei", size=12, color=INK),
        hoverlabel=dict(bgcolor="#fffdf8", bordercolor=LINE, font_size=12),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(size=11)),
    )
    return fig


def md_escape_cell(text: str) -> str:
    return str(text or "").replace("|", "／").replace("\n", " ")
