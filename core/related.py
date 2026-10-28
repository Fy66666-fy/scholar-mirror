"""关联性分析：把「这几篇论文有什么关系」说清楚，而不是画一团线。

四个信号，每个都能单独解释：
    text      标题+摘要的 TF-IDF 余弦 —— 说的是同一件事吗
    concept   主题标签/关键词的 Jaccard —— 概念体系是否重叠（比词面更稳）
    citation  直接引用 或 共享参考文献 —— 学术脉络上是否同源
    meta      同期刊 / 同作者 / 同研究设计 —— 弱信号，只做微调

分数缺失信号时会重新归一化权重：很多源不给参考文献，如果按固定权重算，
没有引用数据的好文章会被系统性低估。这点和查重模块同理。

布局用力导向（Fruchterman–Reingold）自己算，不引入 networkx：
节点数在几十到两百之间，纯 numpy 迭代 300 轮只要几十毫秒，
而且能保证同一份数据每次画出来位置一致（固定随机种子），便于对比。
"""
from __future__ import annotations

import numpy as np

from core import schema
from core import text as T


def _concept_set(p: dict) -> set[str]:
    out = set()
    for k in (p.get("keywords") or []) + (p.get("fields") or []):
        for tok in T.tokenize(str(k)):
            out.add(tok)
    return out


def _ref_keys(p: dict) -> set[str]:
    keys = set()
    for r in (p.get("refs") or []):
        r = str(r).strip().lower()
        if not r:
            continue
        if r.startswith("http"):
            r = r.rsplit("/", 1)[-1]
        keys.add(schema.normalize_doi(r) or r)
    for key in ("doi", "openalex_id", "pmid", "arxiv_id"):
        if p.get(key):
            keys.add(str(p[key]).lower())
    return keys


def _cite_link(a: dict, b: dict) -> tuple[str, float]:
    """a 是否引用 b（或反向）。返回 (方向说明, 强度)。"""
    ra, rb = _ref_keys(a), _ref_keys(b)
    ida = {str(a.get(k, "")).lower() for k in ("doi", "openalex_id", "pmid", "arxiv_id") if a.get(k)}
    idb = {str(b.get(k, "")).lower() for k in ("doi", "openalex_id", "pmid", "arxiv_id") if b.get(k)}
    if idb & ra:
        return "a→b", 1.0
    if ida & rb:
        return "b→a", 1.0
    shared = (ra & rb) - (ida | idb)
    if shared:
        return f"shared:{len(shared)}", min(len(shared) / 4.0, 1.0)
    return "", 0.0


def build_features(papers: list[dict]) -> dict:
    """统一构造一次特征，后续所有两两比较都复用，避免重复算 TF-IDF。"""
    docs = []
    for p in papers:
        parts = [p.get("title") or ""]
        if p.get("abstract"):
            parts.append(p["abstract"])
        if p.get("keywords"):
            parts.append(" ".join(p["keywords"]))
        docs.append(". ".join(parts))
    tf = T.Tfidf(min_df=1, max_features=6000)
    mat = tf.fit_transform(docs)
    sim = T.cosine_matrix(mat)
    concepts = [_concept_set(p) for p in papers]
    refs = [_ref_keys(p) for p in papers]
    return {"tfidf": tf, "matrix": mat, "text_sim": sim, "concepts": concepts, "refs": refs}


def _pair(a: dict, b: dict, i: int, j: int, feats: dict) -> dict:
    text = float(feats["text_sim"][i, j])
    concept = T.jaccard(feats["concepts"][i], feats["concepts"][j])
    cite_kind, cite = _cite_link(a, b)
    meta, meta_reasons = 0.0, []
    va = (a.get("venue") or "").strip().lower()
    vb = (b.get("venue") or "").strip().lower()
    if va and va == vb:
        meta += 0.4
        meta_reasons.append("同一发表载体")
    au_a = {x.split()[-1].lower() for x in (a.get("authors") or []) if x}
    au_b = {x.split()[-1].lower() for x in (b.get("authors") or []) if x}
    shared_au = au_a & au_b
    if shared_au:
        meta += 0.4
        meta_reasons.append(f"共同作者 {len(shared_au)} 人")
    if a.get("design") and a.get("design") == b.get("design"):
        meta += 0.2
        meta_reasons.append(f"同为{schema.DESIGN_LABELS.get(a['design'], '同类研究')}")

    # 有引用数据时引用信号权重更高，没有则分给文本与概念
    has_cite_data = bool(feats["refs"][i] or feats["refs"][j])
    signals = [(text, 0.42), (concept, 0.20), (meta, 0.10)]
    if has_cite_data:
        signals.append((cite, 0.30))
    total_w = sum(w for _, w in signals)
    score = sum(v * w for v, w in signals) / total_w

    reasons = []
    if text >= 0.35:
        reasons.append(f"摘要主题重合 {text:.2f}")
    if concept >= 0.25:
        reasons.append(f"概念标签重叠 {concept:.2f}")
    if cite_kind == "a→b":
        reasons.append("前者引用后者")
    elif cite_kind == "b→a":
        reasons.append("后者引用前者")
    elif cite_kind.startswith("shared:"):
        reasons.append(f"共享 {cite_kind.split(':')[1]} 篇参考文献")
    reasons.extend(meta_reasons)

    return {
        "score": round(float(np.clip(score, 0, 1)), 4),
        "parts": {
            "text": round(text, 3),
            "concept": round(concept, 3),
            "citation": round(cite, 3),
            "meta": round(min(meta, 1.0), 3),
        },
        "citation_dir": cite_kind,
        "reasons": reasons,
    }


def relations(papers: list[dict]) -> np.ndarray:
    """返回 n×n 关联度矩阵（0–1，对角线为 1）。"""
    n = len(papers)
    if n == 0:
        return np.zeros((0, 0))
    feats = build_features(papers)
    m = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            sc = _pair(papers[i], papers[j], i, j, feats)["score"]
            m[i, j] = m[j, i] = sc
    return m


def explain_pair(a: dict, b: dict, papers: list[dict]) -> dict:
    """单独解释两篇的关联（详情弹层用）。"""
    idx = {p.get("sid"): k for k, p in enumerate(papers)}
    if a.get("sid") not in idx or b.get("sid") not in idx:
        return {"score": 0.0, "parts": {}, "reasons": []}
    feats = build_features(papers)
    return _pair(a, b, idx[a["sid"]], idx[b["sid"]], feats)


def top_related(paper: dict, papers: list[dict], k: int = 5) -> list[dict]:
    idx = {p.get("sid"): i for i, p in enumerate(papers)}
    if paper.get("sid") not in idx or len(papers) < 2:
        return []
    feats = build_features(papers)
    i = idx[paper["sid"]]
    out = []
    for j, other in enumerate(papers):
        if j == i:
            continue
        rel = _pair(paper, other, i, j, feats)
        out.append({"paper": other, **rel})
    out.sort(key=lambda x: -x["score"])
    return out[:k]


# --------------------------------------------------------------------------
# 图与布局
# --------------------------------------------------------------------------
def level(score: float) -> str:
    """把 0–1 的关联度翻译成人能判断的说法。

    绝对分数在不同主题上不可比：同一课题的一批文献两两余弦常在 0.15–0.30，
    跨学科混检时中位数只有 0.03。所以这里给的是分档描述，不是「相关性系数」。
    """
    if score >= 0.30:
        return "高度相关"
    if score >= 0.15:
        return "明显相关"
    if score >= 0.07:
        return "弱相关"
    return "关联较弱"


def build_graph(papers: list[dict], threshold: float | None = None,
                max_edges_per_node: int = 4, floor: float = 0.02,
                percentile: float = 75) -> dict:
    """建关联网络。

    阈值默认按分位数取（默认第 75 百分位），而不是固定值：同一主题的一批文献
    两两分数集中在 0.1–0.3，跨学科混检时中位数只有 0.03。固定阈值要么连成一片，
    要么全是孤点。

    每个节点取「最强的 k 个邻居」；若某节点在阈值之上一个邻居都没有，
    退而连它最强的一条（标记 weak），避免图里出现大量无意义的孤点 ——
    但孤立本身也是信息，stats 里照样统计。
    """
    n = len(papers)
    if n == 0:
        return {"nodes": [], "edges": [], "matrix": np.zeros((0, 0)), "stats": {},
                "threshold": 0.0, "scale": 0.0}
    feats = build_features(papers)
    pair_scores = np.zeros((n, n))
    rels: dict[tuple[int, int], dict] = {}
    for i in range(n):
        for j in range(i + 1, n):
            rel = _pair(papers[i], papers[j], i, j, feats)
            pair_scores[i, j] = pair_scores[j, i] = rel["score"]
            rels[(i, j)] = rel

    upper = pair_scores[np.triu_indices(n, 1)]
    auto_thr = float(np.percentile(upper, percentile)) if upper.size else floor
    thr = threshold if threshold is not None else max(floor, auto_thr)
    scale = float(np.percentile(upper, 95)) if upper.size else 1.0
    scale = max(scale, 1e-6)

    edges = []
    seen: set[tuple[int, int]] = set()

    def add_edge(i: int, j: int, weak: bool = False) -> None:
        key = (min(i, j), max(i, j))
        if key in seen:
            return
        seen.add(key)
        rel = rels[key]
        edges.append({
            "source": papers[key[0]]["sid"], "target": papers[key[1]]["sid"],
            "weight": pair_scores[i, j],
            "strength": round(float(pair_scores[i, j] / scale), 3),
            "parts": rel["parts"], "reasons": rel["reasons"], "weak": weak,
        })

    for i in range(n):
        cand = sorted(((pair_scores[i, j], j) for j in range(n)
                       if j != i and pair_scores[i, j] >= thr), reverse=True)[:max_edges_per_node]
        for _, j in cand:
            add_edge(i, j)
        if not cand:
            best = max(((pair_scores[i, j], j) for j in range(n) if j != i), default=(0.0, -1))
            if best[1] >= 0 and best[0] > 0:
                add_edge(i, best[1], weak=True)

    keep = np.zeros((n, n))
    degree = {p["sid"]: 0 for p in papers}
    idx = {p["sid"]: k for k, p in enumerate(papers)}
    for e in edges:
        i, j = idx[e["source"]], idx[e["target"]]
        keep[i, j] = keep[j, i] = e["weight"]
        degree[e["source"]] += 1
        degree[e["target"]] += 1
    comps = _components([p["sid"] for p in papers], edges)
    stats = {
        "nodes": n,
        "edges": len(edges),
        "density": round(len(edges) / max(n * (n - 1) / 2, 1), 3),
        "avg_degree": round(sum(degree.values()) / max(n, 1), 2),
        "isolated": len([s for s, d in degree.items() if d == 0]),
        "components": len(comps),
        "largest_component": max((len(c) for c in comps), default=0),
        "weak_edges": len([e for e in edges if e.get("weak")]),
    }
    return {"nodes": papers, "edges": edges, "matrix": keep, "stats": stats,
            "degree": degree, "threshold": round(thr, 3), "scale": round(scale, 3),
            "percentile": percentile}


def _components(ids: list[str], edges: list[dict]) -> list[list[str]]:
    parent = {i: i for i in ids}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in edges:
        a, b = find(e["source"]), find(e["target"])
        if a != b:
            parent[b] = a
    groups: dict[str, list[str]] = {}
    for i in ids:
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def layout(nodes: list[dict], edges: list[dict], iterations: int = 320, seed: int = 7) -> dict[str, tuple[float, float]]:
    """Fruchterman–Reingold 力导向布局，返回 {sid: (x, y)}，坐标已归一化到 0–1。"""
    n = len(nodes)
    if n == 0:
        return {}
    if n == 1:
        return {nodes[0]["sid"]: (0.5, 0.5)}
    idx = {p["sid"]: i for i, p in enumerate(nodes)}
    rng = np.random.default_rng(seed)
    pos = rng.normal(0, 0.1, size=(n, 2))
    k = 1.0 / np.sqrt(n)
    adj = np.zeros((n, n))
    for e in edges:
        i, j = idx[e["source"]], idx[e["target"]]
        adj[i, j] = adj[j, i] = max(0.05, e["weight"])
    temp = 0.12
    for _ in range(iterations):
        delta = pos[:, None, :] - pos[None, :, :]
        dist = np.linalg.norm(delta, axis=2)
        # 对角线必须是「很大的有限值」而不是 inf：inf 参与乘除会产生 nan，
        # 一轮迭代就把整个布局污染掉。
        np.fill_diagonal(dist, 1e6)
        dist = np.maximum(dist, 1e-4)
        rep = (k * k / dist)[..., None] * (delta / dist[..., None])
        disp = rep.sum(axis=1)
        att = (adj * dist / k)[..., None] * (delta / dist[..., None])
        disp -= att.sum(axis=1)
        length = np.linalg.norm(disp, axis=1, keepdims=True)
        length[length == 0] = 1.0
        pos += (disp / length) * np.minimum(length, temp)
        temp *= 0.985
    lo, hi = pos.min(axis=0), pos.max(axis=0)
    span = np.where((hi - lo) == 0, 1.0, hi - lo)
    pos = (pos - lo) / span
    return {p["sid"]: (float(pos[i, 0]), float(pos[i, 1])) for i, p in enumerate(nodes)}


def bridge_papers(graph: dict, clusters: dict[str, int] | None = None, top: int = 5) -> list[dict]:
    """跨主题「桥梁」：连接不同聚类的边占比最高的节点。

    用跨簇边比例而不是严格的介数中心性 —— 介数在几十个节点上对噪声太敏感，
    而「它把哪两个方向连起来了」这个问题，跨簇边比例回答得更直接。
    """
    edges = graph.get("edges") or []
    if not edges:
        return []
    clusters = clusters or {}
    stat: dict[str, dict] = {}
    for e in edges:
        ca, cb = clusters.get(e["source"]), clusters.get(e["target"])
        for sid, other in ((e["source"], cb), (e["target"], ca)):
            rec = stat.setdefault(sid, {"sid": sid, "edges": 0, "cross": 0, "partners": set()})
            rec["edges"] += 1
            if ca is not None and cb is not None and ca != cb:
                rec["cross"] += 1
            if other is not None:
                rec["partners"].add(other)
    nodes = {p["sid"]: p for p in graph.get("nodes") or []}
    out = []
    for sid, rec in stat.items():
        if rec["cross"] == 0:
            continue
        out.append({
            "sid": sid,
            "title": (nodes.get(sid) or {}).get("title", ""),
            "year": (nodes.get(sid) or {}).get("year"),
            "cross_ratio": round(rec["cross"] / max(rec["edges"], 1), 2),
            "clusters_linked": len(rec["partners"]),
            "edges": rec["edges"],
        })
    out.sort(key=lambda x: (-x["cross_ratio"], -x["clusters_linked"]))
    return out[:top]
