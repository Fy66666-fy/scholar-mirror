"""PubMed 适配器：生物医学领域最权威的索引（3800 万+ 条）。

走 NCBI E-utilities 两步：esearch 拿 PMID 列表，efetch 拿结构化 XML。
比 Europe PMC 多的是 MeSH 主题词（人工标引），这对「同一研究方向的归类」
很有用 —— MeSH 是受控词表，比作者关键词稳定得多。
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from core import http, schema

_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _text(node, path: str) -> str:
    el = node.find(path) if node is not None else None
    return "".join(el.itertext()).strip() if el is not None else ""


def _abstract(art: ET.Element) -> str:
    parts = []
    for ab in art.findall(".//Abstract/AbstractText"):
        label = ab.get("Label") or ""
        body = "".join(ab.itertext()).strip()
        if not body:
            continue
        parts.append(f"{label}: {body}" if label and not body.startswith(label) else body)
    return " ".join(parts)


def _year(art: ET.Element) -> int | None:
    for path in (".//JournalIssue/PubDate/Year", ".//ArticleDate/Year", ".//PubDate/Year"):
        v = _text(art, path)
        if v.isdigit():
            return int(v)
    medline = _text(art, ".//JournalIssue/PubDate/MedlineDate")
    m = re.search(r"(19|20)\d{2}", medline)
    return int(m.group(0)) if m else None


def search(query: str, *, limit: int = 25, year_from: int | None = None,
           oa_only: bool = False, lang: str | None = None, **_) -> list[dict]:
    term = query
    if lang == "zh":
        term += " AND chinese[la]"
    if year_from:
        term += f' AND ("{year_from}"[Date - Publication] : "3000"[Date - Publication])'
    if oa_only:
        term += " AND free full text[sb]"

    es = http.get_json(f"{_BASE}/esearch.fcgi", params={
        "db": "pubmed", "term": term, "retmax": min(max(limit, 1), 100),
        "retmode": "json", "sort": "relevance",
    }, ttl_kind="search")
    if not es:
        return []
    ids = ((es.get("esearchresult") or {}).get("idlist") or [])
    if not ids:
        return []

    xml_text = http.get_text(f"{_BASE}/efetch.fcgi", params={
        "db": "pubmed", "id": ",".join(ids), "retmode": "xml",
    }, ttl_kind="record")
    if not xml_text:
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    out = []
    for art in root.findall(".//PubmedArticle"):
        pmid = _text(art, ".//PMID")
        title = _text(art, ".//ArticleTitle")
        authors = []
        for a in art.findall(".//AuthorList/Author"):
            last, fore = _text(a, "LastName"), _text(a, "ForeName")
            coll = _text(a, "CollectiveName")
            if coll:
                authors.append(coll)
            elif last:
                authors.append(f"{last} {fore}".strip())
        doi, pmc = "", ""
        for aid in art.findall(".//ArticleIdList/ArticleId"):
            idtype = (aid.get("IdType") or "").lower()
            if idtype == "doi":
                doi = (aid.text or "").strip()
            elif idtype == "pmc":
                pmc = (aid.text or "").strip()
        mesh = [_text(m, "DescriptorName") for m in art.findall(".//MeshHeading")]
        pub_types = [_text(p, ".") for p in art.findall(".//PublicationType")]
        keywords = [_text(k, ".") for k in art.findall(".//Keyword")]
        journal = _text(art, ".//Journal/Title")
        volume = _text(art, ".//JournalIssue/Volume")
        issue = _text(art, ".//JournalIssue/Issue")
        pages = _text(art, ".//Pagination/MedlinePgn")
        venue = journal
        if volume:
            venue += f", {volume}"
            if issue:
                venue += f"({issue})"
            if pages:
                venue += f":{pages}"

        out.append(schema.normalize_paper({
            "title": title,
            "abstract": _abstract(art),
            "authors": authors,
            "year": _year(art),
            "venue": venue,
            "doi": doi,
            "pmid": pmid,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
            "pdf_url": f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc}/pdf/" if pmc else "",
            "type": "review" if any("Review" in p for p in pub_types) else "article",
            "fields": [m for m in mesh if m][:8],
            "keywords": keywords[:10],
            "is_oa": bool(pmc),
            "source": "pubmed",
            "extra": {"pmc": pmc, "pub_types": pub_types},
        }))
    return out
