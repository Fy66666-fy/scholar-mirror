"""工作台统计：把散在各表里的数据汇成一屏能看懂的数字。

原则：只读本地库，不发网络请求。首页必须秒开，不能因为要算「今日推荐」
就卡 8 秒 —— 推荐是单独的页面，首页只展示上次结果或一句引导。
"""
from __future__ import annotations

import datetime as dt
import time

from core import activity, db, library, notes, profile, reading, workspace


def _days_ago(ts: float | None) -> int | None:
    if not ts:
        return None
    return (dt.date.today() - dt.date.fromtimestamp(ts)).days


def streak() -> int:
    """连续有活动的天数（今天没活动就从昨天算起）。"""
    days = {d for d, c in activity.per_day(60) if c > 0}
    if not days:
        return 0
    today = dt.date.today()
    cur = today if today.isoformat() in days else today - dt.timedelta(days=1)
    n = 0
    while cur.isoformat() in days:
        n += 1
        cur -= dt.timedelta(days=1)
    return n


def reading_queue(limit: int = 6) -> list[dict]:
    """首页的阅读队列读待读表；队列空了才退回「在读」状态，避免首屏空着。"""
    items = reading.next_up(limit)
    if items:
        return items
    return library.list_papers(state="在读")[:limit]


def library_overview() -> dict:
    st = library.stats()
    papers = library.list_papers()
    years = [p.get("year") for p in papers if p.get("year")]
    return {
        "papers": st["papers"],
        "shelves": st["groups"],
        "states": st["states"],
        "unread": st["states"].get("未读", 0),
        "reading": st["states"].get("在读", 0),
        "done": st["states"].get("已读", 0),
        "starred": st["states"].get("重点", 0),
        "year_span": [min(years), max(years)] if years else None,
        "oa_ratio": round(sum(1 for p in papers if p.get("is_oa")) / len(papers) * 100) if papers else 0,
        "notes": sum(notes.count_by_kind().values()),
    }


def design_mix() -> dict[str, int]:
    from core import schema
    out: dict[str, int] = {}
    for p in library.list_papers():
        d = schema.DESIGN_LABELS.get(p.get("design"), "未识别")
        out[d] = out.get(d, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1])[:6])


def top_venues(limit: int = 5) -> list[tuple[str, int]]:
    counter: dict[str, int] = {}
    for p in library.list_papers():
        v = (p.get("venue") or "").strip()
        if v:
            counter[v] = counter.get(v, 0) + 1
    return sorted(counter.items(), key=lambda kv: -kv[1])[:limit]


def dashboard() -> dict:
    """首页需要的全部数据，一次取齐。"""
    lib = library_overview()
    projects = workspace.list_projects()
    return {
        "library": lib,
        "reading": reading.stats(),
        "projects": projects[:4],
        "project_stats": workspace.overview(),
        "activity": activity.recent(8),
        "activity_days": activity.per_day(14),
        "streak": streak(),
        "profile": profile.summary(),
        "coverage": profile.coverage() if profile.is_ready() else [],
        "designs": design_mix(),
        "venues": top_venues(),
        "queue": reading_queue(),
        "history": library.history(5),
        "generated_at": time.time(),
    }


def health() -> dict:
    """给设置页：库大小、表行数、缓存占用。"""
    from core import http
    files, size_mb = http.cache_size()
    info = db.info()
    return {
        "db": info,
        "cache_files": files,
        "cache_mb": round(size_mb, 2),
        "activity": len(activity.recent(1000)),
    }
