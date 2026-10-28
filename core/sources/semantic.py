"""Semantic Scholar 适配器：唯一直接给「引用上下文 / 相关论文」的源。

匿名调用配额很紧（约 1 req/s，且经常直接 429），所以这里定位是
「有则更好」的增强源：拿得到就补 TLDR 摘要与引用关系，拿不到就跳过，
不影响检索结果完整性。
"""
from __future__ import annotations

from core import http, schema

_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
_FIELDS = ("title,abstract,year,authors,venue,citationCount,externalIds,"
           "openAccessPdf,fieldsOfStudy,publicationTypes,referenceCount,tldr")


def search(query: str, *, limit: int = 25, year_from: int | None = None,
           oa_only: bool = False, **_) -> list[dict]:
    params = {"query": query, "limit": min(max(limit, 1), 100), "fields": _FIELDS}
    if year_from:
        params["year"] = f"{year_from}-"
    if oa_only:
        params["openAccessPdf"] = ""     # S2 用「存在该字段」表示只要 OA
    data = http.get_json(_URL, params=params, ttl_kind="search", retries=1, timeout=20)
    if not data:
        return []

    out = []
    for r in (data.get("data") or []):
        ext = r.get("externalIds") or {}
        oa = r.get("openAccessPdf") or {}
        tldr = (r.get("tldr") or {}).get("text") or ""
        abstract = r.get("abstract") or ""
        out.append(schema.normalize_paper({
            "title": r.get("title") or "",
            "abstract": abstract,
            "authors": [a.get("name", "") for a in (r.get("authors") or [])],
            "year": r.get("year"),
            "venue": r.get("venue") or "",
            "doi": ext.get("DOI") or "",
            "arxiv_id": ext.get("ArXiv") or "",
            "pmid": ext.get("PubMed") or "",
            "url": f"https://www.semanticscholar.org/paper/{r.get('paperId')}" if r.get("paperId") else "",
            "pdf_url": oa.get("url") or "",
            "type": ((r.get("publicationTypes") or [""])[0] or "").lower(),
            "fields": (r.get("fieldsOfStudy") or [])[:8],
            "cited_by": r.get("citationCount") or 0,
            "is_oa": bool(oa.get("url")),
            "source": "semantic",
            "extra": {"tldr": tldr, "s2_id": r.get("paperId") or ""},
        }))
    return out
