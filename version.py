"""版本信息。

首个公开版本发布前不预设版本号：开发期的 0.0.x 递增没有信息量，
反而会让「v0.2 支持了什么」这种问题变得没法回答。
发布时在这里写死一个版本号，并同步 CHANGELOG 与 ROADMAP。
"""

__version__ = "dev"
__stage__ = "开发版 · 未发布"
__build__ = "2026-10-28"


def is_released() -> bool:
    return __version__ != "dev"


def label() -> str:
    return f"v{__version__}" if is_released() else __stage__


def info() -> dict:
    return {"version": __version__, "stage": __stage__, "build": __build__,
            "released": is_released()}
