"""文献导入：BibTeX / RIS / JSON。

为什么要有：真实的研究者手上一定已经有一堆从 Zotero、EndNote、知网导出的文件。
工作台如果不能把「已有资产」接进来，用户就得从头再搜一遍 —— 这是最劝退的一步。

解析器是手写的，不用 bibtexparser：只要覆盖 Zotero / EndNote / Google Scholar /
知网导出的常见形态即可，少一个依赖，也方便对残缺条目做宽容处理
（缺右括号、字段跨行、作者用 and 或分号分隔，都能读）。
"""
from __future__ import annotations

import json
import re

from core import schema

_ENTRY_RE = re.compile(r"@(\w+)\s*\{\s*([^,\n]*)\s*,", re.I)


def _split_entries(text: str) -> list[tuple[str, str, str]]:
    """按 @type{key, ...} 切分，处理花括号嵌套。"""
    out = []
    i = 0
    while True:
        m = _ENTRY_RE.search(text, i)
        if not m:
            break
        kind, key = m.group(1).lower(), m.group(2).strip()
        j = m.end()
        depth = 1
        while j < len(text) and depth > 0:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        out.append((kind, key, text[m.end(): j - 1]))
        i = j
    return out


def _fields(body: str) -> dict[str, str]:
    """解析 `name = {value}` / `name = "value"`，容忍值里再套花括号。"""
    fields: dict[str, str] = {}
    pos = 0
    pat = re.compile(r"(\w+)\s*=\s*", re.I)
    while True:
        m = pat.search(body, pos)
        if not m:
            break
        name = m.group(1).lower()
        k = m.end()
        if k >= len(body):
            break
        if body[k] == "{":
            depth, j = 1, k + 1
            while j < len(body) and depth:
                if body[j] == "{":
                    depth += 1
                elif body[j] == "}":
                    depth -= 1
                j += 1
            val = body[k + 1: j - 1]
            pos = j
        elif body[k] == '"':
            j = body.find('"', k + 1)
            j = len(body) if j < 0 else j
            val = body[k + 1: j]
            pos = j + 1
        else:
            j = body.find(",", k)
            j = len(body) if j < 0 else j
            val = body[k: j]
            pos = j + 1
        fields[name] = re.sub(r"\s+", " ", val.replace("{", "").replace("}", "")).strip()
    return fields


def parse_bibtex(text: str) -> list[dict]:
    papers = []
    for kind, key, body in _split_entries(text or ""):
        f = _fields(body)
        authors = [a.strip() for a in re.split(r"\s+and\s+", f.get("author", "")) if a.strip()]
        year = f.get("year") or ""
        m = re.search(r"(19|20)\d{2}", year)
        p = schema.normalize_paper({
            "title": f.get("title", "") or key,
            "abstract": f.get("abstract", ""),
            "authors": authors,
            "year": int(m.group(0)) if m else None,
            "venue": f.get("journal") or f.get("booktitle") or f.get("publisher", ""),
            "doi": f.get("doi", ""),
            "url": f.get("url", ""),
            "type": "preprint" if kind in ("misc", "unpublished") else
                    ("conference" if kind in ("inproceedings", "conference") else "article"),
            "keywords": [k.strip() for k in re.split(r"[,;]", f.get("keywords", "")) if k.strip()],
            "source": "import",
        })
        p["sid"] = p.get("sid") or schema.make_sid(p)
        papers.append(p)
    return papers


def parse_ris(text: str) -> list[dict]:
    """RIS：每行 `TY  - 类型`，`ER  - ` 结束。作者可多行。"""
    papers = []
    cur: dict[str, list[str]] = {}
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if len(line) < 6 or line[2:6] != "  - ":
            if line.startswith("ER"):
                p = _ris_to_paper(cur)
                if p:
                    papers.append(p)
                cur = {}
            continue
        tag, val = line[:2].upper(), line[6:].strip()
        if tag == "ER":
            p = _ris_to_paper(cur)
            if p:
                papers.append(p)
            cur = {}
        elif tag == "TY":
            cur.setdefault("TY", []).append(val)
        else:
            cur.setdefault(tag, []).append(val)
    if cur:
        p = _ris_to_paper(cur)
        if p:
            papers.append(p)
    return papers


def _ris_to_paper(cur: dict[str, list[str]]) -> dict | None:
    if not cur:
        return None
    title = (cur.get("TI") or cur.get("T1") or [""])[0]
    if not title:
        return None
    year_raw = (cur.get("PY") or cur.get("Y1") or [""])[0]
    m = re.search(r"(19|20)\d{2}", year_raw)
    kind = (cur.get("TY") or ["JOUR"])[0].upper()
    p = schema.normalize_paper({
        "title": title,
        "abstract": (cur.get("AB") or cur.get("N2") or [""])[0],
        "authors": cur.get("AU", []) or cur.get("A1", []),
        "year": int(m.group(0)) if m else None,
        "venue": (cur.get("JO") or cur.get("T2") or cur.get("JA") or [""])[0],
        "doi": (cur.get("DO") or [""])[0],
        "url": (cur.get("UR") or [""])[0],
        "type": "preprint" if kind in ("UNPB", "GEN") else "article",
        "keywords": cur.get("KW", []),
        "source": "import",
    })
    p["sid"] = p.get("sid") or schema.make_sid(p)
    return p


def parse_json(text: str) -> list[dict]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    items = data if isinstance(data, list) else data.get("papers", [])
    out = []
    for it in items:
        if not isinstance(it, dict) or not it.get("title"):
            continue
        p = schema.normalize_paper(it)
        p["source"] = p.get("source") or "import"
        p["sid"] = p.get("sid") or schema.make_sid(p)
        out.append(p)
    return out


def parse_auto(text: str, filename: str = "") -> tuple[list[dict], str]:
    """按内容猜格式，返回 (文献列表, 格式名)。"""
    text = text or ""
    low = filename.lower()
    if low.endswith(".json") or text.lstrip().startswith(("[", "{")):
        return parse_json(text), "JSON"
    if "@" in text and re.search(r"@\w+\s*\{", text):
        return parse_bibtex(text), "BibTeX"
    if re.search(r"^TY\s{2}-", text, re.M):
        return parse_ris(text), "RIS"
    return [], "未知"
