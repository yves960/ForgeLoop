#!/bin/sh
# install-durations-cron —— 蔚 11-03 工单#5 的定时器安装（owner 侧一键）。
#
# 背景：dev agent 的 exec 环境里 `crontab <file>` 会静默杀死会话（三次实测，
# printf 退出码 0 后链路即断），本脚本留给 owner/任意正常终端执行：
#   sh scripts/install-durations-cron.sh
# 卸载：crontab -l | grep -v test-durations | crontab -
LINE='10 7 * * * cd /Users/sy/Projects/self/ForgeLoop && .venv/bin/python -m pytest tests/ -q --durations=10 >> .test-durations.log 2>&1'
TMP="$(mktemp)"
crontab -l 2>/dev/null | grep -v 'test-durations' > "$TMP"
echo "$LINE" >> "$TMP"
crontab "$TMP" && rm -f "$TMP" && echo "[ok] 每日 07:10 pytest --durations 已安装（日志 .test-durations.log）" && crontab -l | tail -1
