#!/usr/bin/env bash
# 后端开发启动脚本：校验 conda 环境 → 安装依赖 → 启动 uvicorn（热重载）
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ "${CONDA_DEFAULT_ENV:-}" != "vizguide" ]]; then
  echo "[dev.sh] 当前 conda 环境不是 vizguide（当前: ${CONDA_DEFAULT_ENV:-无}）"
  echo "[dev.sh] 请先执行: conda activate vizguide"
  exit 1
fi

echo "[dev.sh] python: $(which python)"
python -m pip install -r requirements.txt --quiet

ARGS=(--host 127.0.0.1 --port 8000 --reload)
if [[ -f .env ]]; then
  ARGS+=(--env-file .env)
  echo "[dev.sh] 使用 .env 配置"
fi
exec python -m uvicorn app.main:app "${ARGS[@]}"
