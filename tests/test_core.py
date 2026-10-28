"""数据结构、摘要引擎、查重的单元测试。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import dedupe, schema, summarize, templates  # noqa: E402

STRUCTURED = (
    "Background: Alzheimer's disease diagnosis remains challenging in primary care. "
    "Methods: We trained a convolutional neural network on 1200 MRI scans from three cohorts "
    "and compared its performance with that of radiologists. "
    "Results: The model achieved an AUC of 0.92 (95% CI 0.89 to 0.95), outperforming radiologists (P<0.001). "
    "Conclusions: Deep learning improves diagnostic accuracy, but generalization remains limited."
)

PLAIN = (
    "Microplastics impact soil structure and microbiota, yet the link between aggregate scale "
    "and microbial community composition is unclear. Herein, we investigated the effects of "
    "conventional and biodegradable microplastics on aggregate distribution. Two MP types were "
    "mixed with a silty loam soil at 0.5% (w/w) in a greenhouse for one year. They increased the "
    "proportion of microaggregates from 17% to 32%, while reducing macroaggregates from 84% to 61%. "
    "Such effects were stronger for PE than PLA due to the higher persistence of PE in soils."
)


def _paper(title="", abstract="", **kw):
    return schema.normalize_paper({"title": title, "abstract": abstract, **kw})


def test_normalize_doi():
    assert schema.normalize_doi("https://doi.org/10.1000/ABC.123") == "10.1000/abc.123"
    assert schema.normalize_doi("doi: 10.1000/xyz") == "10.1000/xyz"
    assert schema.normalize_doi("") == ""


def test_design_classification():
    assert schema.classify_design("A randomized controlled trial of exercise") == "rct"
    assert schema.classify_design("Graph neural networks: a survey", "This review summarizes 120 papers") == "review"
    assert schema.classify_design("Meta-analysis of statins", "") == "meta_analysis"
    assert schema.classify_design("", "We conducted semi-structured interviews with 24 teachers") == "qualitative"
    assert schema.classify_design("Soil study", "Two MP types were mixed with soil in a greenhouse") == "experimental"


def test_merge_papers_prefers_richer_fields():
    a = _paper("Same title", "short abstract", doi="10.1000/a", sources=["crossref"])
    b = _paper("Same title", "a much longer abstract with numbers", pmid="123", cited_by=10, sources=["pubmed"])
    m = schema.merge_papers(a, b)
    assert m["abstract"].startswith("a much longer")
    assert m["pmid"] == "123"
    assert m["cited_by"] == 10
    assert set(m["sources"]) == {"crossref", "pubmed"}


def test_structured_summary_uses_sections():
    s = summarize.structured(_paper("AD diagnosis", STRUCTURED), "imrad")
    assert s["structured"] is True
    assert s["slots"]["method"]["sentences"], "结构化摘要应能识别 Methods"
    assert "AUC" in " ".join(x["text"] for x in s["slots"]["findings"]["sentences"])
    assert s["coverage"] >= 4
    assert s["confidence"] >= 45


def test_plain_abstract_infers_method():
    s = summarize.structured(_paper("Microplastics", PLAIN), "imrad")
    assert s["slots"]["method"]["sentences"], "无线索时应按位置推断方法与设计"
    method_text = " ".join(x["text"] for x in s["slots"]["method"]["sentences"])
    assert "mixed with" in method_text
    assert s["slots"]["limitation"]["missing"] is True


def test_chinese_structured_summary():
    zh = _paper("微塑料影响", "目的：探讨微塑料影响。方法：设置三个浓度处理，培养60天。"
                            "结果：多样性指数显著下降（P<0.05）。结论：高浓度会改变群落结构。")
    s = summarize.structured(zh, "imrad")
    assert s["structured"] is True
    assert s["slots"]["question"]["sentences"]
    assert s["slots"]["conclusion"]["sentences"]
    assert s["one_liner"].startswith("高浓度")


def test_template_switch_changes_labels():
    p = _paper("Minimum wage and employment", "We use a difference-in-differences design with panel data.")
    econ = summarize.structured(p, "econ")
    imrad = summarize.structured(p, "imrad")
    assert econ["slots"]["method"]["label"] == "识别策略"
    assert imrad["slots"]["method"]["label"] == "方法与设计"


def test_auto_template_for_review():
    p = _paper("A survey of graph neural networks", "This review summarizes 120 papers.")
    assert templates.auto_template(p) == "review"


def test_dedupe_merges_same_doi():
    a = _paper("Paper A", "abstract one", doi="10.1000/x", sources=["crossref"])
    b = _paper("Paper A (different casing)", "abstract two", doi="10.1000/X", sources=["openalex"])
    out = dedupe.dedupe_papers([a, b])
    assert len(out["papers"]) == 1
    assert out["merged"] == 1
    assert out["papers"][0]["dup_count"] == 2


def test_dedupe_keeps_conflicting_dois_separate():
    a = _paper("Same title here", "abstract", doi="10.1000/a")
    b = _paper("Same title here", "abstract", doi="10.2000/b")
    out = dedupe.dedupe_papers([a, b])
    assert len(out["papers"]) == 2


def test_near_duplicate_preprint_vs_published():
    abstract = ("We trained a convolutional network on 1200 MRI scans and achieved an AUC of 0.92, "
                "outperforming radiologists. Generalization remains limited.")
    a = _paper("Deep learning for Alzheimer diagnosis using MRI", abstract,
               year=2023, doi="10.1000/pre", type="preprint", arxiv_id="2301.00001")
    b = _paper("Deep Learning for Alzheimer Disease Diagnosis Using MRI", abstract,
               year=2024, doi="10.2000/pub", type="journal article")
    pairs = dedupe.near_duplicates([a, b], threshold=0.6)
    assert pairs and pairs[0]["kind"] == "预印本 ↔ 正式版"
    assert pairs[0]["score"] > 0.8


def test_text_similarity_flags_copied_sentence():
    corpus = [_paper("Source paper", STRUCTURED)]
    text = ("We trained a convolutional neural network on 1200 MRI scans from three cohorts. "
            "Our own contribution is a new regularization term.")
    rep = dedupe.text_similarity(text, corpus, threshold=0.5)
    assert rep["hit_sentences"] >= 1
    assert rep["rate"] > 20
    assert rep["matched_papers"]


def test_text_similarity_zero_for_unrelated():
    corpus = [_paper("Source paper", STRUCTURED)]
    rep = dedupe.text_similarity("Minimum wage policy affects regional employment dynamics.", corpus, 0.5)
    assert rep["rate"] == 0.0
