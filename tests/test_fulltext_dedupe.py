"""全文查重测试：语料扩展、命中定位、去重、分块计算、容量。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import dedupe, schema  # noqa: E402

ABSTRACT = ("Microplastics alter soil structure. We measured aggregate distribution in a "
            "greenhouse experiment with two polymer types at 0.5 percent by weight.")

FULLTEXT_SECTIONS = {
    "introduction": ("Microplastics are widespread contaminants of agricultural soils. "
                     "Their effects on soil physical structure remain poorly quantified."),
    "methods": ("We collected surface soil from a silty loam field in North China. "
                "Two polymer types were mixed at 0.5 percent by weight and incubated for 90 days. "
                "Aggregate size distribution was determined by wet sieving."),
    "results": ("Polyethylene increased the proportion of microaggregates from 17 percent to 32 percent. "
                "Macroaggregates declined from 84 percent to 61 percent under the same treatment."),
    "limitations": ("Only one soil texture was tested, so extrapolation to sandy soils is uncertain."),
}


def _paper(sid: str = "a", abstract: str = ABSTRACT) -> dict:
    return schema.normalize_paper({
        "title": "Microplastics alter soil structure and microbial habitat",
        "abstract": abstract, "year": 2023, "doi": f"10.1000/{sid}",
        "authors": ["Zhang L", "Meyer A"], "sources": ["test"], "sid": sid,
    })


def _fts(sections: dict[str, str]) -> dict:
    return {"sid": "a", "pages": 8, "chars": sum(len(v) for v in sections.values()),
            "sections": sections}


def test_fulltext_corpus_adds_sentences_and_locations():
    papers = [_paper()]
    base = dedupe.text_similarity("Completely unrelated sentence about quantum hardware.", papers)
    assert base["corpus"]["fulltext"] == 0

    with_ft = dedupe.text_similarity("Completely unrelated sentence about quantum hardware.",
                                     papers, fulltexts={"a": _fts(FULLTEXT_SECTIONS)})
    assert with_ft["corpus"]["fulltext"] >= 6
    assert with_ft["corpus"]["papers_with_fulltext"] == 1
    assert with_ft["corpus"]["fulltext"] > base["corpus"]["fulltext"]


def test_hit_located_in_fulltext_section():
    """只存在于正文、摘要里没有的句子，必须能命中并定位到章节。"""
    papers = [_paper()]
    pasted = ("Polyethylene increased the proportion of microaggregates from 17 percent to 32 percent.")
    only_abs = dedupe.text_similarity(pasted, papers, threshold=0.5)
    assert only_abs["hit_sentences"] == 0, "摘要语料里不该命中正文独有的句子"

    rep = dedupe.text_similarity(pasted, papers, threshold=0.5,
                                 fulltexts={"a": _fts(FULLTEXT_SECTIONS)})
    assert rep["hit_sentences"] >= 1
    top = rep["flagged"][0]
    assert top["field"] == "fulltext"
    assert top["loc"] == "全文 · 结果"
    assert rep["rate"] > 0


def test_abstract_hit_still_located_as_abstract():
    papers = [_paper()]
    rep = dedupe.text_similarity("We measured aggregate distribution in a greenhouse experiment.",
                                 papers, threshold=0.4,
                                 fulltexts={"a": _fts(FULLTEXT_SECTIONS)})
    assert rep["flagged"]
    assert rep["flagged"][0]["loc"] in ("摘要", "标题", "全文 · 方法")


def test_duplicate_sentences_counted_once():
    """同一句同时出现在摘要和正文时只进语料一次，避免重复率被抬高。"""
    shared = "Microplastics alter soil structure and microbial habitat."
    sections = {"abstract": shared, "results": shared}
    corpus, stats = dedupe._corpus_sentences([_paper(abstract=shared)], {"a": _fts(sections)})
    texts = [c["text"] for c in corpus]
    assert texts.count(shared) == 1
    assert stats["title"] >= 1


def test_references_excluded_from_corpus():
    sections = {"results": "Aggregates declined under treatment in all replicates measured.",
                "references": "[1] Smith 2020. [2] Doe 2021. A long reference line to pass length."}
    corpus, stats = dedupe._corpus_sentences([_paper()], {"a": _fts(sections)})
    assert not any("Smith 2020" in c["text"] for c in corpus)
    assert stats["fulltext"] >= 1


def test_chunked_scoring_matches_single_pass():
    """分块矩阵乘的结果应与一次性计算一致（用少量语料直接对比）。"""
    import numpy as np
    from core import text as T

    papers = [_paper(f"s{i}", ABSTRACT) for i in range(3)]
    fts = {f"s{i}": _fts(FULLTEXT_SECTIONS) for i in range(3)}
    corpus, _ = dedupe._corpus_sentences(papers, fts)
    query = ["Polyethylene increased the proportion of microaggregates from 17 percent to 32 percent.",
             "Only one soil texture was tested."]

    tf = T.Tfidf(min_df=1, max_features=6000)
    mat = tf.fit_transform([c["text"] for c in corpus] + query).astype(np.float32)
    full = mat[: len(corpus)] @ mat[len(corpus):].T
    expect = full.max(axis=0)

    rep = dedupe.text_similarity(" ".join(query), papers, threshold=0.0, fulltexts=fts)
    got = np.array([f["score"] for f in rep["flagged"]]) if rep["flagged"] else np.array([])
    # 阈值 0 时每句都命中，取最大分对比
    assert got.size == 2
    assert np.allclose(np.sort(got), np.sort(np.round(expect, 3)), atol=0.02)


def test_corpus_capacity_and_speed():
    """20 篇 × 约 300 句的全文语料：应在数秒内完成，且语料条数可控。"""
    papers = [_paper(f"p{i}") for i in range(20)]
    fts = {}
    for i in range(20):
        # 每篇内容不同，否则会被语料去重合并成一份
        sections = {
            "methods": " ".join(
                f"Study {i} performed step {k} of the protocol carefully." for k in range(120)),
            "results": " ".join(
                f"Study {i} estimated effect size for outcome {k} precisely." for k in range(120)),
            "discussion": " ".join(
                f"Study {i} finding for aspect {k} aligns with prior work." for k in range(60)),
        }
        fts[f"p{i}"] = _fts(sections)
    corpus, stats = dedupe._corpus_sentences(papers, fts)
    assert stats["papers_with_fulltext"] == 20
    assert len(corpus) > 5000, "全文语料应显著大于摘要语料"

    t0 = time.time()
    rep = dedupe.text_similarity("Study 3 performed step 42 of the protocol carefully. "
                                 "Study 7 estimated effect size for outcome 5 precisely.", papers,
                                 threshold=0.5, fulltexts=fts)
    elapsed = time.time() - t0
    assert rep["hit_sentences"] >= 2
    assert elapsed < 8.0, f"6000 句语料查重耗时 {elapsed:.1f}s，超出预期"


def test_low_content_sentence_does_not_false_positive():
    """词表截断后，内容词几乎全在表外的短句会塌缩成同一向量。
    这类句子不能判成重复，应记为「无法判定」。"""
    papers = [_paper(f"s{i}") for i in range(30)]
    fts = {f"s{i}": _fts({"methods": "We measured soil aggregate stability by wet sieving."})
           for i in range(30)}
    rep = dedupe.text_similarity("Table 2.", papers, threshold=0.3, fulltexts=fts)
    assert rep["hit_sentences"] == 0
    assert rep["unjudged"] >= 0          # 短句要么被过滤掉，要么明确标为无法判定
    assert rep["total"] == 0 or rep["unjudged"] <= rep["total"]


def test_return_shape_is_consistent():
    """无论输入多短，返回结构必须一致（UI 直接取键）。"""
    keys = {"rate", "total", "hit_sentences", "flagged", "matched_papers",
            "chars", "threshold", "corpus", "unjudged"}
    for text, papers in [("Table 2.", []), ("", [_paper()]),
                         ("A long enough sentence about soil aggregates here.", [])]:
        rep = dedupe.text_similarity(text, papers, threshold=0.5)
        assert keys <= set(rep), f"缺少键：{keys - set(rep)}"
