"""文献库：收藏、书架（分组）、标签、笔记、阅读状态。

v0.2 起把存储交给 core.db，本模块只负责「文献」这一块业务：
保存时合并标签而不是覆盖、导入时按 sid 去重、统计只算真实存在的条目。

分组就是书架：一个课题一个书架。标签是跨书架的维度（研究类型 / 方法 / 结论方向）。
两者分开，是因为「这个课题里哪些是 RCT」和「我所有 RCT 在哪」是两个不同的问题。
"""
from __future__ import annotations

import json
import time

from core import db


def _merge_tags(old: str, new: str) -> str:
    parts = [t.strip() for t in (old or "").split(",") if t.strip()]
    for t in (new or "").split(","):
        t = t.strip()
        if t and t not in parts:
            parts.append(t)
    return ",".join(parts)


def save(papers: list[dict], group: str = "未分组", tags: str = "", note: str = "",
         log: bool = True) -> int:
    """收藏文献。已存在则合并标签并更新分组，不覆盖用户笔记。返回新增条数。"""
    added = 0
    with db.connect() as conn:
        for p in papers:
            sid = p.get("sid")
            if not sid:
                continue
            row = conn.execute("SELECT tags, note FROM papers WHERE sid=?", (sid,)).fetchone()
            payload = json.dumps(p, ensure_ascii=False)
            if row:
                conn.execute(
                    "UPDATE papers SET group_name=?, tags=?, data=? WHERE sid=?",
                    (group or "未分组", _merge_tags(row["tags"], tags), payload, sid),
                )
            else:
                conn.execute(
                    "INSERT INTO papers(sid, data, group_name, tags, note, state, saved_at) "
                    "VALUES(?,?,?,?,?,?,?)",
                    (sid, payload, group or "未分组", tags or "", note or "", "未读", time.time()),
                )
                added += 1
    if added and log:
        from core import activity
        activity.log("收藏", f"新增 {added} 篇到「{group or '未分组'}」", papers[0].get("sid", ""))
    return added


def list_papers(group: str | None = None, tag: str | None = None, q: str = "",
                state: str | None = None) -> list[dict]:
    sql = "SELECT * FROM papers WHERE 1=1"
    args: list = []
    if group:
        sql += " AND group_name=?"
        args.append(group)
    if tag:
        sql += " AND (','||tags||',') LIKE ?"
        args.append(f"%,{tag},%")
    if state:
        sql += " AND state=?"
        args.append(state)
    if q:
        sql += " AND (data LIKE ? OR note LIKE ? OR tags LIKE ?)"
        args += [f"%{q}%", f"%{q}%", f"%{q}%"]
    sql += " ORDER BY saved_at DESC"
    out = []
    with db.connect() as conn:
        for row in conn.execute(sql, args):
            p = json.loads(row["data"])
            p["_group"] = row["group_name"]
            p["_tags"] = [t for t in (row["tags"] or "").split(",") if t]
            p["_note"] = row["note"] or ""
            p["_state"] = row["state"] or "未读"
            p["_saved_at"] = row["saved_at"]
            out.append(p)
    return out


def get(sid: str) -> dict | None:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM papers WHERE sid=?", (sid,)).fetchone()
    if not row:
        return None
    p = json.loads(row["data"])
    p["_group"] = row["group_name"]
    p["_tags"] = [t for t in (row["tags"] or "").split(",") if t]
    p["_note"] = row["note"] or ""
    p["_state"] = row["state"] or "未读"
    return p


def update(sid: str, *, group: str | None = None, tags: str | None = None,
           note: str | None = None, state: str | None = None) -> None:
    sets, args = [], []
    for col, val in (("group_name", group), ("tags", tags), ("note", note), ("state", state)):
        if val is not None:
            sets.append(f"{col}=?")
            args.append(val)
    if not sets:
        return
    args.append(sid)
    with db.connect() as conn:
        conn.execute(f"UPDATE papers SET {', '.join(sets)} WHERE sid=?", args)


def bulk_update(sids: list[str], **fields) -> int:
    if not sids:
        return 0
    allowed = {k: v for k, v in fields.items()
               if k in ("group_name", "tags", "state") and v is not None}
    if not allowed:
        return 0
    sets = ", ".join(f"{k}=?" for k in allowed)
    args = list(allowed.values())
    with db.connect() as conn:
        q = ",".join("?" * len(sids))
        cur = conn.execute(f"UPDATE papers SET {sets} WHERE sid IN ({q})", args + sids)
        return cur.rowcount


def remove(sids: list[str], log: bool = True) -> int:
    if not sids:
        return 0
    with db.connect() as conn:
        q = ",".join("?" * len(sids))
        cur = conn.execute(f"DELETE FROM papers WHERE sid IN ({q})", sids)
        n = cur.rowcount
    if n and log:
        from core import activity
        activity.log("移出文献库", f"移除 {n} 篇")
    return n


def groups() -> list[tuple[str, int]]:
    rows = db.rows(
        "SELECT group_name, COUNT(*) c FROM papers GROUP BY group_name ORDER BY c DESC"
    )
    return [(r["group_name"] or "未分组", r["c"]) for r in rows]


def tags() -> list[tuple[str, int]]:
    counter: dict[str, int] = {}
    for row in db.rows("SELECT tags FROM papers"):
        for t in (row["tags"] or "").split(","):
            t = t.strip()
            if t:
                counter[t] = counter.get(t, 0) + 1
    return sorted(counter.items(), key=lambda kv: -kv[1])


def has(sid: str) -> bool:
    return db.scalar("SELECT 1 FROM papers WHERE sid=?", (sid,), default=0) == 1


def all_sids() -> set[str]:
    return {r["sid"] for r in db.rows("SELECT sid FROM papers")}


def add_history(query: str, discipline: str, sources: list[str], n_results: int) -> None:
    with db.connect() as conn:
        conn.execute(
            "INSERT INTO searches(query, discipline, sources, n_results, created_at) VALUES(?,?,?,?,?)",
            (query, discipline, ",".join(sources), n_results, time.time()),
        )
        conn.execute(
            "DELETE FROM searches WHERE id NOT IN "
            "(SELECT id FROM searches ORDER BY created_at DESC LIMIT 60)"
        )


def history(limit: int = 12) -> list[dict]:
    out = []
    for r in db.rows("SELECT * FROM searches ORDER BY created_at DESC LIMIT ?", (limit,)):
        out.append({"query": r["query"], "discipline": r["discipline"],
                    "sources": (r["sources"] or "").split(","), "n": r["n_results"],
                    "at": r["created_at"]})
    return out


def get_kv(key: str, default: str = "") -> str:
    with db.connect() as conn:
        row = conn.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
    return row["v"] if row else default


def set_kv(key: str, value: str) -> None:
    with db.connect() as conn:
        conn.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
                     (key, value))


def stats() -> dict:
    n = db.scalar("SELECT COUNT(*) FROM papers", default=0)
    g = db.scalar("SELECT COUNT(DISTINCT group_name) FROM papers", default=0)
    states = {r["state"]: r["c"] for r in db.rows(
        "SELECT state, COUNT(*) c FROM papers GROUP BY state")}
    return {"papers": n, "groups": g, "states": states}


def duplicates(threshold: float = 0.85) -> list[dict]:
    """库内查重：同一篇被不同源反复收藏、或预印本与正式版并存。"""
    from core import dedupe
    papers = list_papers()
    if len(papers) < 2:
        return []
    return dedupe.near_duplicates(papers, threshold=threshold)


def yearly_counts() -> list[tuple[int, int]]:
    out: dict[int, int] = {}
    for p in list_papers():
        y = p.get("year")
        if y:
            out[y] = out.get(y, 0) + 1
    return sorted(out.items())
