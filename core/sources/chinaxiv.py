"""ChinaXiv 适配器：中国科学院主办的中文预印本平台。

这是目前少数**免注册、可编程访问**的中文库，覆盖理学、工学、农学、地学、
生命科学等方向。它解决的是「中文文献一条都没有」这个问题的一部分：
正式发表的中文期刊仍要靠 Crossref（有 DOI 的那部分）与用户自己的
知网/万方导出文件（走导入通道）。

接口是 POST /api/search，body 为 {"searchText", "page", "size"}，
GET 会返回 400 —— 这一点在 core/http.py 里专门加了 post_json。
"""
from __future__ import annotations

import re

from core import http, schema

_URL = "https://chinaxiv.org/api/search"
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text) -> str:
    if not text:
        return ""
    if isinstance(text, list):
        text = " ".join(str(x) for x in text)
    text = _TAG_RE.sub(" ", str(text))
    return re.sub(r"\s+", " ", text).strip()


def _query_once(query: str, size: int) -> dict | None:
    return http.post_json(_URL, {
        "searchText": query,
        "page": 0,
        "size": size,
    }, ttl_kind="search", timeout=30,
        # 站点的 WAF 会拦带括号/URL 的长 UA，这里用短 UA；别改成全局 UA
        headers={"User-Agent": "ScholarMirror/0.1"})


def search(query: str, *, limit: int = 25, year_from: int | None = None,
           oa_only: bool = False, **_) -> list[dict]:
    size = min(max(limit, 1), 50)
    data = _query_once(query, size)
    # ChinaXiv 的检索是多词 AND，而它的库只有几十万条：
    # 「微塑料 土壤」会直接 0 条。这时退到最长的一个词再查一次，宁可召回宽一点。
    if data and not ((data.get("data") or {}).get("content")):
        words = sorted({w for w in re.split(r"[\s,，;；]+", query) if len(w) >= 2},
                       key=len, reverse=True)
        for w in words[:2]:
            data = _query_once(w, size)
            if data and ((data.get("data") or {}).get("content")):
                break
    if not data or not data.get("success"):
        return []

    out = []
    for it in ((data.get("data") or {}).get("content") or []):
        year = it.get("pubyear") or it.get("year")
        try:
            year = int(str(year)[:4]) if year else None
        except ValueError:
            year = None
        if year_from and year and year < year_from:
            continue
        authors = it.get("authors") or []
        if isinstance(authors, str):
            authors = [a.strip() for a in re.split(r"[,，;；]", authors) if a.strip()]
        # 作者字段偶尔带 "(2,3,6）" 这类上标残留，去掉
        authors = [re.sub(r"[\(（][\d,，\s]*[\)）]\s*$", "", str(a)).strip() for a in authors]
        keywords = it.get("keywords") or []
        if isinstance(keywords, str):
            keywords = [k.strip() for k in re.split(r"[,，;；]", keywords) if k.strip()]
        subjects = it.get("subjects") or it.get("simplesubjects") or []
        if isinstance(subjects, str):
            subjects = [subjects]
        pid = it.get("id") or it.get("uuid") or ""
        out.append(schema.normalize_paper({
            "title": _clean(it.get("title_str") or it.get("title")),
            "abstract": _clean(it.get("abstracts_str") or it.get("abstracts")),
            "authors": [a for a in authors if a][:30],
            "year": year,
            "venue": it.get("jtitle") or "ChinaXiv 预印本",
            "doi": it.get("doi") or "",
            "url": it.get("url") or (f"https://chinaxiv.org/abs/{pid}" if pid else ""),
            "pdf_url": it.get("fulltext") if str(it.get("fulltext") or "").startswith("http") else "",
            "type": "preprint",
            "fields": [str(s) for s in subjects][:6],
            "keywords": [str(k) for k in keywords][:10],
            "cited_by": 0,
            "is_oa": True,
            "lang": "zh",
            "source": "chinaxiv",
        }))
    return out
