# ForgeLoop 验证矩阵

发布前必须从 CLI 入口验证行为，不以 Agent 自报完成作为通过条件。验证使用临时 Git/Maven 仓库、隔离的 `LOOP_ENGINEERING_HOME`，以及只读取 `READ_FILE=.loop/task.md` 的 OpenCode 测试后端。

## Profile 闭环

| Profile | 入口参数 | 预期终态 |
| --- | --- | --- |
| `java-ut-fixer` | `--test UserTest` | `PASS / TARGET_UT_PASSED` |
| `codecheck-fixer` | `--target quality-gate` | `PASS / CODECHECK_PASSED` |
| `sast-fixer` | `--target security-gate` | `PASS / SAST_PASSED` |
| `sca-upgrader` | `--target dependency-scan` | `PASS / SCA_PASSED` |
| `dependency-upgrader` | `--target group:artifact` | `PASS / DEPENDENCY_UPGRADE_PASSED` |

每个场景都必须先观察 Baseline 的确定性失败，再观察 Agent 通过 File Protocol 修改代码，最后由 Verifier 产生 PASS。macOS 使用 `./loop`，Windows 使用 `loop.cmd`。

## 治理与故障场景

- Maven Profile、插件、网络、依赖解析或 Java Runtime 不可用时返回 `BLOCKED`，不消耗修复迭代。
- Agent 启动失败或需要交互确认时返回 `BLOCKED`，并保留 Worktree。
- 越界文件、测试绕过、缺少必需文件或验证输出时不得 PASS。
- `.loop`、`.ralph` 或其子项为符号链接时返回 `UNSAFE_RUNTIME_PATH`，不得向仓库外写入。
- `status` 必须展示最后一次 Verifier 摘要、完整 Maven 日志和可复制的 Worktree 命令。
- `submit` 必须重新验证，并按 `git add -> git commit -> git review` 执行；Hook 或 Review 失败时保留现场，成功后默认清理 Worktree 和 Baseline ref。

## 发布门禁

```bash
uvx ruff format --check src
uvx ruff check .
uvx basedpyright src
python3 -m compileall -q src
git diff --check
```

此外应在目标平台运行上述 CLI 场景。Windows 批处理参数边界需要使用包含 `& | < > ^ % !` 的恶意 selector 做拒绝测试；SCA 场景需要覆盖“请求的 Maven Profile 未激活但命令退出码为 0”的对抗输出。
