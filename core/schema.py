"""统一文献数据结构与学科/研究类型判定。

六个数据源返回的字段名、嵌套层级、缺失习惯都不一样（OpenAlex 用
abstract_inverted_index，Crossref 用 JATS 标签，arXiv 给 Atom XML，
PubMed 给 MEDLINE 风格的 JSON）。这一层把它们压成同一个 dict，
后面所有模块只认这一套字段。

字段约定（缺就留空，不抛异常）：
    sid        稳定标识，形如 "doi:10.xxx" / "pmid:123" / "arxiv:2401.00001"
    title      标题（已清洗）
    abstract   摘要（已清洗，可能为空）
    authors    list[str]
    year       int | None
    venue      期刊/会议名
    doi / pmid / arxiv_id / openalex_id
    url        落地页
    pdf_url    可直链 PDF
    type       文献类型（article / preprint / review / conference / book-chapter ...）
    design     研究设计（见 DESIGN_LABELS）
    fields     学科概念/主题标签
    keywords   作者关键词或抽取关键词
    cited_by   被引次数
    refs       list[str] 参考文献标识（能拿到才算）
    is_oa      是否开放获取
    lang       语种
    sources    list[str] 命中过的数据源
"""
from __future__ import annotations

import hashlib
import re

from core import text as T

# --------------------------------------------------------------------------
# 学科预设：既决定检索时给各源的关键词后缀，也决定默认摘要模板
# --------------------------------------------------------------------------
DISCIPLINES: dict[str, dict] = {
    "通用 / 跨学科": {
        "template": "imrad",
        "sources": ["openalex", "crossref", "semantic", "arxiv"],
        "hint": "不限定领域，按标题摘要全文匹配",
    },
    "医学与生命科学": {
        "template": "imrad",
        "sources": ["pubmed", "europepmc", "openalex", "crossref"],
        "hint": "PubMed + Europe PMC 覆盖最全，预印本看 bioRxiv",
    },
    "计算机与人工智能": {
        "template": "cs",
        "sources": ["arxiv", "semantic", "openalex", "crossref"],
        "hint": "arXiv 抢新最快，Semantic Scholar 补引用关系",
    },
    "工程与材料": {
        "template": "engineering",
        "sources": ["crossref", "openalex", "semantic"],
        "hint": "以 Crossref 的期刊/会议记录为主",
    },
    "经济与管理": {
        "template": "econ",
        "sources": ["crossref", "openalex", "semantic"],
        "hint": "工作论文与期刊混排，注意识别工作论文版本",
    },
    "社会科学": {
        "template": "social",
        "sources": ["crossref", "openalex", "semantic", "europepmc"],
        "hint": "社科摘要常无结构化小标题，模板会自动降级",
    },
    "人文与艺术": {
        "template": "humanities",
        "sources": ["crossref", "openalex"],
        "hint": "以论点—材料—论证结构解读，不强行套 IMRaD",
    },
    "环境与地球科学": {
        "template": "imrad",
        "sources": ["crossref", "openalex", "europepmc", "arxiv"],
        "hint": "跨学科明显，建议同时开 Crossref 与 Europe PMC",
    },
    "物理与数学": {
        "template": "cs",
        "sources": ["arxiv", "crossref", "openalex"],
        "hint": "arXiv 为主，理论类摘要多无结果段",
    },
    "教育与心理": {
        "template": "social",
        "sources": ["crossref", "openalex", "europepmc", "semantic"],
        "hint": "实证研究为主，注意样本与量表信息",
    },
}

# --------------------------------------------------------------------------
# 研究设计判定
# --------------------------------------------------------------------------
DESIGN_LABELS = {
    "meta_analysis": "Meta 分析",
    "systematic_review": "系统评价",
    "rct": "随机对照试验",
    "quasi_experimental": "准实验 / 前后对照",
    "cohort": "队列研究",
    "case_control": "病例对照",
    "cross_sectional": "横断面 / 调查研究",
    "experimental": "受控实验",
    "field": "田间 / 现场研究",
    "qualitative": "质性研究",
    "case_report": "病例报告 / 案例",
    "benchmark": "基准评测 / 对比实验",
    "modeling": "建模与仿真",
    "theoretical": "理论 / 概念建构",
    "review": "叙述性综述",
    "mixed": "混合方法",
    "unknown": "未识别",
}

# 证据层级（跨学科版本：不套临床 GRADE，只区分「因果强度」与「证据来源」）
DESIGN_TIER = {
    "meta_analysis": 5, "systematic_review": 5,
    "rct": 4, "quasi_experimental": 3,
    "cohort": 3, "case_control": 2, "cross_sectional": 2,
    "experimental": 3, "field": 2,
    "benchmark": 3, "modeling": 2, "mixed": 3,
    "qualitative": 2, "case_report": 1, "theoretical": 1,
    "review": 2, "unknown": 0,
}

_DESIGN_CUES: list[tuple[str, tuple[str, ...]]] = [
    ("meta_analysis", ("meta-analysis", "meta analysis", "pooled analysis", "meta分析", "荟萃分析")),
    ("systematic_review", ("systematic review", "prisma", "系统评价", "系统综述")),
    ("rct", ("randomized controlled trial", "randomised controlled trial", "randomized trial",
             "double-blind", "placebo-controlled", "randomly assigned", "随机对照", "双盲", "安慰剂")),
    ("quasi_experimental", ("quasi-experimental", "pre-post", "difference-in-differences",
                            "propensity score", "instrumental variable", "断点回归", "双重差分", "倾向得分")),
    ("cohort", ("cohort study", "prospective cohort", "retrospective cohort", "longitudinal study",
                "follow-up study", "队列研究", "随访研究")),
    ("case_control", ("case-control", "case control", "病例对照")),
    ("experimental", ("we incubated", "incubation experiment", "laboratory experiment",
                      "greenhouse experiment", "pot experiment", "controlled experiment",
                      "microcosm", "batch experiment", "column experiment", "we synthesized",
                      "incubat", "treatment group", "we tested", "were tested", "assay",
                      "greenhouse", "spiked", "were mixed with", "were added to",
                      "were exposed to", "we investigated the effects", "we examined the effects",
                      "培养实验", "室内培养", "盆栽实验", "受控实验", "微宇宙", "处理组", "试验组")),
    ("field", ("field experiment", "field trial", "field survey", "field sampling",
               "in situ measurement", "田间试验", "大田试验", "野外调查", "现场观测")),
    ("cross_sectional", ("cross-sectional", "cross sectional", "questionnaire survey", "survey of",
                         "横断面", "问卷调查", "抽样调查")),
    ("qualitative", ("qualitative study", "semi-structured interview", "focus group", "grounded theory",
                     "ethnograph", "质性研究", "深度访谈", "扎根理论")),
    ("case_report", ("case report", "case series", "a case of", "病例报告", "个案")),
    ("benchmark", ("benchmark", "we evaluate on", "state-of-the-art", "ablation study", "baseline",
                   "基准测试", "消融实验", "对比实验")),
    ("modeling", ("simulation", "finite element", "monte carlo", "mathematical model", "numerical model",
                  "仿真", "有限元", "数值模拟", "建模")),
    ("theoretical", ("we propose a framework", "theoretical framework", "conceptual model", "we argue",
                     "this essay", "理论框架", "概念模型", "本文认为")),
    ("review", ("this review", "we review", "literature review", "narrative review", "综述", "文献回顾")),
    ("mixed", ("mixed-method", "mixed method", "混合方法")),
]


def classify_design(title: str = "", abstract: str = "", pub_type: str = "") -> str:
    """按标题+摘要线索判研究设计。标题命中权重更高（标题常直接写设计）。"""
    t_low = (title or "").lower()
    a_low = (abstract or "").lower()
    p_low = (pub_type or "").lower()
    if "meta-analysis" in p_low or "meta analysis" in p_low:
        return "meta_analysis"
    if "systematic review" in p_low:
        return "systematic_review"
    if "randomized controlled trial" in p_low:
        return "rct"
    if "review" in p_low and not any(k in p_low for k in ("systematic", "meta")):
        return "review"
    best, best_score = "unknown", 0.0
    for design, cues in _DESIGN_CUES:
        score = 0.0
        for cue in cues:
            if cue in t_low:
                score += 2.0
            if cue in a_low:
                score += 1.0
        if score > best_score:
            best, best_score = design, score
    return best if best_score >= 1.0 else "unknown"


# --------------------------------------------------------------------------
# 标识归一化
# --------------------------------------------------------------------------
_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"<>]+", re.I)


def normalize_doi(doi: str | None) -> str:
    if not doi:
        return ""
    doi = str(doi).strip()
    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.I)
    m = _DOI_RE.search(doi)
    return m.group(0).rstrip(".,;)").lower() if m else ""


def normalize_title(title: str) -> str:
    t = T.clean_text(title).lower()
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def title_key(title: str) -> str:
    """用于分块比对的粗键：前 40 个字符，容忍标点与大小写差异。"""
    return normalize_title(title)[:40]


def make_sid(p: dict) -> str:
    if p.get("doi"):
        return f"doi:{p['doi']}"
    if p.get("pmid"):
        return f"pmid:{p['pmid']}"
    if p.get("arxiv_id"):
        return f"arxiv:{p['arxiv_id']}"
    if p.get("openalex_id"):
        return f"openalex:{p['openalex_id']}"
    h = hashlib.blake2b(
        (normalize_title(p.get("title", "")) + str(p.get("year") or "")).encode("utf-8"),
        digest_size=6,
    ).hexdigest()
    return f"sm:{h}"


def empty_paper() -> dict:
    return {
        "sid": "", "title": "", "abstract": "", "authors": [], "year": None,
        "venue": "", "doi": "", "pmid": "", "arxiv_id": "", "openalex_id": "",
        "url": "", "pdf_url": "", "type": "", "design": "unknown",
        "fields": [], "keywords": [], "cited_by": 0, "refs": [],
        "is_oa": False, "lang": "en", "sources": [], "source": "",
        "extra": {},
    }


def normalize_paper(raw: dict) -> dict:
    """把各源适配器的原始输出收敛成标准 Paper。"""
    p = empty_paper()
    p.update({k: v for k, v in raw.items() if k in p})
    p["title"] = T.clean_text(p.get("title"))
    p["abstract"] = T.clean_abstract(p.get("abstract"))
    p["doi"] = normalize_doi(p.get("doi"))
    p["pmid"] = str(p.get("pmid") or "").strip()
    p["arxiv_id"] = str(p.get("arxiv_id") or "").strip()
    p["openalex_id"] = str(p.get("openalex_id") or "").strip()
    if isinstance(p.get("authors"), str):
        p["authors"] = [a.strip() for a in p["authors"].split(";") if a.strip()]
    p["authors"] = [a for a in (p.get("authors") or []) if a][:60]
    p["fields"] = _uniq([f for f in (p.get("fields") or []) if f])[:12]
    p["keywords"] = _uniq([k for k in (p.get("keywords") or []) if k])[:15]
    p["refs"] = _uniq([r for r in (p.get("refs") or []) if r])[:200]
    try:
        p["cited_by"] = int(p.get("cited_by") or 0)
    except (TypeError, ValueError):
        p["cited_by"] = 0
    try:
        p["year"] = int(p["year"]) if p.get("year") else None
    except (TypeError, ValueError):
        p["year"] = None
    p["lang"] = p.get("lang") or T.detect_lang(p["title"] + " " + p["abstract"])
    # 适配器若已给出明确设计就沿用；"unknown" 是默认值，必须走一次判定
    given = p.get("design")
    p["design"] = given if (given in DESIGN_LABELS and given != "unknown") else classify_design(
        p["title"], p["abstract"], p.get("type", "")
    )
    if not p.get("url") and p.get("doi"):
        p["url"] = f"https://doi.org/{p['doi']}"
    p["sources"] = _uniq(p.get("sources") or ([p["source"]] if p.get("source") else []))
    p["sid"] = p.get("sid") or make_sid(p)
    return p


def _uniq(seq) -> list:
    seen, out = set(), []
    for x in seq:
        k = str(x).strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(x)
    return out


def merge_papers(base: dict, other: dict) -> dict:
    """同一篇文献在不同源的记录合并：谁有值用谁，摘要取更长的那条。"""
    out = dict(base)
    for k, v in other.items():
        if k in ("sources", "sid", "extra"):
            continue
        if k == "abstract":
            if len(v or "") > len(out.get("abstract") or ""):
                out["abstract"] = v
        elif k in ("cited_by",):
            out[k] = max(int(out.get(k) or 0), int(v or 0))
        elif k == "refs":
            out[k] = _uniq((out.get("refs") or []) + (v or []))[:200]
        elif k in ("fields", "keywords", "authors"):
            out[k] = _uniq((out.get(k) or []) + (v or []))[: (12 if k == "fields" else 15)]
        elif not out.get(k) and v:
            out[k] = v
    out["sources"] = _uniq((base.get("sources") or []) + (other.get("sources") or []))
    if not out.get("pdf_url") and other.get("pdf_url"):
        out["pdf_url"] = other["pdf_url"]
    if not out.get("url") and other.get("url"):
        out["url"] = other["url"]
    if out.get("design") in (None, "", "unknown") and other.get("design") not in (None, "", "unknown"):
        out["design"] = other["design"]
    return out


def display_authors(p: dict, limit: int = 3) -> str:
    authors = p.get("authors") or []
    if not authors:
        return "作者信息缺失"
    if len(authors) <= limit:
        return ", ".join(authors)
    return ", ".join(authors[:limit]) + f" 等 {len(authors)} 人"


def venue_year(p: dict) -> str:
    venue = T.shorten(p.get("venue") or "", 60) or "来源未标注"
    return f"{venue} · {p['year']}" if p.get("year") else venue
