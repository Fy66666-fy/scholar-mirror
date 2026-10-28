"""版本号唯一来源。更新日志见 CHANGELOG.md，阶段规划见 ROADMAP.md。"""

__version__ = "0.2.0"
__release_date__ = "2026-10-28"
__codename__ = "Workbench"

# 版本语义：0.x 阶段次版本号对应一个可用里程碑，不是「不兼容」信号
HISTORY = [
    ("0.2.0", "2026-10-28", "Workbench", "研究工作台：画像、推荐、项目、笔记、活动流、更新日志、设置"),
    ("0.1.0", "2026-10-28", "Mirror", "首个版本：六源检索、学科摘要、三层查重、关联图谱、聚类精选、缺口分析"),
]


def info() -> dict:
    return {"version": __version__, "date": __release_date__,
            "codename": __codename__, "history": HISTORY}
