"""研究画像：推荐系统的唯一依据。

画像由三部分组成：
    兴趣方向   一个标签 + 一组关键词 + 学科 + 权重（比如「肠道菌群 × 代谢」权重 1.0）
    种子文献   用户标记为「这就是我做的方向」的几篇代表作
    历史行为   检索词与收藏（作为弱信号）

只让用户显式维护兴趣，是因为隐式画像在文献场景里很容易跑偏：
你今天查了一篇教学法的文章，不代表你转行做教育研究。
所以隐式信号只做加权微调，不单独决定推荐。
"""
from __future__ import annotations

import json

from core import db, library

MAX_INTERESTS = 12
_SEP = ",，;；、/|"


def list_interests() -> list[dict]:
    out = []
    for r in db.rows("SELECT * FROM interests ORDER BY weight DESC, id"):
        out.append({
            "id": r["id"], "label": r["label"] or "",
            "keywords": r["keywords"] or "", "discipline": r["discipline"] or "通用 / 跨学科",
            "weight": float(r["weight"] or 1.0), "note": r["note"] or "",
            "created_at": r["created_at"],
        })
    return out


def add_interest(label: str, keywords: str = "", discipline: str = "通用 / 跨学科",
                 weight: float = 1.0, note: str = "") -> int:
    label = (label or "").strip()
    if not label:
        return 0
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO interests(label, keywords, discipline, weight, note, created_at) "
            "VALUES(?,?,?,?,?,?)",
            (label, keywords or "", discipline, float(weight), note or "", 0.0),
        )
        iid = cur.lastrowid
    from core import activity
    activity.log("画像", f"新增研究方向「{label}」")
    return iid


def update_interest(iid: int, **fields) -> None:
    allowed = {k: v for k, v in fields.items()
               if k in ("label", "keywords", "discipline", "weight", "note") and v is not None}
    if not allowed:
        return
    sets = ", ".join(f"{k}=?" for k in allowed)
    with db.connect() as conn:
        conn.execute(f"UPDATE interests SET {sets} WHERE id=?", list(allowed.values()) + [iid])


def remove_interest(iid: int) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM interests WHERE id=?", (iid,))


def split_keywords(interest: dict) -> list[str]:
    raw = interest.get("keywords") or ""
    for sep in _SEP:
        raw = raw.replace(sep, " ")
    return [k.strip() for k in raw.split() if k.strip()]


def interest_text(interest: dict) -> str:
    """用于构建向量的文本：标签重复三次以加权，再拼关键词与备注。"""
    label = interest.get("label") or ""
    return " ".join([label, label, label] + split_keywords(interest) + [interest.get("note") or ""])


def build_query(interest: dict, extra: str = "") -> str:
    kws = split_keywords(interest)
    base = " ".join(kws) if kws else (interest.get("label") or "")
    if extra:
        base = f"{base} {extra}".strip()
    return base


def seeds() -> list[str]:
    raw = library.get_kv("profile_seeds", "[]")
    try:
        return [s for s in json.loads(raw) if isinstance(s, str)]
    except (json.JSONDecodeError, TypeError):
        return []


def set_seeds(sids: list[str]) -> None:
    library.set_kv("profile_seeds", json.dumps(list(dict.fromkeys(sids)), ensure_ascii=False))


def seed_papers() -> list[dict]:
    out = []
    for sid in seeds():
        p = library.get(sid)
        if p:
            out.append(p)
    return out


def is_ready() -> bool:
    return bool(list_interests())


def summary() -> dict:
    items = list_interests()
    disciplines = sorted({i["discipline"] for i in items if i.get("discipline")})
    kws: list[str] = []
    for i in items:
        kws.extend(split_keywords(i))
    return {
        "count": len(items),
        "disciplines": disciplines,
        "keywords": list(dict.fromkeys(kws))[:30],
        "seeds": len(seeds()),
        "weighted": sum(i["weight"] for i in items),
    }


def coverage() -> list[dict]:
    """每个方向在文献库里已有多少篇 —— 让用户看出「哪个方向读得多、哪个是空白」。"""
    from core import text as T

    papers = library.list_papers()
    out = []
    for it in list_interests():
        kws = [k.lower() for k in split_keywords(it)]
        label_tokens = set(T.tokenize(it["label"]))
        hit = 0
        for p in papers:
            blob = ((p.get("title") or "") + " " + (p.get("abstract") or "") + " "
                    + " ".join(p.get("keywords") or [])).lower()
            if any(k and k in blob for k in kws):
                hit += 1
                continue
            if label_tokens and len(label_tokens & set(T.tokenize(blob))) >= max(1, len(label_tokens) // 2):
                hit += 1
        out.append({"label": it["label"], "papers": hit,
                    "share": round(hit / len(papers) * 100) if papers else 0})
    return out
