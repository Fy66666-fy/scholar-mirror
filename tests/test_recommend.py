"""推荐漏斗测试：召回、特征、精排、重排、反馈校准。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, demo, library, profile, reading, recommend


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    return db


@pytest.fixture()
def papers():
    return demo.papers()


@pytest.fixture()
def setup(fresh_db, papers):
    library.save(papers[:2], group="AD")
    profile.add_interest("阿尔茨海默血液标志物",
                         "plasma p-tau217, amyloid, blood biomarker", "医学与生命科学", 1.0)
    profile.add_interest("微塑料与土壤微生物", "microplastics soil microbial",
                         "环境与地球科学", 0.6)
    profile.set_seeds([papers[0]["sid"]])
    return papers


def _cands(papers, skip: set[str]):
    out = [dict(p) for p in papers if p["sid"] not in skip]
    for i, p in enumerate(out):
        p["_channel"] = ["profile", "seed", "citation", "trend"][i % 4]
    return out


def test_recall_merges_channels(setup, monkeypatch):
    papers = setup
    fake = {"papers": papers[:6], "status": [{"source": "x", "label": "X", "ok": True,
                                              "count": 6, "error": "", "seconds": 0.1}],
            "elapsed": 0.1}

    monkeypatch.setattr(recommend, "search_all", lambda *a, **k: fake)
    monkeypatch.setattr(recommend.openalex, "citing", lambda *a, **k: papers[6:8])
    monkeypatch.setattr(recommend.openalex, "search", lambda *a, **k: papers[8:10])

    res = recommend.recall(per_channel=3)
    assert res["candidates"], "至少要有候选"
    channels = {p["_channel"] for p in res["candidates"]}
    assert "profile" in channels
    assert len(channels) >= 3, f"多路召回应产生多个通道，实际 {channels}"
    sids = [p["sid"] for p in res["candidates"]]
    assert len(sids) == len(set(sids)), "召回结果必须去重"


def test_features_have_eight_dims_and_citation(setup, papers):
    cands = _cands(papers, {p["sid"] for p in papers[:2]})
    # 让一篇候选引用种子文献的 DOI，检验引用特征
    seed_doi = papers[0].get("doi")
    cands[0]["refs"] = [seed_doi]
    rows = recommend.build_features(cands)
    assert set(rows[0]["feats"]) == set(recommend.PRIOR)
    cit_row = next(r for r in rows if r["paper"]["sid"] == cands[0]["sid"])
    assert cit_row["feats"]["cit"] >= 1.0


def test_fine_rank_weights_change_order(setup, papers):
    cands = _cands(papers, {p["sid"] for p in papers[:2]})
    rows = recommend.build_features(cands)
    by_recency = recommend.fine_rank(rows, {"recency": 1.0, **{k: 0.0 for k in recommend.PRIOR if k != "recency"}})
    by_oa = recommend.fine_rank(rows, {"oa": 1.0, **{k: 0.0 for k in recommend.PRIOR if k != "oa"}})
    assert by_recency[0]["feats"]["recency"] >= by_recency[-1]["feats"]["recency"]
    assert by_oa[0]["feats"]["oa"] >= by_oa[-1]["feats"]["oa"]
    assert by_recency[0]["reasons"]


def test_rerank_respects_channel_cap(setup, papers):
    cands = _cands(papers, set())
    rows = recommend.build_features(cands)
    scored = recommend.fine_rank(rows)
    for item in scored:
        item["channel"] = "profile"
    picked = recommend.rerank(scored, k=6, max_channel_ratio=0.5, explore_ratio=0.0)
    assert len(picked) <= 3, "单一通道不应超过配额"


def test_rerank_keeps_explore_slot(setup, papers):
    cands = _cands(papers, set())
    rows = recommend.build_features(cands)
    scored = recommend.fine_rank(rows)
    for item in scored:
        item["channel"] = "profile"
    scored[0]["channel"] = "explore"
    picked = recommend.rerank(scored, k=6, explore_ratio=0.2)
    assert any(x["channel"] == "explore" for x in picked)


def test_score_excludes_library_and_queue(setup, papers):
    queued = papers[3]
    reading.add([queued], source="推荐")
    cands = _cands(papers, set())
    items = recommend.score(cands, k=10)
    got = {i["paper"]["sid"] for i in items}
    assert queued["sid"] not in got, "已在待读的条目不应重复推荐"
    assert not (got & library.all_sids())


def test_feedback_events_and_weight_fit(setup, papers):
    cands = _cands(papers, set())
    items = recommend.score(cands, k=8)
    for it in items[:4]:
        recommend.log_event(it["paper"]["sid"], "save", it["channel"], it["score"], it["feats"])
    for it in items[4:]:
        recommend.log_event(it["paper"]["sid"], "skip", it["channel"], it["score"], it["feats"])
    st = recommend.feedback_stats()
    assert st["save"] == 4 and st["skip"] == len(items) - 4
    learned = recommend.fit_weights(min_events=4)
    assert learned is not None
    assert abs(sum(learned.values()) - 1.0) < 0.01
    assert all(v >= 0 for v in learned.values())


def test_fit_weights_needs_both_classes(setup, papers):
    cands = _cands(papers, set())
    items = recommend.score(cands, k=4)
    for it in items:
        recommend.log_event(it["paper"]["sid"], "save", it["channel"], it["score"], it["feats"])
    assert recommend.fit_weights(min_events=3) is None, "只有正样本时不应拟合"


def test_weights_fall_back_to_prior(setup):
    weights, note = recommend._weights()
    assert note == "默认先验"
    assert abs(sum(weights.values()) - 1.0) < 1e-6


def test_save_all_goes_to_reading(setup, papers):
    cands = _cands(papers, set())
    items = recommend.score(cands, k=3)
    added, existed = recommend.save_all(items, priority=1)
    assert added == len(items)
    assert reading.stats()["pending"] == len(items)
    assert reading.stats()["high"] == len(items)
