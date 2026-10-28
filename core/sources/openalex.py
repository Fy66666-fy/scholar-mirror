"""OpenAlex 适配器：跨学科覆盖最广的开放元数据源（2.5 亿+ 作品）。

三个别的源给不了的东西，是这个项目要它的理由：
1. `referenced_works` —— 参考文献列表，关联图谱里的「共被引」边靠它；
2. `abstract_inverted_index` —— 绝大多数作品的摘要，虽然是以「词→位置」存的；
3. `primary_topic` / `keywords` —— 学科主题标签，聚类命名时比纯文本词更准。

注意：OpenAlex 对匿名调用有限流，必须带 mailto 进 polite pool。
"""
from __future__ import annotations

from core import http, schema


def _abstract_from_index(idx: dict | None) -> str:
    """倒排索引还原成正常语序。位置可能重复，按 position 排序后拼接。"""
    if not idx:
        return ""
    slots: list[tuple[int, str]] = []
    for word, positions in idx.items():
        if not isinstance(positions, (list, tuple)):
            continue
        for pos in positions:
            if isinstance(pos, int):
                slots.append((pos, word))
    slots.sort(key=lambda x: x[0])
    return " ".join(w for _, w in slots)


def _pdf_url(work: dict) -> str:
    for key in ("best_oa_location", "primary_location"):
        loc = work.get(key) or {}
        if loc.get("pdf_url"):
            return loc["pdf_url"]
    for loc in (work.get("locations") or []):
        if loc.get("pdf_url"):
            return loc["pdf_url"]
    return ""


def _topics(work: dict) -> list[str]:
    out: list[str] = []
    pt = work.get("primary_topic") or {}
    if pt.get("display_name"):
        out.append(pt["display_name"])
    for tp in (work.get("topics") or [])[:4]:
        if tp.get("display_name"):
            out.append(tp["display_name"])
    for c in (work.get("concepts") or [])[:6]:
        if c.get("display_name") and (c.get("score") or 0) > 0.3:
            out.append(c["display_name"])
    return out


def _keywords(work: dict) -> list[str]:
    out = []
    for kw in (work.get("keywords") or [])[:10]:
        if kw.get("display_name"):
            out.append(kw["display_name"])
    return out


def search(query: str, *, limit: int = 25, year_from: int | None = None,
           oa_only: bool = False, lang: str | None = None, **_) -> list[dict]:
    filters = []
    if lang == "zh":
        filters.append("language:zh")
    if year_from:
        filters.append(f"from_publication_date:{year_from}-01-01")
    if oa_only:
        filters.append("is_oa:true")
    params = {
        "search": query,
        "per-page": min(max(limit, 1), 100),
        "mailto": http.polite_mailto(),
        "sort": "relevance_score:desc",
    }
    if filters:
        params["filter"] = ",".join(filters)
    data = http.get_json("https://api.openalex.org/works", params=params, ttl_kind="search")
    if not data:
        return []

    out = []
    for w in data.get("results") or []:
        oid = (w.get("id") or "").rsplit("/", 1)[-1]
        authors = [
            (a.get("author") or {}).get("display_name", "")
            for a in (w.get("authorships") or [])
        ]
        loc = w.get("primary_location") or {}
        src = (loc.get("source") or {})
        refs = [r.rsplit("/", 1)[-1] for r in (w.get("referenced_works") or [])]
        out.append(schema.normalize_paper({
            "title": w.get("title") or w.get("display_name") or "",
            "abstract": _abstract_from_index(w.get("abstract_inverted_index")),
            "authors": [a for a in authors if a],
            "year": w.get("publication_year"),
            "venue": src.get("display_name") or "",
            "doi": w.get("doi") or "",
            "openalex_id": oid,
            "url": w.get("doi") or (w.get("id") or ""),
            "pdf_url": _pdf_url(w),
            "type": (w.get("type") or "").replace("-", " "),
            "fields": _topics(w),
            "keywords": _keywords(w),
            "cited_by": w.get("cited_by_count") or 0,
            "refs": refs,
            "is_oa": bool((w.get("open_access") or {}).get("is_oa")),
            "source": "openalex",
        }))
    return out
