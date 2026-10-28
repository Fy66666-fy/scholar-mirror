"""本地文献库：SQLite 单文件，零服务、零配置。

存三类东西：
    papers    收藏的文献（整条 JSON 落库，字段演进不影响老数据）
    searches  检索历史（用于「上次查到哪」和一键复现检索式）
    kv        轻量设置（上次用的学科、每源条数、模板选择等）

分组 + 标签 + 笔记是「课题管理」的最小可用集：
分组管课题，标签管跨课题维度（研究类型 / 方法 / 结论方向），笔记记「为什么收它」。
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "mirror.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    sid TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    group_name TEXT DEFAULT '',
    tags TEXT DEFAULT '',
    note TEXT DEFAULT '',
    state TEXT DEFAULT '未读',
    saved_at REAL
);
CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT, discipline TEXT, sources TEXT, n_results INTEGER, created_at REAL
);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT);
CREATE INDEX IF NOT EXISTS idx_papers_group ON papers(group_name);
"""


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def save(papers: list[dict], group: str = "未分组", tags: str = "", note: str = "") -> int:
    """收藏文献。已存在则只更新分组/标签，不覆盖用户笔记。"""
    n = 0
    with _conn() as conn:
        for p in papers:
            sid = p.get("sid")
            if not sid:
                continue
            row = conn.execute("SELECT sid, tags, note FROM papers WHERE sid=?", (sid,)).fetchone()
            if row:
                new_tags = _merge_tags(row["tags"], tags)
                conn.execute(
                    "UPDATE papers SET group_name=?, tags=?, data=? WHERE sid=?",
                    (group or row["group_name"] or "未分组", new_tags, json.dumps(p, ensure_ascii=False), sid),
                )
            else:
                conn.execute(
                    "INSERT INTO papers(sid, data, group_name, tags, note, state, saved_at) VALUES(?,?,?,?,?,?,?)",
                    (sid, json.dumps(p, ensure_ascii=False), group or "未分组", tags or "", note or "", "未读", time.time()),
                )
                n += 1
    return n


def _merge_tags(old: str, new: str) -> str:
    parts = [t.strip() for t in (old or "").split(",") if t.strip()]
    for t in (new or "").split(","):
        t = t.strip()
        if t and t not in parts:
            parts.append(t)
    return ",".join(parts)


def list_papers(group: str | None = None, tag: str | None = None, q: str = "") -> list[dict]:
    sql = "SELECT * FROM papers WHERE 1=1"
    args: list = []
    if group:
        sql += " AND group_name=?"
        args.append(group)
    if tag:
        sql += " AND (','||tags||',') LIKE ?"
        args.append(f"%,{tag},%")
    if q:
        sql += " AND (data LIKE ? OR note LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY saved_at DESC"
    out = []
    with _conn() as conn:
        for row in conn.execute(sql, args):
            p = json.loads(row["data"])
            p["_group"] = row["group_name"]
            p["_tags"] = [t for t in (row["tags"] or "").split(",") if t]
            p["_note"] = row["note"] or ""
            p["_state"] = row["state"] or "未读"
            p["_saved_at"] = row["saved_at"]
            out.append(p)
    return out


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
    with _conn() as conn:
        conn.execute(f"UPDATE papers SET {', '.join(sets)} WHERE sid=?", args)


def remove(sids: list[str]) -> int:
    if not sids:
        return 0
    with _conn() as conn:
        q = ",".join("?" * len(sids))
        cur = conn.execute(f"DELETE FROM papers WHERE sid IN ({q})", sids)
        return cur.rowcount


def groups() -> list[tuple[str, int]]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT group_name, COUNT(*) c FROM papers GROUP BY group_name ORDER BY c DESC"
        ).fetchall()
    return [(r["group_name"] or "未分组", r["c"]) for r in rows]


def tags() -> list[tuple[str, int]]:
    counter: dict[str, int] = {}
    with _conn() as conn:
        for row in conn.execute("SELECT tags FROM papers"):
            for t in (row["tags"] or "").split(","):
                t = t.strip()
                if t:
                    counter[t] = counter.get(t, 0) + 1
    return sorted(counter.items(), key=lambda kv: -kv[1])


def has(sid: str) -> bool:
    with _conn() as conn:
        return conn.execute("SELECT 1 FROM papers WHERE sid=?", (sid,)).fetchone() is not None


def add_history(query: str, discipline: str, sources: list[str], n_results: int) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO searches(query, discipline, sources, n_results, created_at) VALUES(?,?,?,?,?)",
            (query, discipline, ",".join(sources), n_results, time.time()),
        )
        conn.execute(
            "DELETE FROM searches WHERE id NOT IN (SELECT id FROM searches ORDER BY created_at DESC LIMIT 50)"
        )


def history(limit: int = 12) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM searches ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [{"query": r["query"], "discipline": r["discipline"],
             "sources": (r["sources"] or "").split(","), "n": r["n_results"],
             "at": r["created_at"]} for r in rows]


def get_kv(key: str, default: str = "") -> str:
    with _conn() as conn:
        row = conn.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
    return row["v"] if row else default


def set_kv(key: str, value: str) -> None:
    with _conn() as conn:
        conn.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (key, value))


def stats() -> dict:
    with _conn() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM papers").fetchone()["c"]
        g = conn.execute("SELECT COUNT(DISTINCT group_name) c FROM papers").fetchone()["c"]
        states = conn.execute("SELECT state, COUNT(*) c FROM papers GROUP BY state").fetchall()
    return {"papers": n, "groups": g, "states": {r["state"]: r["c"] for r in states}}
