"""统一外部请求层：磁盘缓存 + 退避重试 + 按域名限速 + 可观测统计。

为什么单独一层：六个数据源的配额、限速、错误语义各不相同，
散落在各适配器里会导致「偶发 429 被当成解析失败」这类问题。
这里把所有对外请求收口，上层适配器只关心「拿到 JSON 还是没拿到」。

缓存策略按接口性质分三档：
    search   10 分钟（检索结果变化快，但同一会话内重复点不该再打接口）
    record   24 小时（单篇元数据基本不变）
    static   7 天（学科词表、期刊映射这类）
命中缓存不发请求，离线时也能复现上一次的结果。
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time
from collections import defaultdict
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
CACHE_DIR = DATA_DIR / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

UA = "ScholarMirror/0.1 (academic literature mirror; +https://github.com/)"
HEADERS = {"User-Agent": UA, "Accept": "application/json, text/xml, */*"}

TTL = {"search": 600, "record": 86400, "static": 604800}

# 各域名最小请求间隔（秒）。Semantic Scholar 与 OpenAlex 对匿名调用较严，
# 放慢一点比拿到 429 再重试划算。
HOST_DELAY = {
    "api.openalex.org": 0.45,
    "api.crossref.org": 0.25,
    "export.arxiv.org": 3.0,          # arXiv 官方要求 3 秒 1 次
    "eutils.ncbi.nlm.nih.gov": 0.36,
    "www.ebi.ac.uk": 0.34,
    "api.semanticscholar.org": 1.2,
    "api.unpaywall.org": 1.0,
}
DEFAULT_DELAY = 0.1

_stats_lock = threading.Lock()
_stats = defaultdict(lambda: {"ok": 0, "fail": 0, "cache": 0, "last_error": ""})
_host_locks: dict[str, threading.Lock] = defaultdict(threading.Lock)
_last_hit: dict[str, float] = {}


def _cache_path(key: str) -> Path:
    h = hashlib.blake2b(key.encode("utf-8"), digest_size=12).hexdigest()
    return CACHE_DIR / f"{h}.json"


def _read_cache(key: str, ttl: int):
    path = _cache_path(key)
    if not path.exists():
        return None
    try:
        if time.time() - path.stat().st_mtime > ttl:
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _write_cache(key: str, payload) -> None:
    path = _cache_path(key)
    try:
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        tmp.replace(path)
    except OSError:
        pass


def _throttle(host: str) -> None:
    delay = HOST_DELAY.get(host, DEFAULT_DELAY)
    if delay <= 0:
        return
    lock = _host_locks[host]
    with lock:
        now = time.time()
        wait = delay - (now - _last_hit.get(host, 0.0))
        if wait > 0:
            time.sleep(wait)
        _last_hit[host] = time.time()


def _record(host: str, kind: str, err: str = "") -> None:
    with _stats_lock:
        _stats[host][kind] += 1
        if err:
            _stats[host]["last_error"] = err


def get_json(url: str, *, params: dict | None = None, ttl_kind: str = "search",
             timeout: float = 25.0, retries: int = 3, headers: dict | None = None):
    """GET 并解析 JSON。失败返回 None，由适配器决定是降级还是报错。"""
    key = "json|" + url + "|" + json.dumps(params or {}, sort_keys=True, ensure_ascii=False)
    ttl = TTL.get(ttl_kind, 600)
    cached = _read_cache(key, ttl)
    if cached is not None:
        _record(_host(url), "cache")
        return cached

    host = _host(url)
    for attempt in range(retries + 1):
        try:
            _throttle(host)
            resp = requests.get(url, params=params, headers={**HEADERS, **(headers or {})}, timeout=timeout)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                ra = resp.headers.get("Retry-After")
                wait = float(ra) if (ra or "").replace(".", "", 1).isdigit() else min(1.5 * (2 ** attempt), 8.0)
                time.sleep(wait + random.random() * 0.3)
                continue
            resp.raise_for_status()
            data = resp.json()
            _write_cache(key, data)
            _record(host, "ok")
            return data
        except Exception as exc:  # noqa: BLE001 - 网络层不该把异常抛给 UI
            if attempt >= retries:
                _record(host, "fail", f"{type(exc).__name__}: {exc}")
                return None
            time.sleep(min(1.2 * (2 ** attempt), 6.0) + random.random() * 0.3)
    return None


def post_json(url: str, payload: dict, *, ttl_kind: str = "search", timeout: float = 30.0,
              retries: int = 2, headers: dict | None = None):
    """POST JSON。ChinaXiv 的检索接口只收 POST，GET 会返回 400。"""
    key = "post|" + url + "|" + json.dumps(payload, sort_keys=True, ensure_ascii=False)
    cached = _read_cache(key, TTL.get(ttl_kind, 600))
    if cached is not None:
        _record(_host(url), "cache")
        return cached
    host = _host(url)
    for attempt in range(retries + 1):
        try:
            _throttle(host)
            resp = requests.post(url, json=payload,
                                 headers={**HEADERS, **(headers or {})}, timeout=timeout)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(min(1.5 * (2 ** attempt), 8.0))
                continue
            resp.raise_for_status()
            data = resp.json()
            _write_cache(key, data)
            _record(host, "ok")
            return data
        except Exception as exc:  # noqa: BLE001
            if attempt >= retries:
                _record(host, "fail", f"{type(exc).__name__}: {exc}")
                return None
            time.sleep(min(1.5 * (2 ** attempt), 6.0))
    return None


def get_text(url: str, *, params: dict | None = None, ttl_kind: str = "search",
             timeout: float = 25.0, retries: int = 2, headers: dict | None = None) -> str | None:
    key = "text|" + url + "|" + json.dumps(params or {}, sort_keys=True, ensure_ascii=False)
    ttl = TTL.get(ttl_kind, 600)
    cached = _read_cache(key, ttl)
    if cached is not None:
        _record(_host(url), "cache")
        return cached.get("text")
    host = _host(url)
    for attempt in range(retries + 1):
        try:
            _throttle(host)
            resp = requests.get(url, params=params, headers={**HEADERS, **(headers or {})}, timeout=timeout)
            if resp.status_code in (429, 503) and attempt < retries:
                time.sleep(min(2.0 * (2 ** attempt), 8.0))
                continue
            resp.raise_for_status()
            body = resp.text
            _write_cache(key, {"text": body})
            _record(host, "ok")
            return body
        except Exception as exc:  # noqa: BLE001
            if attempt >= retries:
                _record(host, "fail", f"{type(exc).__name__}: {exc}")
                return None
            time.sleep(min(1.5 * (2 ** attempt), 5.0))
    return None


def _host(url: str) -> str:
    try:
        return url.split("//", 1)[1].split("/", 1)[0]
    except IndexError:
        return url


def stats() -> dict:
    """给「数据源状态」面板用：每个域名成功/失败/命中缓存次数与最近错误。"""
    with _stats_lock:
        return {h: dict(v) for h, v in _stats.items()}


def cache_size() -> tuple[int, float]:
    files = list(CACHE_DIR.glob("*.json"))
    size = sum(f.stat().st_size for f in files if f.exists())
    return len(files), size / 1024 / 1024


def clear_cache() -> int:
    n = 0
    for f in CACHE_DIR.glob("*.json"):
        try:
            f.unlink()
            n += 1
        except OSError:
            pass
    return n


def polite_mailto() -> str:
    """OpenAlex / Crossref 的 polite pool 需要一个联系邮箱。用户可覆盖。"""
    return os.environ.get("SCHOLAR_MIRROR_MAILTO", "scholar-mirror@example.com")
