"""Crossref 适配器：DOI 注册库，覆盖全学科期刊与会议论文。

优势是「元数据权威 + 参考文献常带 DOI」，几乎所有正式出版物都能查到；
短板是没有摘要的比例较高（尤其人文社科与工程会议），且不做相关度排序
之外的语义检索，所以只作为覆盖面兜底，不单独承担「发现」职责。
"""
from __future__ import annotations

import re

from core import http, schema

_JATS_RE = re.compile(r"<[^>]+>")


def _clean_jats(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"</jats:(p|sec|title)>", " ", text)
    text = re.sub(r"<jats:title>(.*?)</jats:title>", r"\1: ", text, flags=re.S)
    text = _JATS_RE.sub("", text)
    return text


def _year(item: dict) -> int | None:
    for key in ("issued", "published-print", "published-online", "created"):
        parts = ((item.get(key) or {}).get("date-parts") or [[None]])[0]
        if parts and parts[0]:
            try:
                return int(parts[0])
            except (TypeError, ValueError):
                continue
    return None


def search(query: str, *, limit: int = 25, year_from: int | None = None,
           oa_only: bool = False, **_) -> list[dict]:
    params = {
        "query.bibliographic": query,
        "rows": min(max(limit, 1), 100),
        "select": "DOI,title,abstract,author,container-title,issued,type,subject,"
                  "is-referenced-by-count,URL,link,reference,license,publisher",
        "mailto": http.polite_mailto(),
    }
    filters = []
    if year_from:
        filters.append(f"from-pub-date:{year_from}-01-01")
    if filters:
        params["filter"] = ",".join(filters)

    data = http.get_json("https://api.crossref.org/works", params=params, ttl_kind="search")
    if not data:
        return []
    items = ((data.get("message") or {}).get("items") or [])

    out = []
    for it in items:
        title = (it.get("title") or [""])[0]
        doi = it.get("DOI") or ""
        # ACS / Elsevier 的「Supporting Information」也会被 Crossref 收录成独立条目，
        # 它们的 DOI 以 .s001 之类结尾、没有摘要与年份，混进来只会制造重复。
        if not title or re.search(r"\.s\d{2,3}$", doi, re.I) or "supporting information" in title.lower():
            continue
        authors = []
        for a in (it.get("author") or []):
            name = a.get("family") or ""
            given = a.get("given") or ""
            if a.get("name"):
                authors.append(a["name"])
            elif name:
                authors.append(f"{name} {given}".strip())
        pdf = ""
        for link in (it.get("link") or []):
            if (link.get("content-type") or "").lower() == "application/pdf" and link.get("URL"):
                pdf = link["URL"]
                break
        refs = []
        for r in (it.get("reference") or []):
            if r.get("DOI"):
                refs.append(schema.normalize_doi(r["DOI"]))
        is_oa = any("creativecommons" in (l.get("URL") or "").lower() for l in (it.get("license") or []))
        out.append(schema.normalize_paper({
            "title": title,
            "abstract": _clean_jats(it.get("abstract") or ""),
            "authors": authors,
            "year": _year(it),
            "venue": (it.get("container-title") or [""])[0],
            "doi": doi,
            "url": it.get("URL") or "",
            "pdf_url": pdf,
            "type": it.get("type") or "",
            "fields": (it.get("subject") or [])[:8],
            "cited_by": it.get("is-referenced-by-count") or 0,
            "refs": refs,
            "is_oa": is_oa,
            "source": "crossref",
        }))
    return out
