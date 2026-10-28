"""推荐：多路召回 → 粗排 → 精排 → 重排，按工业界推荐系统那套漏斗做。

为什么不用「一次检索 + 一个余弦分数」：

    单路召回只能覆盖一种意图。用户写了方向关键词，只能找到字面匹配的论文，
    找不到「引用了你种子文献的那篇」「这个方向最近被引最多的工作」
    「跟你已有收藏完全不像但可能打开新视角的东西」。

所以召回拆成五路，每路负责一种意图，后面再统一排序：

    profile   画像内容：方向关键词 + 摘要语义
    seed      种子近邻：和你标为代表作的那几篇像
    citation  引用脉络：谁引用了你的种子文献（前向引用）
    trend     近期热点：该方向近两年被引增长最快的
    explore   探索：相关性不高但质量不错的，专门留位置

排序分两级。粗排用便宜特征砍掉明显不相关的；精排用八维特征线性加权。
权重不是拍死的：用户点「加入待读」或「不感兴趣」会写进 rec_events 表，
攒够样本后用逻辑回归重新拟合一次，再和先验权重各取一半（防止小样本过拟合）。

重排做三件事：MMR 去同质、单通道配额（防止整页都是热点）、探索位（至少 10%）。
"""
from __future__ import annotations

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from core import db, dedupe, library, profile, reading, related, schema
from core import text as T
from core.sources import openalex, search_all

CHANNELS = {
    "profile": "画像内容",
    "seed": "种子近邻",
    "citation": "引用脉络",
    "trend": "近期热点",
    "explore": "探索",
}

FEATURE_LABELS = {
    "rel": "相关度",
    "prox": "库内邻近",
    "seed": "种子邻近",
    "cit": "引用脉络",
    "velocity": "引用速度",
    "recency": "时效性",
    "novelty": "新颖度",
    "oa": "可获得性",
}

# 先验权重：人工设定，作为冷启动与正则化目标
PRIOR = {
    "rel": 0.26, "prox": 0.14, "seed": 0.10, "cit": 0.12,
    "velocity": 0.10, "recency": 0.10, "novelty": 0.10, "oa": 0.08,
}

MIN_FEEDBACK = 12


# --------------------------------------------------------------------------
# 召回
# --------------------------------------------------------------------------
def _doc(p: dict) -> str:
    parts = [p.get("title") or ""]
    if p.get("abstract"):
        parts.append(p["abstract"])
    if p.get("keywords"):
        parts.append(" ".join(p["keywords"]))
    return ". ".join(parts)


def _seed_query(seeds: list[dict]) -> str:
    if not seeds:
        return ""
    blob = " ".join((p.get("title") or "") for p in seeds[:3])
    terms = [t for t in T.keywords_from_text(blob, 8) if len(t) > 3]
    return " ".join(terms[:5])


def recall(*, interests: list[dict] | None = None, seeds: list[dict] | None = None,
           per_channel: int = 10, year_from: int | None = None,
           sources: list[str] | None = None, use_citation: bool = True,
           use_trend: bool = True, progress=None) -> dict:
    """五路召回，并行执行。

    串行跑五路要 30 秒以上（arXiv 限速 + OpenAlex 两次往返），
    并行之后取决于最慢的一路。线程只做网络等待，不碰 Streamlit。
    """
    interests = interests if interests is not None else profile.list_interests()
    seeds = seeds if seeds is not None else profile.seed_papers()
    if not interests and not seeds:
        return {"candidates": [], "status": [], "queries": [], "error": "画像为空"}

    tasks: list[tuple[str, str, callable]] = []   # (通道, 说明, 函数)
    queries: list[str] = []
    for it in sorted(interests, key=lambda i: -i.get("weight", 1.0))[:2]:
        q = profile.build_query(it)
        if q:
            queries.append(q)
            tasks.append(("profile", q, lambda q=q: search_all(
                q, sources=sources, limit_per_source=per_channel, year_from=year_from)))

    sq = _seed_query(seeds)
    if sq:
        queries.append(sq)
        tasks.append(("seed", sq, lambda: search_all(
            sq, sources=sources, limit_per_source=per_channel, year_from=year_from)))

    if use_citation and seeds:
        for s in seeds[:2]:
            key = s.get("doi") or s.get("openalex_id") or ""
            if key:
                tasks.append(("citation", f"引用 {T.shorten(s.get('title', ''), 24)}",
                              lambda key=key: {"papers": openalex.citing(key, limit=per_channel,
                                                                         year_from=year_from),
                                               "status": []}))

    if use_trend:
        q = queries[0] if queries else (interests[0]["label"] if interests else "")
        if q:
            this_year = time.localtime().tm_year
            tasks.append(("trend", f"热点 {q}", lambda: {"papers": openalex.search(
                q, limit=per_channel, year_from=max(year_from or 0, this_year - 2),
                sort="cited_by_count:desc"), "status": []}))

    if not tasks:
        return {"candidates": [], "status": [], "queries": [], "error": "没有可用的召回词"}

    if progress:
        progress(f"并行召回 {len(tasks)} 路："
                 + "、".join(CHANNELS.get(t[0], t[0]) for t in tasks))

    out: list[dict] = []
    status: list[dict] = []

    def run(channel: str, fn):
        try:
            res = fn()
            return channel, res.get("papers") or [], res.get("status") or [], ""
        except Exception as exc:  # noqa: BLE001
            return channel, [], [], f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=min(5, len(tasks))) as pool:
        futures = [pool.submit(run, ch, fn) for ch, _, fn in tasks]
        for fut in as_completed(futures):
            channel, papers, sts, err = fut.result()
            for p in papers:
                q = dict(p)
                q["_channel"] = channel
                out.append(q)
            for st in sts:
                status.append({**st, "channel": channel})
            if err:
                status.append({"source": channel, "label": CHANNELS.get(channel, channel),
                               "ok": False, "count": 0, "error": err, "seconds": 0.0})

    # 路间去重：同一篇保留先到的通道（通道顺序即意图优先级）
    order = {"profile": 0, "seed": 1, "citation": 2, "trend": 3}
    out.sort(key=lambda p: order.get(p.get("_channel"), 9))
    seen: set[str] = set()
    uniq: list[dict] = []
    for p in out:
        sid = p.get("sid")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        uniq.append(p)
    return {"candidates": uniq, "status": status, "queries": queries, "error": ""}


# --------------------------------------------------------------------------
# 特征
# --------------------------------------------------------------------------
def _refs(p: dict) -> set[str]:
    keys = set()
    for r in (p.get("refs") or []):
        r = str(r).strip().lower()
        if r:
            keys.add(schema.normalize_doi(r) or r)
    for k in ("doi", "openalex_id", "pmid", "arxiv_id"):
        if p.get(k):
            keys.add(str(p[k]).lower())
    return keys


def build_features(candidates: list[dict], *, interests: list[dict] | None = None,
                   seeds: list[dict] | None = None,
                   library_papers: list[dict] | None = None) -> list[dict]:
    """一次 fit，算八维特征。返回 [{paper, channel, feats}]。"""
    interests = interests if interests is not None else profile.list_interests()
    seeds = seeds if seeds is not None else profile.seed_papers()
    library_papers = library_papers if library_papers is not None else library.list_papers()
    if not candidates:
        return []

    interest_docs = [profile.interest_text(i) for i in interests] or [""]
    seed_docs = [_doc(p) for p in seeds]
    lib_docs = [_doc(p) for p in library_papers]
    cand_docs = [_doc(p) for p in candidates]

    tf = T.Tfidf(min_df=1, max_features=8000)
    mat = tf.fit_transform(interest_docs + seed_docs + lib_docs + cand_docs)
    n_i, n_s, n_l = len(interest_docs), len(seed_docs), len(lib_docs)
    i_mat = mat[:n_i]
    s_mat = mat[n_i:n_i + n_s]
    l_mat = mat[n_i + n_s:n_i + n_s + n_l]
    c_mat = mat[n_i + n_s + n_l:]

    iw = np.array([max(i.get("weight", 1.0), 0.1) for i in interests] or [1.0])
    iw = iw / iw.sum()
    interest_kw = [[k.lower() for k in profile.split_keywords(i)] for i in interests]

    seed_refs = [(_refs(s), str(s.get("doi") or s.get("openalex_id") or "").lower()) for s in seeds]
    now_year = time.localtime().tm_year
    years = [p.get("year") for p in candidates if p.get("year")]
    newest = max(years) if years else now_year
    raw_velocity = []
    for p in candidates:
        age = max(1, now_year - (p.get("year") or now_year) + 1)
        raw_velocity.append((p.get("cited_by") or 0) / age)
    max_vel = max(raw_velocity) if raw_velocity else 0.0

    rows = []
    for idx, p in enumerate(candidates):
        vec = c_mat[idx]
        text_low = _doc(p).lower()

        sims_i = T.cosine_matrix(np.vstack([vec, i_mat]))[0, 1:] if n_i else np.array([])
        sims_s = T.cosine_matrix(np.vstack([vec, s_mat]))[0, 1:] if n_s else np.array([])
        sims_l = T.cosine_matrix(np.vstack([vec, l_mat]))[0, 1:] if n_l else np.array([])

        rels = []
        for ii, kws in enumerate(interest_kw):
            kw_hit = (sum(1 for k in kws if k and k in text_low) / len(kws)) if kws else 0.0
            cos = float(sims_i[ii]) if sims_i.size else 0.0
            rels.append(0.6 * kw_hit + 0.4 * min(1.0, cos / 0.30))
        if rels:
            rel_arr = np.array(rels)
            rel = float(np.max(rel_arr * iw) / iw.max())
            best_i = int(np.argmax(rel_arr * iw))
        else:
            rel, best_i = 0.0, -1

        prox = min(1.0, float(np.max(sims_l)) / 0.30) if sims_l.size else 0.0
        seed_sim = min(1.0, float(np.max(sims_s)) / 0.30) if sims_s.size else 0.0

        # 引用脉络：引用种子 / 被种子引用 / 共享参考文献
        cit = 0.0
        cand_refs = _refs(p)
        for refs, sid_key in seed_refs:
            if sid_key and sid_key in cand_refs:
                cit = max(cit, 1.0)
            elif refs:
                shared = len(refs & cand_refs)
                if shared:
                    cit = max(cit, min(0.8, 0.3 + 0.1 * shared))

        velocity = (raw_velocity[idx] / max_vel) if max_vel > 0 else 0.0
        age = max(0, newest - (p.get("year") or newest))
        recency = 0.5 ** (age / 5.0)
        novelty = 1.0 - min(1.0, prox) if n_l else 0.5
        oa = 1.0 if p.get("pdf_url") else (0.7 if p.get("is_oa") else 0.2)

        rows.append({
            "paper": p,
            "channel": p.get("_channel") or "profile",
            "interest": interests[best_i]["label"] if best_i >= 0 else "",
            "feats": {"rel": rel, "prox": prox, "seed": seed_sim, "cit": cit,
                      "velocity": velocity, "recency": recency,
                      "novelty": novelty, "oa": oa},
        })
    return rows


# --------------------------------------------------------------------------
# 排序
# --------------------------------------------------------------------------
def _weights() -> tuple[dict, str]:
    """返回 (权重, 来源说明)。有足够反馈时用拟合权重与先验各半。"""
    learned = fit_weights()
    if not learned:
        return dict(PRIOR), "默认先验"
    n = feedback_stats()["total"]
    merged = {k: round(0.5 * PRIOR[k] + 0.5 * learned.get(k, PRIOR[k]), 4) for k in PRIOR}
    total = sum(merged.values()) or 1.0
    return {k: v / total for k, v in merged.items()}, f"已用 {n} 次反馈校准"


def _reasons(f: dict, interest: str = "") -> list[str]:
    """把特征翻译成人能读的理由。放在 core 里，UI 与导出一致。"""
    out = []
    if interest and f["rel"] >= 0.15:
        out.append(f"命中画像「{interest}」")
    if f["cit"] >= 0.5:
        out.append("与你的种子文献有引用关系")
    if f["seed"] >= 0.35:
        out.append("和种子文献主题接近")
    if f["prox"] >= 0.35:
        out.append("和你库里已有文献接近")
    if f["velocity"] >= 0.6:
        out.append("近两年被引增长快")
    if f["recency"] >= 0.8:
        out.append("近两年发表")
    if f["novelty"] >= 0.8:
        out.append("与你现有收藏差异较大")
    if f["oa"] >= 0.9:
        out.append("开放获取")
    return out[:4] or ["按综合特征入选"]


def fine_rank(rows: list[dict], weights: dict | None = None) -> list[dict]:
    weights = weights or PRIOR
    scored = []
    for r in rows:
        f = r["feats"]
        score = sum(f[k] * weights.get(k, 0.0) for k in f)
        # 探索通道单独标记：相关性低但质量不差的候选，留给探索位
        channel = r["channel"]
        if (channel not in ("explore", "trend") and f["rel"] < 0.08
                and f["velocity"] > 0.6 and f["prox"] < 0.2):
            channel = "explore"
        scored.append({
            "paper": r["paper"],
            "channel": channel,
            "interest": r.get("interest", ""),
            "score": round(float(score) * 100, 1),
            "feats": {k: round(v, 4) for k, v in f.items()},
            "parts": {FEATURE_LABELS[k]: round(f[k] * 100, 1) for k in f},
            "reasons": _reasons(f, r.get("interest", "")),
        })
    scored.sort(key=lambda x: -x["score"])
    return scored


def rerank(scored: list[dict], k: int = 20, diversity: float = 0.72,
           explore_ratio: float = 0.12, max_channel_ratio: float = 0.5) -> list[dict]:
    """MMR + 通道配额 + 探索位。"""
    if not scored:
        return []
    pool = scored[: max(k * 4, 40)]
    vectors = {}
    docs = [_doc(x["paper"]) for x in pool]
    tf = T.Tfidf(min_df=1)
    mat = tf.fit_transform(docs)
    for i, x in enumerate(pool):
        vectors[id(x)] = mat[i]

    cap = max(1, int(math.ceil(k * max_channel_ratio)))
    explore_quota = max(1, int(round(k * explore_ratio))) if any(
        x["channel"] == "explore" for x in pool) else 0

    selected: list[dict] = []
    used_channel: dict[str, int] = {}
    explore_used = 0
    remaining = pool[:]

    def take(cand: dict) -> None:
        nonlocal explore_used
        selected.append(cand)
        used_channel[cand["channel"]] = used_channel.get(cand["channel"], 0) + 1
        if cand["channel"] == "explore":
            explore_used += 1

    # 先占探索位：从 explore 通道里挑分数最高的一条
    if explore_quota:
        for cand in remaining:
            if cand["channel"] == "explore":
                take(cand)
                remaining.remove(cand)
                break

    while remaining and len(selected) < k:
        best, best_val = None, -1e9
        for cand in remaining:
            if cand["channel"] == "explore":
                if explore_quota and explore_used >= explore_quota:
                    continue
            elif used_channel.get(cand["channel"], 0) >= cap:
                continue
            if selected:
                sim = max(T.cosine(vectors[id(cand)], vectors[id(s)]) for s in selected)
                val = diversity * (cand["score"] / 100) - (1 - diversity) * sim
            else:
                val = cand["score"] / 100
            if val > best_val:
                best, best_val = cand, val
        if best is None:
            break
        take(best)
        remaining.remove(best)

    # 按分数重排：探索位只保证「至少出现一条」，不保证排在前面的位置
    selected.sort(key=lambda x: -x["score"])
    return selected


# --------------------------------------------------------------------------
# 对外
# --------------------------------------------------------------------------
def score(candidates: list[dict], *, interests: list[dict] | None = None,
          seeds: list[dict] | None = None, library_papers: list[dict] | None = None,
          k: int = 20, diversity: float = 0.72,
          weights: dict | None = None) -> list[dict]:
    """跳过召回，直接对给定候选打分（重排权重时用，不重新联网）。"""
    library_papers = library_papers if library_papers is not None else library.list_papers()
    if not candidates:
        return []

    uniq = dedupe.dedupe_papers(candidates)["papers"]
    lib_sids = {p.get("sid") for p in library_papers}
    queued = reading.sids()
    lib_titles = [(p.get("title") or "") for p in library_papers]
    known_tokens = [set(T.tokenize(t)) for t in lib_titles if t]

    pool = []
    for p in uniq:
        if p.get("sid") in lib_sids or p.get("sid") in queued:
            continue
        toks = set(T.tokenize(p.get("title") or ""))
        if toks and any(T.jaccard(toks, kt) >= 0.85 for kt in known_tokens if kt):
            continue
        pool.append(p)
    if not pool:
        return []

    rows = build_features(pool, interests=interests, seeds=seeds,
                          library_papers=library_papers)
    scored = fine_rank(rows, weights)
    if len(scored) > k * 2:
        kept = [x for x in scored
                if x["feats"]["rel"] >= 0.05 or x["feats"]["prox"] >= 0.10
                or x["feats"]["cit"] >= 0.2]
        scored = kept or scored[:k]
    return rerank(scored, k=k, diversity=diversity)


def recommend(*, k: int = 20, per_channel: int = 10, year_from: int | None = None,
              sources: list[str] | None = None, use_citation: bool = True,
              use_trend: bool = True, diversity: float = 0.72,
              progress=None) -> dict:
    interests = profile.list_interests()
    seeds = profile.seed_papers()
    started = time.time()
    if not interests and not seeds:
        return {"items": [], "basis": {}, "status": [], "seconds": 0.0,
                "error": "还没有研究画像。先去「研究画像」加一个方向，或把几篇代表作设为种子文献。"}

    rec = recall(interests=interests, seeds=seeds, per_channel=per_channel,
                 year_from=year_from, sources=sources, use_citation=use_citation,
                 use_trend=use_trend, progress=progress)
    if rec.get("error"):
        return {"items": [], "basis": {}, "status": [], "seconds": 0.0, "error": rec["error"]}

    weights, weight_note = _weights()
    items = score(rec["candidates"], interests=interests, seeds=seeds,
                  k=k, diversity=diversity, weights=weights)

    # 展示即曝光，写进事件表，供后续校准
    for rank, it in enumerate(items, 1):
        log_event(it["paper"]["sid"], "impression", it["channel"], it["score"],
                  it["feats"], rank=rank)

    channel_counts: dict[str, int] = {}
    for it in items:
        channel_counts[it["channel"]] = channel_counts.get(it["channel"], 0) + 1

    from core import activity
    activity.log("推荐", f"生成 {len(items)} 条推荐（{weight_note}）")
    return {
        "items": items,
        "candidates": rec["candidates"],
        "basis": {
            "interests": [i["label"] for i in interests],
            "seeds": len(seeds),
            "queries": rec["queries"],
            "candidates": len(rec["candidates"]),
            "channels": {CHANNELS.get(k2, k2): v for k2, v in channel_counts.items()},
            "weights": {FEATURE_LABELS[k2]: round(v, 3) for k2, v in weights.items()},
            "weight_note": weight_note,
        },
        "status": rec["status"],
        "seconds": round(time.time() - started, 1),
        "error": "" if items else "没有找到新的候选文献。可以放宽年份、增加数据源，或补充画像关键词。",
    }


def to_papers(items: list[dict]) -> list[dict]:
    return [it["paper"] for it in items]


def save_all(items: list[dict], priority: int = 2) -> tuple[int, int]:
    """推荐结果统一进待读，不直接塞进文献库书架。"""
    return reading.add(to_papers(items), priority=priority, source="推荐")


# --------------------------------------------------------------------------
# 反馈与权重校准
# --------------------------------------------------------------------------
def log_event(sid: str, action: str, channel: str = "", score: float = 0.0,
              feats: dict | None = None, rank: int = 0) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO rec_events(sid, action, channel, score, features, created_at) "
            "VALUES(?,?,?,?,?,?)",
            (sid, action, channel, float(score),
             json.dumps(feats or {}, ensure_ascii=False), time.time()),
        )
        conn.execute("DELETE FROM rec_events WHERE id NOT IN "
                     "(SELECT id FROM rec_events ORDER BY created_at DESC LIMIT 2000)")


def feedback_stats() -> dict:
    rows = db.rows("SELECT action, COUNT(*) c FROM rec_events GROUP BY action")
    counts = {r["action"]: r["c"] for r in rows}
    return {
        "total": sum(counts.values()),
        "impression": counts.get("impression", 0),
        "save": counts.get("save", 0),
        "skip": counts.get("skip", 0),
        "positive": counts.get("save", 0),
        "negative": counts.get("skip", 0),
        "ready": counts.get("save", 0) >= 4 and counts.get("skip", 0) >= 4,
    }


def _training_set() -> tuple[np.ndarray, np.ndarray]:
    rows = db.rows(
        "SELECT action, features FROM rec_events WHERE action IN ('save','skip') "
        "ORDER BY created_at DESC LIMIT 500"
    )
    X, y = [], []
    keys = list(PRIOR)
    for r in rows:
        try:
            f = json.loads(r["features"] or "{}")
        except json.JSONDecodeError:
            continue
        if not all(k in f for k in keys):
            continue
        X.append([float(f[k]) for k in keys])
        y.append(1.0 if r["action"] == "save" else 0.0)
    return np.array(X), np.array(y)


def fit_weights(*, min_events: int = MIN_FEEDBACK, epochs: int = 400,
                lr: float = 0.6, l2: float = 0.08) -> dict | None:
    """逻辑回归 + 向先验的 L2 正则。样本不足或只有单一类别时返回 None。"""
    X, y = _training_set()
    if len(y) < min_events or len(set(y.tolist())) < 2:
        return None
    keys = list(PRIOR)
    prior = np.array([PRIOR[k] for k in keys])
    w = prior.copy()
    b = 0.0
    n = len(y)
    for _ in range(epochs):
        z = X @ w + b
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        grad = X.T @ (p - y) / n + l2 * (w - prior)
        b -= lr * float(np.mean(p - y))
        w -= lr * grad
    w = np.clip(w, 0.0, None)
    if w.sum() <= 1e-6:
        return None
    w = w / w.sum()
    return {k: round(float(v), 4) for k, v in zip(keys, w)}
