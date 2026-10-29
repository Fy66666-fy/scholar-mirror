"""PDF 全文解析：把「摘要没写」和「研究没做」区分开。

为什么需要这一层：缺口分析的十条规则只看摘要，正文里做了但摘要没提的
会被误判成「报告缺失」。全文解析之后，六个槽位能从正文重新抽取，
来源明确标为「全文」，缺口复核也有了依据。

设计取舍：
- 解析用 pypdf（纯文本抽取，快，零编译依赖）。版面/字体级的精确切分
  （pdfplumber）对扫描版和双栏 PDF 更准，但慢一个数量级，留给 A2 按需升级。
- 章节识别走「编号 + 已知标题词」两类正则，中英各一份。识别不出章节时
  不硬猜，返回空 sections，上层仍可对整篇正文做句子级抽取。
- 全文存 SQLite（含逐章文本）。一篇论文全文几百 KB，SQLite 完全够，
  不引入对象存储这类多余复杂度。
"""
from __future__ import annotations

import io
import json
import re
import time

from core import db
from core import text as T

# --------------------------------------------------------------------------
# 章节识别
# --------------------------------------------------------------------------
# 规范名 → 六槽位。同一槽位可以有多个章节来源，取句子时合并。
_SLOT_OF = {
    "abstract": None,        # 摘要不并入六槽位：那是摘要引擎自己的输入
    "background": "question",
    "introduction": "question",
    "related_work": "question",
    "methods": "method",
    "data": "data",
    "results": "findings",
    "discussion": "conclusion",
    "conclusion": "conclusion",
    "limitations": "limitation",
    "references": None,      # 参考文献不进任何槽位
    "acknowledgements": None,
    "funding": None,
    "supplementary": None,
    "appendix": None,
}

# 标题词表：按规范名给正则。匹配行首的独立短行才算章节标题。
_HEADINGS: list[tuple[str, tuple[re.Pattern, ...]]] = [
    ("abstract", (r"^abstract\b", r"^摘\s*要$", r"^摘要[:：]?$")),
    ("background", (r"^background\b", r"^背景\b", r"^研究背景")),
    ("introduction", (r"^(introduction|general introduction)\b", r"^(引言|前言|绪论|导言)$")),
    ("related_work", (r"^(related works?|literature review|prior work)\b", r"^文献综述$", r"^相关工作$")),
    ("methods", (r"^(methods?|materials and methods|patients and methods|methods and materials|"
                 r"methodology|study design|experimental (design|section)|model and methods|"
                 r"data and methods|research (design|methods?))\b",
                 r"^(方法|材料与方法|资料与方法|对象与方法|研究方法|实验方法|实验设计|数据与方法)$")),
    ("data", (r"^(data|dataset|datasets|materials|study population|participants|"
              r"data availability|empirical (strategy|framework)|identification strategy)\b",
              r"^(数据|数据来源|研究对象|资料来源)$")),
    ("results", (r"^(results?|findings|empirical results|experimental results|"
                 r"main results|numerical results|simulation results)\b",
                 r"^(结果|研究结果|实验结果|主要发现|实证结果)$")),
    ("discussion", (r"^(discussion|interpretation)\b", r"^讨论$")),
    ("conclusion", (r"^(conclusions?|concluding remarks|summary and conclusion)\b",
                    r"^(结论|总结|结语|研究结论)$")),
    ("limitations", (r"^(limitations?|strengths and limitations|limitations and future)\b",
                     r"^(局限(性)?|不足|研究局限|局限性分析)$")),
    ("acknowledgements", (r"^acknowledg(e)?ments?\b", r"^致谢$")),
    ("funding", (r"^(funding|conflicts? of interest|competing interests|financial disclosure)\b",
                 r"^(基金|利益冲突|资金来源)$")),
    ("references", (r"^(references|bibliography|works cited|literature cited)\b",
                    r"^(参考文献|引用文献)$")),
    ("appendix", (r"^(appendix|appendices|annex)\b", r"^(附录|附件)$")),
    ("supplementary", (r"^supplementary (materials?|information|data)\b", r"^补充材料$")),
]

# 编号标题：1. Introduction / 2. Methods / 3.1 Data / 2 方法
_NUM_HEAD = re.compile(
    r"^\s*(\d+(?:\.\d+)*)[.、]?\s+(?P<name>[A-Za-z][A-Za-z \-&]{2,40}|[\u4e00-\u9fff]{2,12})\s*$"
)
_PLAIN_HEAD = re.compile(
    r"^\s*(?P<name>[A-Z][A-Za-z \-&]{2,40}|[\u4e00-\u9fff]{2,12})\s*:?\s*$"
)


def match_heading(line: str) -> str | None:
    """一行文本是不是章节标题。返回规范名，不是则 None。

    保守策略：行长 ≤ 60、不含句号结尾，命中已知标题词表才算；
    编号标题（2. Methods）放宽到直接映射。
    """
    s = line.strip()
    if not s or len(s) > 60 or s.endswith((".", "。", ";", "；", ",", "，")):
        return None
    core = s.rstrip(":：").strip()

    # 编号标题：取出文字部分去词表里查
    m = _NUM_HEAD.match(core)
    if m:
        num, name = m.group(1), m.group("name").strip()
        # 附录编号（A.1 / S1）跳过
        canonical = _canonical_of(name)
        if canonical:
            return canonical
        return None
    if re.match(r"^\d", core):
        return None

    canonical = _canonical_of(core)
    if canonical:
        return canonical

    # 全大写短行（IMRaD 排版常见：METHODS / RESULTS）
    if core.isupper() and 3 <= len(core) <= 40 and " " not in core.strip() or \
       (core.isupper() and len(core.split()) <= 4):
        return _canonical_of(core.capitalize())
    return None


def _canonical_of(name: str) -> str | None:
    low = re.sub(r"\s+", " ", name.strip().lower())
    if not low:
        return None
    for canonical, patterns in _HEADINGS:
        for pat in patterns:
            if re.match(pat, low) or re.match(pat, low.rstrip("s")):
                return canonical
    # 复数等变体：results -> result 已由上面 rstrip 处理一部分
    return None


def split_sections(text: str) -> dict[str, str]:
    """把全文切成规范章节。返回 {规范名: 章节文本}。

    必须在带换行的原始文本上调用（标题是按行识别的）；章节体内的换行
    在这里做段落重排。没识别出任何标题时返回 {} —— 宁可空着交给句子级
    抽取，也不硬猜。
    """
    if not text:
        return {}
    lines = text.splitlines()
    marks: list[tuple[int, str]] = []
    for i, line in enumerate(lines):
        h = match_heading(line)
        if h:
            # 同名章节只取第一次出现（正文里 "Results" 可能再次出现在图表标题）
            if all(h != m[1] for m in marks):
                marks.append((i, h))
    if len(marks) < 2:
        return {}
    out: dict[str, str] = {}
    for k, (start, name) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(lines)
        out[name] = _reflow("\n".join(lines[start + 1:end]))
    return out


def _reflow(text: str) -> str:
    """PDF 换行会把句子切碎：段内换行合并成空格，连字符断词接回去。
    只在章节体内用 —— 全局重排会把标题行粘进正文，标题就找不到了。"""
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    text = re.sub(r"(?<=[^\n。.!?！？])\n(?!\n)", " ", text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# --------------------------------------------------------------------------
# PDF 解析
# --------------------------------------------------------------------------
def parse_pdf_bytes(data: bytes) -> dict:
    """抽取 PDF 全文并切章节。失败抛异常，由调用方决定怎么提示。"""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:  # noqa: BLE001
            raise ValueError("PDF 已加密，无法解析") from exc
    pages: list[str] = []
    for pg in reader.pages:
        try:
            pages.append(pg.extract_text() or "")
        except Exception:  # noqa: BLE001
            pages.append("")
    raw = "\n".join(pages)
    # 章节必须在带换行的原始文本上切 —— 重排之后标题就没了
    sections = split_sections(raw)
    text = _reflow(raw)
    return {
        "pages": len(pages),
        "chars": len(text),
        "text": text,
        "sections": sections,
    }


# --------------------------------------------------------------------------
# 存取
# --------------------------------------------------------------------------
def save(sid: str, parsed: dict, file_name: str = "") -> None:
    db.execute(
        "INSERT INTO fulltext(sid, pages, chars, sections, text, file_name, added_at) "
        "VALUES(?,?,?,?,?,?,?) ON CONFLICT(sid) DO UPDATE SET pages=excluded.pages, "
        "chars=excluded.chars, sections=excluded.sections, text=excluded.text, "
        "file_name=excluded.file_name, added_at=excluded.added_at",
        (sid, parsed.get("pages", 0), parsed.get("chars", 0),
         json.dumps(parsed.get("sections") or {}, ensure_ascii=False),
         parsed.get("text", ""), file_name, time.time()),
    )


def load(sid: str) -> dict | None:
    r = db.rows("SELECT * FROM fulltext WHERE sid=?", (sid,))
    if not r:
        return None
    row = dict(r[0])
    row["sections"] = json.loads(row.get("sections") or "{}")
    return row


def has(sid: str) -> bool:
    return bool(db.rows("SELECT 1 FROM fulltext WHERE sid=?", (sid,)))


def remove(sid: str) -> None:
    db.execute("DELETE FROM fulltext WHERE sid=?", (sid,))


def slot_sections(sections: dict[str, str]) -> dict[str, list[tuple[str, str]]]:
    """规范章节 → 六槽位。返回 {slot: [(规范名, 章节文本)]}，槽位顺序与 templates.SLOTS 一致。"""
    from core import templates

    out: dict[str, list[tuple[str, str]]] = {s: [] for s in templates.SLOTS}
    for name, body in (sections or {}).items():
        slot = _SLOT_OF.get(name)
        if slot:
            out[slot].append((name, body))
    return out


def sec_label(canonical: str) -> str:
    names = {
        "abstract": "摘要", "background": "背景", "introduction": "引言",
        "related_work": "相关工作", "methods": "方法", "data": "数据",
        "results": "结果", "discussion": "讨论", "conclusion": "结论",
        "limitations": "局限", "references": "参考文献",
        "acknowledgements": "致谢", "funding": "基金", "appendix": "附录",
        "supplementary": "补充材料",
    }
    return names.get(canonical, canonical)


def parse_stats(sections: dict[str, str]) -> list[tuple[str, str, int]]:
    """给界面展示：[(中文名, 规范名, 字符数)]，按字符数降序。"""
    out = [(sec_label(k), k, len(v)) for k, v in (sections or {}).items()]
    return sorted(out, key=lambda x: -x[2])
