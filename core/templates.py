"""学科摘要模板。

「摘要」这件事在不同学科里长得完全不一样：医学摘要是 Background/Methods/
Results/Conclusions 四段式，计算机论文是 Problem–Approach–Experiments，
经济学期刊要求写识别策略，人文学科根本没有「结果」这一栏。
用同一套 IMRaD 去套所有论文，抽出来的东西一定是错的。

所以这里做的是「模板 + 统一槽位」两层：
    模板层  决定读哪些线索词、按什么顺序呈现（各学科自己的写法）
    槽位层  统一收敛到 question / method / data / findings / conclusion /
            limitation 六个槽，跨论文对比、聚类、缺口分析都只认这六个

新增学科只要往 TEMPLATES 里加一条，不需要改抽取引擎。
"""
from __future__ import annotations

# 统一槽位（顺序即展示顺序）
SLOTS = ["question", "method", "data", "findings", "conclusion", "limitation"]
SLOT_LABELS = {
    "question": "研究问题",
    "method": "方法与设计",
    "data": "数据与样本",
    "findings": "主要发现",
    "conclusion": "结论与意义",
    "limitation": "局限与展望",
}

# 通用线索词（各模板在此基础上叠加自己的领域词）
BASE_CUES: dict[str, tuple[str, ...]] = {
    "question": (
        "we investigate", "we examine", "we study", "this study", "this paper",
        "aim of this study", "objective", "purpose of", "research question",
        "we address", "we ask", "here we", "we test", "hypothes",
        "研究目的", "本文旨在", "旨在", "探讨", "考察", "研究问题", "试图回答",
    ),
    "method": (
        "we propose", "we present", "we develop", "we introduce", "we design",
        "we conducted", "we performed", "we used", "we apply", "method",
        "approach", "framework", "algorithm", "model architecture", "protocol",
        "randomized", "we built", "we train",
        "were incubated", "was measured", "were analyzed", "were collected",
        "was conducted", "samples were", "were determined", "were assessed",
        "was used to", "were randomly", "we measured", "we assessed",
        "were mixed", "were added", "were treated", "were prepared", "were tested",
        "were obtained", "were grown", "were cultured", "were assigned", "were exposed",
        "方法", "采用", "构建", "提出", "设计", "实验", "模型", "算法", "技术路线",
        "测定", "检测", "培养", "随机分为",
    ),
    "data": (
        "data from", "dataset", "cohort", "participants", "sample of", "we collected",
        "survey", "respondents", "corpus", "benchmark", "training set", "test set",
        "n =", "patients were", "we recruited",
        "样本", "数据", "受访者", "病例", "语料", "数据集", "纳入",
    ),
    "findings": (
        "we found", "results show", "results indicate", "our results", "we observe",
        "was associated with", "significantly", "increased", "decreased", "improved",
        "outperform", "achiev", "higher than", "lower than", "compared with",
        "结果显示", "研究发现", "发现", "显著", "提高", "降低", "优于", "表明",
    ),
    "conclusion": (
        "in conclusion", "we conclude", "these findings", "our findings suggest",
        "this suggests", "implications for", "taken together", "overall",
        "结论", "综上", "本研究认为", "提示", "意义在于", "由此可见",
    ),
    "limitation": (
        "limitation", "limited by", "small sample", "single-cent", "further research",
        "future work", "future research", "remains unclear", "remains unknown",
        "should be explored", "we did not", "cannot rule out", "caution",
        "局限", "不足", "有待", "尚需", "未来研究", "后续工作", "未能", "有待进一步",
    ),
}

# 模板：name/desc/cues(叠加)/slot_labels(覆盖展示名)/structured 提示
TEMPLATES: dict[str, dict] = {
    "imrad": {
        "name": "IMRaD 实证研究",
        "desc": "医学、生命科学、心理学等标准四段式摘要：背景—方法—结果—结论",
        "tags": ["医学", "生命科学", "心理", "公卫"],
        "extra_cues": {
            "method": ("trial", "intervention", "control group", "placebo", "assay",
                       "regression", "interviews", "试验", "干预", "对照组", "量表"),
            "data": ("inclusion criteria", "eligible", "随访", "入组"),
            "findings": ("hazard ratio", "odds ratio", "confidence interval", "p =", "p<",
                         "mean difference", "效应量"),
        },
        "slot_labels": {},
    },
    "cs": {
        "name": "计算机 / 工程论文",
        "desc": "问题—方法—实验设置—结果—局限，重点抓指标数字与基线对比",
        "tags": ["计算机", "人工智能", "工程", "物理", "数学"],
        "extra_cues": {
            "question": ("challenge", "bottleneck", "suffer from", "fail to", "problem of",
                         "痛点", "难以", "瓶颈"),
            "method": ("architecture", "module", "loss function", "fine-tun", "pre-train",
                       "transformer", "encoder", "decoder", "pipeline", "模块", "损失函数"),
            "data": ("imagenet", "glue", "squad", "benchmark suite", "ablation",
                     "baseline", "sota", "state-of-the-art"),
            "findings": ("bleu", "f1", "accuracy", "auc", "perplexity", "latency",
                         "speedup", "gpu", "参数", "准确率", "推理速度"),
            "limitation": ("compute", "scalab", "generaliz", "out-of-distribution",
                           "future work will", "泛化", "算力"),
        },
        "slot_labels": {"findings": "实验结果", "conclusion": "结论与影响"},
    },
    "econ": {
        "name": "经济 / 管理研究",
        "desc": "问题—数据与识别策略—发现—政策含义，识别策略是审稿人最看重的部分",
        "tags": ["经济", "管理", "金融", "会计"],
        "extra_cues": {
            "method": ("identification strategy", "difference-in-differences", "instrumental variable",
                       "regression discontinuity", "fixed effects", "endogeneity", "iv estimate",
                       "识别策略", "双重差分", "工具变量", "断点回归", "固定效应", "内生性"),
            "data": ("panel data", "firm-level", "administrative data", "world bank",
                     "census", "面板数据", "企业层面", "宏观数据"),
            "findings": ("elasticity", "percentage points", "standard deviation increase",
                         "robustness", "placebo test", "弹性", "百分点", "稳健性"),
            "conclusion": ("policy implication", "practitioners", "managers should",
                           "政策含义", "管理启示"),
        },
        "slot_labels": {"method": "识别策略", "conclusion": "结论与政策含义"},
    },
    "social": {
        "name": "社会科学实证",
        "desc": "问题—数据与方法—发现—讨论与启示，适合教育学、社会学、传播学",
        "tags": ["社会", "教育", "传播", "公共管理"],
        "extra_cues": {
            "method": ("semi-structured", "coding", "thematic analysis", "scale", "inventory",
                       "structural equation", "logistic regression", "访谈", "编码", "量表",
                       "结构方程", "回归"),
            "data": ("respondents", "questionnaire", "focus group", "fieldwork", "课堂观察"),
            "findings": ("participants reported", "themes emerged", "correlation",
                         "受访者", "主题", "相关"),
        },
        "slot_labels": {"conclusion": "讨论与启示", "limitation": "研究局限"},
    },
    "humanities": {
        "name": "人文与理论",
        "desc": "论点—材料—论证路径—意义，不强行套「结果」栏",
        "tags": ["人文", "艺术", "哲学", "历史", "文学"],
        "extra_cues": {
            "question": ("this article argues", "i argue", "this essay", "we contend",
                         "本文认为", "笔者以为", "文章指出"),
            "method": ("close reading", "archival", "textual analysis", "genealog",
                       "comparative reading", "细读", "文本分析", "档案", "谱系"),
            "data": ("archive", "manuscript", "corpus of", "primary sources",
                     "档案", "手稿", "原始文献"),
            "findings": ("reveals", "demonstrates", "i show", "we show", "suggests that",
                         "揭示", "论证", "说明"),
            "conclusion": ("ultimately", "I conclude", "the significance", "总之", "意义"),
        },
        "slot_labels": {"question": "核心论点", "method": "材料与方法", "data": "史料与文本",
                        "findings": "论证要点", "conclusion": "结论与意义"},
    },
    "review": {
        "name": "综述 / Meta 分析",
        "desc": "范围—纳入方法—共识—争议—空白，适合系统评价与叙述性综述",
        "tags": ["综述", "系统评价", "Meta"],
        "extra_cues": {
            "question": ("this review", "we review", "aims to summarize", "scope",
                         "综述", "本文回顾", "梳理"),
            "method": ("prisma", "we searched", "inclusion criteria", "risk of bias",
                       "pubmed", "embase", "检索", "纳入标准", "偏倚风险"),
            "data": ("studies were included", "n = ", "纳入文献", "篇文献"),
            "findings": ("evidence suggests", "consistent", "heterogeneity", "pooled",
                         "证据", "异质性", "合并"),
            "conclusion": ("evidence gaps", "future trials", "证据空白", "未来研究"),
        },
        "slot_labels": {"method": "纳入与评价方法", "data": "纳入文献",
                        "findings": "主要共识", "conclusion": "争议与空白"},
    },
}

# 学科 → 默认模板
DISCIPLINE_TEMPLATE = {
    "通用 / 跨学科": "imrad",
    "医学与生命科学": "imrad",
    "计算机与人工智能": "cs",
    "工程与材料": "cs",
    "经济与管理": "econ",
    "社会科学": "social",
    "人文与艺术": "humanities",
    "环境与地球科学": "imrad",
    "物理与数学": "cs",
    "教育与心理": "social",
}


def get(key: str) -> dict:
    return TEMPLATES.get(key) or TEMPLATES["imrad"]


def cues_for(key: str) -> dict[str, tuple[str, ...]]:
    tpl = get(key)
    out = {}
    for slot in SLOTS:
        merged = list(BASE_CUES.get(slot, ()))
        merged += list((tpl.get("extra_cues") or {}).get(slot, ()))
        out[slot] = tuple(merged)
    return out


def slot_label(key: str, slot: str) -> str:
    return (get(key).get("slot_labels") or {}).get(slot) or SLOT_LABELS[slot]


def auto_template(paper: dict) -> str:
    """按研究设计与标题线索猜模板。综述类优先，其余看学科标签。"""
    design = paper.get("design") or "unknown"
    if design in ("review", "systematic_review", "meta_analysis"):
        return "review"
    title = (paper.get("title") or "").lower()
    if any(k in title for k in ("survey", "review", "overview", "state of the art", "research agenda")):
        return "review"
    if any(k in title for k in ("essay", "poetics", "narrative", "hermeneutic", "philosoph")):
        return "humanities"
    if any(k in title for k in ("identification strategy", "firm-level", "policy implication")):
        return "econ"
    if design == "theoretical":
        return "humanities"
    if design in ("benchmark", "modeling"):
        return "cs"
    return "imrad"
