"""查重：三个层次，解决三种不同的「重复」。

第一层 · 跨源合并
    同一篇论文在 PubMed、Europe PMC、Crossref 里各有一条记录，字段互有缺失。
    这一层把它们并成一条，并记下「合并了哪几个源」，避免用户看到三份一样的东西。

第二层 · 结果集近似重复
    多源聚合之后仍会有「不是同一 DOI、但其实是同一项工作」的情况：
    预印本与正式发表版、会议版与期刊版、同一课题的拆分发表。
    用标题 shingle + 摘要余弦 + SimHash 三路打分，给出「疑似」而不是「判定」，
    并明确标注它属于哪一类重复 —— 判定权留给人。

第三层 · 文本查重
    用户粘一段自己写的稿子，逐句比对语料，给出重复率与命中来源。
    做法是「句子级最佳匹配 + 覆盖率」，不是简单的整篇余弦：
    整篇余弦对「抄了两段」这种局部重复不敏感，逐句比对才看得出问题在哪。
"""
from __future__ import annotations

import re

import numpy as np

from core import schema
from core import text as T


# --------------------------------------------------------------------------
# 并查集
# --------------------------------------------------------------------------
class _DSU:
    def __init__(self, n: int):
        self.p = list(range(n))

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra

    def groups(self) -> dict[int, list[int]]:
        out: dict[int, list[int]] = {}
        for i in range(len(self.p)):
            out.setdefault(self.find(i), []).append(i)
        return out


def _strong_keys(p: dict) -> list[str]:
    keys = []
    if p.get("doi"):
        keys.append("doi:" + schema.normalize_doi(p["doi"]))
    if p.get("pmid"):
        keys.append("pmid:" + str(p["pmid"]))
    if p.get("arxiv_id"):
        keys.append("arxiv:" + re.sub(r"v\d+$", "", str(p["arxiv_id"])))
    return keys


def _conflicting_doi(a: dict, b: dict) -> bool:
    da, db = schema.normalize_doi(a.get("doi")), schema.normalize_doi(b.get("doi"))
    return bool(da and db and da != db)


def dedupe_papers(papers: list[dict], fuzzy_title: float = 0.88) -> dict:
    """跨源合并。返回 {'papers': 合并后列表, 'groups': [...], 'merged': n}。"""
    papers = [p for p in papers if p.get("title")]
    if not papers:
        return {"papers": [], "groups": [], "merged": 0}

    dsu = _DSU(len(papers))
    # 1) 强标识（DOI / PMID / arXiv）直接合并
    index: dict[str, int] = {}
    for i, p in enumerate(papers):
        for k in _strong_keys(p):
            if k in index:
                dsu.union(index[k], i)
            else:
                index[k] = i

    # 2) 标题模糊合并：只在前 40 字符相同（分块）内比较，避免 O(n²)
    #    且两条记录 DOI 冲突时一律不并 —— 那是同一题目的两篇不同论文。
    by_prefix: dict[str, list[int]] = {}
    for i, p in enumerate(papers):
        tk = schema.title_key(p.get("title", ""))
        if len(tk) >= 12:
            by_prefix.setdefault(tk, []).append(i)
    for idxs in by_prefix.values():
        for a in range(len(idxs)):
            for b in range(a + 1, len(idxs)):
                i, j = idxs[a], idxs[b]
                if _conflicting_doi(papers[i], papers[j]):
                    continue
                ta = set(T.tokenize(papers[i]["title"]))
                tb = set(T.tokenize(papers[j]["title"]))
                if T.jaccard(ta, tb) >= fuzzy_title:
                    dsu.union(i, j)

    merged: list[dict] = []
    groups: list[dict] = []
    for root, idxs in dsu.groups().items():
        if len(idxs) == 1:
            p = dict(papers[idxs[0]])
            p["dup_group"] = ""
            p["dup_count"] = 1
            p["merged_sources"] = list(p.get("sources") or [])
            merged.append(p)
            continue
        base = dict(papers[idxs[0]])
        for j in idxs[1:]:
            base = schema.merge_papers(base, papers[j])
        base["dup_group"] = f"g{root}"
        base["dup_count"] = len(idxs)
        base["merged_sources"] = schema._uniq(
            [s for j in idxs for s in (papers[j].get("sources") or [])]
        )
        merged.append(base)
        groups.append({
            "group": f"g{root}",
            "count": len(idxs),
            "titles": [papers[j].get("title", "") for j in idxs],
            "sources": [papers[j].get("sources") or [papers[j].get("source")] for j in idxs],
            "kept": base.get("title", ""),
            "doi": base.get("doi", ""),
        })

    merged.sort(key=lambda p: (-(p.get("dup_count") or 1), -(p.get("year") or 0)))
    return {"papers": merged, "groups": groups, "merged": len(papers) - len(merged)}


# --------------------------------------------------------------------------
# 近似重复
# --------------------------------------------------------------------------
def _pair_score(a: dict, b: dict) -> dict:
    ta = (a.get("title") or "") + ". " + (a.get("abstract") or "")
    tb = (b.get("title") or "") + ". " + (b.get("abstract") or "")
    title_j = T.jaccard(set(T.tokenize(a.get("title") or "")), set(T.tokenize(b.get("title") or "")))
    abs_cos = 0.0
    has_abs = bool(a.get("abstract")) and bool(b.get("abstract"))
    if has_abs:
        tf = T.Tfidf()
        m = tf.fit_transform([ta, tb])
        abs_cos = float(np.clip(m[0] @ m[1], 0, 1))
    sh_a = T.shingles(a.get("abstract") or a.get("title") or "", 3)
    sh_b = T.shingles(b.get("abstract") or b.get("title") or "", 3)
    cont = max(T.containment(sh_a, sh_b), T.containment(sh_b, sh_a))
    ham = T.hamming(T.simhash64(ta), T.simhash64(tb))
    fingerprint = 1.0 - ham / 64.0

    # 信号缺失时要重新归一化权重。否则「两条都没摘要、但标题一字不差」的记录
    # 只能拿到 0.62 分，被误判成弱相关 —— 这是多源合并里最典型的假阴性。
    signals = [(title_j, 0.30), (cont, 0.17), (fingerprint, 0.15)]
    if has_abs:
        signals.append((abs_cos, 0.38))
    total_w = sum(w for _, w in signals)
    score = sum(v * w for v, w in signals) / total_w
    # 标题几乎一字不差，且年份相同：直接抬到高置信区间
    if title_j >= 0.95 and abs((a.get("year") or 0) - (b.get("year") or 0)) <= 1:
        score = max(score, 0.9)
    return {
        "score": round(float(np.clip(score, 0, 1)), 4),
        "title_sim": round(title_j, 4),
        "abstract_cos": round(abs_cos, 4),
        "overlap": round(cont, 4),
        "fingerprint": round(fingerprint, 4),
        "hamming": ham,
    }


def _kind(a: dict, b: dict, score: float) -> tuple[str, str]:
    """给出重复类型与建议处置。"""
    if a.get("doi") and a.get("doi") == b.get("doi"):
        return "同一文献", "保留一条，合并字段"
    a_pre = (a.get("type") or "").lower().startswith("preprint") or bool(a.get("arxiv_id")) and not a.get("doi")
    b_pre = (b.get("type") or "").lower().startswith("preprint") or bool(b.get("arxiv_id")) and not b.get("doi")
    if a_pre != b_pre and score >= 0.72:
        return "预印本 ↔ 正式版", "引用正式版，预印本作为版本记录"
    if score >= 0.93:
        return "高度重复", "核对是否重复发表 / 一稿多投"
    if score >= 0.82:
        return "内容高度相似", "回原文确认是否为同一研究的不同报告"
    if score >= 0.70:
        return "主题与方法接近", "可归入同一研究方向"
    return "弱相关", "无需处理"


def near_duplicates(papers: list[dict], threshold: float = 0.62, limit: int = 60) -> list[dict]:
    """两两比对，返回按分数降序的疑似重复对。"""
    n = len(papers)
    out = []
    for i in range(n):
        for j in range(i + 1, n):
            a, b = papers[i], papers[j]
            if not a.get("title") or not b.get("title"):
                continue
            # 先做廉价预筛：标题词集完全不相交且年份差 > 3 的，直接跳过
            if a.get("year") and b.get("year") and abs(a["year"] - b["year"]) > 3:
                ta, tb = set(T.tokenize(a["title"])), set(T.tokenize(b["title"]))
                if T.jaccard(ta, tb) < 0.15:
                    continue
            sc = _pair_score(a, b)
            if sc["score"] < threshold:
                continue
            kind, advice = _kind(a, b, sc["score"])
            out.append({
                "a_sid": a.get("sid", ""), "b_sid": b.get("sid", ""),
                "a_title": a.get("title", ""), "b_title": b.get("title", ""),
                "a_year": a.get("year"), "b_year": b.get("year"),
                "a_source": "/".join(a.get("sources") or [a.get("source", "")]),
                "b_source": "/".join(b.get("sources") or [b.get("source", "")]),
                "kind": kind, "advice": advice, **sc,
            })
    out.sort(key=lambda x: -x["score"])
    return out[:limit]


# --------------------------------------------------------------------------
# 文本查重
# --------------------------------------------------------------------------
def _corpus_sentences(papers: list[dict]) -> list[dict]:
    out = []
    for p in papers:
        # 标题也进语料：抄标题同样算重复，且标题短、命中率高
        if p.get("title"):
            out.append({"text": p["title"], "sid": p.get("sid", ""), "title": p.get("title", ""),
                        "year": p.get("year"), "field": "title"})
        for s in T.split_sentences(p.get("abstract") or ""):
            if len(s) >= 18:
                out.append({"text": s, "sid": p.get("sid", ""), "title": p.get("title", ""),
                            "year": p.get("year"), "field": "abstract"})
    return out


def text_similarity(text: str, papers: list[dict], threshold: float = 0.52) -> dict:
    """逐句查重。

    对每一句：在语料所有句子里找最相似的一句，取余弦。超过阈值即标为命中。
    重复率按「命中句的字符数 / 总字符数」算，比按句数更贴近直觉
    （抄一句长句和抄一句短句，严重程度显然不同）。
    """
    sentences = [s for s in T.split_sentences(text) if len(s) >= 12]
    corpus = _corpus_sentences(papers)
    if not sentences:
        return {"rate": 0.0, "total": 0, "flagged": [], "matched_papers": [], "chars": 0}
    if not corpus:
        return {"rate": 0.0, "total": len(sentences), "flagged": [], "matched_papers": [], "chars": len(text)}

    tf = T.Tfidf(min_df=1)
    all_texts = [s["text"] for s in corpus] + sentences
    mat = tf.fit_transform(all_texts)
    cmat = T.cosine_matrix(mat)
    corpus_mat = cmat[: len(corpus), len(corpus):]      # 行=语料句, 列=输入句

    flagged = []
    total_chars = sum(len(s) for s in sentences)
    hit_chars = 0.0
    matched_papers: dict[str, dict] = {}

    for col, sent in enumerate(sentences):
        col_scores = corpus_mat[:, col]
        best = int(np.argmax(col_scores)) if col_scores.size else -1
        score = float(col_scores[best]) if best >= 0 else 0.0
        if score >= threshold and best >= 0:
            src = corpus[best]
            hit_chars += len(sent) * min(1.0, score / 0.9)
            flagged.append({
                "sentence": sent,
                "match": src["text"],
                "score": round(score, 3),
                "title": src["title"],
                "sid": src["sid"],
                "year": src["year"],
            })
            key = src["sid"]
            rec = matched_papers.setdefault(key, {"sid": key, "title": src["title"],
                                                  "year": src["year"], "hits": 0, "best": 0.0})
            rec["hits"] += 1
            rec["best"] = max(rec["best"], round(score, 3))

    rate = round(hit_chars / total_chars * 100, 1) if total_chars else 0.0
    return {
        "rate": min(rate, 100.0),
        "total": len(sentences),
        "hit_sentences": len(flagged),
        "chars": total_chars,
        "flagged": sorted(flagged, key=lambda x: -x["score"]),
        "matched_papers": sorted(matched_papers.values(), key=lambda x: (-x["hits"], -x["best"])),
        "threshold": threshold,
    }


def duplicate_summary(papers: list[dict]) -> dict:
    """给检索结果页一个概览：多少条来自多源、多少对疑似重复。"""
    multi = [p for p in papers if len(p.get("merged_sources") or p.get("sources") or []) > 1]
    pairs = near_duplicates(papers, threshold=0.82)
    return {
        "total": len(papers),
        "multi_source": len(multi),
        "suspicious_pairs": len(pairs),
        "high_risk": len([p for p in pairs if p["score"] >= 0.93]),
    }
