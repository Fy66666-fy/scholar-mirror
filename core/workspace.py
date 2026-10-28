"""研究项目：把「一个课题」组织起来。

一个项目 = 一个研究问题 + 一批文献 + 一组里程碑 + 若干笔记。
这是工作台和「文献管理工具」的分界线：文献库回答「我有什么」，
项目回答「我在做什么、做到哪一步了」。

项目里的文献带角色（核心 / 背景 / 方法 / 对照 / 待读），
因为同一篇文献在不同课题里的作用不一样 —— 综述里的背景文献，可能是某个项目的核心证据。
"""
from __future__ import annotations

import json
import time

from core import db

STATUSES = ["进行中", "暂停", "已完成", "归档"]
ROLES = ["核心", "背景", "方法", "对照", "待读"]


def create(name: str, question: str = "", description: str = "",
           status: str = "进行中") -> int:
    name = (name or "").strip()
    if not name:
        return 0
    now = time.time()
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO projects(name, question, description, status, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?)",
            (name, question or "", description or "", status, now, now),
        )
        pid = cur.lastrowid
    from core import activity
    activity.log("项目", f"新建项目「{name}」")
    return pid


def update(pid: int, **fields) -> None:
    allowed = {k: v for k, v in fields.items()
               if k in ("name", "question", "description", "status") and v is not None}
    if not allowed:
        return
    sets = ", ".join(f"{k}=?" for k in allowed)
    args = list(allowed.values()) + [time.time(), pid]
    with db.connect() as conn:
        conn.execute(f"UPDATE projects SET {sets}, updated_at=? WHERE id=?", args)


def delete(pid: int) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM projects WHERE id=?", (pid,))
        conn.execute("DELETE FROM project_papers WHERE project_id=?", (pid,))
        conn.execute("DELETE FROM milestones WHERE project_id=?", (pid,))


def list_projects(status: str | None = None) -> list[dict]:
    sql = "SELECT * FROM projects"
    args: tuple = ()
    if status:
        sql += " WHERE status=?"
        args = (status,)
    sql += " ORDER BY updated_at DESC"
    out = []
    for r in db.rows(sql, args):
        pid = r["id"]
        total = db.scalar("SELECT COUNT(*) FROM milestones WHERE project_id=?", (pid,), default=0)
        done = db.scalar("SELECT COUNT(*) FROM milestones WHERE project_id=? AND done=1",
                         (pid,), default=0)
        npapers = db.scalar("SELECT COUNT(*) FROM project_papers WHERE project_id=?", (pid,), default=0)
        nnotes = db.scalar("SELECT COUNT(*) FROM notes WHERE project_id=?", (pid,), default=0)
        out.append({
            "id": pid, "name": r["name"], "question": r["question"] or "",
            "description": r["description"] or "", "status": r["status"] or "进行中",
            "created_at": r["created_at"], "updated_at": r["updated_at"],
            "papers": npapers, "notes": nnotes,
            "milestones": total, "done": done,
            "progress": round(done / total * 100) if total else 0,
        })
    return out


def get(pid: int) -> dict | None:
    for p in list_projects():
        if p["id"] == pid:
            return p
    return None


def add_paper(pid: int, sid: str, role: str = "核心") -> bool:
    if not sid:
        return False
    with db.connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM project_papers WHERE project_id=? AND sid=?", (pid, sid)
        ).fetchone()
        if exists:
            conn.execute("UPDATE project_papers SET role=? WHERE project_id=? AND sid=?",
                         (role, pid, sid))
            return False
        conn.execute("INSERT INTO project_papers(project_id, sid, role, added_at) VALUES(?,?,?,?)",
                     (pid, sid, role, time.time()))
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (time.time(), pid))
    from core import activity
    activity.log("项目", f"加入项目文献（{role}）", sid)
    return True


def remove_paper(pid: int, sid: str) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM project_papers WHERE project_id=? AND sid=?", (pid, sid))


def papers(pid: int) -> list[dict]:
    """项目里的文献，带上角色与库内元数据（不在库里时退回项目表里的 sid）。"""
    from core import library

    rows = db.rows(
        "SELECT pp.sid, pp.role, pp.added_at FROM project_papers pp "
        "WHERE pp.project_id=? ORDER BY pp.added_at DESC", (pid,)
    )
    out = []
    for r in rows:
        p = library.get(r["sid"])
        if not p:
            p = {"sid": r["sid"], "title": f"（文献库中已不存在：{r['sid']}）", "abstract": ""}
        p["_role"] = r["role"]
        p["_added_at"] = r["added_at"]
        out.append(p)
    return out


def milestones(pid: int) -> list[dict]:
    return [{"id": r["id"], "title": r["title"], "due": r["due"] or "",
             "done": bool(r["done"]), "created_at": r["created_at"]}
            for r in db.rows("SELECT * FROM milestones WHERE project_id=? ORDER BY done, id", (pid,))]


def add_milestone(pid: int, title: str, due: str = "") -> int:
    title = (title or "").strip()
    if not title:
        return 0
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO milestones(project_id, title, due, done, created_at) VALUES(?,?,?,0,?)",
            (pid, title, due or "", time.time()),
        )
        conn.execute("UPDATE projects SET updated_at=? WHERE id=?", (time.time(), pid))
        return cur.lastrowid


def toggle_milestone(mid: int, done: bool) -> None:
    with db.connect() as conn:
        conn.execute("UPDATE milestones SET done=? WHERE id=?", (1 if done else 0, mid))


def remove_milestone(mid: int) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM milestones WHERE id=?", (mid,))


def overview() -> dict:
    projects = list_projects()
    active = [p for p in projects if p["status"] == "进行中"]
    return {
        "total": len(projects),
        "active": len(active),
        "papers": sum(p["papers"] for p in projects),
        "milestones": sum(p["milestones"] for p in projects),
        "done": sum(p["done"] for p in projects),
    }


def export(pid: int) -> str:
    """项目快照（JSON），方便备份或换机器。"""
    proj = get(pid) or {}
    payload = {
        "project": proj,
        "papers": [{k: v for k, v in p.items() if not k.startswith("_")} for p in papers(pid)],
        "milestones": milestones(pid),
        "notes": [],
    }
    from core import notes
    payload["notes"] = notes.list_notes(project_id=pid, limit=500)
    return json.dumps(payload, ensure_ascii=False, indent=2)
