"""导出：BibTeX / RIS / Markdown / XLSX / JSON。

导出不是「顺手做一下」的功能，而是这个工具的终点之一：
读完之后要把结果带走 —— 进 Zotero、进综述初稿、进组会汇报。
所以字段在检索阶段就尽量取全（卷期页码、团体作者、DOI、PDF 链接），
这里只做格式映射，不再补字段。
"""
from __future__ import annotations

import io
import json
import re
import time

from core import schema, summarize
from core import text as T


def _bib_key(p: dict, used: set[str]) -> str:
    au = (p.get("authors") or ["anon"])[0]
    surname = re.sub(r"[^A-Za-z\u4e00-\u9fff]", "", au.split()[-1] if au.split() else "anon")[:12] or "anon"
    word = ""
    for w in re.findall(r"[A-Za-z\u4e00-\u9fff]{3,}", p.get("title") or ""):
        if w.lower() not in {"the", "and", "for", "with", "from", "using", "based"}:
            word = w[:10]
            break
    base = f"{surname}{p.get('year') or 'nd'}{word}"
    key, i = base, 0
    while key in used:
        i += 1
        key = f"{base}{chr(96 + i)}"
    used.add(key)
    return key


def to_bibtex(papers: list[dict]) -> str:
    used: set[str] = set()
    out = []
    for p in papers:
        kind = "article"
        t = (p.get("type") or "").lower()
        if "preprint" in t or p.get("arxiv_id"):
            kind = "misc"
        elif "conference" in t or "proceedings" in t:
            kind = "inproceedings"
        fields = [
            ("title", p.get("title")),
            ("author", " and ".join(p.get("authors") or [])),
            ("journal", p.get("venue")),
            ("year", p.get("year")),
            ("doi", p.get("doi")),
            ("url", p.get("url")),
            ("eprint", p.get("arxiv_id")),
            ("abstract", T.shorten(p.get("abstract") or "", 1200)),
        ]
        body = ",\n".join(
            f"  {k} = {{{v}}}" for k, v in fields if v not in (None, "", [])
        )
        out.append(f"@{kind}{{{_bib_key(p, used)},\n{body}\n}}")
    return "\n\n".join(out)


def to_ris(papers: list[dict]) -> str:
    out = []
    for p in papers:
        lines = ["TY  - JOUR" if "preprint" not in (p.get("type") or "").lower() else "TY  - UNPB"]
        if p.get("title"):
            lines.append(f"TI  - {p['title']}")
        for a in (p.get("authors") or []):
            lines.append(f"AU  - {a}")
        if p.get("year"):
            lines.append(f"PY  - {p['year']}")
        if p.get("venue"):
            lines.append(f"JO  - {p['venue']}")
        if p.get("doi"):
            lines.append(f"DO  - {p['doi']}")
        if p.get("url"):
            lines.append(f"UR  - {p['url']}")
        if p.get("abstract"):
            lines.append(f"AB  - {T.clean_text(p['abstract'])}")
        for k in (p.get("keywords") or [])[:8]:
            lines.append(f"KW  - {k}")
        lines.append("ER  - ")
        out.append("\n".join(lines))
    return "\n\n".join(out)


def to_json(papers: list[dict]) -> str:
    return json.dumps(papers, ensure_ascii=False, indent=2)


def comparison_markdown(rows: list[dict], topic: str = "") -> str:
    head = "| # | 文献 | 年份 | 设计 | 研究问题 | 方法 | 样本 | 主要发现 | 局限 |"
    sep = "|---|---|---|---|---|---|---|---|---|"
    lines = [f"## 横向对比{f'：{topic}' if topic else ''}", "", head, sep]
    for i, r in enumerate(rows, 1):
        cells = [
            str(i),
            T.shorten(r.get("title", ""), 60).replace("|", "／"),
            str(r.get("year") or "—"),
            r.get("design", "—"),
            T.shorten(r.get("question", ""), 70).replace("|", "／") or "—",
            T.shorten(r.get("method", ""), 70).replace("|", "／") or "—",
            str(r.get("sample") or "—"),
            T.shorten(r.get("findings", ""), 90).replace("|", "／") or "—",
            T.shorten(r.get("limitation", ""), 60).replace("|", "／") or "未提及",
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _slot_text(summ: dict, slot: str) -> str:
    vals = summ["slots"][slot]["sentences"]
    return " ".join(v["text"] for v in vals) if vals else ""


def report_markdown(papers: list[dict], *, topic: str = "", meta: dict | None = None,
                    cluster_res: dict | None = None, curated: list[dict] | None = None,
                    gap_res: dict | None = None, directions: list[dict] | None = None,
                    graph: dict | None = None, bridges: list[dict] | None = None,
                    dup: dict | None = None) -> str:
    """生成一份可直接发出去的完整分析报告。"""
    meta = meta or {}
    lines: list[str] = []
    now = time.strftime("%Y-%m-%d %H:%M")
    lines.append(f"# 文献镜像分析报告：{topic or '未命名主题'}")
    lines.append("")
    lines.append(f"> 生成时间：{now}　|　文献数：{len(papers)}　|　"
                 f"数据源：{', '.join(meta.get('sources') or []) or '—'}")
    lines.append("")
    lines.append("## 一、本次检索")
    lines.append("")
    lines.append(f"- 检索式：`{meta.get('query', topic) or '—'}`")
    lines.append(f"- 学科方向：{meta.get('discipline', '—')}")
    lines.append(f"- 年份下限：{meta.get('year_from') or '不限'}")
    lines.append(f"- 原始命中：{meta.get('raw_count', len(papers))} 条，"
                 f"跨源合并后 {len(papers)} 条"
                 + (f"（合并 {dup.get('merged', 0)} 条重复）" if dup else ""))
    lines.append("")
    if cluster_res and cluster_res.get("clusters"):
        lines.append("## 二、研究方向分布")
        lines.append("")
        lines.append(f"共识别 **{cluster_res['k']}** 个方向（{cluster_res.get('method', '')}，"
                     f"轮廓系数 {cluster_res.get('silhouette', 0)}）。")
        lines.append("")
        lines.append("| 方向 | 文献数 | 年份跨度 | 主要设计 | 代表文献 |")
        lines.append("|---|---|---|---|---|")
        for c in cluster_res["clusters"]:
            yr = c.get("year_range")
            span = f"{yr[0]}–{yr[1]}" if yr else "—"
            designs = "、".join(list(c["designs"].keys())[:2])
            rep = T.shorten(c["representative"].get("title", ""), 48)
            lines.append(f"| {c['name']} | {c['size']} | {span} | {designs} | {rep} |")
        lines.append("")

    if curated:
        lines.append("## 三、精选文献")
        lines.append("")
        lines.append("精选分 = 影响力 30% + 新近度 20% + 相关度 28% + 完整度 14% + 可获得性 8%。")
        lines.append("")
        for r in curated[:10]:
            p = r["paper"]
            lines.append(f"### {r['rank']}. {p.get('title', '')}")
            lines.append("")
            lines.append(f"- 出处：{schema.venue_year(p)}")
            lines.append(f"- 作者：{schema.display_authors(p)}")
            lines.append(f"- 精选分：{r['score']}（{'、'.join(f'{k} {v}' for k, v in r['parts'].items())}）")
            if r.get("tags"):
                lines.append(f"- 标签：{' · '.join(r['tags'])}")
            lines.append(f"- 入选理由：{r.get('why', '')}")
            if p.get("doi"):
                lines.append(f"- DOI：{p['doi']}")
            lines.append("")

    lines.append("## 四、逐篇结构化摘要")
    lines.append("")
    for i, p in enumerate(papers, 1):
        s = summarize.structured(p)
        lines.append(f"### {i}. {p.get('title', '')}")
        lines.append("")
        lines.append(f"*{schema.venue_year(p)}　|　{schema.DESIGN_LABELS.get(p.get('design'), '未识别')}"
                     f"　|　完整度 {s['coverage']}/6　|　置信度 {s['confidence']}（{s['confidence_label']}）*")
        lines.append("")
        if s["one_liner"]:
            lines.append(f"**一句话**：{s['one_liner']}")
            lines.append("")
        for slot in ("question", "method", "data", "findings", "conclusion", "limitation"):
            val = _slot_text(s, slot)
            label = s["slots"][slot]["label"]
            lines.append(f"- **{label}**：{val if val else '摘要未提及'}")
        if s["numbers"]:
            lines.append(f"- **关键数值**：{'、'.join(x['value'] for x in s['numbers'][:8])}")
        lines.append("")

    if graph and graph.get("stats"):
        lines.append("## 五、关联结构")
        lines.append("")
        st = graph["stats"]
        lines.append(f"节点 {st['nodes']}、边 {st['edges']}、平均度 {st['avg_degree']}、"
                     f"连通分量 {st['components']}（最大 {st['largest_component']} 个节点）。")
        lines.append("")
        if bridges:
            lines.append("**跨方向桥梁文献**（把不同方向连起来的节点）：")
            lines.append("")
            for b in bridges:
                lines.append(f"- {b['title']}（跨簇边占比 {b['cross_ratio']}，连接 {b['clusters_linked']} 个方向）")
            lines.append("")

    if gap_res and gap_res.get("gaps"):
        lines.append("## 六、研究缺口")
        lines.append("")
        if gap_res.get("caveat"):
            lines.append(f"> ⚠️ {gap_res['caveat']}")
            lines.append("")
        for g in gap_res["gaps"]:
            lines.append(f"### [{g['severity']}] {g['title']}")
            lines.append("")
            lines.append(f"- 依据：{g['detail']}")
            lines.append(f"- 为什么算缺口：{g['why']}")
            lines.append(f"- 建议：{g['suggestion']}")
            if g.get("evidence"):
                lines.append("- 证据原文：")
                for e in g["evidence"][:3]:
                    lines.append(f"  - 《{T.shorten(e['title'], 60)}》{e.get('year') or ''}："
                                 f"{T.shorten(e.get('quote') or '', 120)}")
            lines.append("")

    if directions:
        lines.append("## 七、后续研究方向建议")
        lines.append("")
        for i, d in enumerate(directions, 1):
            lines.append(f"**{i}. {d['title']}**")
            lines.append("")
            lines.append(f"- 依据缺口：{d['basis']}")
            lines.append(f"- 推荐设计：{d['design']}")
            lines.append(f"- 预期贡献：{d['contribution']}")
            lines.append(f"- 风险与替代：{d['risk']}")
            for q in d.get("questions") or []:
                lines.append(f"- 可检验问题：{q}")
            lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("### 方法说明")
    lines.append("")
    lines.append("摘要为抽取式，每一条都来自原文原句，未做改写或生成；"
                 "「完整度 x/6」统计六个槽位中抽到的数量，不代表研究质量；"
                 "缺口分析基于可核对的文本信号（样本量、随访、设计、报告规范等），"
                 "样本量少于 4 篇时不出结论；结论冲突只提示方向不一致，不判断对错。")
    lines.append("")
    return "\n".join(lines)


def to_xlsx(papers: list[dict], *, cluster_res: dict | None = None,
            gap_res: dict | None = None, curated: list[dict] | None = None) -> bytes:
    """三到四个工作表：文献汇总 / 结构化摘要 / 方向与精选 / 研究缺口。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    header_fill = PatternFill("solid", fgColor="1F4E5F")
    header_font = Font(color="FFFFFF", bold=True)

    def style_header(ws, ncol: int) -> None:
        for c in range(1, ncol + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(vertical="center")
        ws.freeze_panes = "A2"

    def autofit(ws, widths: list[int]) -> None:
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

    ws = wb.active
    ws.title = "文献汇总"
    cols = ["标题", "作者", "年份", "来源", "类型", "研究设计", "被引", "DOI", "开放获取", "链接", "来源库"]
    ws.append(cols)
    for p in papers:
        ws.append([
            p.get("title", ""), schema.display_authors(p, 6), p.get("year"),
            p.get("venue", ""), p.get("type", ""),
            schema.DESIGN_LABELS.get(p.get("design"), "未识别"),
            p.get("cited_by", 0), p.get("doi", ""),
            "是" if p.get("is_oa") else "否", p.get("url", ""),
            "/".join(p.get("merged_sources") or p.get("sources") or []),
        ])
    style_header(ws, len(cols))
    autofit(ws, [60, 28, 8, 32, 14, 14, 8, 30, 10, 42, 20])

    ws2 = wb.create_sheet("结构化摘要")
    cols2 = ["标题", "模板", "研究问题", "方法与设计", "数据与样本", "主要发现", "结论与意义",
             "局限与展望", "完整度", "置信度", "一句话结论"]
    ws2.append(cols2)
    for p in papers:
        s = summarize.structured(p)
        ws2.append([
            p.get("title", ""), s["template_name"],
            _slot_text(s, "question"), _slot_text(s, "method"), _slot_text(s, "data"),
            _slot_text(s, "findings"), _slot_text(s, "conclusion"), _slot_text(s, "limitation"),
            f"{s['coverage']}/6", s["confidence"], s["one_liner"],
        ])
    style_header(ws2, len(cols2))
    autofit(ws2, [50, 16, 40, 40, 34, 46, 40, 34, 10, 10, 40])

    if curated or cluster_res:
        ws3 = wb.create_sheet("方向与精选")
        cols3 = ["方向", "精选排名", "标题", "年份", "精选分", "影响力", "新近度", "相关度",
                 "完整度", "可获得性", "标签", "理由"]
        ws3.append(cols3)
        cmap = {}
        if cluster_res:
            for c in cluster_res["clusters"]:
                for sid in c["sids"]:
                    cmap[sid] = c["name"]
        for r in (curated or []):
            p = r["paper"]
            parts = r["parts"]
            ws3.append([
                cmap.get(p.get("sid"), ""), r["rank"], p.get("title", ""), p.get("year"),
                r["score"], parts.get("影响力"), parts.get("新近度"), parts.get("相关度"),
                parts.get("完整度"), parts.get("可获得性"), "、".join(r.get("tags") or []), r.get("why", ""),
            ])
        style_header(ws3, len(cols3))
        autofit(ws3, [26, 10, 52, 8, 10, 10, 10, 10, 10, 12, 22, 46])

    if gap_res and gap_res.get("gaps"):
        ws4 = wb.create_sheet("研究缺口")
        cols4 = ["严重度", "缺口", "占比/计数", "依据", "原因", "建议", "推荐设计", "可检验问题"]
        ws4.append(cols4)
        for g in gap_res["gaps"]:
            ws4.append([
                g["severity"], g["title"], g.get("share"), g.get("detail"),
                g.get("why"), g.get("suggestion"), g.get("design"),
                "\n".join(g.get("questions") or []),
            ])
        style_header(ws4, len(cols4))
        autofit(ws4, [8, 40, 12, 50, 50, 50, 28, 50])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
