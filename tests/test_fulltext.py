"""全文解析测试：章节切分、槽位映射、PDF 端到端、存取回路。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from core import fulltext as FT  # noqa: E402
from core import schema, summarize  # noqa: E402

PAPER_TEXT = """Abstract
We evaluated plasma p-tau217 for Alzheimer screening.

1. Introduction
Blood biomarkers are urgently needed for Alzheimer disease.

2. Methods
We enrolled 600 participants from three memory clinics.
Amyloid PET served as the reference standard.

3. Results
Plasma p-tau217 discriminated amyloid positivity with an AUC of 0.94.
Sensitivity was 86% and specificity 84%.

4. Discussion
Our findings confirm p-tau217 as a screening biomarker.

5. Limitations
Single-lab measurement and short follow-up limit generalizability.

References
[1] Smith 2020.
"""

ZH_TEXT = """摘要
探讨聚乙烯微塑料对土壤微生物群落的影响。

1 引言
微塑料污染日益受到关注。

2 材料与方法
采集农田表层土壤，设置三个浓度处理，培养 60 天。

3 结果
5% 处理组 Shannon 指数下降 0.42。

4 结论
高浓度微塑料显著改变土壤微生物群落结构。

5 局限性
培养周期较短，结论外推需谨慎。

参考文献
[1] 张三 2023.
"""


def test_split_sections_english():
    secs = FT.split_sections(PAPER_TEXT)
    assert set(secs) >= {"abstract", "introduction", "methods", "results",
                         "discussion", "limitations", "references"}
    assert "600 participants" in secs["methods"]
    assert "AUC of 0.94" in secs["results"]


def test_split_sections_chinese():
    secs = FT.split_sections(ZH_TEXT)
    assert {"introduction", "methods", "results", "conclusion", "limitations"} <= set(secs)
    assert "Shannon" in secs["results"]


def test_no_sections_when_no_headings():
    assert FT.split_sections("Just a paragraph. No headings at all here.") == {}
    assert FT.split_sections("") == {}


def test_heading_not_confused_with_body_text():
    # 正文里出现 "Results:" 开头的句子（行首、但以句号结尾/太长）不应被当标题
    text = ("1. Introduction\nThis study measures outcomes. Results: the effect was large "
            "and consistent across all subgroups of interest in every model we fitted.\n"
            "2. Methods\nWe used regression.\n3. Results\nAUC was 0.9.\n4. Discussion\nGood.\n")
    secs = FT.split_sections(text)
    assert set(secs) == {"introduction", "methods", "results", "discussion"}
    assert "Results: the effect was large" in secs["introduction"]


def test_slot_mapping():
    secs = FT.split_sections(PAPER_TEXT)
    slots = FT.slot_sections(secs)
    assert [n for n, _ in slots["question"]] == ["introduction"]
    assert [n for n, _ in slots["method"]] == ["methods"]
    assert [n for n, _ in slots["findings"]] == ["results"]
    assert [n for n, _ in slots["limitation"]] == ["limitations"]
    assert not slots["data"]          # 没有独立数据章节
    assert "references" not in FT._SLOT_OF or FT._SLOT_OF["references"] is None


def test_structured_fulltext_slots_and_missing():
    secs = FT.split_sections(PAPER_TEXT)
    p = schema.normalize_paper({"title": "p-tau217 screening", "abstract": "Brief.", "sid": "t:1"})
    s = summarize.structured_fulltext(p, secs)
    assert s["source"] == "fulltext"
    assert s["structured"] is True
    for slot in ("question", "method", "findings", "conclusion", "limitation"):
        assert s["slots"][slot]["sentences"], f"{slot} 应从全文抽到"
        for x in s["slots"][slot]["sentences"]:
            assert x["loc"].startswith("全文 · ")
    assert s["slots"]["data"]["missing"] is True     # 没有数据章节就老实标缺失
    vals = [n["value"] for n in s["numbers"]]
    assert any("0.94" in v for v in vals)


def test_fulltext_roundtrip(tmp_path):
    import core.db as db
    db.DB_PATH = tmp_path / "t.db"
    secs = FT.split_sections(PAPER_TEXT)
    FT.save("t:1", {"pages": 8, "chars": 1234, "sections": secs, "text": PAPER_TEXT}, "a.pdf")
    assert FT.has("t:1")
    row = FT.load("t:1")
    assert row["pages"] == 8 and row["file_name"] == "a.pdf"
    assert row["sections"]["methods"]
    FT.save("t:1", {"pages": 9, "chars": 2000, "sections": secs, "text": PAPER_TEXT}, "b.pdf")
    assert FT.load("t:1")["pages"] == 9, "重复保存应覆盖"
    FT.remove("t:1")
    assert not FT.has("t:1")


def _make_pdf(lines: list[str]) -> bytes:
    """手工构造最小合法 PDF（Helvetica 单页），供 pypdf 抽取。"""
    content = "BT /F1 10 Tf 12 TL 40 750 Td\n" + "".join(
        f"({l.replace('(', r'\\(').replace(')', r'\\)')}) Tj T*\n" for l in lines) + "ET"
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content.encode())} >>\nstream\n{content}\nendstream".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (b"trailer\n<< /Size " + str(len(objs) + 1).encode() + b" /Root 1 0 R >>\n"
            b"startxref\n" + str(xref).encode() + b"\n%%EOF")
    return out


def test_parse_pdf_end_to_end():
    pdf = _make_pdf([
        "Plasma p-tau217 for Alzheimer screening", "Abstract", "We evaluated plasma p-tau217.",
        "1. Introduction", "Blood biomarkers are urgently needed for Alzheimer disease.",
        "2. Methods", "We enrolled 600 participants from three memory clinics.",
        "3. Results", "The AUC was 0.94.",
        "5. Limitations", "Short follow-up limits generalizability.",
        "References", "[1] Smith 2020.",
    ])
    parsed = FT.parse_pdf_bytes(pdf)
    assert parsed["pages"] == 1 and parsed["chars"] > 200
    assert {"abstract", "introduction", "methods", "results", "limitations"} <= set(parsed["sections"])
    # 重排后标题行不粘进正文
    assert "urgently needed" in parsed["sections"]["introduction"]
    p = schema.normalize_paper({"title": "p-tau217", "abstract": "Brief.", "sid": "t:2"})
    s = summarize.structured_fulltext(p, parsed["sections"])
    assert s["slots"]["method"]["sentences"]
    assert s["slots"]["findings"]["sentences"]


def test_parse_pdf_encrypted():
    import io
    from pypdf import PdfReader
    from pypdf._page import PageObject

    # 构造一个加密 PDF 比较繁琐，这里直接验证错误路径：喂非法字节
    with pytest.raises(Exception):
        FT.parse_pdf_bytes(b"not a pdf at all")


def test_sec_label_and_stats():
    secs = FT.split_sections(PAPER_TEXT)
    stats = FT.parse_stats(secs)
    names = {zh for zh, _, _ in stats}
    assert {"方法", "结果", "引言", "局限"} <= names
    assert stats[0][2] >= stats[-1][2], "按字符数降序"
