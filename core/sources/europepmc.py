"""Europe PMC 适配器：覆盖 PubMed 之外的生命科学文献，并给出开放全文标记。

相比 PubMed，它多两件事：直接返回参考文献列表（referenceList），
以及 OA 全文的 XML 地址。关联图谱在纯文本相似度之外，靠这些引用边
把「同一课题的不同分支」连起来。
"""
from __future__ import annotations

from core import http, schema

_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


def search(query: str, *, limit: int = 25, year_from: int | None = None,
           oa_only: bool = False, lang: str | None = None, **_) -> list[dict]:
    q = query
    if lang == "zh":
        q += ' AND LANG:"chi"'
    if year_from:
        q += f" AND (FIRST_PDATE:[{year_from}-01-01 TO 3000-12-31])"
    if oa_only:
        q += " AND OPEN_ACCESS:y"
    data = http.get_json(_URL, params={
        "query": q, "format": "json", "pageSize": min(max(limit, 1), 100),
        "resultType": "core", "sort": "CITED desc",
    }, ttl_kind="search")
    if not data:
        return []

    out = []
    for r in ((data.get("resultList") or {}).get("result") or []):
        refs = []
        for ref in ((r.get("referenceList") or {}).get("reference") or []):
            if ref.get("id"):
                refs.append(str(ref["id"]).lower())
        kw = [k for k in ((r.get("keywordList") or {}).get("keyword") or []) if k]
        mesh = [
            (m.get("descriptorName") or "")
            for m in ((r.get("meshHeadingList") or {}).get("meshHeading") or [])
        ]
        full_text_urls = ((r.get("fullTextUrlList") or {}).get("fullTextUrl") or [])
        pdf = ""
        for u in full_text_urls:
            if (u.get("documentStyle") or "").upper() == "PDF" and u.get("url"):
                pdf = u["url"]
                break
        venue = r.get("journalTitle") or r.get("bookOrReportDetails", {}).get("publisher") or ""
        out.append(schema.normalize_paper({
            "title": r.get("title") or "",
            "abstract": r.get("abstractText") or "",
            "authors": [a.strip() for a in (r.get("authorString") or "").split(",") if a.strip()],
            "year": r.get("pubYear"),
            "venue": venue,
            "doi": r.get("doi") or "",
            "pmid": r.get("pmid") or "",
            "url": f"https://europepmc.org/article/{r.get('source', 'MED')}/{r.get('id', '')}" if r.get("id") else "",
            "pdf_url": pdf,
            "type": (r.get("pubType") or "").lower(),
            "fields": [m for m in mesh if m][:8] or [k for k in kw][:6],
            "keywords": kw[:10],
            "cited_by": r.get("citedByCount") or 0,
            "refs": refs,
            "is_oa": (r.get("isOpenAccess") or "").upper() == "Y",
            "source": "europepmc",
            "extra": {"pmcid": r.get("pmcid") or "", "source_db": r.get("source") or ""},
        }))
    return out
