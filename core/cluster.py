"""主题聚类与精选。

聚类用的是平均连接层次聚类，不用 k-means：一批文献里「一个大方向 + 两个小分支」
是常态，k-means 会强行把大方向切成等大的块，而层次聚类允许簇大小悬殊。
k 不猜，用轮廓系数在 2–8 之间选；只有 3 篇以下时不聚类。

簇名不是「Cluster 1」，而是从簇内**区别于全局**的词里取（tf-idf 质心差），
所以会出现「肠道菌群 · 短链脂肪酸」「长期随访 · 心血管结局」这种能直接读的名字。

精选分数是五个可解释维度加权，每一项都能在界面上拆开看：
影响力（被引，对数压缩）、新近度（指数衰减）、相关度（与检索主题或簇心）、
信息完整度（摘要/元数据齐全程度）、可获得性（OA/PDF）。
不做「黑箱排序」，因为用户要能反驳这个排序。
"""
from __future__ import annotations

import math
import re

import numpy as np

from core import related, schema
from core import text as T


def _combined_sim(papers: list[dict], feats: dict | None = None) -> np.ndarray:
    """文本余弦为主，概念重叠做平滑：纯文本会把「同一概念不同措辞」拆开。"""
    feats = feats or related.build_features(papers)
    text_sim = feats["text_sim"]
    n = len(papers)
    concept = np.zeros((n, n))
    for i in range(n):
        for j in range(i + 1, n):
            c = T.jaccard(feats["concepts"][i], feats["concepts"][j])
            concept[i, j] = concept[j, i] = c
    return 0.75 * text_sim + 0.25 * concept


def _agglomerate(sim: np.ndarray, k: int | None = None, threshold: float = 0.55) -> list[int]:
    n = len(sim)
    if n == 0:
        return []
    clusters: list[list[int]] = [[i] for i in range(n)]
    while len(clusters) > 1:
        best, bi, bj = -1.0, -1, -1
        for a in range(len(clusters)):
            for b in range(a + 1, len(clusters)):
                vals = [sim[i, j] for i in clusters[a] for j in clusters[b]]
                avg = sum(vals) / len(vals)
                if avg > best:
                    best, bi, bj = avg, a, b
        if k is not None and len(clusters) <= k:
            break
        if k is None and best < threshold:
            break
        clusters[bi].extend(clusters[bj])
        clusters.pop(bj)
    labels = [0] * n
    # 按簇大小降序编号，让「0 号」永远是最大的方向
    clusters.sort(key=len, reverse=True)
    for cid, members in enumerate(clusters):
        for m in members:
            labels[m] = cid
    return labels


def _silhouette(sim: np.ndarray, labels: list[int]) -> float:
    n = len(labels)
    uniq = sorted(set(labels))
    if len(uniq) < 2 or n < 3:
        return 0.0
    dist = 1.0 - sim
    scores = []
    for i in range(n):
        own = [j for j in range(n) if j != i and labels[j] == labels[i]]
        if not own:
            scores.append(0.0)
            continue
        a = float(np.mean([dist[i, j] for j in own]))
        b = min(
            float(np.mean([dist[i, j] for j in range(n) if labels[j] == c]))
            for c in uniq if c != labels[i]
        )
        scores.append((b - a) / max(a, b) if max(a, b) > 0 else 0.0)
    return round(float(np.mean(scores)), 4)


def cluster(papers: list[dict], k: int | None = None, threshold: float = 0.55) -> dict:
    """聚类并命名。返回 {labels, clusters, k, silhouette, method}。"""
    n = len(papers)
    if n == 0:
        return {"labels": [], "clusters": [], "k": 0, "silhouette": 0.0, "method": "none"}
    feats = related.build_features(papers)
    sim = _combined_sim(papers, feats)

    if n < 3:
        labels = [0] * n
        sil, method = 0.0, "样本过少，不聚类"
    elif k is not None:
        labels = _agglomerate(sim, k=k)
        sil, method = _silhouette(sim, labels), f"平均连接 · 指定 k={k}"
    else:
        best = (-2.0, None)
        for kk in range(2, min(9, n)):
            lab = _agglomerate(sim, k=kk)
            if len(set(lab)) < 2:
                continue
            s = _silhouette(sim, lab)
            if s > best[0]:
                best = (s, lab)
        if best[1] is None:
            labels = _agglomerate(sim, threshold=threshold)
            sil = _silhouette(sim, labels)
        else:
            labels, sil = best[1], best[0]
        method = "平均连接 · 轮廓系数选 k"

    clusters = _describe(papers, labels, feats)
    return {"labels": labels, "clusters": clusters, "k": len({*labels}), "silhouette": sil, "method": method}


def _distinctive_terms(papers: list[dict], members: list[int], feats: dict, top: int = 6) -> list[str]:
    mat = feats["matrix"]
    vocab = feats["tfidf"].vocab
    inv = {i: t for t, i in vocab.items()}
    if not members or mat.shape[1] == 0:
        return []
    in_mean = mat[members].mean(axis=0)
    out_idx = [i for i in range(mat.shape[0]) if i not in members]
    if out_idx:
        out_mean = mat[out_idx].mean(axis=0)
    else:
        out_mean = np.zeros_like(in_mean)
    score = in_mean - 0.7 * out_mean
    idx = np.argsort(-score)[: top * 4]
    surfaces = T.surface_map([(p.get("title") or "") + " " + (p.get("abstract") or "") for p in papers])
    out, seen = [], set()
    for i in idx:
        stem = inv.get(int(i), "")
        if not stem or score[i] <= 0 or stem in seen:
            continue
        if len(stem) <= 2 and stem.isascii():
            continue
        if stem.lower() in _LABEL_BLOCK:
            continue
        seen.add(stem)
        out.append(surfaces.get(stem, stem))
        if len(out) >= top:
            break
    return out


# MeSH 的 check tag 与学科分类里的泛词，当方向名毫无信息量
_LABEL_BLOCK = {
    "humans", "animals", "male", "female", "adult", "aged", "middle aged",
    "young adult", "adolescent", "child", "child, preschool", "infant",
    "mice", "rats", "dogs", "pregnancy", "retrospective studies",
    "prospective studies", "risk factors", "treatment outcome", "time factors",
    "research", "study", "studies", "review", "analysis", "method", "methods",
    "model", "models", "effect", "effects", "application", "case", "results",
    "人类", "动物", "综述", "研究", "应用", "影响", "分析", "方法", "进展",
}


def _label_candidates(papers: list[dict], members: list[int], others: list[int], top: int = 3) -> list[str]:
    """优先用作者关键词 / 主题标签命名：它们是人写的，比抽出来的词更像「方向名」。"""
    def freq(idxs: list[int]) -> dict[str, float]:
        """作者关键词比学科分类更能代表方向，权重 1.0 : 0.4。"""
        c: dict[str, float] = {}
        for i in idxs:
            for k in (papers[i].get("keywords") or []):
                k = str(k).strip()
                if 3 <= len(k) <= 40:
                    c[k] = c.get(k, 0.0) + 1.0
            for k in (papers[i].get("fields") or []):
                k = str(k).strip()
                if 3 <= len(k) <= 40:
                    c[k] = c.get(k, 0.0) + 0.4
        return c

    inside = freq(members)
    outside = freq(others)
    n_in, n_out = max(len(members), 1), max(len(others), 1)
    # arXiv 分类码（cs.CL、math.OC）和过短的缩写不适合当方向名
    code_re = re.compile(r"^[a-z\-]{2,12}(\.[A-Za-z]{2})?$")
    scored = []
    for term, cnt in inside.items():
        if cnt < max(1.5, 0.3 * n_in):
            continue
        if code_re.match(term) or term.strip().lower() in _LABEL_BLOCK:
            continue
        # 中文三字词（微塑料、土壤微生物）是正常词长，不能按英文的 4 字符门槛过滤
        if term.isascii() and len(term) < 4:
            continue
        if not term.isascii() and len(term) < 3:
            continue
        in_ratio = cnt / n_in
        out_ratio = outside.get(term, 0) / n_out
        if in_ratio <= out_ratio * 1.4:
            continue
        scored.append((in_ratio - out_ratio, cnt, term))
    scored.sort(reverse=True)
    return [t for _, _, t in scored[:top]]


def _describe(papers: list[dict], labels: list[int], feats: dict) -> list[dict]:
    out = []
    for cid in sorted(set(labels)):
        members = [i for i, lab in enumerate(labels) if lab == cid]
        others = [i for i, lab in enumerate(labels) if lab != cid]
        sub = [papers[i] for i in members]
        years = [p["year"] for p in sub if p.get("year")]
        terms = _distinctive_terms(papers, members, feats, top=6)
        labels_from_meta = _label_candidates(papers, members, others, top=3)
        name_terms = labels_from_meta or terms[:2]
        # 代表性论文：簇内平均关联度最高的一篇
        rep_idx = members[0]
        if len(members) > 1:
            best = -1.0
            for i in members:
                avg = float(np.mean([feats["text_sim"][i, j] for j in members if j != i]))
                if avg > best:
                    best, rep_idx = avg, i
        # 簇内凝聚度：成员两两文本相似度的均值
        if len(members) > 1:
            vals = [feats["text_sim"][i, j] for a, i in enumerate(members) for j in members[a + 1:]]
            cohesion = round(float(np.mean(vals)), 3)
        else:
            cohesion = 1.0
        designs = {}
        for p in sub:
            d = schema.DESIGN_LABELS.get(p.get("design"), "未识别")
            designs[d] = designs.get(d, 0) + 1
        cites = sorted([p.get("cited_by") or 0 for p in sub], reverse=True)
        out.append({
            "id": cid,
            "name": " · ".join(name_terms[:2]) if name_terms else f"方向 {cid + 1}",
            "terms": terms,
            "meta_labels": labels_from_meta,
            "size": len(members),
            "sids": [p["sid"] for p in sub],
            "members": members,
            "year_range": [min(years), max(years)] if years else None,
            "median_cites": cites[len(cites) // 2] if cites else 0,
            "designs": designs,
            "cohesion": cohesion,
            "representative": sub[members.index(rep_idx)] if rep_idx in members else sub[0],
            "oa_ratio": round(sum(1 for p in sub if p.get("is_oa")) / len(sub), 2),
        })
    return out


# --------------------------------------------------------------------------
# 精选
# --------------------------------------------------------------------------
def _impact_score(cites: int, max_cites: int) -> float:
    if max_cites <= 0:
        return 0.0
    return math.log1p(max(cites, 0)) / math.log1p(max_cites)


def _recency_score(year: int | None, newest: int, oldest: int) -> float:
    if not year:
        return 0.35
    if newest == oldest:
        return 1.0
    # 半衰期 5 年：10 年前的工作仍有 0.25 分，不会被完全埋掉
    return float(0.5 ** (max(newest - year, 0) / 5.0))


def _completeness(p: dict) -> tuple[float, list[str]]:
    checks = {
        "有摘要": len(p.get("abstract") or "") >= 400,
        "有 DOI": bool(p.get("doi")),
        "作者完整": len(p.get("authors") or []) >= 3,
        "有发表载体": bool(p.get("venue")),
        "有关键词": bool(p.get("keywords") or p.get("fields")),
        "有年份": bool(p.get("year")),
    }
    got = sum(1 for v in checks.values() if v)
    return got / len(checks), [k for k, v in checks.items() if v]


def curate(papers: list[dict], query: str = "", labels: list[int] | None = None,
           top_n: int | None = None) -> list[dict]:
    """精选排序。返回带分项解释的列表。"""
    if not papers:
        return []
    years = [p["year"] for p in papers if p.get("year")]
    newest, oldest = (max(years), min(years)) if years else (0, 0)
    max_cites = max([p.get("cited_by") or 0 for p in papers] + [0])

    feats = related.build_features(papers)
    if query.strip():
        qv = feats["tfidf"].transform_one(query)
        relevance = [T.cosine(qv, feats["matrix"][i]) if np.any(qv) else 0.0 for i in range(len(papers))]
    else:
        relevance = []
        for i in range(len(papers)):
            if labels:
                same = [j for j in range(len(papers)) if labels[j] == labels[i] and j != i]
            else:
                same = [j for j in range(len(papers)) if j != i]
            relevance.append(float(np.mean([feats["text_sim"][i, j] for j in same])) if same else 0.0)

    max_rel = max(relevance) if relevance else 0.0
    rows = []
    for i, p in enumerate(papers):
        impact = _impact_score(p.get("cited_by") or 0, max_cites)
        recency = _recency_score(p.get("year"), newest, oldest)
        rel = relevance[i] / max_rel if max_rel > 0 else 0.0
        comp, comp_tags = _completeness(p)
        access = 1.0 if p.get("pdf_url") else (0.7 if p.get("is_oa") else 0.2)
        score = 0.30 * impact + 0.20 * recency + 0.28 * rel + 0.14 * comp + 0.08 * access
        tags = []
        if impact >= 0.75:
            tags.append("高被引")
        if p.get("year") and newest and newest - p["year"] <= 3:
            tags.append("近三年")
        if p.get("is_oa") or p.get("pdf_url"):
            tags.append("开放获取")
        if comp >= 0.83:
            tags.append("信息完整")
        if (p.get("cited_by") or 0) >= 50:
            tags.append("领域经典")
        rows.append({
            "paper": p,
            "score": round(score * 100, 1),
            "parts": {
                "影响力": round(impact * 100, 1),
                "新近度": round(recency * 100, 1),
                "相关度": round(rel * 100, 1),
                "完整度": round(comp * 100, 1),
                "可获得性": round(access * 100, 1),
            },
            "tags": tags,
            "why": _why(impact, recency, rel, comp, p),
        })
    rows.sort(key=lambda r: -r["score"])
    for rank, r in enumerate(rows, 1):
        r["rank"] = rank
    return rows[:top_n] if top_n else rows


def _why(impact: float, recency: float, rel: float, comp: float, p: dict) -> str:
    bits = []
    if impact >= 0.7:
        bits.append(f"被引 {p.get('cited_by', 0)} 次，在本批文献中影响力靠前")
    if recency >= 0.8 and p.get("year"):
        bits.append(f"{p['year']} 年发表，时效性强")
    if rel >= 0.75:
        bits.append("与检索主题高度贴合")
    if comp >= 0.83:
        bits.append("摘要与元数据完整，可直接用于综述引用")
    if not bits:
        bits.append("综合表现均衡，可作为补充阅读")
    return "；".join(bits) + "。"


def report(papers: list[dict], res: dict | None = None) -> dict:
    """给页面用的汇总：方向数、最大方向、年份跨度、OA 比例。"""
    res = res or cluster(papers)
    years = [p["year"] for p in papers if p.get("year")]
    return {
        "n": len(papers),
        "k": res["k"],
        "silhouette": res["silhouette"],
        "method": res["method"],
        "year_span": [min(years), max(years)] if years else None,
        "oa_ratio": round(sum(1 for p in papers if p.get("is_oa")) / len(papers), 2) if papers else 0,
        "largest": max((c["size"] for c in res["clusters"]), default=0),
        "designs": _design_dist(papers),
    }


def _design_dist(papers: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in papers:
        d = schema.DESIGN_LABELS.get(p.get("design"), "未识别")
        out[d] = out.get(d, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
