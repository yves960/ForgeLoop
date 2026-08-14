#!/usr/bin/env bash
# setup-oikb.sh — oikb 一次性安装/配置脚本（占位模板，需用户填写 API key）
#
# ⚠️ 安全约定: 用户的 Open WebUI API key 一律不硬编码进任何仓库文件。
#    请在本脚本里填入后运行；key 只会写入 oikb 自己的用户级配置，不进 git。
#
# API key 获取: Open WebUI → 设置 → 账号 → API 密钥（Settings → Account → API Keys）
set -euo pipefail

# ====== 请填写（必填）======================================
# 把下面替换成你的真实 API key，例如 sk-xxxxxxxxxxxx
OIKB_API_KEY="sk-REPLACE_ME"
# ===========================================================

# Open WebUI 地址（默认本机 8080，可用环境变量覆盖）
OIKB_URL="${OIKB_URL:-http://127.0.0.1:8080}"

if [[ "${OIKB_API_KEY}" == *"REPLACE_ME"* ]]; then
  echo "[setup-oikb] 请先编辑 $0，把 OIKB_API_KEY 换成你的真实 API key。" >&2
  exit 1
fi

# 1) 安装 oikb（user 级；需 Python >= 3.11）
if ! command -v oikb >/dev/null 2>&1; then
  PY=""
  for cand in python3.13 python3.12 python3.11; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
  done
  if [ -z "$PY" ]; then
    echo "[setup-oikb] 未找到 Python >= 3.11，请先安装后再运行本脚本。" >&2
    exit 1
  fi
  echo "[setup-oikb] 使用 ${PY} 安装 oikb（user 级）..."
  "$PY" -m pip install --user oikb || "$PY" -m pip install --user --break-system-packages oikb
fi

# 2) 写入 oikb 配置（url + token，存于用户级配置，不进仓库）
oikb config set url "${OIKB_URL}"
oikb config set token "${OIKB_API_KEY}"

# 3) 展示结果
oikb config get
echo "[setup-oikb] 完成。现在可用: scripts/sync-evidence.sh <run-id> <kb-id>"
