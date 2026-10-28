"""文本算法底座。

本项目所有「理解」能力都落在这一层：分句、分词、TF-IDF、余弦相似度、
SimHash 指纹、shingle 重叠、关键数值抽取。全部为纯 Python + numpy 实现，
不依赖 jieba / sklearn，保证离线可用、装完就能跑。

设计上有两个约束：
1. 中英混排要都能处理。中文没有分词器，用字符二元组（bigram）替代，
   对「摘要级」文本的相似度判断足够，且不会因为专有名词被切碎而失真。
2. 每个函数都必须对脏数据宽容。真实接口返回的摘要常带 HTML 标签、
   版权尾巴、"Abstract" 前缀、连续空白，清洗放在 clean_abstract 里统一做。
"""
from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

import numpy as np

# --------------------------------------------------------------------------
# 清洗
# --------------------------------------------------------------------------
_TAG_RE = re.compile(r"<[^>]{1,200}>")
_WS_RE = re.compile(r"\s+")
# 摘要尾部常见的版权 / 出版商声明，删掉以免污染关键词
_TAIL_PATTERNS = [
    r"©\s*\d{4}.*$",
    r"Copyright\s+©.*$",
    r"All rights reserved\.?.*$",
    r"Published by .*$",
    r"This article is protected by copyright.*$",
    r"^(Abstract|ABSTRACT|摘要)\s*[:：.\-—]?\s*",
]


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = _TAG_RE.sub(" ", str(text))
    text = (
        text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
        .replace("\u00a0", " ").replace("\u2009", " ").replace("\u202f", " ")
    )
    return _WS_RE.sub(" ", text).strip()


def clean_abstract(text: str) -> str:
    text = clean_text(text)
    if not text:
        return ""
    for pat in _TAIL_PATTERNS:
        text = re.sub(pat, "", text, flags=re.I | re.S).strip()
    return text


# --------------------------------------------------------------------------
# 语言判断与分句
# --------------------------------------------------------------------------
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def detect_lang(text: str) -> str:
    """粗略判断语种：zh / en。只用于选择分词策略与展示顺序。"""
    if not text:
        return "en"
    cjk = len(_CJK_RE.findall(text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if cjk == 0:
        return "en"
    return "zh" if cjk * 3 >= latin else "en"


# 句号后不应断句的常见缩写与情形
_ABBREV = {
    "al", "e.g", "i.e", "vs", "fig", "figs", "eq", "eqs", "ref", "refs",
    "dr", "mr", "mrs", "ms", "prof", "approx", "cf", "ca", "no", "vol",
    "pp", "p", "st", "jr", "sr", "inc", "ltd", "co", "et", "resp", "suppl",
    "min", "max", "sd", "se", "ci", "hr", "or", "rr", "n", "u.s", "u.k",
}
_SENT_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\[\"'“])")
_ZH_END = re.compile(r"(?<=[。！？；])")


def split_sentences(text: str, min_len: int = 2) -> list[str]:
    """分句。英文按句末标点+大写开头切，中文按。！？；切。

    处理两类易错点：
    - "et al. 2020" / "e.g. 3.5" / "Fig. 2" 不应断句；
    - 小数 "0.05" 两侧不应断句（由后向断言大写/数字+括号缓解，
      再对纯数字开头做一次合并）。
    """
    text = clean_text(text)
    if not text:
        return []
    if detect_lang(text) == "zh":
        raw = [s for s in _ZH_END.split(text) if s.strip()]
    else:
        raw = _SENT_END.split(text)
        # 合并被误切的片段：前一段以缩写结尾，或后一段以纯数字/小写开头
        merged: list[str] = []
        for seg in raw:
            seg = seg.strip()
            if not seg:
                continue
            if merged:
                prev = merged[-1]
                tail = prev.rstrip(".").split(" ")[-1].lower()
                starts_num = bool(re.match(r"^[\d,.\-–]", seg))
                if tail in _ABBREV or (prev.endswith(".") and starts_num):
                    merged[-1] = prev + " " + seg
                    continue
            merged.append(seg)
        raw = merged
    out = []
    for s in raw:
        s = s.strip()
        if len(s) >= min_len:
            out.append(s)
    return out


# --------------------------------------------------------------------------
# 分词
# --------------------------------------------------------------------------
STOPWORDS_EN = set("""
a an the and or but if then than that this these those of in on at to for from by with without
as is are was were be been being do does did doing have has had having not no nor so such
we our us they their them it its he she his her you your i my me
can could may might must shall should will would
also both each few more most other some any all only own same very just about into over after
before between during under above below up down out off again further once here there when where
why how what which who whom whose
using used use uses based results result study studies paper article show shows showed shown
however therefore thus moreover furthermore although though while whereas because since
one two three et al fig figure table eq equation respectively including included
new novel high low large small significantly significant compared comparison
""".split())

# 中文虚词与学术套话（用于关键词与摘要句子打分）
STOPWORDS_ZH = set("""
的 了 和 与 及 或 在 是 有 为 对 从 到 被 把 而 也 都 就 又 还 但 却 则 因 由 于 之 其 此 该 本
我们 本文 本研究 该研究 结果显示 研究表明 结果 方法 目的 结论 分析 探讨 通过 进行 具有 可以 能够
以及 同时 此外 然而 因此 并且 不同 相关 影响 作用 情况 问题 方面 过程 水平 程度 显著 明显 提高 降低
""".split())

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-']{1,}|[\u4e00-\u9fff]+|\d+(?:\.\d+)?")

_EN_SUFFIX = ("ational", "ization", "ations", "ation", "ingly", "edly", "ies", "ing", "ed", "es", "s", "ly")


def _stem(word: str) -> str:
    """极简词干化：只处理最常见的英文屈折后缀，避免过度合并。"""
    w = word.lower()
    if len(w) <= 4 or not w.isalpha():
        return w
    for suf in _EN_SUFFIX:
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            base = w[: -len(suf)]
            if suf == "ies":
                base += "y"
            return base
    return w


def tokenize(text: str, lang: str | None = None) -> list[str]:
    """分词：英文词干化并去停用词；中文取字符二元组并去停用词。"""
    text = clean_text(text)
    if not text:
        return []
    lang = lang or detect_lang(text)
    tokens: list[str] = []
    for chunk in _WORD_RE.findall(text):
        if _CJK_RE.match(chunk):
            if chunk in STOPWORDS_ZH:
                continue
            if len(chunk) == 1:
                continue
            for i in range(len(chunk) - 1):
                bg = chunk[i: i + 2]
                if bg not in STOPWORDS_ZH:
                    tokens.append(bg)
        else:
            low = chunk.lower()
            if low in STOPWORDS_EN or len(low) < 3:
                continue
            if low.isdigit():
                continue
            tokens.append(_stem(low))
    return tokens


def term_counts(text: str) -> Counter:
    return Counter(tokenize(text))


def surface_map(texts: list[str]) -> dict[str, str]:
    """词干 → 最常出现的原始写法。

    tokenize 会把 "microplastics" 归成 "microplast"，聚类命名时直接显示词干
    会很难看。这里保留一份「原始形态」对照，展示时用它还原。
    """
    counts: dict[str, Counter] = {}
    for text in texts:
        for raw in _WORD_RE.findall(clean_text(text or "")):
            if _CJK_RE.match(raw):
                continue
            low = raw.lower()
            if len(low) < 3 or low in STOPWORDS_EN:
                continue
            stem = _stem(low)
            counts.setdefault(stem, Counter())[low] += 1
    return {stem: c.most_common(1)[0][0] for stem, c in counts.items() if c}


def keywords_from_text(text: str, top_n: int = 10) -> list[str]:
    """无监督关键词：词频 × 长度权重 × 首段加成，去重后取前 N。

    比纯词频好在：长词（更具体）权重更高，出现在标题/首句的词加权，
    能压掉 "patient"、"model" 这类到处都是的高频泛词。
    """
    tokens = tokenize(text)
    if not tokens:
        return []
    counts = Counter(tokens)
    first_part = " ".join(split_sentences(text)[:2])
    head_tokens = set(tokenize(first_part))
    scored = {}
    for tok, c in counts.items():
        length_bonus = 1.0 + min(len(tok), 12) * 0.06
        head_bonus = 1.35 if tok in head_tokens else 1.0
        scored[tok] = c * length_bonus * head_bonus
    ranked = sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))
    out, seen = [], set()
    for tok, _ in ranked:
        if tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
        if len(out) >= top_n:
            break
    return out


# --------------------------------------------------------------------------
# TF-IDF 与相似度
# --------------------------------------------------------------------------
class Tfidf:
    """极简 TF-IDF：sublinear tf + 平滑 idf + L2 归一化。

    fit_transform 后同时保留稀疏字典（用于解释单词贡献）和稠密矩阵
    （用于聚类/布局的向量运算），避免上层再转一次。
    """

    def __init__(self, min_df: int = 1, max_features: int = 4000):
        self.min_df = min_df
        self.max_features = max_features
        self.vocab: dict[str, int] = {}
        self.idf: np.ndarray | None = None
        self.matrix: np.ndarray | None = None

    def fit_transform(self, docs: list[str]) -> np.ndarray:
        tokenized = [tokenize(d) for d in docs]
        df = Counter()
        for toks in tokenized:
            df.update(set(toks))
        n = max(len(docs), 1)
        items = [(t, c) for t, c in df.items() if c >= self.min_df]
        items.sort(key=lambda kv: (-kv[1], kv[0]))
        items = items[: self.max_features]
        self.vocab = {t: i for i, (t, _) in enumerate(items)}
        idf = np.zeros(len(self.vocab), dtype=np.float64)
        for t, i in self.vocab.items():
            idf[i] = math.log((n + 1) / (df[t] + 1)) + 1.0
        self.idf = idf
        mat = np.zeros((len(docs), len(self.vocab)), dtype=np.float64)
        for r, toks in enumerate(tokenized):
            if not toks:
                continue
            tf = Counter(t for t in toks if t in self.vocab)
            for t, c in tf.items():
                mat[r, self.vocab[t]] = (1.0 + math.log(c)) * idf[self.vocab[t]]
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self.matrix = mat / norms
        return self.matrix

    def transform_one(self, text: str) -> np.ndarray:
        if self.idf is None:
            raise RuntimeError("Tfidf 尚未 fit")
        vec = np.zeros(len(self.vocab), dtype=np.float64)
        tf = Counter(t for t in tokenize(text) if t in self.vocab)
        for t, c in tf.items():
            vec[self.vocab[t]] = (1.0 + math.log(c)) * self.idf[self.vocab[t]]
        n = np.linalg.norm(vec)
        return vec / n if n else vec

    def top_terms(self, row: int, n: int = 6) -> list[str]:
        if self.matrix is None or not self.vocab:
            return []
        inv = {i: t for t, i in self.vocab.items()}
        vec = self.matrix[row]
        idx = np.argsort(-vec)[:n]
        return [inv[i] for i in idx if vec[i] > 0]


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def cosine_matrix(mat: np.ndarray) -> np.ndarray:
    if mat.size == 0:
        return np.zeros((0, 0))
    norms = np.linalg.norm(mat, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    m = mat / norms
    sim = m @ m.T
    np.clip(sim, 0.0, 1.0, out=sim)
    return sim


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / len(a | b)


# --------------------------------------------------------------------------
# 指纹：SimHash + shingle
# --------------------------------------------------------------------------
def simhash64(text: str) -> int:
    """64 位 SimHash。用 blake2b 做特征哈希，稳定、跨进程一致。"""
    tokens = tokenize(text)
    if not tokens:
        return 0
    weights = Counter(tokens)
    bits = [0.0] * 64
    for tok, w in weights.items():
        h = int.from_bytes(hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest(), "big")
        for i in range(64):
            bits[i] += w if (h >> i) & 1 else -w
    out = 0
    for i in range(64):
        if bits[i] > 0:
            out |= 1 << i
    return out


def hamming(a: int, b: int) -> int:
    return int(a ^ b).bit_count()


def shingles(text: str, k: int = 3) -> set[str]:
    """词级 k-shingle，用于查重中的「连续片段重叠」判断。"""
    toks = tokenize(text)
    if len(toks) < k:
        return {" ".join(toks)} if toks else set()
    return {" ".join(toks[i: i + k]) for i in range(len(toks) - k + 1)}


def containment(a: set, b: set) -> float:
    """a 被 b 覆盖的比例（查重看「这段话有多少能在语料里找到」）。"""
    if not a:
        return 0.0
    return len(a & b) / len(a)


# --------------------------------------------------------------------------
# 关键数值抽取（摘要里的证据锚点）
# --------------------------------------------------------------------------
_NUM_PATTERNS = [
    ("p_value", re.compile(r"\b[Pp]\s*[<>=≤≥]\s*0?\.\d+")),
    ("ci", re.compile(r"\b9[05]\s*%\s*(?:CI|confidence interval)\s*[:：]?\s*[\[(]?\s*-?\d[\d.,]*\s*(?:to|[-–,])\s*-?\d[\d.,]*", re.I)),
    ("effect", re.compile(r"\b(?:HR|OR|RR|aHR|aOR|IRR|β|beta)\s*[=:≈]?\s*\d?\.?\d+\s*(?:\([^)]{0,40}\))?", re.I)),
    ("percent", re.compile(r"(?<![\d.])\d{1,3}(?:\.\d+)?\s?%")),
    ("sample", re.compile(r"\b(?:n\s*=\s*|N\s*=\s*)\d[\d,]*|\b\d[\d,]{1,}\s+(?:patients|participants|subjects|samples|respondents|cases|children|adults|records|images|documents)\b", re.I)),
    ("mean_sd", re.compile(r"\d+(?:\.\d+)?\s*(?:±|\+/-|\+-)\s*\d+(?:\.\d+)?"),),
    ("auc", re.compile(r"\bAUC\s*(?:of|[:=])?\s*0?\.\d+", re.I)),
    ("accuracy", re.compile(r"\b(?:accuracy|F1|precision|recall)\s*(?:of|[:=])?\s*(?:0?\.\d+|\d{1,3}(?:\.\d+)?\s?%)", re.I)),
]
_ZH_NUM_PATTERNS = [
    ("percent", re.compile(r"(?<![\d.])\d{1,3}(?:\.\d+)?\s?%")),
    ("sample", re.compile(r"\d[\d,]*\s*(?:例|名|位|人|份|篇|个样本|例患者)")),
    ("p_value", re.compile(r"[Pp]\s*[<>=]\s*0?\.\d+")),
]


def extract_numbers(text: str) -> list[dict]:
    """返回 [{'type','value','start','end'}]，用于在原文里高亮证据锚点。"""
    if not text:
        return []
    found: list[dict] = []
    seen_spans: list[tuple[int, int]] = []
    for typ, pat in _NUM_PATTERNS + (_ZH_NUM_PATTERNS if detect_lang(text) == "zh" else []):
        for m in pat.finditer(text):
            s, e = m.span()
            if any(not (e <= s0 or s >= e0) for s0, e0 in seen_spans):
                continue
            seen_spans.append((s, e))
            found.append({"type": typ, "value": m.group(0).strip(), "start": s, "end": e})
    found.sort(key=lambda x: x["start"])
    return found


def extract_sample_size(text: str) -> int | None:
    """从摘要里抽最大样本量。取最大值而非第一个，避免把「3 组」当成样本量。"""
    if not text:
        return None
    cands: list[int] = []
    for m in re.finditer(r"(?:n\s*=\s*|N\s*=\s*)(\d[\d,]*)", text):
        cands.append(int(m.group(1).replace(",", "")))
    for m in re.finditer(r"(\d[\d,]{1,})\s+(?:patients|participants|subjects|samples|respondents|cases|children|adults|records|images|documents|articles|studies|papers)\b", text, re.I):
        cands.append(int(m.group(1).replace(",", "")))
    for m in re.finditer(r"(\d[\d,]{1,})\s*(?:例|名|位|人|份|篇)", text):
        cands.append(int(m.group(1).replace(",", "")))
    cands = [c for c in cands if 0 < c < 100_000_000]
    return max(cands) if cands else None


def fmt_int(n: int | float | None) -> str:
    if n is None:
        return "—"
    return f"{int(n):,}"


def shorten(text: str, limit: int = 180) -> str:
    text = clean_text(text)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    for sep in ("。", ". ", "；", "; "):
        idx = cut.rfind(sep)
        if idx > limit * 0.6:
            return cut[: idx + len(sep)].strip()
    return cut.rstrip() + "…"
