"""推荐：按研究画像推文献，并且把「为什么推它」摊开给你看。"""
from __future__ import annotations

import datetime as dt

import streamlit as st

from core import library, profile, recommend, schema
from core import text as T
from core.sources import SOURCE_INFO, default_sources
from ui import theme


def _default_sources() -> list[str]:
    interests = profile.list_interests()
    picked: list[str] = []
    for it in interests:
        for s in default_sources(it.get("discipline", "通用 / 跨学科")):
            if s not in picked:
                picked.append(s)
    return picked[:5] or ["crossref", "openalex", "arxiv"]


def _controls() -> None:
    c1, c2, c3, c4 = st.columns([1, 1, 1.2, 1.6])
    k = c1.slider("推荐条数", 5, 40, 15, 5)
    per = c2.slider("每方向召回", 5, 25, 10, 5)
    this_year = dt.date.today().year
    year_from = c3.number_input("起始年份", 1990, this_year, this_year - 3, 1)
    sources = c4.multiselect("数据源", list(SOURCE_INFO), default=_default_sources(),
                             format_func=lambda s: SOURCE_INFO[s]["label"])

    with st.expander("打分权重（不认可排序时来这里调）", expanded=False):
        st.caption("五项相加为 100%。调完点「用新权重重排」即可，不会重新联网。")
        cols = st.columns(5)
        keys = list(recommend.DEFAULT_WEIGHTS)
        weights = {}
        for col, key in zip(cols, keys):
            weights[key] = col.slider(key, 0.0, 0.6, recommend.DEFAULT_WEIGHTS[key], 0.02,
                                      key=f"w_{key}")
        c5, c6 = st.columns([1, 1])
        diversity = c5.slider("多样性（MMR）", 0.3, 1.0, 0.72, 0.02,
                              help="调低会允许更多同质论文挤在一起；调高会更分散但相关性略降。")
        rescore = c6.button("用新权重重排", use_container_width=True)

    return {"k": k, "per": per, "year_from": int(year_from), "sources": sources,
            "weights": weights, "diversity": diversity, "rescore": rescore}


def _card(item: dict, idx: int) -> None:
    p = item["paper"]
    parts = item["parts"]
    bars = "".join(theme.bar(k, v) for k, v in parts.items())
    badges = [item["interest"]] if item.get("interest") else []
    if p.get("is_oa"):
        badges.append("开放获取")
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
        f'<div style="margin-top:7px;">{theme.pills(badges, "solid")}</div>'
        f'<div style="margin-top:7px;">{theme.pills(item["reasons"], "gold")}</div>'
        f'<div class="sm-abs" style="margin-top:8px;">{theme.esc(T.shorten(p.get("abstract") or "（无摘要）", 220))}</div>'
        f'</div><div style="width:190px;">{bars}</div></div></div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns([1, 1, 3])
    if c1.button("收藏", key=f"rfav_{p['sid']}", use_container_width=True):
        n = library.save([p], group="推荐", tags=item.get("interest") or "")
        st.toast("已收藏" if n else "已在文献库")
    if c2.button("看摘要", key=f"rsum_{p['sid']}", use_container_width=True):
        st.session_state[f"open_{p['sid']}"] = not st.session_state.get(f"open_{p['sid']}", False)
    if st.session_state.get(f"open_{p['sid']}"):
        from core import summarize
        s = summarize.structured(p)
        cols = st.columns(2)
        for i, slot in enumerate(("question", "method", "findings", "conclusion")):
            cell = s["slots"][slot]
            txt = cell["sentences"][0]["text"] if cell["sentences"] else "摘要未提及"
            with cols[i % 2]:
                st.markdown(
                    f'<div class="sm-slot {"empty" if not cell["sentences"] else ""}">'
                    f'<div class="lb">{theme.esc(cell["label"])}</div>'
                    f'<div class="tx">{theme.esc(T.shorten(txt, 260))}</div></div>',
                    unsafe_allow_html=True,
                )


def render() -> None:
    theme.hero(
        "推荐",
        "按研究画像多路召回，五路信号加权打分，MMR 保证多样性。"
        "每条都给出「命中哪个方向 / 和哪篇收藏接近 / 为什么值得看」，不接受可以直接调权重重排。",
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
    theme.stats([
        ("依据方向", str(s["count"]), "个"),
        ("种子文献", str(s["seeds"]), "篇"),
        ("关键词", str(len(s["keywords"])), "个"),
        ("文献库", str(len(library.list_papers())), "篇"),
    ])

    cfg = _controls()

    c1, c2 = st.columns([1, 3])
    if c1.button("生成推荐", type="primary", use_container_width=True):
        with st.spinner("正在多路召回并打分…（首次会打几个检索接口，约 5–15 秒）"):
            res = recommend.recommend(k=cfg["k"], per_interest=cfg["per"],
                                      year_from=cfg["year_from"], sources=cfg["sources"],
                                      progress=lambda m: st.write(f"· {m}"))
        st.session_state["rec_result"] = res
        st.session_state["rec_candidates"] = res.get("candidates") or []
        st.session_state["rec_weights"] = cfg["weights"]
    c2.caption("召回用的是画像关键词；如果结果太泛，回画像把关键词写具体一点。")

    res = st.session_state.get("rec_result")
    if cfg["rescore"] and st.session_state.get("rec_candidates"):
        items = recommend.score(st.session_state["rec_candidates"], k=cfg["k"],
                                weights=cfg["weights"], diversity=cfg["diversity"])
        st.session_state["rec_result"] = {**res, "items": items}
        res = st.session_state["rec_result"]
        st.toast("已按新权重重排")

    if not res:
        theme.section("还没生成", "点上面的「生成推荐」。每次生成都会重新读画像，改完画像不用重启。", "01")
        return

    if res.get("error"):
        st.warning(res["error"])
        return

    basis = res.get("basis") or {}
    theme.stats([
        ("推荐条数", str(len(res["items"])), "条"),
        ("召回候选", str(basis.get("candidates", 0)), "篇"),
        ("召回轮次", str(len(basis.get("queries") or [])), "轮"),
        ("耗时", str(res.get("seconds", 0)), "秒"),
    ])
    st.caption("召回式：" + "　|　".join(basis.get("queries") or []))

    failed = [s for s in (res.get("status") or []) if not s.get("ok")]
    if failed:
        st.caption("以下源本次未返回结果：" + "、".join(sorted({f["label"] for f in failed})))

    theme.section("推荐清单", "分数是相对值，只用于排序；五项分项解释了这个分数从哪来。", "02")
    for i, item in enumerate(res["items"], 1):
        _card(item, i)

    c1, c2 = st.columns(2)
    if c1.button("全部收藏到「推荐」书架", use_container_width=True):
        n = recommend.save_all(res["items"], group="推荐")
        st.success(f"新增 {n} 篇")
    with c2:
        import json
        st.download_button("导出推荐清单 JSON",
                           json.dumps(res["items"], ensure_ascii=False, indent=2).encode("utf-8"),
                           file_name="recommendations.json", use_container_width=True)

    theme.method_note(
        "推荐不联网训练、不画像你的阅读行为，只用你显式写的方向与关键词做匹配。"
        "分数偏低（比如 20 分）不代表文献差，只说明它和你的画像关键词重合得少 —— "
        "跨学科的经典工作常常这样被低估。"
    )
