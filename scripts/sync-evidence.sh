#!/usr/bin/env bash
# sync-evidence.sh — 把 ForgeLoop run 的 evidence 目录同步到 Open WebUI Knowledge Base
#
# 用法:
#   scripts/sync-evidence.sh <run-id> <kb-id>
#
# 依赖: oikb 已安装且已运行 scripts/setup-oikb.sh 完成配置（url + token）
# 详见 docs/OIKB_INTEGRATION.md
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <run-id> <kb-id>" >&2
  echo "  <run-id>  ForgeLoop run id（如 r-20260814-abc123）" >&2
  echo "  <kb-id>   Open WebUI Knowledge Base id" >&2
  exit 2
fi

RUN_ID="$1"
KB_ID="$2"

# ForgeLoop 仓库根目录（可用 LOOP_HOME 环境变量覆盖）
LOOP_HOME="${LOOP_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"

if ! command -v oikb >/dev/null 2>&1; then
  echo "[sync-evidence] 错误: 未找到 oikb。请先运行 scripts/setup-oikb.sh 完成安装与配置。" >&2
  exit 1
fi

# 定位 run 的 evidence 目录。ForgeLoop 默认 runtime 根目录在仓库同级 .loop-engineering/，
# 也支持 LOOP_ENGINEERING_HOME 或 loop config runtime-root 覆盖；最后回退到 $LOOP_HOME/runs/。
CANDIDATES=(
  "${LOOP_ENGINEERING_HOME:-}/runs/${RUN_ID}/evidence"
  "${LOOP_HOME}/../.loop-engineering/runs/${RUN_ID}/evidence"
  "${LOOP_HOME}/runs/${RUN_ID}/evidence"
)

EVIDENCE_DIR=""
for dir in "${CANDIDATES[@]}"; do
  if [ -n "$dir" ] && [ -d "$dir" ]; then
    EVIDENCE_DIR="$dir"
    break
  fi
done

if [ -z "$EVIDENCE_DIR" ]; then
  echo "[sync-evidence] 错误: 找不到 run=${RUN_ID} 的 evidence 目录，已尝试:" >&2
  printf '  - %s\n' "${CANDIDATES[@]}" >&2
  exit 1
fi

echo "[sync-evidence] run=${RUN_ID} kb=${KB_ID} src=${EVIDENCE_DIR}/"
exec oikb sync "${EVIDENCE_DIR}/" --kb-id "${KB_ID}"
