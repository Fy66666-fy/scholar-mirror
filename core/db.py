"""统一数据层：一个 SQLite 文件，九张表。

为什么单独抽一层：v0.1 只有文献库，直接写在 library.py 里；到了工作台阶段，
项目、里程碑、笔记、画像、活动流都要落库，如果每个模块各开一个连接、各写一份
schema，迁移就会变成灾难。

约定：
- 所有模块通过 `connect()` 拿连接，不自己拼路径 —— 测试只需要改 `db.DB_PATH`；
- 表结构用 `CREATE TABLE IF NOT EXISTS` 增量演进，不引入迁移框架（单人本地工具，
  加列用 `ALTER TABLE` 兜底，见 `_ensure_columns`）；
- 时间统一存 unix 时间戳（float），展示层再格式化。
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "mirror.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

SCHEMA = """
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

CREATE TABLE IF NOT EXISTS interests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    keywords TEXT DEFAULT '',
    discipline TEXT DEFAULT '通用 / 跨学科',
    weight REAL DEFAULT 1.0,
    note TEXT DEFAULT '',
    created_at REAL
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    question TEXT DEFAULT '',
    description TEXT DEFAULT '',
    status TEXT DEFAULT '进行中',
    created_at REAL,
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS project_papers (
    project_id INTEGER NOT NULL,
    sid TEXT NOT NULL,
    role TEXT DEFAULT '核心',
    added_at REAL,
    PRIMARY KEY (project_id, sid)
);

CREATE TABLE IF NOT EXISTS milestones (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    due TEXT DEFAULT '',
    done INTEGER DEFAULT 0,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sid TEXT DEFAULT '',
    project_id INTEGER DEFAULT 0,
    kind TEXT DEFAULT '笔记',
    text TEXT NOT NULL,
    quote TEXT DEFAULT '',
    created_at REAL
);

CREATE TABLE IF NOT EXISTS activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    detail TEXT DEFAULT '',
    sid TEXT DEFAULT '',
    created_at REAL
);

CREATE INDEX IF NOT EXISTS idx_papers_group ON papers(group_name);
CREATE INDEX IF NOT EXISTS idx_notes_sid ON notes(sid);
CREATE INDEX IF NOT EXISTS idx_pp_project ON project_papers(project_id);
CREATE INDEX IF NOT EXISTS idx_ms_project ON milestones(project_id);
CREATE INDEX IF NOT EXISTS idx_activity_time ON activity(created_at);
"""

# 旧库升级用：缺哪列补哪列（SQLite 的 ADD COLUMN 很便宜，也不需要重建表）
_EXPECTED = {
    "papers": {
        "group_name": "TEXT DEFAULT ''", "tags": "TEXT DEFAULT ''",
        "note": "TEXT DEFAULT ''", "state": "TEXT DEFAULT '未读'", "saved_at": "REAL",
    },
    "searches": {"discipline": "TEXT DEFAULT ''", "sources": "TEXT DEFAULT ''",
                 "n_results": "INTEGER DEFAULT 0"},
}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _ensure_columns(conn)
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    for table, cols in _EXPECTED.items():
        try:
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        except sqlite3.Error:
            continue
        for col, decl in cols.items():
            if col not in have:
                try:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
                except sqlite3.Error:
                    pass


def scalar(sql: str, args: tuple = (), default=0):
    with connect() as conn:
        row = conn.execute(sql, args).fetchone()
    if row is None:
        return default
    return row[0] if row[0] is not None else default


def rows(sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    with connect() as conn:
        return conn.execute(sql, args).fetchall()


def execute(sql: str, args: tuple = ()) -> int:
    with connect() as conn:
        cur = conn.execute(sql, args)
        return cur.lastrowid or cur.rowcount


def info() -> dict:
    """给设置页用：库文件大小、各表行数。"""
    size = DB_PATH.stat().st_size / 1024 / 1024 if DB_PATH.exists() else 0.0
    tables = ["papers", "searches", "interests", "projects", "project_papers",
              "milestones", "notes", "activity"]
    counts = {}
    for t in tables:
        try:
            counts[t] = scalar(f"SELECT COUNT(*) FROM {t}", default=0)
        except sqlite3.Error:
            counts[t] = 0
    return {"path": str(DB_PATH), "size_mb": round(size, 2), "counts": counts}
