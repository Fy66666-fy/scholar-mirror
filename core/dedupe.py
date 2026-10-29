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
_POPCNT = np.array([bin(i).count("1") for i in range(256)], dtype=np.int16)


def _doc_pre(p: dict) -> dict:
    title = p.get("title") or ""
    abstract = p.get("abstract") or ""
    text = title + ". " + abstract
    return {
        "tokens": set(T.tokenize(title)),
        "shingles": T.shingles(abstract or title, 3),
        "h": T.simhash64(text),
        "has_abs": bool(abstract),
        "text": text,
    }


def _hamming_matrix(hs: np.ndarray) -> np.ndarray:
    """SimHash 64 位两两汉明距离，按字节查表，分块算防止 n 大时爆内存。"""
    n = len(hs)
    out = np.zeros((n, n), dtype=np.int16)
    u8 = np.ascontiguousarray(hs).view(np.uint8).reshape(n, 8)
    for s in range(0, n, 256):
        e = min(s + 256, n)
        block = u8[s:e, None, :] ^ u8[None, :, :]
        out[s:e] = _POPCNT[block].sum(axis=-1, dtype=np.int16)
    return out


def _pre_screen(papers: list[dict]) -> dict:
    """一次性预计算所有两两比较需要的量，之后逐对只剩集合运算。

    - 摘要余弦：全语料拟合一次 TF-IDF，矩阵乘法出全部两两余弦
      （旧实现每对重新拟合一次 TF-IDF，300 篇就是 4.5 万次拟合 = 35 秒）
    - 标题 Jaccard：词表 0/1 矩阵乘法
    - SimHash 指纹：字节异或 + 查表
    """
    docs = [_doc_pre(p) for p in papers]
    n = len(docs)
    tf = T.Tfidf(min_df=1, max_features=4000)
    mat = tf.fit_transform([d["text"] for d in docs]).astype(np.float32)
    # 分块算余弦，600 篇 × 4000 词的矩阵乘也只需 ~0.5s、几十 MB
    cos = np.zeros((n, n), dtype=np.float32)
    for s in range(0, n, 256):
        e = min(s + 256, n)
        cos[s:e] = np.clip(mat[s:e] @ mat.T, 0.0, 1.0)

    # 标题 Jaccard：inter = A∩B，jaccard = inter / (|A|+|B|-inter)
    terms: set = set()
    for d in docs:
        terms |= d["tokens"]
    tj = np.zeros((n, n), dtype=np.float32)
    if terms:
        pos = {t: i for i, t in enumerate(terms)}
        inc = np.zeros((n, len(terms)), dtype=np.float32)
        for i, d in enumerate(docs):
            for t in d["tokens"]:
                inc[i, pos[t]] = 1.0
        inter = inc @ inc.T
        sz = inc.sum(axis=1)
        union = sz[:, None] + sz[None, :] - inter
        tj = np.divide(inter, union, out=np.zeros_like(inter), where=union > 0)

    hs = np.array([d["h"] for d in docs], dtype=np.uint64)
    ham = _hamming_matrix(hs).astype(np.float32)
    return {
        "docs": docs, "cos": cos, "tj": tj,
        "fpr": 1.0 - ham / 64.0, "ham": ham,
    }


def _pair_result(i: int, j: int, scr: dict) -> dict:
    """用预计算结果拼出一对的完整打分，字段与旧 _pair_score 完全一致。"""
    docs = scr["docs"]
    a, b = docs[i], docs[j]
    has_abs = a["has_abs"] and b["has_abs"]
    abs_cos = float(scr["cos"][i, j]) if has_abs else 0.0
    title_j = float(scr["tj"][i, j])
    cont = max(T.containment(a["shingles"], b["shingles"]),
               T.containment(b["shingles"], a["shingles"]))
    ham = int(scr["ham"][i, j])
    fingerprint = 1.0 - ham / 64.0

    # 信号缺失时要重新归一化权重。否则「两条都没摘要、但标题一字不差」的记录
    # 只能拿到 0.62 分，被误判成弱相关 —— 这是多源合并里最典型的假阴性。
    signals = [(title_j, 0.30), (cont, 0.17), (fingerprint, 0.15)]
    if has_abs:
        signals.append((abs_cos, 0.38))
    total_w = sum(w for _, w in signals)
    score = sum(v * w for v, w in signals) / total_w
    return {
        "score": score, "title_sim": title_j, "abstract_cos": abs_cos,
        "overlap": cont, "fingerprint": fingerprint, "hamming": ham,
        "has_abs": has_abs,
    }


def near_duplicates(papers: list[dict], threshold: float = 0.62, limit: int = 60) -> list[dict]:
    """两两比对，返回按分数降序的疑似重复对。

    先用精确的上界预筛（余弦/标题/指纹都是精确值，只有 containment 用上界 1），
    过不了上界的对不进精算 —— 结果和全量精算完全一致，但工作量从 O(n²) 次
    TF-IDF 拟合降到 O(n²) 次矩阵乘加。
    """
    n = len(papers)
    if n < 2:
        return []
    scr = _pre_screen(papers)
    docs = scr["docs"]
    cos, tj, fpr = scr["cos"], scr["tj"], scr["fpr"]
    has_abs = np.array([d["has_abs"] for d in docs])
    both = has_abs[:, None] & has_abs[None, :]
    years = np.array([(p.get("year") or 0) for p in papers])

    # 上界：containment 未算，取 1；无摘要时按旧逻辑去掉 0.38 权重后归一
    w = np.where(both, 1.0, 0.62)
    ub = (0.38 * cos * both + 0.30 * tj + 0.17 + 0.15 * fpr) / w
    # 标题几乎一字不差 + 年份接近会被直接抬到 0.9，这类对也要进精算
    boost = (tj >= 0.95) & (np.abs(years[:, None] - years[None, :]) <= 1)
    cand = (np.triu(ub, 1) >= threshold) | np.triu(boost, 1)

    out = []
    for i, j in zip(*np.nonzero(cand)):
        if i >= j:
            continue
        a, b = papers[i], papers[j]
        if not a.get("title") or not b.get("title"):
            continue
        # 廉价跳过：标题词集完全不相交且年份差 > 3
        tji = float(tj[i, j])
        if a.get("year") and b.get("year") and abs(a["year"] - b["year"]) > 3 and tji < 0.15:
            continue
        sc = _pair_result(int(i), int(j), scr)
        # 标题几乎一字不差，且年份相同：直接抬到高置信区间
        if sc["title_sim"] >= 0.95 and abs((a.get("year") or 0) - (b.get("year") or 0)) <= 1:
            sc["score"] = max(sc["score"], 0.9)
        sc["score"] = round(float(np.clip(sc["score"], 0, 1)), 4)
        if sc["score"] < threshold:
            continue
        kind, advice = _kind(a, b, sc["score"])
        out.append({
            "a_sid": a.get("sid", ""), "b_sid": b.get("sid", ""),
            "a_title": a.get("title", ""), "b_title": b.get("title", ""),
            "a_year": a.get("year"), "b_year": b.get("year"),
            "a_source": "/".join(a.get("sources") or [a.get("source", "")]),
            "b_source": "/".join(b.get("sources") or [b.get("source", "")]),
            "kind": kind, "advice": advice,
            "score": sc["score"], "title_sim": round(sc["title_sim"], 4),
            "abstract_cos": round(sc["abstract_cos"], 4),
            "overlap": round(sc["overlap"], 4),
            "fingerprint": round(sc["fingerprint"], 4),
            "hamming": sc["hamming"],
        })
    out.sort(key=lambda x: -x["score"])
    return out[:limit]


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


# --------------------------------------------------------------------------
# 文本查重
# --------------------------------------------------------------------------
def _corpus_sentences(papers: list[dict], fulltexts: dict[str, dict] | None = None,
                      max_per_paper: int = 600) -> tuple[list[dict], dict]:
    """构造查重语料：标题 + 摘要 +（可选）已解析的全文分章。

    全文按章节进语料，命中时能说清「抄自哪一篇的哪一章」——摘要级查重
    只能说「抄自某篇」，说不清位置。同一句话在多个来源出现时只留第一次
    （标题 > 摘要 > 全文），避免重复命中把重复率抬高。
    """
    fulltexts = fulltexts or {}
    out: list[dict] = []
    seen: set[str] = set()
    stats = {"title": 0, "abstract": 0, "fulltext": 0, "papers_with_fulltext": 0, "truncated": 0}

    def add(text: str, p: dict, field: str, loc: str) -> None:
        key = text.strip()
        if len(key) < 12 or key in seen:
            return
        seen.add(key)
        out.append({"text": text, "sid": p.get("sid", ""), "title": p.get("title", ""),
                    "year": p.get("year"), "field": field, "loc": loc})
        stats[field] += 1

    for p in papers:
        sid = p.get("sid", "")
        if p.get("title"):
            add(p["title"], p, "title", "标题")
        for s in T.split_sentences(p.get("abstract") or ""):
            if len(s) >= 18:
                add(s, p, "abstract", "摘要")
        ft = fulltexts.get(sid)
        if not ft:
            continue
        stats["papers_with_fulltext"] += 1
        secs = ft.get("sections") or {}
        used = 0
        for sec_name, body in secs.items():
            if sec_name in ("references", "acknowledgements", "funding"):
                continue
            label = f"全文 · {_sec_zh(sec_name)}"
            for s in T.split_sentences(body):
                if len(s) < 18:
                    continue
                if used >= max_per_paper:
                    stats["truncated"] += 1
                    break
                before = stats["fulltext"]
                add(s, p, "fulltext", label)
                if stats["fulltext"] > before:
                    used += 1
    return out, stats


def _sec_zh(name: str) -> str:
    from core import fulltext as FT
    return FT.sec_label(name)


def _vocab_cap(n_docs: int) -> int:
    """按文档数收词表：Tfidf 内部是稠密矩阵，6000 句 × 6000 词要 288MB。

    目标是把矩阵压在 200MB 以内（float64 建表阶段），再转 float32。
    语料少时不设限，语料多时降词表 —— 逐句查重靠的是高频实词，
    砍掉长尾词对命中率影响很小。
    """
    return int(min(6000, max(2000, 2.0e8 / (8 * max(n_docs, 1)))))


def text_similarity(text: str, papers: list[dict], threshold: float = 0.52,
                    fulltexts: dict[str, dict] | None = None) -> dict:
    """逐句查重。

    对每一句：在语料所有句子里找最相似的一句，取余弦。超过阈值即标为命中。
    重复率按「命中句的字符数 / 总字符数」算，比按句数更贴近直觉
    （抄一句长句和抄一句短句，严重程度显然不同）。

    fulltexts 传 {sid: 解析结果} 时语料从摘要扩到全文，命中能定位到章节。
    语料上千句时逐块做矩阵乘，不一次性铺开整张余弦矩阵（否则几千句
    × 数千词就是几百 MB）。
    """
    sentences = [s for s in T.split_sentences(text) if len(s) >= 12]
    corpus, corpus_stats = _corpus_sentences(papers, fulltexts)
    if not sentences:
        return {"rate": 0.0, "total": 0, "hit_sentences": 0, "flagged": [], "matched_papers": [],
                "chars": 0, "threshold": threshold, "corpus": corpus_stats, "unjudged": 0}
    if not corpus:
        return {"rate": 0.0, "total": len(sentences), "hit_sentences": 0, "flagged": [],
                "matched_papers": [], "chars": len(text), "threshold": threshold,
                "corpus": corpus_stats, "unjudged": len(sentences)}

    tf = T.Tfidf(min_df=1, max_features=_vocab_cap(len(corpus) + len(sentences)))
    all_texts = [s["text"] for s in corpus] + sentences
    mat = tf.fit_transform(all_texts).astype(np.float32)

    # 有效词守卫：词表截断后，内容词全落在表外的句子会塌缩成同一个近零向量，
    # 两两余弦变成 1.0 的假命中。这里分两道关：
    #   1) 向量全零的句子不参与（语料排除、待检句记为无法判定）
    #   2) 命中对必须有实际词重合（≥2 个词），否则算塌缩artifact而不是重复
    nnz = (mat != 0).sum(axis=1)
    corpus_mask = nnz[: len(corpus)] >= 1
    query_mask = nnz[len(corpus):] >= 1
    corpus_ids = np.nonzero(corpus_mask)[0]
    unjudged = int((~query_mask).sum())
    if corpus_ids.size == 0:
        return {"rate": 0.0, "total": len(sentences), "hit_sentences": 0, "chars": len(text),
                "flagged": [], "matched_papers": [], "threshold": threshold,
                "corpus": corpus_stats, "unjudged": unjudged}

    corpus_vec = mat[corpus_ids]
    query = mat[len(corpus):][query_mask].T          # V×Q

    best_score = np.zeros(query.shape[1], dtype=np.float32)
    best_idx = np.zeros(query.shape[1], dtype=np.int64)
    for start in range(0, corpus_vec.shape[0], 2048):
        block = corpus_vec[start:start + 2048] @ query
        local = block.argmax(axis=0)
        local_score = block.max(axis=0)
        better = local_score > best_score
        best_score[better] = local_score[better]
        best_idx[better] = local[better] + start

    flagged = []
    total_chars = sum(len(s) for s in sentences)
    hit_chars = 0.0
    matched_papers: dict[str, dict] = {}
    tok_cache: dict[int, set] = {}

    def _tokens(text: str) -> set:
        return set(T.tokenize(text))

    judged = [i for i, ok in enumerate(query_mask) if ok]
    for col, sent_i in enumerate(judged):
        score = float(best_score[col])
        if score < threshold:
            continue
        src_i = int(corpus_ids[int(best_idx[col])])
        src = corpus[src_i]
        sent = sentences[sent_i]
        # 塌缩artifact 判定：余弦很高但词面几乎不重合
        ctok = tok_cache.get(src_i)
        if ctok is None:
            ctok = tok_cache[src_i] = _tokens(src["text"])
        if len(_tokens(sent) & ctok) < 2:
            unjudged += 1
            continue
        hit_chars += len(sent) * min(1.0, score / 0.9)
        flagged.append({
            "sentence": sent,
            "match": src["text"],
            "score": round(score, 3),
            "title": src["title"],
            "sid": src["sid"],
            "year": src["year"],
            "field": src["field"],
            "loc": src["loc"],
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
        "corpus": corpus_stats,
        "unjudged": unjudged,
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
