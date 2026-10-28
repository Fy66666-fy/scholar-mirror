"""arXiv 适配器：预印本，计算机 / 物理 / 数学方向「最新进展」的主渠道。

arXiv 只提供 Atom XML，没有 JSON 接口，也没有被引次数。它的价值在时效性
（论文常在正式发表前 6–18 个月上线）与全文可得（PDF 直链），
所以查重模块里「预印本—正式版配对」主要靠它。
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from core import http, schema

_NS = {
    "a": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
    "os": "http://a9.com/-/spec/opensearch/1.1/",
}


def _parse_query(query: str) -> str:
    """把自然语言查询转成 arXiv 的检索式。

    原文直接塞进 all: 会被特殊字符（冒号、括号）打断，这里按空格拆词，
    每个词加 all:，词间 AND —— 对「找某主题的近期论文」这个场景足够。
    """
    words = [w for w in re.split(r"[\s,;]+", query.strip()) if w]
    words = [re.sub(r'[^\w\-\u4e00-\u9fff]', "", w) for w in words]
    words = [w for w in words if w]
    if not words:
        return "all:science"
    return " AND ".join(f"all:{w}" for w in words[:8])


def search(query: str, *, limit: int = 25, year_from: int | None = None,
           oa_only: bool = False, **_) -> list[dict]:
    params = {
        "search_query": _parse_query(query),
        "start": 0,
        "max_results": min(max(limit, 1), 100),
        "sortBy": "relevance",
        "sortOrder": "descending",
    }
    xml_text = http.get_text("https://export.arxiv.org/api/query", params=params, ttl_kind="search")
    if not xml_text:
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    out = []
    for entry in root.findall("a:entry", _NS):
        raw_id = (entry.findtext("a:id", "", _NS) or "").strip()
        arxiv_id = raw_id.rsplit("/abs/", 1)[-1]
        arxiv_id = re.sub(r"v\d+$", "", arxiv_id)
        title = (entry.findtext("a:title", "", _NS) or "").strip()
        summary = (entry.findtext("a:summary", "", _NS) or "").strip()
        published = (entry.findtext("a:published", "", _NS) or "")[:4]
        authors = [
            (a.findtext("a:name", "", _NS) or "").strip()
            for a in entry.findall("a:author", _NS)
        ]
        pdf_url = ""
        for link in entry.findall("a:link", _NS):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf_url = link.get("href") or ""
        cats = [c.get("term") for c in entry.findall("a:category", _NS) if c.get("term")]
        doi = (entry.findtext("arxiv:doi", "", _NS) or "").strip()
        journal_ref = (entry.findtext("arxiv:journal_ref", "", _NS) or "").strip()
        out.append(schema.normalize_paper({
            "title": re.sub(r"\s+", " ", title),
            "abstract": re.sub(r"\s+", " ", summary),
            "authors": [a for a in authors if a],
            "year": int(published) if published.isdigit() else None,
            "venue": journal_ref or "arXiv 预印本",
            "doi": doi,
            "arxiv_id": arxiv_id,
            "url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "",
            "pdf_url": pdf_url or (f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else ""),
            "type": "preprint",
            "fields": cats[:6],
            "is_oa": True,
            "source": "arxiv",
        }))
    return out
