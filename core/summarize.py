"""结构化摘要引擎。

做法是「线索加权抽取」，不调用大模型：
1. 先看摘要有没有结构化小标题（Background/Methods/Results/Conclusions 或
   中文的 目的/方法/结果/结论）。有就直接按段归属，准确率最高。
2. 没有小标题，就按「线索词 + 句位置 + 数字密度」给每句话算六个槽位的
   亲和度，再全局贪心分配（一句话只归一个槽，避免同一句在四个栏里重复出现）。
3. 分配完还有空槽，用兜底规则补：结果槽优先给含数字的句子，结论槽给末句。
4. 每个槽都保留原句与句序号，界面上可以点回原文核对 —— 抽取式摘要的
   可信度全靠这一点，不能只给一句「模型总结」。

输出的槽位是统一的（question/method/data/findings/conclusion/limitation），
所以不同学科、不同模板的论文可以直接横向对比。
"""
from __future__ import annotations

import re

from core import schema, templates
from core import text as T

_STRUCT_LABELS = [
    ("question", ("background", "introduction", "objective", "aim", "purpose", "context",
                  "rationale", "研究背景", "背景", "目的", "引言")),
    ("method", ("methods", "method", "materials and methods", "methodology", "approach",
                "design", "方法", "资料与方法", "研究方法")),
    ("data", ("data", "participants", "sample", "setting", "数据", "对象", "样本")),
    ("findings", ("results", "findings", "result", "结果", "主要结果")),
    ("conclusion", ("conclusions", "conclusion", "discussion", "implications", "结论", "讨论")),
    ("limitation", ("limitations", "limitation", "局限", "不足")),
]

_STRUCT_RE = re.compile(
    r"(?P<label>background|introduction|objective|aim|purpose|methods?|materials and methods|"
    r"methodology|results?|findings?|conclusions?|discussion|limitations?|"
    r"研究背景|背景|目的|方法|资料与方法|结果|结论|讨论|局限|不足)\s*[:：]\s*",
    re.I,
)


def split_structured(abstract: str) -> dict[str, list[str]]:
    """按结构化小标题切段。返回 {slot: [段落文本]}，无小标题时返回 {}。"""
    if not abstract:
        return {}
    marks = list(_STRUCT_RE.finditer(abstract))
    if len(marks) < 2:
        return {}
    # 小标题必须出现在开头 40% 之前，否则可能是正文里偶然出现的 "Results:"
    if marks[0].start() > max(60, len(abstract) * 0.4):
        return {}
    out: dict[str, list[str]] = {}
    for i, m in enumerate(marks):
        label = m.group("label").lower()
        start = m.end()
        end = marks[i + 1].start() if i + 1 < len(marks) else len(abstract)
        body = abstract[start:end].strip(" ;；,，")
        if not body:
            continue
        slot = _label_to_slot(label)
        out.setdefault(slot, []).append(body)
    return out


def _label_to_slot(label: str) -> str:
    for slot, names in _STRUCT_LABELS:
        if label in names:
            return slot
    return "findings"


# 句位置先验：不同槽在摘要里的典型位置
def _position_prior(slot: str, pos: float) -> float:
    if slot == "question":
        return 1.1 if pos < 0.28 else 0.0
    if slot == "method":
        return 0.45 if 0.12 <= pos <= 0.62 else 0.0
    if slot == "data":
        return 0.25 if 0.10 <= pos <= 0.65 else 0.0
    if slot == "findings":
        return 0.55 if 0.30 <= pos <= 0.90 else 0.0
    if slot == "conclusion":
        return 1.3 if pos >= 0.68 else 0.0
    if slot == "limitation":
        return 0.75 if pos >= 0.55 else 0.0
    return 0.0


def _cue_hits(sentence: str, cues: tuple[str, ...]) -> tuple[int, list[str]]:
    low = sentence.lower()
    hits = [c for c in cues if c in low]
    return len(hits), hits


def score_sentences(sentences: list[str], template_key: str) -> list[dict[str, float]]:
    cues = templates.cues_for(template_key)
    n = max(len(sentences), 1)
    rows = []
    for i, s in enumerate(sentences):
        pos = i / n
        low = s.lower()
        nums = T.extract_numbers(s)
        num_types = {x["type"] for x in nums}
        row: dict[str, float] = {}
        for slot in templates.SLOTS:
            hits, _ = _cue_hits(low, cues[slot])
            score = min(hits, 3) * 1.0 + _position_prior(slot, pos)
            if slot == "findings" and nums:
                score += min(len(num_types), 3) * 0.7
            if slot == "data" and re.search(r"\b(n\s*=\s*\d|\d+\s*(?:例|名|位))", low):
                score += 1.0
            if len(s) < 40:
                score -= 0.35
            row[slot] = round(score, 3)
        rows.append(row)
    return rows


def _assign(sentences: list[str], scores: list[dict[str, float]],
            max_per_slot: int = 2, threshold: float = 1.0) -> dict[str, list[int]]:
    """全局贪心分配：按 (分数降序) 依次认领，句子与槽位名额都是独占的。"""
    cands = []
    for i, row in enumerate(scores):
        for slot, sc in row.items():
            if sc >= threshold:
                cands.append((sc, i, slot))
    cands.sort(key=lambda x: (-x[0], x[1], templates.SLOTS.index(x[2])))
    used_sent: set[int] = set()
    slots: dict[str, list[int]] = {s: [] for s in templates.SLOTS}
    for sc, i, slot in cands:
        if i in used_sent or len(slots[slot]) >= max_per_slot:
            continue
        slots[slot].append(i)
        used_sent.add(i)
    for slot in slots:
        slots[slot].sort()
    return slots


# 无小标题、无线索时的位置兜底：学术摘要的叙述顺序高度稳定，
# 按区间取「未被占用的最佳句」比留空更有用，但要标成 inferred（推断）。
_ZONES = {
    "question": (0.0, 0.30),
    "method": (0.20, 0.58),
    "data": (0.20, 0.62),
    "findings": (0.42, 0.88),
    "conclusion": (0.78, 1.01),
}


def _infer_by_zone(sentences: list[str], slots: dict[str, list[int]],
                   scores: list[dict[str, float]]) -> set[str]:
    used = {i for idx in slots.values() for i in idx}
    inferred: set[str] = set()
    n = max(len(sentences), 1)
    for slot, (lo, hi) in _ZONES.items():
        if slots[slot] or len(sentences) < 4:
            continue
        best, best_sc = None, -1e9
        for i, s in enumerate(sentences):
            if i in used:
                continue
            pos = i / n
            if not (lo <= pos <= hi):
                continue
            sc = scores[i].get(slot, 0.0)
            # 结果句常含 "were measured" 这类方法词，容易串到方法槽。
            # 若该句更像「主要发现」，就不拿来填方法与数据。
            if slot in ("method", "data") and scores[i].get("findings", 0) > sc + 0.4:
                continue
            if sc > best_sc:
                best, best_sc = i, sc
        if best is not None:
            slots[slot].append(best)
            used.add(best)
            inferred.add(slot)

    # 位置兜底仍失败时（摘要句子很少、分区里没有空闲句），
    # 退一步取「该方法槽得分最高且未被占用」的句子，不再限制位置。
    for slot in ("method", "data"):
        if slots[slot] or len(sentences) < 3:
            continue
        cand = [(scores[i].get(slot, 0.0), i) for i in range(len(sentences)) if i not in used]
        if not cand:
            continue
        sc, i = max(cand)
        if sc >= 0.4:
            slots[slot].append(i)
            used.add(i)
            inferred.add(slot)
    return inferred


def _fallback_fill(sentences: list[str], slots: dict[str, list[int]]) -> None:
    used = {i for idx in slots.values() for i in idx}
    if not sentences:
        return
    if not slots["findings"]:
        best, best_n = None, -1
        for i, s in enumerate(sentences):
            if i in used:
                continue
            k = len({x["type"] for x in T.extract_numbers(s)})
            if k > best_n:
                best, best_n = i, k
        if best is not None and best_n >= 1:
            slots["findings"].append(best)
            used.add(best)
    if not slots["conclusion"]:
        for i in range(len(sentences) - 1, -1, -1):
            if i not in used:
                slots["conclusion"].append(i)
                used.add(i)
                break
    if not slots["question"]:
        for i in range(len(sentences)):
            if i not in used:
                slots["question"].append(i)
                used.add(i)
                break


def _locate(text: str, sentence: str) -> dict:
    idx = text.find(sentence)
    return {"start": idx, "end": idx + len(sentence) if idx >= 0 else -1}


def _one_liner(slots: dict[str, list[str]]) -> str:
    def first(slot: str) -> str:
        vals = slots.get(slot) or []
        return vals[0] if vals else ""

    text = first("conclusion") or first("findings")
    if not text:
        return ""
    text = re.sub(
        r"^(in conclusion|in summary|overall|taken together|we conclude that|"
        r"these findings suggest that|our (?:findings|results) (?:suggest|indicate|show) that|"
        r"综上(?:所述)?|结论[:：]?|本研究(?:认为|发现)|研究(?:结果)?表明)[,，:：\s]*",
        "", text.strip(), flags=re.I,
    )
    text = T.shorten(text, 96)
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text


def structured(paper: dict, template_key: str | None = None, max_per_slot: int = 2) -> dict:
    """单篇结构化摘要。这是整个系统最核心的一次「理解」。"""
    tpl_key = template_key or templates.auto_template(paper)
    abstract = paper.get("abstract") or ""
    title = paper.get("title") or ""
    body = abstract or ""
    sentences = T.split_sentences(body) if body else []
    section_map = split_structured(body)

    slot_sents: dict[str, list[str]] = {s: [] for s in templates.SLOTS}
    inferred_slots: set[str] = set()
    if section_map:
        for slot, paras in section_map.items():
            for para in paras:
                slot_sents[slot].extend(T.split_sentences(para))
        # 结构化摘要里未被任何小标题覆盖的句子，交给线索引擎补
        covered = " ".join(" ".join(v) for v in slot_sents.values())
        rest = [s for s in sentences if s not in covered]
        if rest:
            sc = score_sentences(rest, tpl_key)
            extra = _assign(rest, sc, max_per_slot=1, threshold=1.4)
            for slot, idxs in extra.items():
                slot_sents[slot].extend(rest[i] for i in idxs)
    else:
        scores = score_sentences(sentences, tpl_key)
        assign = _assign(sentences, scores, max_per_slot=max_per_slot)
        _fallback_fill(sentences, assign)
        inferred_slots = _infer_by_zone(sentences, assign, scores)
        for slot, idxs in assign.items():
            slot_sents[slot] = [sentences[i] for i in idxs]

    out_slots = {}
    filled = 0
    for slot in templates.SLOTS:
        vals = slot_sents.get(slot) or []
        vals = [v for v in vals if len(v) > 8][:max_per_slot]
        if vals:
            filled += 1
        out_slots[slot] = {
            "label": templates.slot_label(tpl_key, slot),
            "sentences": [{"text": v, "loc": _locate(body, v)} for v in vals],
            "missing": not vals,
            "inferred": slot in inferred_slots,
        }

    numbers = T.extract_numbers(body)
    coverage = filled / len(templates.SLOTS)
    structured_flag = bool(section_map)
    conf = 0
    conf += coverage * 45
    conf += 15 if structured_flag else 0
    conf += min(len(numbers), 6) * 3
    conf += min(len(body) / 1400, 1.0) * 15
    if len(body) < 120:
        conf *= 0.6
    confidence = int(round(min(conf, 98)))

    return {
        "sid": paper.get("sid", ""),
        "title": title,
        "template": tpl_key,
        "template_name": templates.get(tpl_key)["name"],
        "structured": structured_flag,
        "slots": out_slots,
        "one_liner": _one_liner({s: [x["text"] for x in out_slots[s]["sentences"]] for s in out_slots}),
        "numbers": numbers,
        "coverage": filled,
        "coverage_pct": int(round(coverage * 100)),
        "confidence": confidence,
        "confidence_label": "高" if confidence >= 70 else ("中" if confidence >= 45 else "低"),
        "sentence_count": len(sentences),
        "chars": len(body),
        "has_abstract": bool(body),
        "source": "abstract" if body else "title_only",
    }


def batch(papers: list[dict], template_key: str | None = None) -> list[dict]:
    return [structured(p, template_key) for p in papers]


def structured_fulltext(paper: dict, sections: dict[str, str],
                        template_key: str | None = None,
                        max_per_slot: int = 3) -> dict:
    """从 PDF 全文章节重新抽取六槽位。输出结构与 structured() 同构，
    但 source 标「fulltext」，每句的 loc 指向章节名而不是摘要位置。

    与摘要版的关键差别：全文里证据是按章节组织的，所以不做「按位置推断」
    （那套启发式是为摘要的紧凑结构设计的）；某槽位抽不到就老实标 missing，
    这本身就是全文比摘要诚实的地方 —— 摘要没写 ≠ 研究没做。
    """
    from core import fulltext as FT

    tpl_key = template_key or templates.auto_template(paper)
    slot_bodies = FT.slot_sections(sections)   # {slot: [(规范名, 章节文本)]}

    out_slots = {}
    filled = 0
    all_numbers = []
    for slot in templates.SLOTS:
        picked: list[dict] = []
        for sec_name, body in slot_bodies.get(slot) or []:
            sents = [s for s in T.split_sentences(body) if len(s) > 8]
            if not sents:
                continue
            # 每章用线索打分选最贴的几句，保底取段首（方法章的第一句通常是设计概述）
            sc = score_sentences(sents, tpl_key)
            ranked = sorted(range(len(sents)),
                            key=lambda i: -(sc[i].get(slot, 0.0) + (0.3 if i == 0 else 0.0)))
            sec_label = FT.sec_label(sec_name)
            for i in ranked[:max_per_slot]:
                picked.append({"text": sents[i], "loc": f"全文 · {sec_label}"})
            all_numbers.extend(T.extract_numbers(body))
        # 去重并限制总量
        seen: set[str] = set()
        uniq = []
        for x in picked:
            if x["text"] in seen:
                continue
            seen.add(x["text"])
            uniq.append(x)
        picked = uniq[:max_per_slot + 1]
        if picked:
            filled += 1
        out_slots[slot] = {
            "label": templates.slot_label(tpl_key, slot),
            "sentences": picked,
            "missing": not picked,
            "inferred": False,
        }

    # 数字去重（同一数值可能在方法与结果章各出现一次）
    seen_n = set()
    numbers = []
    for n in all_numbers:
        key = (n.get("kind"), n.get("value"))
        if key in seen_n:
            continue
        seen_n.add(key)
        numbers.append(n)

    coverage = filled / len(templates.SLOTS)
    conf = coverage * 45 + 20 + min(len(numbers), 6) * 3
    confidence = int(round(min(conf, 98)))

    return {
        "sid": paper.get("sid", ""),
        "title": paper.get("title", ""),
        "template": tpl_key,
        "template_name": templates.get(tpl_key)["name"],
        "structured": True,
        "slots": out_slots,
        "one_liner": _one_liner({s: [x["text"] for x in out_slots[s]["sentences"]] for s in out_slots}),
        "numbers": numbers,
        "coverage": filled,
        "coverage_pct": int(round(coverage * 100)),
        "confidence": confidence,
        "confidence_label": "高" if confidence >= 70 else ("中" if confidence >= 45 else "低"),
        "sentence_count": 0,
        "chars": sum(len(v) for v in (sections or {}).values()),
        "has_abstract": bool(paper.get("abstract")),
        "source": "fulltext",
    }


def keywords(paper: dict, top_n: int = 8) -> list[str]:
    """优先用作者/MeSH 关键词，缺失时从标题摘要抽。"""
    given = [k for k in (paper.get("keywords") or []) if k]
    fields = [f for f in (paper.get("fields") or []) if f]
    auto = T.keywords_from_text((paper.get("title") or "") + ". " + (paper.get("abstract") or ""), top_n)
    out, seen = [], set()
    for src in (given, fields, auto):
        for k in src:
            key = k.lower()
            if key and key not in seen:
                seen.add(key)
                out.append(k)
            if len(out) >= top_n:
                return out
    return out


def compare_rows(papers: list[dict], template_key: str | None = None) -> list[dict]:
    """多篇横向对比表：每格都带原句，可回溯。"""
    rows = []
    for p in papers:
        s = structured(p, template_key, max_per_slot=1)
        slots = s["slots"]

        def cell(slot: str) -> str:
            vals = slots[slot]["sentences"]
            return T.shorten(vals[0]["text"], 190) if vals else ""

        n = T.extract_sample_size(p.get("abstract") or "")
        rows.append({
            "sid": p.get("sid", ""),
            "title": T.shorten(p.get("title", ""), 90),
            "year": p.get("year"),
            "design": schema.DESIGN_LABELS.get(p.get("design"), "未识别"),
            "question": cell("question"),
            "method": cell("method"),
            "sample": n,
            "data": cell("data"),
            "findings": cell("findings"),
            "conclusion": cell("conclusion"),
            "limitation": cell("limitation"),
            "coverage": s["coverage"],
            "confidence": s["confidence"],
            "template": s["template_name"],
        })
    return rows
