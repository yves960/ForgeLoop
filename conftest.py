"""conftest —— 蔚 2026-11-11 P3：durations 记录进程内化。

crontab 在 dev exec 环境装不上（11-03 三次实证，别再试了）——改为每次
pytest 结束由 terminal reporter hook 追加一行 top-5 durations 到
.test-durations.log：不依赖系统调度，谁跑测试谁贡献数据。
这是 10-27 P2#2（同机 35.5s vs 1.10s 的 32 倍波动）唯一欠着的定位弹药：
下次复现时日志里就有最慢项分布可对证。
"""
from datetime import datetime, timezone
from pathlib import Path

LOG = Path(__file__).resolve().parent / ".test-durations.log"


def pytest_terminal_summary(terminalreporter, exitstatus, config):  # noqa: ANN001
    try:
        stats = terminalreporter.stats or {}
        durations = []
        for state in ("passed", "failed", "error"):
            for rep in stats.get(state, []):
                dur = getattr(rep, "duration", None)
                if dur is not None and rep.when == "call":
                    durations.append((dur, rep.nodeid))
        durations.sort(reverse=True)
        counts = {s: len(stats.get(s, [])) for s in ("passed", "failed", "error", "skipped")}
        top = " | ".join(f"{nodeid.split('::')[-1]}={dur:.3f}s" for dur, nodeid in durations[:5])
        line = (
            f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} "
            f"exit={exitstatus} pass={counts['passed']} fail={counts['failed']} "
            f"error={counts['error']} skip={counts['skipped']} top5: {top}\n"
        )
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:  # noqa: BLE001 - 统计钩子绝不许弄红测试
        pass
