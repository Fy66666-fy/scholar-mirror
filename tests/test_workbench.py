"""工作台层测试：画像、推荐、项目、笔记、活动、导入、更新日志、统计。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import (activity, changelog, db, demo, importer, library, notes,
                  profile, recommend, schema, stats, workspace)


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    return db


@pytest.fixture()
def papers():
    return demo.papers()


def test_db_schema_creates_all_tables(fresh_db):
    info = fresh_db.info()
    for table in ("papers", "searches", "interests", "projects", "project_papers",
                  "milestones", "notes", "activity"):
        assert table in info["counts"]


def test_library_save_merges_tags_and_keeps_note(fresh_db, papers):
    library.save(papers[:2], group="A", tags="x")
    library.save(papers[:2], group="A", tags="y")
    library.update(papers[0]["sid"], note="我的笔记")
    library.save(papers[:2], group="A", tags="z")
    p = library.get(papers[0]["sid"])
    assert p["_note"] == "我的笔记"
    assert set(p["_tags"]) == {"x", "y", "z"}
    assert library.stats()["papers"] == 2


def test_library_bulk_and_remove(fresh_db, papers):
    library.save(papers[:3], group="A")
    sids = [p["sid"] for p in papers[:3]]
    assert library.bulk_update(sids, state="已读") == 3
    assert library.stats()["states"].get("已读") == 3
    assert library.remove(sids[:2]) == 2
    assert library.stats()["papers"] == 1


def test_library_duplicates_detects_same_paper(fresh_db, papers):
    a = papers[0]
    b = dict(a)
    b["sid"] = "dup:1"
    b["doi"] = "10.9999/other"
    library.save([a, b], group="A")
    dups = library.duplicates(threshold=0.8)
    assert dups and dups[0]["score"] >= 0.8


def test_profile_keywords_and_summary(fresh_db):
    profile.add_interest("方向一", "plasma p-tau217, amyloid", "医学与生命科学", 1.5)
    profile.add_interest("方向二", "microplastics soil", "环境与地球科学", 0.5)
    s = profile.summary()
    assert s["count"] == 2
    assert "p-tau217" in s["keywords"]
    items = profile.list_interests()
    assert items[0]["label"] == "方向一", "权重高的排在前面"
    assert profile.split_keywords(items[0]) == ["plasma", "p-tau217", "amyloid"]


def test_profile_update_and_delete(fresh_db):
    iid = profile.add_interest("方向", "kw")
    profile.update_interest(iid, label="新名字", weight=2.0)
    assert profile.list_interests()[0]["label"] == "新名字"
    profile.remove_interest(iid)
    assert profile.list_interests() == []


def test_profile_seeds_roundtrip(fresh_db, papers):
    library.save(papers[:3], group="A")
    profile.set_seeds([p["sid"] for p in papers[:2]])
    assert len(profile.seed_papers()) == 2
    assert profile.summary()["seeds"] == 2


def test_profile_coverage(fresh_db, papers):
    library.save(papers, group="A")
    profile.add_interest("微塑料", "microplastics soil", "环境与地球科学")
    cov = profile.coverage()
    assert cov[0]["papers"] >= 1


def test_workspace_project_lifecycle(fresh_db, papers):
    library.save(papers[:3], group="A")
    pid = workspace.create("课题", "研究问题？", "背景")
    assert workspace.add_paper(pid, papers[0]["sid"], "核心")
    assert not workspace.add_paper(pid, papers[0]["sid"], "背景"), "重复加入只更新角色"
    m1 = workspace.add_milestone(pid, "里程碑一")
    workspace.add_milestone(pid, "里程碑二")
    workspace.toggle_milestone(m1, True)
    p = workspace.get(pid)
    assert p["papers"] == 1
    assert p["milestones"] == 2 and p["done"] == 1
    assert p["progress"] == 50
    assert len(workspace.papers(pid)) == 1
    assert workspace.papers(pid)[0]["_role"] == "背景"
    workspace.update(pid, status="已完成")
    assert workspace.get(pid)["status"] == "已完成"
    payload = json.loads(workspace.export(pid))
    assert payload["project"]["name"] == "课题"
    workspace.delete(pid)
    assert workspace.get(pid) is None


def test_notes_kinds_and_filter(fresh_db, papers):
    library.save(papers[:1], group="A")
    sid = papers[0]["sid"]
    notes.add("摘录一句话", sid=sid, kind="摘录", quote="原文")
    notes.add("我的判断", sid=sid, kind="笔记")
    notes.add("项目级想法", project_id=99, kind="笔记")
    assert len(notes.list_notes(sid=sid)) == 2
    assert notes.count_by_kind()["摘录"] == 1
    assert len(notes.list_notes(project_id=99)) == 1
    assert len(notes.list_notes(q="判断")) == 1


def test_activity_log_and_streak(fresh_db):
    activity.log("检索", "查了 AD")
    activity.log("收藏", "收了 3 篇")
    assert len(activity.recent(10)) == 2
    assert activity.counts()["检索"] == 1
    assert stats.streak() == 1
    days = activity.per_day(7)
    assert len(days) == 7 and days[-1][1] == 2


def test_stats_dashboard_shape(fresh_db, papers):
    library.save(papers[:4], group="A")
    profile.add_interest("方向", "microplastics")
    workspace.create("项目")
    d = stats.dashboard()
    assert d["library"]["papers"] == 4
    assert d["project_stats"]["total"] == 1
    assert "queue" in d and "activity_days" in d


def test_importer_bibtex_nested_braces(fresh_db):
    bib = """@article{a1,
  title = {A study of {DNA} methylation in {A}lzheimer},
  author = {Smith, John and Doe, Jane},
  journal = {Nature},
  year = {2020},
  doi = {10.1000/abc}
}"""
    papers = importer.parse_bibtex(bib)
    assert len(papers) == 1
    assert papers[0]["title"] == "A study of DNA methylation in Alzheimer"
    assert papers[0]["authors"] == ["Smith, John", "Doe, Jane"]
    assert papers[0]["doi"] == "10.1000/abc"
    assert papers[0]["year"] == 2020


def test_importer_ris(fresh_db):
    ris = "TY  - JOUR\nTI  - Microplastics in soil\nAU  - Zhang, L\nAU  - Meyer, A\nPY  - 2023\nDO  - 10.1000/xyz\nER  - "
    papers = importer.parse_ris(ris)
    assert len(papers) == 1
    assert papers[0]["authors"] == ["Zhang, L", "Meyer, A"]
    assert papers[0]["year"] == 2023


def test_importer_auto_detect():
    assert importer.parse_auto("@article{a, title={T}}")[1] == "BibTeX"
    assert importer.parse_auto("TY  - JOUR\nTI  - T\nER  - ")[1] == "RIS"
    assert importer.parse_auto('[{"title": "T"}]')[1] == "JSON"
    assert importer.parse_auto("hello")[1] == "未知"


def test_changelog_parse():
    rels = changelog.parse()
    assert rels and rels[0]["version"] == "0.2.0"
    assert any(s["title"] == "新增" for s in rels[0]["sections"])
    assert changelog.tone("修复") == "warn"
    assert changelog.stats()["releases"] >= 2


def test_recommend_score_prefers_matching_topic(fresh_db, papers):
    library.save(papers[:2], group="A")
    profile.add_interest("微塑料", "microplastics soil microbial", "环境与地球科学", 1.0)
    cands = [p for p in papers[3:] if p["sid"] not in library.all_sids()]
    items = recommend.score(cands, k=5)
    assert items
    top = items[0]["paper"]["title"].lower()
    assert "microplastic" in top or "soil" in top
    assert set(items[0]["parts"]) == {"相关度", "库内邻近", "种子邻近", "影响力", "时效性"}
    assert items[0]["reasons"]


def test_recommend_excludes_library_items(fresh_db, papers):
    library.save(papers[:4], group="A")
    profile.add_interest("微塑料", "microplastics soil", "环境与地球科学", 1.0)
    items = recommend.score(list(papers), k=10)
    got = {i["paper"]["sid"] for i in items}
    assert not (got & library.all_sids()), "已收藏的不应再被推荐"


def test_recommend_empty_profile_returns_error(fresh_db):
    res = recommend.recommend()
    assert res["items"] == []
    assert "画像" in res["error"]


def test_recommend_diversity_reduces_duplicates(fresh_db, papers):
    profile.add_interest("微塑料", "microplastics soil", "环境与地球科学", 1.0)
    cands = [p for p in papers if "microplastic" in (p.get("title") or "").lower()
             or "soil" in (p.get("title") or "").lower()]
    if len(cands) >= 2:
        items = recommend.score(cands, k=len(cands), diversity=0.9)
        assert len({i["paper"]["sid"] for i in items}) == len(items)


def test_settings_health(fresh_db):
    h = stats.health()
    assert "db" in h and "cache_mb" in h
