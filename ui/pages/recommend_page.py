"""推荐：五路召回、八维打分、可调权重，结果进待读而不是直接塞进文献库。"""
from __future__ import annotations

import datetime as dt
import json

import streamlit as st

from core import library, llm, profile, reading, recommend, schema, summarize
from core import text as T
from core.sources import SOURCE_INFO, default_sources
from ui import theme

CHANNEL_TONE = {"profile": "solid", "seed": "ok", "citation": "gold",
                "trend": "warn", "explore": ""}


def _default_sources() -> list[str]:
    picked: list[str] = []
    for it in profile.list_interests():
        for s in default_sources(it.get("discipline", "通用 / 跨学科")):
            if s not in picked:
                picked.append(s)
    return picked[:5] or ["crossref", "openalex", "arxiv"]


def _controls() -> dict:
    c1, c2, c3, c4 = st.columns([1, 1, 1.2, 1.6])
    k = c1.slider("推荐条数", 5, 40, 15, 5)
    per = c2.slider("每路召回", 5, 25, 10, 5)
    this_year = dt.date.today().year
    year_from = c3.number_input("起始年份", 1990, this_year, this_year - 3, 1)
    sources = c4.multiselect("数据源", list(SOURCE_INFO), default=_default_sources(),
                             format_func=lambda s: SOURCE_INFO[s]["label"])

    with st.expander("召回通道与权重", expanded=False):
        st.caption("召回决定「有哪些候选」，权重决定「怎么排」。调权重不会重新联网。")
        c5, c6 = st.columns(2)
        use_cit = c5.checkbox("启用引用脉络召回（前向引用，走 OpenAlex）", value=True)
        use_trend = c6.checkbox("启用近期热点召回（近两年被引最高）", value=True)
        cols = st.columns(4)
        labels = list(recommend.FEATURE_LABELS.values())
        keys = list(recommend.FEATURE_LABELS)
        weights = {}
        for i, key in enumerate(keys):
            weights[key] = cols[i % 4].slider(recommend.FEATURE_LABELS[key], 0.0, 0.5,
                                              recommend.PRIOR[key], 0.02, key=f"w_{key}")
        c7, c8 = st.columns([1, 1])
        diversity = c7.slider("多样性（MMR）", 0.3, 1.0, 0.72, 0.02)
        rescore = c8.button("用新权重重排", use_container_width=True)

    return {"k": k, "per": per, "year_from": int(year_from), "sources": sources,
            "use_citation": use_cit, "use_trend": use_trend,
            "weights": weights, "diversity": diversity, "rescore": rescore}


def _card(item: dict, idx: int) -> None:
    p = item["paper"]
    channel = recommend.CHANNELS.get(item["channel"], item["channel"])
    bars = "".join(theme.bar(k, v) for k, v in item["parts"].items())
    url = p.get("url") or (f"https://doi.org/{p['doi']}" if p.get("doi") else "")
    title = theme.esc(p.get("title", ""))
    if url:
        title = (f'<a href="{theme.esc(url)}" target="_blank" style="color:#1b2a33;'
                 f'text-decoration:none;border-bottom:1px solid #d8d2c6;">{title}</a>')
    st.markdown(
        f'<div class="sm-card"><div style="display:flex;gap:16px;">'
        f'<div style="min-width:44px;text-align:center;">'
        f'<div style="font-size:20px;font-weight:700;color:#a8822f;'
        f'font-variant-numeric:tabular-nums;">{idx:02d}</div>'
        f'<div style="font-size:10.5px;color:#8b9499;">{item["score"]:.0f} 分</div></div>'
        f'<div style="flex:1;min-width:0;">'
        f'<div style="font-size:14.5px;font-weight:650;line-height:1.5;">{title}</div>'
        f'<div class="sm-meta" style="margin-top:5px;">{theme.esc(schema.venue_year(p))}'
        f' · {theme.esc(schema.display_authors(p))}</div>'
        f'<div style="margin-top:7px;">{theme.pill(channel, CHANNEL_TONE.get(item["channel"], ""))}'
        f'{theme.pills(item.get("reasons") or [], "gold")}</div>'
        f'<div class="sm-abs" style="margin-top:8px;">{theme.esc(T.shorten(p.get("abstract") or "（无摘要）", 200))}</div>'
        f'</div><div style="width:186px;">{bars}</div></div></div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns([1, 1, 3])
    queued = reading.has(p["sid"])
    if c1.button("已待读" if queued else "设为待读", key=f"rq_{p['sid']}",
                 use_container_width=True, type="primary" if not queued else "secondary"):
        if queued:
            st.toast("已在待读队列")
        else:
            reading.add_one(p, priority=2, source="推荐")
            recommend.log_event(p["sid"], "save", item["channel"], item["score"], item["feats"])
            st.toast("已加入待读")
    if c2.button("不感兴趣", key=f"rs_{p['sid']}", use_container_width=True):
        recommend.log_event(p["sid"], "skip", item["channel"], item["score"], item["feats"])
        st.session_state.setdefault("rec_hidden", set()).add(p["sid"])
        st.toast("已记录，会降低同类推荐的权重")
    if c3.button("看摘要", key=f"rsum_{p['sid']}", use_container_width=True):
        st.session_state[f"open_{p['sid']}"] = not st.session_state.get(f"open_{p['sid']}", False)
    if st.session_state.get(f"open_{p['sid']}"):
        s = summarize.structured(p)
        cols = st.columns(2)
        for i, slot in enumerate(("question", "method", "findings", "conclusion")):
            cell = s["slots"][slot]
            txt = cell["sentences"][0]["text"] if cell["sentences"] else "摘要未提及"
            with cols[i % 2]:
                st.markdown(
                    f'<div class="sm-slot {"empty" if not cell["sentences"] else ""}">'
                    f'<div class="lb">{theme.esc(cell["label"])}</div>'
                    f'<div class="tx">{theme.esc(T.shorten(txt, 240))}</div></div>',
                    unsafe_allow_html=True,
                )


def render() -> None:
    theme.hero(
        "推荐",
        "五路召回（画像、种子、引用、热点、探索），八维特征打分，再做多样性与配额。"
        "结果只进「待读」，不进收藏 —— 想长期留的再去文献库。",
        "DISCOVER · 推荐",
    )
    if not profile.is_ready() and not profile.seeds():
        theme.empty("先建一个研究方向", "推荐需要知道你在做什么。去「研究画像」加一个方向，"
                                        "或把库里几篇代表作设为种子文献。")
        if st.button("去建画像 →", type="primary"):
            st.session_state["_goto"] = "研究画像"
            st.rerun()
        return

    s = profile.summary()
    fb = recommend.feedback_stats()
    theme.stats([
        ("依据方向", str(s["count"]), "个"),
        ("种子文献", str(s["seeds"]), "篇"),
        ("待读队列", str(reading.stats()["pending"]), "篇"),
        ("反馈样本", str(fb["save"] + fb["skip"]), "条"),
    ])

    cfg = _controls()

    c1, c2 = st.columns([1, 3])
    if c1.button("生成推荐", type="primary", use_container_width=True):
        with st.spinner("多路召回 + 排序中…（引用召回会多打两个 OpenAlex 接口）"):
            res = recommend.recommend(k=cfg["k"], per_channel=cfg["per"],
                                      year_from=cfg["year_from"], sources=cfg["sources"],
                                      use_citation=cfg["use_citation"],
                                      use_trend=cfg["use_trend"],
                                      diversity=cfg["diversity"],
                                      progress=lambda m: st.write(f"· {m}"))
        st.session_state["rec_result"] = res
        st.session_state["rec_candidates"] = res.get("candidates") or []
        st.session_state.pop("rec_hidden", None)
    c2.caption(f"当前排序权重：{recommend._weights()[1]}。反馈够 12 条后会自动校准，"
               "冷启动阶段用先验权重。")

    res = st.session_state.get("rec_result")
    if cfg["rescore"] and st.session_state.get("rec_candidates"):
        items = recommend.score(st.session_state["rec_candidates"], k=cfg["k"],
                                weights=cfg["weights"], diversity=cfg["diversity"])
        st.session_state["rec_result"] = {**res, "items": items}
        res = st.session_state["rec_result"]
        st.toast("已按新权重重排")

    if not res:
        theme.section("还没生成", "点「生成推荐」。每次生成都会重读画像，改完画像不用重启。", "01")
        return
    if res.get("error"):
        st.warning(res["error"])
        return

    basis = res.get("basis") or {}
    channels = basis.get("channels") or {}
    theme.stats([
        ("推荐条数", str(len(res["items"])), "条"),
        ("候选池", str(basis.get("candidates", 0)), "篇"),
        ("召回轮次", str(len(basis.get("queries") or [])), "轮"),
        ("耗时", str(res.get("seconds", 0)), "秒"),
    ])
    st.caption("召回式：" + "　|　".join(basis.get("queries") or []))
    if channels:
        st.markdown(theme.pills([f"{k} {v}" for k, v in channels.items()], "solid"),
                    unsafe_allow_html=True)

    failed = [s for s in (res.get("status") or []) if not s.get("ok")]
    if failed:
        st.caption("以下源本次未返回结果：" + "、".join(sorted({f["label"] for f in failed})))

    theme.section("推荐清单", "分数是加权结果，右侧分项说明它从哪来。", "02")
    hidden = st.session_state.get("rec_hidden") or set()
    shown = [it for it in res["items"] if it["paper"]["sid"] not in hidden]
    if not shown:
        st.info("这一批都标记为不感兴趣了，重新生成一次试试。")
    for i, item in enumerate(shown, 1):
        _card(item, i)

    c1, c2, c3 = st.columns([1.2, 1, 1])
    if c1.button("全部加入待读", use_container_width=True):
        added, existed = recommend.save_all(shown, priority=2)
        for it in shown:
            recommend.log_event(it["paper"]["sid"], "save", it["channel"], it["score"], it["feats"])
        st.success(f"新增 {added} 篇，已在队列 {existed} 篇")
    c2.download_button("导出 JSON", json.dumps(shown, ensure_ascii=False, indent=2).encode("utf-8"),
                       file_name="recommendations.json", use_container_width=True)
    if c3.button("去待读 →", use_container_width=True):
        st.session_state["_goto"] = "待读"
        st.rerun()

    theme.method_note(
        "推荐只依据你显式写的方向、种子文献和反馈，不训练你的阅读行为画像。"
        "分数低不代表文献差，只说明它和你现在写下的关键词重合得少；跨学科的经典工作常被这样低估。"
        "「不感兴趣」只影响排序权重，不会从待读或文献库里删任何东西。"
    )
