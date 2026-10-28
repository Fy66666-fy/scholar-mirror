"""关联、聚类、缺口、导出与文献库的测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import cluster, db, dedupe, export, gaps, library, related, schema  # noqa: E402

TOPICS = {
    "ad": [
        ("Deep learning for Alzheimer diagnosis on MRI", "We trained a CNN on 1200 MRI scans and reached AUC 0.92. Generalization is limited.", 2021),
        ("Plasma p-tau217 as a blood biomarker", "In a multicentre cohort of 600 participants followed 60 months, p-tau217 predicted amyloid status.", 2022),
        ("Tau PET imaging in early Alzheimer disease", "We imaged 180 patients with tau PET and correlated with cognition over 24 months.", 2020),
        ("CSF biomarkers and hippocampal atrophy", "CSF amyloid and tau were measured in 240 patients; atrophy predicted conversion.", 2019),
    ],
    "soil": [
        ("Microplastics alter soil aggregates", "Two microplastic types were mixed with soil in a greenhouse for one year; macroaggregates fell.", 2023),
        ("Microplastics reduce soil microbial diversity", "We incubated soil with polyethylene at three doses; bacterial diversity declined significantly.", 2022),
        ("Biodegradable microplastics and soil enzymes", "A 90-day incubation showed enzyme activity changes under biodegradable microplastics.", 2024),
        ("Earthworms and microplastics in agricultural soil", "Field sampling across 12 farms found earthworm avoidance of microplastic hotspots.", 2021),
    ],
}


def _build(key: str) -> list[dict]:
    out = []
    for i, (title, abstract, year) in enumerate(TOPICS[key]):
        out.append(schema.normalize_paper({
            "title": title, "abstract": abstract, "year": year,
            "authors": [f"Author {key}{i}"], "venue": "Journal of " + key,
            "doi": f"10.5555/{key}.{i}", "cited_by": (i + 1) * 7,
            "keywords": ["alzheimer", "biomarker"] if key == "ad" else ["microplastics", "soil"],
            "sources": ["test"], "sid": f"{key}:{i}",
        }))
    return out


def test_relations_matrix_shape_and_symmetry():
    ps = _build("ad")
    m = related.relations(ps)
    assert m.shape == (4, 4)
    assert (m == m.T).all()
    assert (m.diagonal() == 1).all()
    # 同一主题内部应比跨主题更像
    other = _build("soil")
    assert m[0, 1] > 0


def test_graph_adaptive_threshold_creates_edges():
    ps = _build("ad") + _build("soil")
    g = related.build_graph(ps)
    assert g["stats"]["nodes"] == 8
    assert g["stats"]["edges"] >= 4, "自适应阈值应至少连出主题内部的边"
    assert g["threshold"] > 0


def test_layout_is_normalized_and_finite():
    ps = _build("ad") + _build("soil")
    g = related.build_graph(ps)
    pos = related.layout(g["nodes"], g["edges"])
    assert len(pos) == len(ps)
    for x, y in pos.values():
        assert 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0


def test_top_related_returns_reasons():
    ps = _build("ad")
    rels = related.top_related(ps[0], ps, k=3)
    assert rels
    assert rels[0]["score"] >= rels[-1]["score"]
    assert isinstance(rels[0]["reasons"], list)


def test_cluster_separates_topics():
    ps = _build("ad") + _build("soil")
    res = cluster.cluster(ps, k=2)
    labels = res["labels"]
    assert len(set(labels)) == 2
    ad_labels = {labels[i] for i in range(4)}
    soil_labels = {labels[i] for i in range(4, 8)}
    assert ad_labels != soil_labels, "两个主题应落到不同簇"


def test_cluster_names_are_readable():
    ps = _build("ad") + _build("soil")
    res = cluster.cluster(ps, k=2)
    for c in res["clusters"]:
        assert c["name"]
        assert not c["name"].startswith("Cluster")


def test_curate_is_ranked_and_explained():
    ps = _build("ad")
    rows = cluster.curate(ps, "alzheimer biomarker")
    assert [r["rank"] for r in rows] == list(range(1, len(ps) + 1))
    assert rows[0]["score"] >= rows[-1]["score"]
    assert set(rows[0]["parts"]) == {"影响力", "新近度", "相关度", "完整度", "可获得性"}
    assert rows[0]["why"].endswith("。")


def test_gaps_caveat_when_too_few_papers():
    res = gaps.detect(_build("ad")[:2])
    assert "低于" in res["caveat"]
    assert res["gaps"] == []


def test_gaps_detects_small_sample():
    ps = []
    for i in range(6):
        ps.append(schema.normalize_paper({
            "title": f"Study {i} on microplastics", "abstract": "We studied 12 samples and found changes.",
            "year": 2022, "design": "experimental", "sid": f"s{i}", "sources": ["test"],
        }))
    res = gaps.detect(ps)
    keys = {g["key"] for g in res["gaps"]}
    assert "sample" in keys
    sample_gap = next(g for g in res["gaps"] if g["key"] == "sample")
    assert sample_gap["evidence"]
    assert sample_gap["questions"]


def test_gaps_detects_missing_reproducibility():
    ps = []
    for i in range(5):
        ps.append(schema.normalize_paper({
            "title": f"Trial {i}", "abstract": "We enrolled 400 patients in a randomized trial and found improvement.",
            "year": 2023, "sid": f"r{i}", "sources": ["test"],
        }))
    res = gaps.detect(ps)
    assert any(g["key"] == "repro" for g in res["gaps"])


def test_directions_reference_gaps():
    ps = _build("ad") + _build("soil")
    res = gaps.detect(ps)
    dirs = gaps.directions(ps, res)
    assert len(dirs) == len(res["gaps"])
    for d in dirs:
        assert d["basis"] and d["design"] and d["risk"]


def test_concept_matrix_dimensions():
    ps = _build("ad") + _build("soil")
    res = cluster.cluster(ps, k=2)
    mat = gaps.concept_matrix(ps, res["labels"], res, top_terms=5)
    assert len(mat["matrix"]) == len(mat["clusters"])
    assert all(len(row) == len(mat["terms"]) for row in mat["matrix"])


def test_export_bibtex_and_ris():
    ps = _build("ad")
    bib = export.to_bibtex(ps)
    assert bib.count("@") == len(ps)
    assert "10.5555/ad.0" in bib
    ris = export.to_ris(ps)
    assert ris.count("TY  - ") == len(ps)
    assert "ER  - " in ris


def test_export_xlsx_is_valid_zip():
    ps = _build("ad")
    data = export.to_xlsx(ps)
    assert data[:2] == b"PK"
    assert len(data) > 4000


def test_report_markdown_contains_sections():
    ps = _build("ad") + _build("soil")
    res = cluster.cluster(ps, k=2)
    gap_res = gaps.detect(ps)
    md = export.report_markdown(
        ps, topic="test", meta={"query": "q", "sources": ["test"]},
        cluster_res=res, curated=cluster.curate(ps), gap_res=gap_res,
        directions=gaps.directions(ps, gap_res),
    )
    for heading in ("## 一、本次检索", "## 二、研究方向分布", "## 四、逐篇结构化摘要", "### 方法说明"):
        assert heading in md


def test_library_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    ps = _build("ad")[:2]
    assert library.save(ps, group="AD", tags="biomarker") == 2
    assert library.save(ps, group="AD", tags="imaging") == 0
    items = library.list_papers(group="AD")
    assert len(items) == 2
    assert "imaging" in items[0]["_tags"]
    library.update(ps[0]["sid"], note="核心文献", state="重点")
    item = library.list_papers(q="核心文献")[0]
    assert item["_note"] == "核心文献"
    assert item["_state"] == "重点"
    assert library.stats()["papers"] == 2
    assert library.remove([ps[0]["sid"]]) == 1
    assert library.stats()["papers"] == 1


def test_dedupe_summary_counts():
    a = _build("ad")[0]
    b = dict(a)
    b["sources"] = ["openalex"]
    b["sid"] = "dup"
    merged = dedupe.dedupe_papers([a, b])["papers"]
    summ = dedupe.duplicate_summary(merged)
    assert summ["total"] == 1
    assert summ["multi_source"] == 1
