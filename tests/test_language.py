"""语言与模型层测试：ChinaXiv、中文过滤、翻译、LLM 配置。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db, llm, library, translate
from core import sources as S
from core.sources import chinaxiv


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    return db


CHINAXIV_FIXTURE = {
    "success": True,
    "data": {
        "total": 2,
        "content": [
            {
                "id": "97834",
                "title": "毛乌素沙地林药间作对根际土壤微生物群落结构的影响",
                "abstracts": "<p>研究林药间作对根际土壤微生物的影响。</p>",
                "authors": ["苟莉", "王瑞霞(2,3)"],
                "keywords": ["毛乌素沙地", "微生物群落"],
                "subjects": ["生物学"],
                "doi": "10.12074/202609.00146",
                "pubyear": "2026",
                "url": "https://chinaxiv.org/abs/97834",
            }
        ],
    },
}


def test_chinaxiv_maps_fields(fresh_db, monkeypatch):
    monkeypatch.setattr(chinaxiv.http, "post_json", lambda *a, **k: CHINAXIV_FIXTURE)
    papers = chinaxiv.search("土壤 微生物", limit=5)
    assert len(papers) == 1
    p = papers[0]
    assert p["title"].startswith("毛乌素沙地")
    assert p["abstract"].startswith("研究林药间作")
    assert p["lang"] == "zh"
    assert p["doi"] == "10.12074/202609.00146"
    assert p["year"] == 2026
    assert p["source"] == "chinaxiv"
    assert "王瑞霞" in p["authors"], "作者上标残留应被去掉"


def test_chinaxiv_falls_back_to_single_word(fresh_db, monkeypatch):
    calls = []

    def fake(url, payload, **kw):
        calls.append(payload["searchText"])
        if payload["searchText"] == "土壤 微生物":
            return {"success": True, "data": {"content": []}}
        return CHINAXIV_FIXTURE

    monkeypatch.setattr(chinaxiv.http, "post_json", fake)
    papers = chinaxiv.search("土壤 微生物", limit=5)
    assert papers, "多词 0 命中时应退到单词重试"
    assert len(calls) >= 2


def test_chinaxiv_handles_failure(fresh_db, monkeypatch):
    monkeypatch.setattr(chinaxiv.http, "post_json", lambda *a, **k: None)
    assert chinaxiv.search("x") == []


def test_lang_filter_injected(monkeypatch):
    captured = {}

    def fake_get_json(url, **kw):
        captured["params"] = kw.get("params", {})
        return None

    monkeypatch.setattr(S.pubmed.http, "get_json", fake_get_json)
    S.pubmed.search("微塑料", lang="zh")
    assert "chinese[la]" in captured["params"]["term"]

    monkeypatch.setattr(S.europepmc.http, "get_json", fake_get_json)
    S.europepmc.search("微塑料", lang="zh")
    assert 'LANG:"chi"' in captured["params"]["query"]

    monkeypatch.setattr(S.openalex.http, "get_json", fake_get_json)
    S.openalex.search("微塑料", lang="zh")
    assert "language:zh" in captured["params"]["filter"]


def test_translate_uses_engine_and_reports(fresh_db, monkeypatch):
    monkeypatch.setattr(translate, "_mymemory", lambda text, s, d: ("微塑料改变土壤结构", ""))
    r = translate.translate("Microplastics alter soil structure", "zh")
    assert r["ok"] and "微塑料" in r["text"]
    assert "MyMemory" in r["engine"]


def test_translate_off_switch(fresh_db):
    library.set_kv("translate_engine", "off")
    r = translate.translate("hello world", "zh")
    assert not r["ok"]
    assert "关闭" in r["error"]
    library.set_kv("translate_engine", "auto")


def test_translate_failure_is_reported(fresh_db, monkeypatch):
    monkeypatch.setattr(translate, "_mymemory", lambda text, s, d: (None, "接口无响应"))
    r = translate.translate("hello", "zh")
    assert not r["ok"] and r["error"]


def test_translate_chunking():
    text = " ".join(["This is a sentence about microplastics and soil."] * 30)
    chunks = translate._split_for_api(text, limit=200)
    assert len(chunks) > 1
    assert all(len(c) <= 240 for c in chunks)


def test_glossary_fixes_untranslated_terms():
    assert "微塑料" in translate._apply_glossary("研究发现 microplastics 影响土壤")


def test_llm_config_roundtrip(fresh_db):
    assert not llm.is_ready()
    llm.save("https://example.com/v1", "sk-test-123456789", "gpt-4o-mini", True)
    st = llm.status()
    assert st["ready"] and st["base"] == "https://example.com/v1"
    assert st["model"] == "gpt-4o-mini"
    assert st["key"].startswith("sk-") and "…" in st["key"], "Key 必须打码"
    assert "123456789" not in st["key"]
    llm.clear()
    assert not llm.is_ready()


def test_llm_chat_without_key(fresh_db):
    text, err = llm.chat([{"role": "user", "content": "hi"}])
    assert text is None and "Key" in err


def test_llm_chat_parses_openai_shape(fresh_db, monkeypatch):
    llm.save("https://example.com/v1", "sk-x", "m", True)
    monkeypatch.setattr(llm.http, "post_json",
                        lambda *a, **k: {"choices": [{"message": {"content": "可用"}}]})
    text, err = llm.chat([{"role": "user", "content": "hi"}])
    assert text == "可用" and err == ""


def test_llm_chat_reports_api_error(fresh_db, monkeypatch):
    llm.save("https://example.com/v1", "sk-x", "m", True)
    monkeypatch.setattr(llm.http, "post_json",
                        lambda *a, **k: {"error": {"message": "invalid api key"}})
    text, err = llm.chat([{"role": "user", "content": "hi"}])
    assert text is None and "invalid api key" in err


def test_deep_summary_prompt_only_uses_given_slots(fresh_db, monkeypatch):
    llm.save("https://example.com/v1", "sk-x", "m", True)
    seen = {}

    def fake_post(url, payload, **kw):
        seen["payload"] = payload
        return {"choices": [{"message": {"content": "摘要"}}]}

    monkeypatch.setattr(llm.http, "post_json", fake_post)
    llm.deep_summary("标题", {"研究问题": ["原文一句"]}, "一句话")
    prompt = seen["payload"]["messages"][-1]["content"]
    assert "原文一句" in prompt
    assert "不得" in seen["payload"]["messages"][0]["content"]
