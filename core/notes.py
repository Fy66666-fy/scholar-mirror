"""笔记与摘录。

区分两种东西，是因为它们在研究工作里的用法完全不同：
    摘录（quote）  原文里的句子，一字不改，带出处，用来写综述时引用；
    笔记（note）   自己的想法、疑问、与其他文献的关系，用来推进思考。

笔记可以挂在某篇文献上，也可以挂在某个项目上（跨文献的阶段性想法）。
"""
from __future__ import annotations

import time

from core import db

KINDS = ["笔记", "摘录", "疑问", "方法", "结论"]


def add(text: str, *, sid: str = "", project_id: int = 0, kind: str = "笔记",
        quote: str = "", log: bool = True) -> int:
    text = (text or "").strip()
    if not text:
        return 0
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO notes(sid, project_id, kind, text, quote, created_at) VALUES(?,?,?,?,?,?)",
            (sid or "", project_id or 0, kind, text, quote or "", time.time()),
        )
        nid = cur.lastrowid
    if log:
        from core import activity
        activity.log("笔记", f"{kind}：{text[:40]}", sid)
    return nid


def list_notes(*, sid: str | None = None, project_id: int | None = None,
               kind: str | None = None, q: str = "", limit: int = 200) -> list[dict]:
    sql = "SELECT * FROM notes WHERE 1=1"
    args: list = []
    if sid:
        sql += " AND sid=?"
        args.append(sid)
    if project_id:
        sql += " AND project_id=?"
        args.append(project_id)
    if kind:
        sql += " AND kind=?"
        args.append(kind)
    if q:
        sql += " AND (text LIKE ? OR quote LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    return [{"id": r["id"], "sid": r["sid"], "project_id": r["project_id"],
             "kind": r["kind"], "text": r["text"], "quote": r["quote"] or "",
             "at": r["created_at"]} for r in db.rows(sql, tuple(args))]


def update(note_id: int, text: str) -> None:
    with db.connect() as conn:
        conn.execute("UPDATE notes SET text=? WHERE id=?", (text, note_id))


def remove(note_id: int) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM notes WHERE id=?", (note_id,))


def count_by_kind() -> dict[str, int]:
    return {r["kind"]: r["c"] for r in db.rows(
        "SELECT kind, COUNT(*) c FROM notes GROUP BY kind")}


def count_for(sid: str) -> int:
    return db.scalar("SELECT COUNT(*) FROM notes WHERE sid=?", (sid,), default=0)
