"""研究缺口识别与后续方向建议。

这一层最容易变成「一本正经地胡说」。所以定三条规矩：

1. **只从文本里能核对的信号出发**。样本量、随访时长、单/多中心、有无对照、
   有没有报效应量、有没有写局限 —— 全部是可定位的字段或原句，不猜。
2. **每条缺口都要带证据**。给出触发它的比例、命中的文献与原句，用户可以点回去
   核对，也可以直接反驳「这条不成立」。
3. **不给「谁对谁错」的结论**。结论冲突只报「方向不一致 + 可能原因」，
   不给裁定；研究建议给的是「可检验的问题」，不是「应该做什么」。

规则按证据强度排序，样本不足 4 篇时只出观察不出结论 —— 3 篇文献算出来的
「比例」没有意义，这一点必须在界面上说清楚。
"""
from __future__ import annotations

import math
import re
from collections import Counter

from core import cluster as C
from core import schema, summarize
from core import text as T

MIN_PAPERS_FOR_CLAIM = 4

_POS = (
    "improved", "effective", "superior", "benefit", "significant improvement",
    "outperform", "reduced risk", "protective", "lower risk", "better than",
    "increased survival", "significant increase", "positive effect",
    "显著提高", "显著改善", "有效", "优于", "降低风险", "保护作用", "明显改善",
)
_NEG = (
    "no significant", "not significant", "did not", "no difference", "no effect",
    "ineffective", "failed to", "not associated", "harmful", "increased risk",
    "worse", "no association", "unclear", "controversial",
    "无显著", "未见差异", "无效", "未发现", "无统计学意义", "反而", "风险增加",
)
_FUTURE_CUES = (
    "future work", "future research", "further studies", "further research",
    "should be explored", "should investigate", "warranted", "remains to be",
    "needs to be", "next step", "open question",
    "未来研究", "有待进一步", "尚需", "后续研究", "需进一步", "值得探索",
)
_LIMIT_CUES = (
    "limitation", "limited by", "small sample", "single-cent", "cannot rule out",
    "may not be generaliz", "recall bias", "selection bias", "confound",
    "局限", "不足", "样本量小", "单中心", "难以推广", "偏倚", "混杂",
)
_REPRO_CUES = ("code is available", "data are available", "data availability",
               "open-source", "github.com", "公开数据", "代码开源", "数据可获取")

# 「未来工作」里出现但信息量为零的词，不能拿来当研究方向
_GENERIC = {
    "research", "future", "work", "study", "studies", "paper", "approach", "method",
    "analysis", "further", "more", "also", "need", "needed", "important", "role",
    "effect", "effects", "result", "results", "conclusion", "understanding", "evidence",
    "explore", "investigate", "furthermore", "however", "therefore", "whether", "using",
    "研究", "未来", "进一步", "需要", "重要", "作用", "影响", "分析", "方法",
}


def _followup_months(text: str) -> float | None:
    low = text.lower()
    best = None
    for m in re.finditer(r"(?:follow(?:ed)?[- ]?up|followup)[^.]{0,40}?(\d+(?:\.\d+)?)\s*(month|year|week)", low):
        val, unit = float(m.group(1)), m.group(2)
        months = val * (12 if unit.startswith("year") else (1 if unit.startswith("month") else 0.25))
        best = max(best or 0, months)
    for m in re.finditer(r"(?:随访|观察)[^。]{0,12}?(\d+(?:\.\d+)?)\s*(个月|月|年|周)", text):
        val, unit = float(m.group(1)), m.group(2)
        months = val * (12 if unit == "年" else (0.25 if unit == "周" else 1))
        best = max(best or 0, months)
    for m in re.finditer(r"median follow-up (?:of )?(\d+(?:\.\d+)?)\s*(months|years)", low):
        val, unit = float(m.group(1)), m.group(2)
        months = val * (12 if unit.startswith("year") else 1)
        best = max(best or 0, months)
    return best


def _centers(text: str) -> str:
    low = text.lower()
    if any(k in low for k in ("multicent", "multi-cent", "multi cent", "多中心", "跨机构")):
        return "multi"
    if any(k in low for k in ("single-cent", "single cent", "single institution", "单中心", "单家医院")):
        return "single"
    return "unknown"


def _has_control(text: str) -> bool:
    low = text.lower()
    return any(k in low for k in ("control group", "placebo", "compared with", "than in the",
                                  "对照组", "安慰剂", "与…比较", "相比"))


def polarity(text: str) -> tuple[str, str]:
    """结论倾向：positive / negative / mixed / unclear。"""
    low = (text or "").lower()
    p = sum(1 for c in _POS if c in low)
    n = sum(1 for c in _NEG if c in low)
    if p and n:
        return ("mixed", "同时出现正负表述")
    if p:
        return ("positive", "正向表述")
    if n:
        return ("negative", "无效应/负向表述")
    return ("unclear", "未给出明确方向")


def signals(paper: dict, summ: dict | None = None) -> dict:
    summ = summ or summarize.structured(paper)
    body = paper.get("abstract") or ""
    concl = " ".join(s["text"] for s in summ["slots"]["conclusion"]["sentences"]) or body[-320:]
    limit_sents = [s["text"] for s in summ["slots"]["limitation"]["sentences"]]
    future = [s for s in T.split_sentences(body) if any(c in s.lower() for c in _FUTURE_CUES)]
    pol, pol_note = polarity(concl)
    nums = {x["type"] for x in summ["numbers"]}
    return {
        "sid": paper.get("sid", ""),
        "title": paper.get("title", ""),
        "year": paper.get("year"),
        "design": paper.get("design", "unknown"),
        "n": T.extract_sample_size(body),
        "followup": _followup_months(body),
        "centers": _centers(body),
        "control": _has_control(body),
        "effect": bool(nums & {"ci", "effect", "p_value", "auc"}),
        "limitations": limit_sents,
        "has_limitation": bool(limit_sents) or any(c in body.lower() for c in _LIMIT_CUES),
        "future": future[:3],
        "repro": any(c in body.lower() for c in _REPRO_CUES),
        "polarity": pol,
        "polarity_note": pol_note,
        "conclusion": concl,
    }


def _pct(a: int, b: int) -> int:
    return int(round(a / b * 100)) if b else 0


def _evidence(sigs: list[dict], pred, limit: int = 4, quote_key: str = "conclusion") -> list[dict]:
    out = []
    for s in sigs:
        if pred(s):
            quote = s.get(quote_key) or ""
            if isinstance(quote, list):
                quote = quote[0] if quote else ""
            out.append({"sid": s["sid"], "title": s["title"], "year": s["year"], "quote": T.shorten(quote, 220)})
        if len(out) >= limit:
            break
    return out


def _top_terms(papers: list[dict], n: int = 8) -> list[str]:
    blob = " ".join((p.get("title") or "") + " " + (p.get("abstract") or "") for p in papers)
    return T.keywords_from_text(blob, n)


def detect(papers: list[dict], labels: list[int] | None = None) -> dict:
    """主入口：返回 {gaps:[...], signals:[...], caveat:str, stats:{}}。"""
    if not papers:
        return {"gaps": [], "signals": [], "caveat": "", "stats": {}}
    sigs = [signals(p) for p in papers]
    total = len(sigs)
    enough = total >= MIN_PAPERS_FOR_CLAIM
    terms = _top_terms(papers, 10)
    topic = "、".join(terms[:3]) if terms else "该主题"
    gaps: list[dict] = []

    # 1) 证据层级：干预性研究占比
    rct = [s for s in sigs if s["design"] in ("rct", "quasi_experimental")]
    obs = [s for s in sigs if s["design"] in ("cohort", "case_control", "cross_sectional")]
    if enough and total and len(rct) / total < 0.25 and len(obs) / total >= 0.4:
        gaps.append({
            "key": "design", "kind": "证据层级", "severity": "高",
            "title": "干预性证据不足，因果结论只能算「相关」",
            "share": _pct(len(rct), total),
            "detail": f"{total} 篇中仅 {len(rct)} 篇为随机/准实验设计（{_pct(len(rct), total)}%），"
                      f"而观察性研究占 {_pct(len(obs), total)}%。",
            "why": "观察性设计无法排除混杂与反向因果，即便效应量显著，也不能直接支持「干预有效」。",
            "suggestion": "若要支撑因果判断，需要至少一项随机对照或准实验设计（双重差分/工具变量/断点回归）来复现关键结论。",
            "design": "随机对照试验 / 准实验（DID、IV、RDD）",
            "evidence": _evidence(sigs, lambda s: s["design"] in ("cohort", "cross_sectional", "case_control")),
            "questions": [
                f"在{topic}中，把观察到的关联放进随机或准实验框架后，效应量是否仍然成立？",
                f"若以{topic}为干预靶点，哪一类人群的边际收益最大？",
            ],
        })

    # 2) 样本量
    ns = [s["n"] for s in sigs if s["n"]]
    if enough and ns:
        med = sorted(ns)[len(ns) // 2]
        small = [s for s in sigs if s["n"] and s["n"] < 50]
        if med < 150 or len(small) / max(len(ns), 1) >= 0.3:
            gaps.append({
                "key": "sample", "kind": "样本规模", "severity": "中" if med >= 80 else "高",
                "title": "样本规模普遍偏小，统计效能可能不足",
                "share": _pct(len(small), len(ns)),
                "detail": f"报告了样本量的 {len(ns)} 篇中，中位样本量 {med}；{len(small)} 篇不足 50 例。",
                "why": "小样本下的效应量估计方差大，阴性结果也不能排除「效能不足」，容易出现结论反复。",
                "suggestion": "合并多中心数据，或做功效分析后按最小可检测效应确定样本量；小样本研究适合作为先导试验。",
                "design": "多中心队列 / 前瞻性注册研究",
                "evidence": _evidence(sigs, lambda s: s["n"] and s["n"] < 50),
                "questions": [
                    f"在现有最小效应量的假设下，需要多大样本才能在 80% 效能下检出{topic}的差异？",
                    "把多项小样本研究合并后，异质性的主要来源是人群、剂量还是终点定义？",
                ],
            })

    # 3) 随访时长
    fus = [s["followup"] for s in sigs if s["followup"]]
    if enough and fus:
        short = [s for s in sigs if s["followup"] and s["followup"] < 12]
        if len(short) / len(fus) >= 0.4:
            gaps.append({
                "key": "followup", "kind": "时间维度", "severity": "中",
                "title": "随访偏短，长期结局与滞后效应看不清",
                "share": _pct(len(short), len(fus)),
                "detail": f"报告随访时长的 {len(fus)} 篇中，{len(short)} 篇不足 12 个月。",
                "why": "短随访只能看到即时效应；如果效应随时间衰减或出现延迟获益，短窗研究会给出相反结论。",
                "suggestion": "延长观察窗至 24–60 个月，并在多个时间点重复测量，以区分即时效应与累积效应。",
                "design": "长期前瞻性队列 / 延长随访的 RCT",
                "evidence": _evidence(sigs, lambda s: s["followup"] and s["followup"] < 12),
                "questions": [
                    f"{topic}的效应在 12 个月后是维持、衰减还是反转？",
                    "是否存在「早期获益、后期抵消」的时间依赖模式？",
                ],
            })

    # 4) 外部效度：单中心
    centers = [s for s in sigs if s["centers"] != "unknown"]
    single = [s for s in centers if s["centers"] == "single"]
    if enough and centers and len(single) / len(centers) >= 0.45:
        gaps.append({
            "key": "center", "kind": "外部效度", "severity": "中",
            "title": "以单中心研究为主，跨人群可推广性待验证",
            "share": _pct(len(single), len(centers)),
            "detail": f"明确交代研究场所的 {len(centers)} 篇中，{len(single)} 篇为单中心。",
            "why": "单中心的患者构成、操作规范与设备条件都更同质，效应量常高于多中心验证结果。",
            "suggestion": "在多中心、跨地区样本上做外部验证，并报告按中心分层的效应一致性。",
            "design": "多中心外部验证 / 分层再分析",
            "evidence": _evidence(sigs, lambda s: s["centers"] == "single"),
            "questions": [
                f"把{topic}的模型或结论迁移到不同地区、不同级别机构时，性能下降多少？",
                "效应在不同基线风险人群中是否保持同向？",
            ],
        })

    # 5) 结论冲突
    conflicts = []
    for i in range(len(sigs)):
        for j in range(i + 1, len(sigs)):
            a, b = sigs[i], sigs[j]
            if {a["polarity"], b["polarity"]} == {"positive", "negative"}:
                sim = T.jaccard(set(T.tokenize(a["title"] + " " + a["conclusion"])),
                                set(T.tokenize(b["title"] + " " + b["conclusion"])))
                if sim >= 0.18:
                    conflicts.append((a, b, sim))
    if len(conflicts) >= 1:
        gaps.append({
            "key": "conflict", "kind": "结论一致性", "severity": "高",
            "title": "同一主题下结论方向不一致，需要分层解释",
            "share": len(conflicts),
            "detail": f"检出 {len(conflicts)} 对结论方向相反的文献（主题词重叠 ≥ 0.18）。",
            "why": "结论冲突通常来自人群、剂量、终点定义或随访窗不同，而不是谁做错了。",
            "suggestion": "按「人群 × 剂量/强度 × 终点定义 × 随访时长」四个维度做亚组拆分，再判断是否真冲突。",
            "design": "分层 Meta 分析 / 个体数据再分析",
            "evidence": [
                {"sid": a["sid"], "title": a["title"], "year": a["year"],
                 "quote": T.shorten(a["conclusion"], 160), "stance": "正向"}
                for a, b, s in conflicts[:3]
            ] + [
                {"sid": b["sid"], "title": b["title"], "year": b["year"],
                 "quote": T.shorten(b["conclusion"], 160), "stance": "负向"}
                for a, b, s in conflicts[:2]
            ],
            "questions": [
                "把结论相反的几项研究按人群与剂量分层后，方向是否重新一致？",
                "终点定义的差异（替代终点 vs 硬终点）能否解释分歧？",
            ],
        })

    # 6) 方法同质化
    method_terms = Counter()
    for s in sigs:
        for tok in T.tokenize(" ".join(s["limitations"]) + " " + (s["conclusion"] or "")):
            method_terms[tok] += 1
    designs = Counter(s["design"] for s in sigs)
    if enough and designs:
        top_design, top_cnt = designs.most_common(1)[0]
        if top_cnt / total >= 0.55 and top_design not in ("unknown",):
            gaps.append({
                "key": "method", "kind": "方法多样性", "severity": "中",
                "title": f"方法路径偏单一，{schema.DESIGN_LABELS.get(top_design, top_design)}占主导",
                "share": _pct(top_cnt, total),
                "detail": f"{total} 篇中 {top_cnt} 篇采用同一类设计（{_pct(top_cnt, total)}%）。",
                "why": "单一方法下的重复验证会放大该方法本身的系统性偏差，难以发现「方法之外」的规律。",
                "suggestion": "引入互补方法做三角验证：定量结论用质性访谈解释机制，模型结论用真实场景实验校验。",
                "design": "混合方法 / 跨范式三角验证",
                "evidence": _evidence(sigs, lambda s: s["design"] == top_design),
                "questions": [
                    f"用与主流不同的方法（如质性、仿真、现场实验）研究{topic}，会得到哪些主流方法看不到的机制？",
                    "现有方法的共同假设中，哪一条最可能不成立？",
                ],
            })

    # 7) 概念空白：未来工作里高频、但现有研究少做
    fut_tokens = Counter()
    for s in sigs:
        for f in s["future"]:
            fut_tokens.update(T.tokenize(f))
    body_tokens = Counter()
    for p in papers:
        body_tokens.update(T.tokenize((p.get("title") or "") + " " + (p.get("abstract") or "")))
    hot_future = [(t, c) for t, c in fut_tokens.most_common(40)
                  if c >= 2 and t not in _GENERIC and body_tokens.get(t, 0) <= c * 3]
    if enough and hot_future:
        terms_hot = [t for t, c in hot_future[:4]]
        gaps.append({
            "key": "concept", "kind": "概念空白", "severity": "中",
            "title": "被反复提出、但尚缺实证的方向",
            "share": len(hot_future),
            "hot_terms": terms_hot,
            "detail": "以下概念在「未来工作」句里高频出现，却在现有摘要的实质结论中很少落地："
                      + "、".join(terms_hot),
            "why": "一个概念反复出现在 future work，说明领域公认它重要；但在结论里缺席，说明还没人做成。",
            "suggestion": "把其中可行性最高的一项做成最小可验证研究（pilot），先确认效应存在再扩样本。",
            "design": "先导研究（pilot）→ 主研究",
            "evidence": _evidence(sigs, lambda s: bool(s["future"]), quote_key="future"),
            "questions": [
                f"「{terms_hot[0] if terms_hot else topic}」在现有数据里能否被操作化定义并测量？",
                "如果把它作为主要终点，最小可检测效应是多少？",
            ],
        })

    # 8) 可复现性
    no_repro = [s for s in sigs if not s["repro"]]
    if enough and len(no_repro) / total >= 0.8:
        gaps.append({
            "key": "repro", "kind": "可复现性", "severity": "中",
            "title": "数据与代码可得性普遍未交代",
            "share": _pct(len(no_repro), total),
            "detail": f"{len(no_repro)}/{total} 篇摘要未提及数据或代码的获取方式。",
            "why": "摘要层面不交代可得性，通常意味着正文也没有规范的数据声明，复现成本高。",
            "suggestion": "投稿时附数据/代码可用性声明（FAIR 原则），至少提供分析脚本与变量字典。",
            "design": "复现研究 / 开放科学实践",
            "evidence": _evidence(sigs, lambda s: not s["repro"]),
            "questions": [
                "现有结论在公开数据上能否被独立复现？差异来自实现细节还是数据版本？",
            ],
        })

    # 9) 效应量报告
    no_effect = [s for s in sigs if not s["effect"]]
    if enough and len(no_effect) / total >= 0.5:
        gaps.append({
            "key": "effect", "kind": "报告规范", "severity": "低",
            "title": "效应量与不确定性报告不足",
            "share": _pct(len(no_effect), total),
            "detail": f"{len(no_effect)}/{total} 篇摘要未见效应量、置信区间或 P 值。",
            "why": "只有「显著/不显著」的二元表述无法用于合并分析，也无法判断实际意义大小。",
            "suggestion": "报告点估计 + 95% 置信区间，并说明最小临床/实践重要差异。",
            "design": "报告规范改进（无需新研究）",
            "evidence": _evidence(sigs, lambda s: not s["effect"]),
            "questions": ["把各研究的效应量统一到同一尺度后，合并效应是多少？"],
        })

    # 10) 设计信息缺失：摘要没交代设计，证据分级无从谈起
    unknown_design = [s for s in sigs if s["design"] in ("unknown", "")]
    if enough and len(unknown_design) / total >= 0.35:
        gaps.append({
            "key": "design_report", "kind": "报告完整性", "severity": "低",
            "title": "相当比例的摘要未交代研究设计",
            "share": _pct(len(unknown_design), total),
            "detail": f"{len(unknown_design)}/{total} 篇无法从标题与摘要判断研究设计。",
            "why": "设计不可辨，读者无法评估证据强度，综述时也难以分层。",
            "suggestion": "在摘要中明确写出一句设计声明（如「随机双盲对照」「回顾性队列」「受控培养实验」）。",
            "design": "报告规范改进（无需新研究）",
            "evidence": _evidence(sigs, lambda s: s["design"] in ("unknown", "")),
            "questions": ["若按设计重新分层，各层的结论方向是否一致？"],
        })

    order = {"高": 0, "中": 1, "低": 2}
    gaps.sort(key=lambda g: (order.get(g["severity"], 3), -int(g.get("share") or 0)))

    caveat = ""
    if not enough:
        caveat = (f"当前只有 {total} 篇文献，低于 {MIN_PAPERS_FOR_CLAIM} 篇的统计门槛，"
                  "以下仅作观察记录，不构成对该领域的判断。建议扩大检索后再看。")

    stats = {
        "n": total,
        "median_n": sorted(ns)[len(ns) // 2] if ns else None,
        "rct_share": _pct(len(rct), total),
        "single_center_share": _pct(len(single), len(centers)) if centers else None,
        "median_followup": sorted(fus)[len(fus) // 2] if fus else None,
        "conflicts": len(conflicts),
        "designs": dict(designs.most_common()),
    }
    return {"gaps": gaps, "signals": sigs, "caveat": caveat, "stats": stats}


def directions(papers: list[dict], gap_result: dict, labels: list[int] | None = None, top: int = 5) -> list[dict]:
    """把缺口翻译成「可执行的研究方向」。每条都带依据、设计与风险。"""
    gaps = gap_result.get("gaps") or []
    if not papers or not gaps:
        return []
    terms = _top_terms(papers, 10)
    topic = "、".join(terms[:3]) if terms else "该主题"
    out = []
    for g in gaps[:top]:
        key = g["key"]
        if key == "design":
            title = f"用随机或准实验设计复现「{terms[0] if terms else topic}」的关键关联"
            contrib = "把现有相关性结论升级为可支持因果判断的证据"
            risk = "随机化在部分场景不可行，需退而用准实验并做敏感性分析"
        elif key == "sample":
            title = f"建多中心联合样本，检验小样本结论是否稳健"
            contrib = "提高统计效能，缩小效应量估计的不确定性"
            risk = "多中心数据口径不一致，需先统一变量定义"
        elif key == "followup":
            title = f"延长随访窗，刻画「{terms[0] if terms else topic}」效应的时间曲线"
            contrib = "区分即时效应与长期效应，解释结论反复"
            risk = "长期随访脱落率高，需要预先设计缺失处理方案"
        elif key == "center":
            title = "跨地区外部验证，量化可推广性衰减"
            contrib = "给出模型/结论在不同人群中的性能边界"
            risk = "外部数据获取周期长，可先用公开数据集替代"
        elif key == "conflict":
            title = "按人群 × 剂量 × 终点分层，定位结论分歧的来源"
            contrib = "把「谁对谁错」转化为「在什么条件下成立」"
            risk = "分层后每格样本变少，需要个体数据或更大合并样本"
        elif key == "method":
            title = "引入互补方法做三角验证"
            contrib = "发现单一范式看不到的机制与边界条件"
            risk = "跨范式研究周期长，建议先做小规模混合方法试点"
        elif key == "concept":
            hot = (g.get("hot_terms") or [""])[0] or topic
            title = f"把「{hot}」做成可测量的最小研究"
            contrib = "把领域公认但未落地的概念转为可验证变量"
            risk = "概念操作化本身可能没有共识，需先做量表/指标开发"
        elif key == "repro":
            title = "做一次独立复现，并公开数据与脚本"
            contrib = "为领域提供可复用的基线，降低后续研究成本"
            risk = "原始数据可能无法获取，需退而用合成数据验证流程"
        else:
            title = "统一效应量报告口径，支持后续合并分析"
            contrib = "让已有研究可被纳入 Meta 分析"
            risk = "需要回溯原文补数据，工作量大"

        out.append({
            "gap_key": key,
            "title": title,
            "basis": g["title"],
            "design": g.get("design", ""),
            "contribution": contrib,
            "risk": risk,
            "questions": g.get("questions") or [],
            "severity": g.get("severity", "中"),
            "evidence_count": len(g.get("evidence") or []),
        })
    return out


def concept_matrix(papers: list[dict], labels: list[int], res: dict | None = None, top_terms: int = 10) -> dict:
    """概念 × 研究方向 的覆盖矩阵，用来看「哪个方向把哪些概念吃透了」。"""
    if not papers:
        return {"terms": [], "clusters": [], "matrix": []}
    res = res or C.cluster(papers)
    terms = _top_terms(papers, top_terms)
    clusters = res["clusters"]
    matrix = []
    for c in clusters:
        idxs = c["members"]
        row = []
        for term in terms:
            hit = sum(1 for i in idxs if term in T.tokenize(
                (papers[i].get("title") or "") + " " + (papers[i].get("abstract") or "")))
            row.append(hit)
        matrix.append(row)
    return {
        "terms": terms,
        "clusters": [c["name"] for c in clusters],
        "sizes": [c["size"] for c in clusters],
        "matrix": matrix,
    }
