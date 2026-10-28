"""待读队列：一个独立的阅读清单，不跟推荐混在一起。

为什么要单独一张表，而不是复用文献库的状态：

    文献库回答「我有什么」——收藏是长期资产，可能三年后还要引用；
    待读队列回答「我接下来读什么」——它是一个短期队列，读完就该消失。

把两者塞进一个字段，会出现两种别扭：收藏夹里堆满「待读」标签，
或者清空待读时把收藏一起删了。所以这里用 reading_list 单独存队列，
文献库里同步一个 `待读` 状态只是为了列表页能筛出来，队列本身是权威。

优先级用 1/2/3 三档（高/中/低），不做手工拖拽排序：
排序会随新条目不断失效，而三档优先级在几十条规模下够用且不会乱。
"""
from __future__ import annotations

import time

from core import db, library

PRIORITIES = {1: "高", 2: "中", 3: "低"}
SOURCES = ["检索", "推荐", "图谱", "聚类", "手动", "导入"]


def add(papers: list[dict], *, priority: int = 2, source: str = "手动",
        note: str = "", log: bool = True) -> tuple[int, int]:
    """加入待读。返回 (新增条数, 已存在条数)。

    同时写文献库（书架「待读」、状态「待读」），这样离线也能看到元数据；
    但队列本身以 reading_list 为准。
    """
    added = existed = 0
    now = time.time()
    for p in papers:
        sid = p.get("sid")
        if not sid:
            continue
        with db.connect() as conn:
            row = conn.execute("SELECT sid FROM reading_list WHERE sid=?", (sid,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE reading_list SET priority=?, source=?, done_at=0 WHERE sid=?",
                    (int(priority), source, sid),
                )
                existed += 1
            else:
                conn.execute(
                    "INSERT INTO reading_list(sid, priority, source, note, added_at, done_at) "
                    "VALUES(?,?,?,?,?,0)",
                    (sid, int(priority), source, note or "", now),
                )
                added += 1
        library.save([p], group="待读")
        library.update(sid, state="待读")
    if log and (added or existed):
        from core import activity
        activity.log("待读", f"加入 {added} 篇（{PRIORITIES.get(priority, '中')}优先）",
                     papers[0].get("sid", "") if papers else "")
    return added, existed


def add_one(paper: dict, *, priority: int = 2, source: str = "手动") -> bool:
    added, _ = add([paper], priority=priority, source=source)
    return added == 1


def has(sid: str) -> bool:
    return db.scalar("SELECT 1 FROM reading_list WHERE sid=? AND done_at=0", (sid,), default=0) == 1


def list_items(include_done: bool = False, priority: int | None = None) -> list[dict]:
    where, args = [], []
    if not include_done:
        where.append("r.done_at=0")
    if priority:
        where.append("r.priority=?")
        args.append(int(priority))
    sql = "SELECT r.* FROM reading_list r"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY r.done_at DESC, r.priority ASC, r.added_at DESC"
    out = []
    for r in db.rows(sql, tuple(args)):
        p = library.get(r["sid"])
        if not p:
            p = {"sid": r["sid"], "title": f"（文献库中已不存在：{r['sid']}）", "abstract": ""}
        p["_priority"] = r["priority"]
        p["_priority_label"] = PRIORITIES.get(r["priority"], "中")
        p["_source"] = r["source"] or "手动"
        p["_added_at"] = r["added_at"]
        p["_done"] = bool(r["done_at"])
        p["_note"] = r["note"] or ""
        out.append(p)
    return out


def next_up(n: int = 3) -> list[dict]:
    """首页用：高优先级在前，同优先级按加入时间倒序。"""
    items = list_items()
    items.sort(key=lambda p: (p["_priority"], -(p["_added_at"] or 0)))
    return items[:n]


def mark_done(sid: str) -> None:
    with db.connect() as conn:
        conn.execute("UPDATE reading_list SET done_at=? WHERE sid=?", (time.time(), sid))
    library.update(sid, state="已读")
    from core import activity
    activity.log("阅读", "标记读完", sid)


def reopen(sid: str) -> None:
    with db.connect() as conn:
        conn.execute("UPDATE reading_list SET done_at=0 WHERE sid=?", (sid,))
    library.update(sid, state="待读")


def set_priority(sid: str, priority: int) -> None:
    with db.connect() as conn:
        conn.execute("UPDATE reading_list SET priority=? WHERE sid=?", (int(priority), sid))


def remove(sid: str) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM reading_list WHERE sid=?", (sid,))
    p = library.get(sid)
    if p and p.get("_state") == "待读":
        library.update(sid, state="未读")


def clear_done(older_days: int = 30) -> int:
    cutoff = time.time() - older_days * 86400
    with db.connect() as conn:
        cur = conn.execute("DELETE FROM reading_list WHERE done_at>0 AND done_at<?", (cutoff,))
        return cur.rowcount


def stats() -> dict:
    pending = db.scalar("SELECT COUNT(*) FROM reading_list WHERE done_at=0", default=0)
    high = db.scalar("SELECT COUNT(*) FROM reading_list WHERE done_at=0 AND priority=1", default=0)
    week = time.time() - 7 * 86400
    added_week = db.scalar("SELECT COUNT(*) FROM reading_list WHERE added_at>?", (week,), default=0)
    done_week = db.scalar("SELECT COUNT(*) FROM reading_list WHERE done_at>?", (week,), default=0)
    by_source = {r["source"]: r["c"] for r in db.rows(
        "SELECT source, COUNT(*) c FROM reading_list WHERE done_at=0 GROUP BY source")}
    return {"pending": pending, "high": high, "added_week": added_week,
            "done_week": done_week, "by_source": by_source}


def sids() -> set[str]:
    return {r["sid"] for r in db.rows("SELECT sid FROM reading_list WHERE done_at=0")}
