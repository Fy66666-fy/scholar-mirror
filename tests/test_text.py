"""文本层单元测试。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import text as T  # noqa: E402


def test_split_sentences_handles_abbrev():
    s = "Smith et al. 2020 reported a 3.5 fold increase. The effect was small. We agree."
    out = T.split_sentences(s)
    assert len(out) == 3
    assert out[0].startswith("Smith et al. 2020")


def test_split_sentences_chinese():
    out = T.split_sentences("目的：探讨影响。方法：采集样本；结果：显著下降。结论：成立。")
    assert len(out) >= 3
    assert any("结论" in x for x in out)


def test_detect_lang():
    assert T.detect_lang("这是一段中文摘要") == "zh"
    assert T.detect_lang("This is an English abstract") == "en"


def test_tokenize_stems_and_drops_stopwords():
    toks = T.tokenize("The studies were analyzing microplastics in soils")
    assert "the" not in toks
    assert "were" not in toks
    assert any(t.startswith("microplast") for t in toks)


def test_tokenize_chinese_bigrams():
    toks = T.tokenize("微塑料影响土壤微生物群落")
    assert "微塑" in toks
    assert all(len(t) <= 2 for t in toks)


def test_tfidf_cosine_orders_similarity():
    docs = [
        "deep learning for medical image segmentation with transformers",
        "transformer models for medical image segmentation",
        "labor economics of minimum wage policy",
    ]
    tf = T.Tfidf()
    m = tf.fit_transform(docs)
    assert T.cosine(m[0], m[1]) > T.cosine(m[0], m[2])
    assert abs(T.cosine(m[0], m[0]) - 1.0) < 1e-6


def test_simhash_identical_and_different():
    a = T.simhash64("graph neural networks for molecular property prediction")
    b = T.simhash64("graph neural networks for molecular property prediction")
    c = T.simhash64("soil microbial community response to microplastics")
    assert T.hamming(a, b) == 0
    assert T.hamming(a, c) > 8


def test_shingles_and_containment():
    a = T.shingles("we trained a model on three cohorts of patients", 3)
    b = T.shingles("we trained a model on three cohorts of patients with dementia", 3)
    assert T.containment(a, b) == 1.0
    assert T.containment(b, a) < 1.0


def test_extract_numbers_types():
    s = "The model reached an AUC of 0.92 (95% CI 0.89 to 0.95), P<0.001, in 1200 patients, a 12.3% gain."
    nums = T.extract_numbers(s)
    kinds = {n["type"] for n in nums}
    assert "p_value" in kinds
    assert "auc" in kinds
    assert "percent" in kinds
    vals = [n["value"] for n in nums]
    assert "12.3%" in vals
    assert not any(v == "3%" for v in vals), "小数点后的数字不应被切成百分数"


def test_extract_sample_size_takes_max():
    assert T.extract_sample_size("We enrolled 40 patients in phase 1 and 320 patients in phase 2.") == 320
    assert T.extract_sample_size("纳入 128 例患者") == 128
    assert T.extract_sample_size("no numbers here") is None


def test_keywords_from_text_prefers_specific():
    text = ("Microplastics alter soil aggregate distribution. "
            "Microplastics in soil reduce bacterial diversity, and biodegradable microplastics differ.")
    kws = T.keywords_from_text(text, 6)
    assert any("microplast" in k for k in kws)


def test_surface_map_restores_original_form():
    surfaces = T.surface_map(["Microplastics in soils", "microplastics everywhere"])
    stem = T.tokenize("microplastics")[0]
    assert surfaces.get(stem) in ("microplastics", "Microplastics")
