#!/usr/bin/env bash
# sync-evidence.sh — 把 ForgeLoop run 的 evidence 目录同步到 Open WebUI Knowledge Base
#
# 用法:
#   scripts/sync-evidence.sh <run-id> <kb-id> [--apply]
#
# 默认行为：DRY-RUN（只打印差量不真上传），必须显式 --apply 才会真传到 KB。
# 这是有意为之的安全护栏——oikb 没有任何 include/exclude 默认值，会扫整个源目录。
#
# 依赖: oikb 已安装且已运行 scripts/setup-oikb.sh 完成配置（url + token）
# 详见 docs/OIKB_INTEGRATION.md
set -euo pipefail

usage() {
  cat <<'EOF' >&2
Usage: scripts/sync-evidence.sh <run-id> <kb-id> [--apply]

  <run-id>    ForgeLoop run id（如 r-20260814-abc123）
  <kb-id>     Open WebUI Knowledge Base id（UUID 格式）
  --apply     真传到 KB。**省略时默认 dry-run**，只打印差量

安全默认值：
  - 只白名单 *.txt/*.md/*.json/*.log exclude *.env/*secret*/*token*/*auth*/*credential*/*password*/*key*/*private* 与 .DS_Store
  - 想换 glob 请直接编辑本脚本「SAFETY GLOBS」段，或 PR 给我们

EOF
  exit 2
}

if [ "$#" -lt 2 ]; then
  usage
fi

RUN_ID="$1"
KB_ID="$2"
shift 2

APPLY=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --dry-run) APPLY=0 ;;
    -h|--help) usage ;;
    *) echo "[sync-evidence] 未知参数: $arg" >&2; usage ;;
  esac
done

# 防御性：仅接受 UUID 格式的 kb-id（Open WebUI 实际格式），避免参数错位把
# 别的内容传到错误 KB。
if ! [[ "$KB_ID" =~ ^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$ ]]; then
  echo "[sync-evidence] 错误: kb-id 必须是 UUID 格式，实际收到: '$KB_ID'" >&2
  exit 1
fi

if ! command -v oikb >/dev/null 2>&1; then
  echo "[sync-evidence] 错误: 未找到 oikb。请先运行 scripts/setup-oikb.sh 完成安装与配置。" >&2
  exit 1
fi

# ForgeLoop 仓库根目录（可用 LOOP_HOME 环境变量覆盖）
LOOP_HOME="${LOOP_HOME:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"

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

# ─────────────────────────────────────────────────────────────────────────────
# SAFETY GLOBS — 单点真相
# 改这里就改所有调用方的安全边界。oikb 默认无 glob → 会扫整个源目录 → 之前
# 干跑 /tmp 时把 authstore.json / oa_token.txt 列到了差量。改成显式白名单 +
# 黑名单双保险。新加 evidence 产物（如 *.xml）请同步更新 INCLUDE。
# ─────────────────────────────────────────────────────────────────────────────
INCLUDES=(
  --include "*.txt"
  --include "*.md"
  --include "*.json"
  --include "*.log"
)

EXCLUDES=(
  --exclude "*.env"
  --exclude "*.env.*"
  --exclude "*secret*"
  --exclude "*token*"
  --exclude "*auth*"
  --exclude "*credential*"
  --exclude "*password*"
  --exclude "*key*"
  --exclude "*private*"
  --exclude ".DS_Store"
)

# macOS scproxy(Clash) 会劫持 localhost → 502。oikb 用 urllib 会被环境变量
# 导走，必须显式 NO_PROXY 屏蔽。
export NO_PROXY="localhost,127.0.0.1"
export no_proxy="localhost,127.0.0.1"

MODE_FLAG="--dry-run"
if [ "$APPLY" -eq 1 ]; then
  MODE_FLAG=""
  echo "[sync-evidence] ⚠️  --apply 模式：将真传到 Open WebUI KB=${KB_ID}"
  echo "[sync-evidence]    src=${EVIDENCE_DIR}/"
  echo "[sync-evidence]    include白名单 + exclude黑名单 已应用 (见脚本 SAFETY GLOBS 段)"
  echo ""
else
  echo "[sync-evidence] ℹ️  DRY-RUN 模式（默认）：只显示差量，不会真传"
  echo "[sync-evidence]    传 --apply 才会真传到 KB=${KB_ID}"
  echo "[sync-evidence]    src=${EVIDENCE_DIR}/"
  echo ""
fi

# shellcheck disable=SC2086
exec oikb sync "${EVIDENCE_DIR}/" --kb-id "${KB_ID}" \
  "${INCLUDES[@]}" "${EXCLUDES[@]}" $MODE_FLAG
