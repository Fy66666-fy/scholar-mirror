"""推荐引擎：按研究画像推文献，并且说清「为什么推它」。

流程是「召回 → 打分 → 去重 → 多样性」四步：

    召回   每个兴趣方向取前三个，各查一轮；再用种子文献的标题词补一轮
    打分   相关度 / 库内邻近 / 种子邻近 / 影响力 / 时效 五路加权，缺信号则重归一化
    去重   与文献库已有条目高度重合的直接剔除（推一篇你已经收藏的没有意义）
    多样性 MMR：先选高分，再逐步惩罚「与已选高度相似」的候选，避免 20 条全是同一篇的跟风工作

打分权重是可解释的：界面上每一项都单独展示，用户不认可排序时知道该调哪里。
"""
from __future__ import annotations

import time

import numpy as np

from core import dedupe, library, profile, related, schema
from core import text as T
from core.sources import search_all

DEFAULT_WEIGHTS = {
    "相关度": 0.34,
    "库内邻近": 0.22,
    "种子邻近": 0.14,
    "影响力": 0.16,
    "时效性": 0.14,
}


def _doc(p: dict) -> str:
    parts = [p.get("title") or ""]
    if p.get("abstract"):
        parts.append(p["abstract"])
    if p.get("keywords"):
        parts.append(" ".join(p["keywords"]))
    return ". ".join(parts)


def _seed_query(seeds: list[dict]) -> str:
    """用种子文献标题里信息量最高的词做一次检索。"""
    if not seeds:
        return ""
    blob = " ".join((p.get("title") or "") for p in seeds[:3])
    terms = [t for t in T.keywords_from_text(blob, 8) if len(t) > 3]
    return " ".join(terms[:5])


def recall(*, interests: list[dict] | None = None, seeds: list[dict] | None = None,
           per_interest: int = 10, year_from: int | None = None,
           sources: list[str] | None = None, progress=None) -> dict:
    """召回候选。返回 {'candidates': [...], 'queries': [...], 'status': [...]}。"""
    interests = interests if interests is not None else profile.list_interests()
    seeds = seeds if seeds is not None else profile.seed_papers()
    if not interests and not seeds:
        return {"candidates": [], "queries": [], "status": [], "error": "画像为空"}

    picks = sorted(interests, key=lambda i: -i.get("weight", 1.0))[:3]
    jobs: list[tuple[str, str]] = []
    for it in picks:
        q = profile.build_query(it)
        if q:
            jobs.append((it.get("label", ""), q))
    sq = _seed_query(seeds)
    if sq:
        jobs.append(("种子文献", sq))

    seen_q, uniq_jobs = set(), []
    for label, q in jobs:
        if q.lower() in seen_q:
            continue
        seen_q.add(q.lower())
        uniq_jobs.append((label, q))

    candidates: list[dict] = []
    status: list[dict] = []
    for label, q in uniq_jobs:
        if progress:
            progress(f"检索「{label}」：{q}")
        res = search_all(q, sources=sources, limit_per_source=per_interest,
                         year_from=year_from)
        for s in res["status"]:
            status.append({**s, "query": q, "interest": label})
        for p in res["papers"]:
            p["_interest"] = label
            p["_query"] = q
            candidates.append(p)
    return {"candidates": candidates, "queries": uniq_jobs, "status": status, "error": ""}


def score(candidates: list[dict], *, interests: list[dict] | None = None,
          seeds: list[dict] | None = None, library_papers: list[dict] | None = None,
          k: int = 20, diversity: float = 0.72,
          weights: dict[str, float] | None = None) -> list[dict]:
    """对候选打分、去重、做 MMR 多样性选择。"""
    interests = interests if interests is not None else profile.list_interests()
    seeds = seeds if seeds is not None else profile.seed_papers()
    library_papers = library_papers if library_papers is not None else library.list_papers()
    weights = weights or DEFAULT_WEIGHTS

    if not candidates:
        return []

    # 1) 去重（候选内部）+ 剔除已在库里的
    uniq = dedupe.dedupe_papers(candidates)["papers"]
    lib_sids = {p.get("sid") for p in library_papers}
    lib_titles = [(p.get("title") or "") for p in library_papers]
    known_tokens = [set(T.tokenize(t)) for t in lib_titles if t]

    pool: list[dict] = []
    for p in uniq:
        if p.get("sid") in lib_sids:
            continue
        toks = set(T.tokenize(p.get("title") or ""))
        if toks and any(T.jaccard(toks, kt) >= 0.85 for kt in known_tokens if kt):
            continue
        pool.append(p)
    if not pool:
        return []

    # 2) 统一向量空间：兴趣 + 种子 + 库 + 候选，一次 fit
    interest_docs = [profile.interest_text(i) for i in interests] or [""]
    seed_docs = [_doc(p) for p in seeds]
    lib_docs = [_doc(p) for p in library_papers]
    cand_docs = [_doc(p) for p in pool]

    tf = T.Tfidf(min_df=1, max_features=8000)
    mat = tf.fit_transform(interest_docs + seed_docs + lib_docs + cand_docs)
    n_i, n_s, n_l = len(interest_docs), len(seed_docs), len(lib_docs)
    i_mat = mat[:n_i]
    s_mat = mat[n_i: n_i + n_s]
    l_mat = mat[n_i + n_s: n_i + n_s + n_l]
    c_mat = mat[n_i + n_s + n_l:]

    iw = np.array([max(i.get("weight", 1.0), 0.1) for i in interests] or [1.0])
    iw = iw / iw.sum()
    max_cites = max([p.get("cited_by") or 0 for p in pool] + [0])
    years = [p.get("year") for p in pool if p.get("year")]
    newest = max(years) if years else 0

    scored = []
    interest_kw = [[k.lower() for k in profile.split_keywords(i)] for i in interests]
    for idx, p in enumerate(pool):
        vec = c_mat[idx]
        text_low = _doc(p).lower()
        sims_i = T.cosine_matrix(np.vstack([vec, i_mat]))[0, 1:] if n_i else np.array([])
        sims_l = T.cosine_matrix(np.vstack([vec, l_mat]))[0, 1:] if n_l else np.array([])
        sims_s = T.cosine_matrix(np.vstack([vec, s_mat]))[0, 1:] if n_s else np.array([])

        # 相关度 = 关键词命中率 60% + 余弦相似 40%。
        # 纯余弦在「短画像 vs 长摘要」上会被系统性压低（0.05 就算不错了），
        # 单靠它排序会让被引高但跑题的论文排到前面。
        rels = []
        for ii, kws in enumerate(interest_kw):
            kw_hit = (sum(1 for k in kws if k and k in text_low) / len(kws)) if kws else 0.0
            cos = float(sims_i[ii]) if sims_i.size else 0.0
            cos_norm = min(1.0, cos / 0.30)
            rels.append(0.6 * kw_hit + 0.4 * cos_norm)
        if rels:
            rels_arr = np.array(rels)
            rel = float(np.max(rels_arr * iw) / iw.max())
            best_i = int(np.argmax(rels_arr * iw))
        else:
            rel, best_i = 0.0, -1
        prox = min(1.0, float(np.max(sims_l)) / 0.30) if sims_l.size else 0.0
        seed_sim = min(1.0, float(np.max(sims_s)) / 0.30) if sims_s.size else 0.0
        impact = (np.log1p(p.get("cited_by") or 0) / np.log1p(max_cites)) if max_cites else 0.0
        recency = 0.5 ** (max(newest - (p.get("year") or newest), 0) / 5.0) if newest else 0.4

        parts = {"相关度": rel, "库内邻近": prox, "种子邻近": seed_sim,
                 "影响力": float(impact), "时效性": float(recency)}
        # 缺信号的项不参与加权，避免「没有种子文献」被系统性扣分
        avail = {k: v for k, v in weights.items()
                 if not (k == "种子邻近" and not n_s) and not (k == "库内邻近" and not n_l)}
        total_w = sum(avail.values()) or 1.0
        score_val = sum(parts[k] * w for k, w in avail.items()) / total_w

        reasons = []
        if best_i >= 0 and rel > 0.05:
            reasons.append(f"命中画像「{interests[best_i]['label']}」")
        if prox >= 0.35 and sims_l.size:
            nearest = library_papers[int(np.argmax(sims_l))]
            reasons.append(f"与库内《{T.shorten(nearest.get('title', ''), 28)}》主题接近")
        if seed_sim >= 0.4:
            reasons.append("与你的种子文献相近")
        if p.get("year") and newest and newest - p["year"] <= 2:
            reasons.append("近两年发表")
        if (p.get("cited_by") or 0) >= 50:
            reasons.append(f"被引 {p['cited_by']} 次")
        if p.get("is_oa") or p.get("pdf_url"):
            reasons.append("开放获取")

        scored.append({
            "paper": p,
            "score": round(float(score_val) * 100, 1),
            "parts": {k: round(v * 100, 1) for k, v in parts.items()},
            "reasons": reasons,
            "interest": p.get("_interest") or (interests[best_i]["label"] if best_i >= 0 else ""),
            "vector": vec,
        })

    scored.sort(key=lambda x: -x["score"])

    # 软过滤：相关度、库内邻近、种子邻近都为 0 的，属于「完全跑题」，
    # 只在候选池明显大于需求时才剔除，避免小样本时把结果清空。
    if len(scored) > k * 2:
        kept = [x for x in scored
                if x["parts"]["相关度"] >= 5 or x["parts"]["库内邻近"] >= 10
                or x["parts"]["种子邻近"] >= 10]
        scored = kept or scored[:k]

    # 3) MMR 多样性：避免整页都是同一篇的跟风工作
    selected: list[dict] = []
    sel_vecs: list[np.ndarray] = []
    remaining = scored[:]
    while remaining and len(selected) < k:
        if not selected:
            best = remaining.pop(0)
        else:
            best, best_val = None, -1e9
            for cand in remaining:
                sim = max(T.cosine(cand["vector"], v) for v in sel_vecs)
                val = diversity * (cand["score"] / 100) - (1 - diversity) * sim
                if val > best_val:
                    best, best_val = cand, val
            remaining.remove(best)
        sel_vecs.append(best["vector"])
        selected.append({k: v for k, v in best.items() if k != "vector"})
    return selected


def recommend(*, k: int = 20, per_interest: int = 10, year_from: int | None = None,
              sources: list[str] | None = None, progress=None) -> dict:
    """一步到位：召回 + 打分。返回结果连同「依据」一起给出，便于界面解释。"""
    interests = profile.list_interests()
    seeds = profile.seed_papers()
    started = time.time()
    if not interests and not seeds:
        return {"items": [], "basis": {}, "status": [], "seconds": 0.0,
                "error": "还没有研究画像。先去「研究画像」加一个方向，或把几篇代表作设为种子文献。"}

    rec = recall(interests=interests, seeds=seeds, per_interest=per_interest,
                 year_from=year_from, sources=sources, progress=progress)
    if rec.get("error"):
        return {"items": [], "basis": {}, "status": [], "seconds": 0.0, "error": rec["error"]}

    items = score(rec["candidates"], interests=interests, seeds=seeds, k=k)
    from core import activity
    activity.log("推荐", f"生成 {len(items)} 条推荐")
    return {
        "items": items,
        "candidates": rec["candidates"],
        "basis": {
            "interests": [i["label"] for i in interests],
            "seeds": len(seeds),
            "queries": [q for _, q in rec["queries"]],
            "candidates": len(rec["candidates"]),
            "pool": len(items),
        },
        "status": rec["status"],
        "seconds": round(time.time() - started, 1),
        "error": "" if items else "没有找到新的候选文献。可以放宽年份、增加数据源，或补充画像关键词。",
    }


def to_papers(items: list[dict]) -> list[dict]:
    return [it["paper"] for it in items]


def save_all(items: list[dict], group: str = "推荐", tags: str = "") -> int:
    return library.save(to_papers(items), group=group, tags=tags)
