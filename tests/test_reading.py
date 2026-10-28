"""待读队列测试。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, demo, library, reading


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    return db


@pytest.fixture()
def papers():
    return demo.papers()


def test_add_writes_queue_and_library(fresh_db, papers):
    added, existed = reading.add(papers[:2], priority=1, source="检索")
    assert (added, existed) == (2, 0)
    assert reading.stats()["pending"] == 2
    p = library.get(papers[0]["sid"])
    assert p["_state"] == "待读"
    assert p["_group"] == "待读"


def test_add_is_idempotent_and_updates_priority(fresh_db, papers):
    reading.add(papers[:1], priority=3, source="检索")
    added, existed = reading.add(papers[:1], priority=1, source="推荐")
    assert (added, existed) == (0, 1)
    items = reading.list_items()
    assert items[0]["_priority"] == 1
    assert items[0]["_source"] == "推荐"


def test_priority_order(fresh_db, papers):
    reading.add([papers[0]], priority=3, source="检索")
    reading.add([papers[1]], priority=1, source="检索")
    items = reading.list_items()
    assert items[0]["sid"] == papers[1]["sid"]
    assert reading.next_up(1)[0]["sid"] == papers[1]["sid"]


def test_mark_done_hides_from_queue_and_sets_read(fresh_db, papers):
    reading.add(papers[:1], priority=2)
    reading.mark_done(papers[0]["sid"])
    assert reading.list_items() == []
    assert len(reading.list_items(include_done=True)) == 1
    assert library.get(papers[0]["sid"])["_state"] == "已读"
    assert reading.stats()["done_week"] == 1
    reading.reopen(papers[0]["sid"])
    assert reading.stats()["pending"] == 1


def test_remove_keeps_library_entry(fresh_db, papers):
    reading.add(papers[:1])
    reading.remove(papers[0]["sid"])
    assert reading.stats()["pending"] == 0
    assert library.get(papers[0]["sid"])["_state"] == "未读"
    assert library.stats()["papers"] == 1


def test_stats_by_source(fresh_db, papers):
    reading.add(papers[:2], source="检索")
    reading.add(papers[2:3], source="推荐")
    st = reading.stats()
    assert st["by_source"] == {"检索": 2, "推荐": 1}
    assert st["high"] == 0


def test_has_and_sids(fresh_db, papers):
    reading.add(papers[:2])
    assert reading.has(papers[0]["sid"])
    assert reading.sids() == {p["sid"] for p in papers[:2]}


def test_set_priority(fresh_db, papers):
    reading.add(papers[:1], priority=2)
    reading.set_priority(papers[0]["sid"], 1)
    assert reading.stats()["high"] == 1
