"""内置演示数据：12 篇跨学科文献，离线可用。

用途有两个：第一次打开时不联网也能看到完整效果；以及在没有网络的环境里
验证分析链路是否正常。数据是人工撰写的示例摘要，不对应真实发表物，
DOI 也是占位值 —— 界面上会标明「演示数据」。
"""
from __future__ import annotations

from core import schema

_RAW = [
    {
        "title": "Plasma p-tau217 predicts amyloid status in a multicentre memory clinic cohort",
        "abstract": (
            "Background: Blood-based biomarkers are needed to triage patients for amyloid PET. "
            "Methods: We measured plasma p-tau217 in 612 participants from three memory clinics, "
            "followed for a median of 48 months, and compared it with amyloid PET and CSF testing. "
            "Results: p-tau217 discriminated amyloid status with an AUC of 0.94 (95% CI 0.91 to 0.97), "
            "outperforming p-tau181 (AUC 0.87, P<0.001). Higher baseline p-tau217 was associated with "
            "faster cognitive decline (HR 2.1, 95% CI 1.6 to 2.8 per doubling). "
            "Conclusions: Plasma p-tau217 is an accurate triage test in memory clinics. "
            "Limitations: single assay platform, and follow-up shorter than 5 years. "
            "Future work should test implementation in primary care and in diverse populations."
        ),
        "authors": ["Karim N", "Olsen M", "Ferreira L", "Yamada H"],
        "year": 2024, "venue": "Alzheimer's & Dementia", "doi": "10.1000/demo.101",
        "cited_by": 148, "keywords": ["p-tau217", "amyloid", "blood biomarker", "diagnosis"],
        "is_oa": True, "type": "article", "sources": ["pubmed", "europepmc"],
    },
    {
        "title": "Tau PET and hippocampal volume jointly predict conversion to dementia",
        "abstract": (
            "Background: Conversion from mild cognitive impairment to dementia is heterogeneous. "
            "Methods: We imaged 240 participants with tau PET and structural MRI at baseline and "
            "repeated cognitive testing every 12 months for 36 months. "
            "Results: Combining tau burden in the entorhinal cortex with hippocampal volume predicted "
            "conversion with an AUC of 0.89, compared with 0.81 for hippocampal volume alone (P=0.01). "
            "Conclusions: Multimodal imaging improves prognostic accuracy. "
            "Limitations: single-centre cohort with predominantly White participants."
        ),
        "authors": ["Rinaldi P", "Chen W", "Adeyemi O"],
        "year": 2023, "venue": "Neurology", "doi": "10.1000/demo.102",
        "cited_by": 96, "keywords": ["tau PET", "hippocampus", "conversion", "MRI"],
        "is_oa": False, "type": "article", "sources": ["pubmed"],
    },
    {
        "title": "Deep learning for Alzheimer disease diagnosis using structural MRI: a systematic review",
        "abstract": (
            "Background: Deep learning models for Alzheimer disease diagnosis are numerous but rarely validated. "
            "Methods: We searched PubMed and Embase for studies published between 2015 and 2024 and included "
            "94 studies covering 61 cohorts; risk of bias was assessed with QUADAS-2. "
            "Results: Reported AUCs ranged from 0.78 to 0.99, but only 12 studies used external validation. "
            "Heterogeneity was high (I2 = 87%), and 41 studies reused the same public datasets. "
            "Conclusions: Reported performance is likely optimistic; external validation and standardized "
            "preprocessing are needed before clinical deployment. "
            "Limitations: many included studies reported insufficient methodological detail."
        ),
        "authors": ["Novak J", "Silva R", "Hoffmann K"],
        "year": 2025, "venue": "npj Digital Medicine", "doi": "10.1000/demo.103",
        "cited_by": 37, "keywords": ["deep learning", "MRI", "systematic review", "validation"],
        "is_oa": True, "type": "review", "sources": ["openalex", "crossref"],
    },
    {
        "title": "Biodegradable microplastics alter soil aggregate distribution and bacterial networks",
        "abstract": (
            "Background: Biodegradable plastics are promoted as a sustainable alternative, but their "
            "effects on soil structure remain unclear. "
            "Methods: Two microplastic types (polyethylene and polylactic acid) were mixed with a silty "
            "loam soil at 0.5% (w/w) and incubated in a greenhouse for 12 months; aggregates and bacterial "
            "communities were measured at four time points. "
            "Results: Microaggregates increased from 17% to 32% under polyethylene, while macroaggregates "
            "fell from 84% to 61%. Bacterial diversity decreased by 12% and co-occurrence network "
            "complexity increased. "
            "Conclusions: Both types alter soil structure, with stronger effects for polyethylene. "
            "Limitations: single soil type and one dose; field validation is needed."
        ),
        "authors": ["Zhang L", "Meyer A", "Okafor C"],
        "year": 2024, "venue": "Environmental Pollution", "doi": "10.1000/demo.201",
        "cited_by": 58, "keywords": ["microplastics", "soil aggregates", "bacteria", "biodegradable"],
        "is_oa": False, "type": "article", "sources": ["pubmed", "europepmc"],
    },
    {
        "title": "Microplastics reduce soil microbial diversity: a 90-day incubation study",
        "abstract": (
            "We incubated agricultural soil with polyethylene microplastics at 0%, 1% and 5% (w/w) for 90 days. "
            "Bacterial diversity declined significantly at 5% (Shannon index −0.42, P<0.01), and nitrogen "
            "cycling enzyme activity fell by 23%. "
            "Conclusions: High-dose microplastic exposure reduces microbial diversity and nitrogen turnover. "
            "Limitations: short incubation and a single soil texture limit generalization."
        ),
        "authors": ["Ibrahim S", "Wang Y"],
        "year": 2022, "venue": "Soil Biology and Biochemistry", "doi": "10.1000/demo.202",
        "cited_by": 121, "keywords": ["microplastics", "microbial diversity", "incubation", "nitrogen"],
        "is_oa": False, "type": "article", "sources": ["crossref"],
    },
    {
        "title": "Field survey of microplastic accumulation along an agricultural gradient",
        "abstract": (
            "Background: Most microplastic studies are laboratory incubations. "
            "Methods: We sampled soils from 24 farms across an urbanization gradient and quantified "
            "microplastic abundance by FTIR imaging. "
            "Results: Abundance ranged from 42 to 1280 particles per kg, correlated with mulch film use "
            "(r = 0.61, P<0.001). "
            "Conclusions: Agricultural practices dominate microplastic loading at the field scale. "
            "Limitations: cross-sectional design cannot establish temporal trends."
        ),
        "authors": ["Duarte M", "Klein B", "Sun Q"],
        "year": 2023, "venue": "Science of the Total Environment", "doi": "10.1000/demo.203",
        "cited_by": 44, "keywords": ["microplastics", "field survey", "agriculture", "FTIR"],
        "is_oa": True, "type": "article", "sources": ["openalex"],
    },
    {
        "title": "Chain-of-thought prompting improves multi-step reasoning in small language models",
        "abstract": (
            "We evaluate chain-of-thought prompting on five reasoning benchmarks using models with 1B to 7B "
            "parameters. Few-shot chain-of-thought improves accuracy by 8.4 points on average over standard "
            "prompting, but gains vanish on tasks requiring external knowledge. "
            "We also find that self-consistency decoding adds a further 3.1 points at 5x inference cost. "
            "Limitations: evaluation is limited to English benchmarks and short contexts. "
            "Future work should examine multilingual settings and tool use."
        ),
        "authors": ["Park J", "Iyer A", "Lund E"],
        "year": 2024, "venue": "arXiv 预印本", "doi": "",
        "arxiv_id": "2401.00001", "cited_by": 22,
        "keywords": ["chain-of-thought", "reasoning", "prompting", "language model"],
        "is_oa": True, "type": "preprint", "sources": ["arxiv"],
    },
    {
        "title": "Chain-of-Thought Prompting Improves Multi-Step Reasoning in Small Language Models: An Empirical Study",
        "abstract": (
            "We evaluate chain-of-thought prompting on five reasoning benchmarks using models with 1B to 7B "
            "parameters. Few-shot chain-of-thought improves accuracy by 8.4 points on average over standard "
            "prompting, but gains vanish on tasks requiring external knowledge. "
            "We also find that self-consistency decoding adds a further 3.1 points at 5x inference cost. "
            "Limitations: evaluation is limited to English benchmarks and short contexts."
        ),
        "authors": ["Park J", "Iyer A", "Lund E"],
        "year": 2025, "venue": "Proceedings of ACL", "doi": "10.1000/demo.301",
        "cited_by": 61, "keywords": ["chain-of-thought", "reasoning", "prompting"],
        "is_oa": False, "type": "conference", "sources": ["crossref", "semantic"],
    },
    {
        "title": "Do reasoning benchmarks measure reasoning? Evidence from controlled perturbations",
        "abstract": (
            "Background: Benchmark scores are often treated as evidence of reasoning ability. "
            "Methods: We perturb 2,400 benchmark items by changing surface form while preserving the "
            "underlying solution path, and evaluate 11 models. "
            "Results: Accuracy drops by 14.7 points on average under surface perturbations, with larger "
            "drops for smaller models. "
            "Conclusions: Current benchmarks partially measure pattern matching rather than reasoning. "
            "Limitations: perturbation templates cover only arithmetic and logical tasks."
        ),
        "authors": ["Moreau T", "Singh R"],
        "year": 2025, "venue": "arXiv 预印本", "doi": "", "arxiv_id": "2502.00002",
        "cited_by": 9, "keywords": ["benchmark", "reasoning", "robustness", "evaluation"],
        "is_oa": True, "type": "preprint", "sources": ["arxiv", "semantic"],
    },
    {
        "title": "Minimum wage increases and employment: evidence from contiguous county pairs",
        "abstract": (
            "We estimate the employment effects of state minimum wage increases using a "
            "difference-in-differences design on contiguous county pairs from 2000 to 2019. "
            "Data come from administrative payroll records covering 2.1 million workers. "
            "Results: a 10% minimum wage increase reduces employment by 1.2 percentage points "
            "(95% CI −2.1 to −0.3), driven by the retail and hospitality sectors. "
            "Placebo tests on bordering counties without increases show no effect. "
            "Policy implications for regional labor markets are discussed. "
            "Limitations: administrative data do not cover informal employment."
        ),
        "authors": ["Berger H", "Osei K"],
        "year": 2021, "venue": "Journal of Labor Economics", "doi": "10.1000/demo.401",
        "cited_by": 210, "keywords": ["minimum wage", "employment", "difference-in-differences"],
        "is_oa": False, "type": "article", "sources": ["crossref", "openalex"],
    },
    {
        "title": "Minimum wage and firm entry: a regression discontinuity approach",
        "abstract": (
            "We study how minimum wage thresholds affect firm entry using a regression discontinuity design "
            "on state borders. Firm registration data cover 480,000 establishments. "
            "Results: crossing the threshold reduces entry by 6.3% in low-margin sectors, with no detectable "
            "effect on high-margin sectors. "
            "Conclusions: adjustment operates through firm entry rather than incumbent employment. "
            "Limitations: the running variable is measured with error near the threshold."
        ),
        "authors": ["Alvarez D", "Kim S", "Wright P"],
        "year": 2023, "venue": "Review of Economics and Statistics", "doi": "10.1000/demo.402",
        "cited_by": 63, "keywords": ["minimum wage", "firm entry", "regression discontinuity"],
        "is_oa": False, "type": "article", "sources": ["crossref"],
    },
    {
        "title": "Teachers' experiences of emergency remote teaching: a qualitative study",
        "abstract": (
            "This qualitative study examines how teachers experienced the shift to emergency remote teaching. "
            "We conducted semi-structured interviews with 24 teachers from 8 schools and applied thematic "
            "analysis with member checking. "
            "Results: three themes emerged — workload intensification, digital inequity, and assessment "
            "improvisation. Participants reported inadequate institutional support and persistent uncertainty. "
            "Conclusions: remote teaching amplified existing inequalities rather than creating new ones. "
            "Limitations: small purposive sample from a single district; findings are transferable rather "
            "than generalizable."
        ),
        "authors": ["Fischer A", "Nakamura R"],
        "year": 2022, "venue": "Teaching and Teacher Education", "doi": "10.1000/demo.501",
        "cited_by": 88, "keywords": ["remote teaching", "qualitative", "digital equity", "teachers"],
        "is_oa": True, "type": "article", "sources": ["crossref", "openalex"],
    },
    # 同一条记录的另一个源版本：用来演示「跨源合并」把两条并成一条
    {
        "title": "Plasma p-tau217 predicts amyloid status in memory clinic cohorts",
        "abstract": "Plasma p-tau217 discriminated amyloid status with an AUC of 0.94 in 612 participants from three memory clinics.",
        "authors": ["Karim N", "Olsen M"],
        "year": 2024, "venue": "Alzheimer's & Dementia", "doi": "10.1000/demo.101",
        "cited_by": 150, "keywords": ["p-tau217", "amyloid"],
        "is_oa": True, "type": "article", "sources": ["openalex"],
    },
]


def papers() -> list[dict]:
    out = []
    for i, raw in enumerate(_RAW):
        p = schema.normalize_paper({**raw, "source": (raw.get("sources") or ["demo"])[0]})
        p["sid"] = p.get("sid") or f"demo:{i}"
        p["demo"] = True
        out.append(p)
    return out


def meta() -> dict:
    return {
        "query": "演示数据集（跨学科 12 篇）",
        "discipline": "通用 / 跨学科",
        "sources": ["pubmed", "europepmc", "openalex", "crossref", "arxiv", "semantic"],
        "raw_count": 13,
        "year_from": 2021,
    }
