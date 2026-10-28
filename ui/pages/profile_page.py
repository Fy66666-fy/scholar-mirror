"""研究画像：告诉系统你在做什么。

只让用户显式维护，不做隐式推断 —— 文献场景里隐式画像很容易跑偏：
你今天查了一篇教学法的文章，不代表你转行做教育研究。
"""
from __future__ import annotations

import json

import streamlit as st

from core import library, profile, schema
from core import text as T
from ui import theme


def _add_form() -> None:
    theme.section("新增研究方向", "关键词用逗号或空格分隔。写得越具体，推荐越准（例：plasma p-tau217, amyloid PET, blood biomarker）。", "01")
    with st.form("add_interest", clear_on_submit=True):
        c1, c2 = st.columns([2, 1])
        label = c1.text_input("方向名称", placeholder="例：阿尔茨海默病血液标志物")
        discipline = c2.selectbox("学科", list(schema.DISCIPLINES))
        keywords = st.text_input("关键词", placeholder="plasma p-tau217, amyloid, blood biomarker, diagnosis")
        c3, c4 = st.columns([1, 2])
        weight = c3.slider("权重", 0.2, 2.0, 1.0, 0.1,
                           help="权重高的方向在推荐里优先。一般保持 1.0，只有一个主攻方向时不必调。")
        note = c4.text_input("备注（可选）", placeholder="例：关注 2023 年后的队列研究")
        if st.form_submit_button("添加方向", type="primary"):
            if not (label or "").strip():
                st.warning("先给方向起个名字。")
            elif len(profile.list_interests()) >= profile.MAX_INTERESTS:
                st.warning(f"最多 {profile.MAX_INTERESTS} 个方向。删掉一些再加。")
            else:
                profile.add_interest(label.strip(), keywords.strip(), discipline, weight, note.strip())
                st.success("已添加")
                st.rerun()


def _interest_list() -> None:
    items = profile.list_interests()
    theme.section("我的方向", f"共 {len(items)} 个。权重决定推荐时的优先级。", "02")
    if not items:
        theme.empty("还没有方向", "上面加一个，或者直接用「从检索历史提取」——把你最近的检索词变成方向。")
        return

    coverage = {c["label"]: c for c in profile.coverage()}
    for it in items:
        cov = coverage.get(it["label"], {"papers": 0, "share": 0})
        kws = profile.split_keywords(it)
        st.markdown(
            f'<div class="sm-card accent">'
            f'<div style="display:flex;justify-content:space-between;gap:12px;">'
            f'<div style="font-size:15.5px;font-weight:700;">{theme.esc(it["label"])}</div>'
            f'<div style="font-size:12px;color:#6b767c;">权重 {it["weight"]:.1f} · '
            f'{theme.esc(it["discipline"])}</div></div>'
            f'<div style="margin-top:8px;">{theme.pills(kws, "solid")}</div>'
            f'<div style="font-size:12.5px;color:#6b767c;margin-top:8px;">'
            f'库内已有 {cov["papers"]} 篇（{cov["share"]}%）'
            f'{"　·　" + theme.esc(it["note"]) if it["note"] else ""}</div></div>',
            unsafe_allow_html=True,
        )
        with st.expander("编辑 / 删除", expanded=False):
            c1, c2 = st.columns([2, 1])
            new_label = c1.text_input("方向名称", value=it["label"], key=f"il_{it['id']}")
            new_disc = c2.selectbox("学科", list(schema.DISCIPLINES),
                                    index=list(schema.DISCIPLINES).index(it["discipline"])
                                    if it["discipline"] in schema.DISCIPLINES else 0,
                                    key=f"id_{it['id']}")
            new_kw = st.text_input("关键词", value=it["keywords"], key=f"ik_{it['id']}")
            c3, c4 = st.columns([1, 2])
            new_w = c3.slider("权重", 0.2, 2.0, float(it["weight"]), 0.1, key=f"iw_{it['id']}")
            new_note = c4.text_input("备注", value=it["note"], key=f"in_{it['id']}")
            c5, c6 = st.columns(2)
            if c5.button("保存", key=f"is_{it['id']}", use_container_width=True):
                profile.update_interest(it["id"], label=new_label, keywords=new_kw,
                                        discipline=new_disc, weight=new_w, note=new_note)
                st.rerun()
            if c6.button("删除", key=f"idel_{it['id']}", use_container_width=True):
                profile.remove_interest(it["id"])
                st.rerun()


def _seeds() -> None:
    papers = library.list_papers()
    theme.section("种子文献", "从文献库里挑 2–5 篇「这就是我做的方向」的代表作。推荐会围绕它们展开。", "03")
    if not papers:
        st.caption("文献库还是空的。先去检索或导入几篇，再回来设种子。")
        return
    options = {p["sid"]: f'{T.shorten(p.get("title", ""), 72)}（{p.get("year") or "—"}）'
               for p in papers}
    current = [s for s in profile.seeds() if s in options]
    picked = st.multiselect("选择种子文献", list(options), default=current,
                            format_func=lambda s: options[s])
    c1, c2 = st.columns([1, 3])
    if c1.button("保存种子", type="primary", use_container_width=True):
        profile.set_seeds(picked)
        st.success(f"已保存 {len(picked)} 篇")
        st.rerun()
    c2.caption("种子文献不需要多：3 篇代表作比 30 篇泛读更能定住方向。")


def _extract_from_history() -> None:
    hist = library.history(10)
    if not hist:
        return
    theme.section("从检索历史提取", "把最近查过的主题一键变成方向，省得手打。", "04")
    options = {f'{h["query"]}（{h["discipline"]}）': h for h in hist[:8]}
    pick = st.selectbox("选择一条检索记录", list(options), label_visibility="collapsed")
    h = options[pick]
    if st.button("加为研究方向"):
        profile.add_interest(h["query"][:40], h["query"], h["discipline"], 1.0,
                             "从检索历史提取")
        st.rerun()


def _transfer() -> None:
    theme.section("画像迁移", "导出一份 JSON，换机器或分享给同组的人。", "05")
    payload = json.dumps({"interests": profile.list_interests(),
                          "seeds": profile.seeds()}, ensure_ascii=False, indent=2)
    c1, c2 = st.columns(2)
    c1.download_button("导出画像 JSON", payload.encode("utf-8"),
                       file_name="research_profile.json", use_container_width=True)
    up = c2.file_uploader("导入画像", type=["json"], label_visibility="collapsed")
    if up is not None:
        try:
            data = json.loads(up.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            st.error("文件读不出来，确认是导出的 JSON。")
            return
        added = 0
        for it in data.get("interests", []):
            if it.get("label"):
                profile.add_interest(it["label"], it.get("keywords", ""),
                                     it.get("discipline", "通用 / 跨学科"),
                                     float(it.get("weight", 1.0)), it.get("note", ""))
                added += 1
        if data.get("seeds"):
            profile.set_seeds(list(profile.seeds()) + data["seeds"])
        st.success(f"导入 {added} 个方向")
        st.rerun()


def render() -> None:
    theme.hero(
        "研究画像",
        "推荐系统唯一的依据。一个方向 = 标签 + 关键词 + 学科 + 权重。"
        "关键词决定召回，权重决定优先级，种子文献决定「什么样的论文算和你像」。",
        "PROFILE · 画像",
    )
    s = profile.summary()
    theme.stats([
        ("研究方向", str(s["count"]), "个"),
        ("关键词", str(len(s["keywords"])), "个"),
        ("种子文献", str(s["seeds"]), "篇"),
        ("覆盖学科", str(len(s["disciplines"])), "个"),
    ])

    if s["count"]:
        c1, c2 = st.columns([1, 3])
        if c1.button("去看推荐 →", type="primary", use_container_width=True):
            st.session_state["_goto"] = "推荐"
            st.rerun()
        c2.caption("画像改完不需要手动刷新，推荐页每次生成都会重新读取。")

    _add_form()
    _interest_list()
    _seeds()
    _extract_from_history()
    _transfer()

    theme.method_note(
        "为什么不让系统自动猜你的方向：文献检索里的临时查询（帮同事查的、审稿要看的）会污染画像，"
        "而画像一旦跑偏，推荐会连着几周都不对。显式维护多花 30 秒，省掉后面反复纠偏。"
    )
