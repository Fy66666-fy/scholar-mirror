"""更新日志解析：把 CHANGELOG.md 读成结构化数据，供「更新日志」页面渲染。

格式沿用 Keep a Changelog：
    ## [0.2.0] - 2026-10-28
    ### 新增
    - **研究画像**：一句话说明
"""
from __future__ import annotations

import re
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"

_RELEASE = re.compile(r"^##\s*\[?([\w.\-]+)\]?\s*(?:-\s*(\d{4}-\d{2}-\d{2}))?\s*$")
_SECTION = re.compile(r"^###\s*(.+?)\s*$")
_ITEM = re.compile(r"^[-*]\s+(.*)$")

SECTION_TONES = {
    "新增": "ok", "Added": "ok",
    "改进": "solid", "Changed": "solid",
    "修复": "warn", "Fixed": "warn",
    "移除": "", "Removed": "",
    "文档": "gold", "Docs": "gold",
    "测试": "gold", "Tests": "gold",
}


def parse(text: str | None = None) -> list[dict]:
    text = text if text is not None else (CHANGELOG.read_text(encoding="utf-8")
                                          if CHANGELOG.exists() else "")
    releases: list[dict] = []
    cur: dict | None = None
    section: dict | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        m = _RELEASE.match(line)
        if m:
            cur = {"version": m.group(1), "date": m.group(2) or "", "sections": []}
            releases.append(cur)
            section = None
            continue
        if cur is None:
            continue
        m = _SECTION.match(line)
        if m:
            section = {"title": m.group(1), "items": []}
            cur["sections"].append(section)
            continue
        m = _ITEM.match(line)
        if m and section is not None:
            item = m.group(1).strip()
            bold = re.match(r"\*\*(.+?)\*\*\s*[:：]?\s*(.*)", item)
            if bold:
                section["items"].append({"title": bold.group(1), "text": bold.group(2)})
            else:
                section["items"].append({"title": "", "text": item})
    return releases


def current() -> dict | None:
    releases = parse()
    return releases[0] if releases else None


def tone(section_title: str) -> str:
    return SECTION_TONES.get(section_title, "")


def stats() -> dict:
    releases = parse()
    items = sum(len(s["items"]) for r in releases for s in r["sections"])
    return {"releases": len(releases), "items": items,
            "latest": releases[0]["version"] if releases else "—"}
