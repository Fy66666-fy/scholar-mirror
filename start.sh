#!/usr/bin/env bash
# 文献镜像 ScholarMirror 启动脚本（macOS / Linux）
set -e
cd "$(dirname "$0")"

PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done

if [ -z "$PY" ]; then
  echo "没有找到 python3，请先安装 Python 3.10+"
  exit 1
fi

if ! "$PY" -c "import streamlit, numpy, plotly" >/dev/null 2>&1; then
  echo "安装依赖中..."
  "$PY" -m pip install -r requirements.txt
fi

echo "文献镜像启动中： http://localhost:8601"
exec "$PY" -m streamlit run app.py --server.port 8601
