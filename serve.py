"""云端部署入口：监听 $PORT，绑定 0.0.0.0，默认开启公开演示模式。

本地开发请直接用 `streamlit run app.py`（或双击 启动.bat）。
这个文件只负责把 Streamlit 挂到平台注入的端口上，并打开会话隔离。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = os.environ.get("PORT", "8601")

# 公开部署时每个浏览器会话一个独立库，访客之间不互相污染
os.environ.setdefault("SM_PUBLIC_DEMO", "1")

cmd = [
    sys.executable, "-m", "streamlit", "run", str(ROOT / "app.py"),
    "--server.port", str(PORT),
    "--server.address", "0.0.0.0",
    "--server.headless", "true",
    "--server.fileWatcherType", "none",
    "--server.enableCORS", "false",
    "--browser.gatherUsageStats", "false",
]
print(f"[serve] port={PORT} public_demo={os.environ.get('SM_PUBLIC_DEMO')}", flush=True)
sys.exit(subprocess.call(cmd, cwd=str(ROOT)))
