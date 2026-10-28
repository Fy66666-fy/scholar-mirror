"""活动流：把用户做过的事记下来，首页才有「最近在干什么」。

不做埋点分析，只做「可回看的操作记录」。上限 500 条，超了删最旧的 ——
本地工具不需要无限历史，反而需要打开快。
"""
from __future__ import annotations

import time

from core import db

KINDS = ["检索", "收藏", "移出文献库", "阅读", "笔记", "项目", "画像", "导入", "推荐", "分析"]


def log(kind: str, detail: str = "", sid: str = "") -> None:
    with db.connect() as conn:
        conn.execute("INSERT INTO activity(kind, detail, sid, created_at) VALUES(?,?,?,?)",
                     (kind, detail[:200], sid, time.time()))
        conn.execute("DELETE FROM activity WHERE id NOT IN "
                     "(SELECT id FROM activity ORDER BY created_at DESC LIMIT 500)")


def recent(limit: int = 20, kind: str | None = None) -> list[dict]:
    if kind:
        rows = db.rows("SELECT * FROM activity WHERE kind=? ORDER BY created_at DESC LIMIT ?",
                       (kind, limit))
    else:
        rows = db.rows("SELECT * FROM activity ORDER BY created_at DESC LIMIT ?", (limit,))
    return [{"id": r["id"], "kind": r["kind"], "detail": r["detail"] or "",
             "sid": r["sid"] or "", "at": r["created_at"]} for r in rows]


def per_day(days: int = 14) -> list[tuple[str, int]]:
    """最近 N 天每天的活动条数，用于首页的小柱状图。"""
    import datetime as dt

    buckets: dict[str, int] = {}
    for r in db.rows("SELECT created_at FROM activity"):
        day = dt.date.fromtimestamp(r["created_at"]).isoformat()
        buckets[day] = buckets.get(day, 0) + 1
    today = dt.date.today()
    out = []
    for i in range(days - 1, -1, -1):
        d = (today - dt.timedelta(days=i)).isoformat()
        out.append((d, buckets.get(d, 0)))
    return out


def counts() -> dict[str, int]:
    return {r["kind"]: r["c"] for r in db.rows(
        "SELECT kind, COUNT(*) c FROM activity GROUP BY kind ORDER BY c DESC")}


def clear() -> int:
    with db.connect() as conn:
        cur = conn.execute("DELETE FROM activity")
        return cur.rowcount
