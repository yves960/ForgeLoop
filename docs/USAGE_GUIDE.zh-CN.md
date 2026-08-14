# Loop Engineering 使用与运维指南

## 1. 适用范围

按任务复杂度选择入口：

- 一次性小改动使用普通 Coding Agent。
- 单仓、单目标、低风险且只有一个验证命令的重复任务，优先使用 Claude Code `/loop`。
- 需要 Worktree、Runtime Baseline、强 Policy、确定性 Verifier、Evidence、Human Review 或企业 Git Delivery 时，使用 Loop Engineering。

当前正式提供 `java-ut-fixer`、`codecheck-fixer`、`sast-fixer`、
`sca-upgrader` 与 `dependency-upgrader`。它们共用同一 Runtime，只通过
Profile 声明任务模板、修改范围、绕过模式、Verifier 参数和原因码。

## 2. 环境要求

通用依赖：

- Git
- Python 3.10+
- Bun 与 npm
- 全局安装的 Open Ralph Wiggum
- Java、Maven，或仓库内的 `mvnw` / `mvnw.cmd`
- 一个已认证的 Coding Agent：Claude Code 兼容 CLI 或 OpenCode

macOS 推荐使用 Homebrew Python：

```bash
brew install python git bun
chmod +x ./loop
./loop --help
```

如果需要指定 Python：

```bash
LOOP_PYTHON=/opt/homebrew/bin/python3 ./loop --help
```

Windows 使用：

```cmd
loop.cmd --help
```

## 3. Coding Agent 配置

### OpenCode

先确认 OpenCode 已登录且可用：

```bash
opencode --version
opencode models
```

配置一次：

```bash
./loop config agent opencode --protocol opencode
```

无人值守 Loop 不能等待权限确认。仅对可信仓库启用 OpenCode 自动批准：

```bash
./loop config agent-arg --value=--auto
```

运行时实际采用短参数 File Protocol：

```text
opencode run --auto READ_FILE=.loop/task.md
```

完整任务、Verifier 反馈和 Maven 输出始终通过 `.loop/` 文件传递，不进入 shell 长参数。OpenCode 的 `--auto` 只自动批准原本需要询问的权限，显式 `deny` 规则仍生效。权限策略参考 [OpenCode Permissions](https://opencode.ai/docs/permissions/)，非交互命令参考 [OpenCode CLI](https://opencode.ai/docs/cli/)。

### Claude Code 兼容 Backend

macOS/Linux：

```bash
./loop config agent claude --protocol claude-code
```

Windows 企业封装：

```cmd
loop.cmd config agent D:\tools\agent.bat --protocol claude-code
loop.cmd config agent-arg --value=--skip-safe-check
```

实际调用为：

```text
<agent> <fixed-args> -p READ_FILE=.loop/task.md
```

查看或清理配置：

```bash
./loop config show
./loop config clear-agent-args
./loop config clear-agent
```

Run 结束钩子（`loop submit` 完成后可配 webhook 调 sync-evidence.sh）：

```bash
./loop config hook-on-complete "https://your-webhook.example/loop-complete"
./loop config clear-hook-on-complete
```

详见 `docs/OIKB_INTEGRATION.md`。

每次 Run 也可用 `--agent-command`、`--agent-protocol`、`--agent-arg` 临时覆盖；环境变量为 `LOOP_AGENT_COMMAND`、`LOOP_AGENT_PROTOCOL`、`LOOP_AGENT_ARGS`。

## 4. Runtime Root

默认 Runtime 位于仓库同级目录：

```text
/workspace/service
/workspace/.loop-engineering/
├── runs/
└── worktrees/
```

覆盖优先级：

```text
LOOP_ENGINEERING_HOME
→ loop config runtime-root
→ repository sibling .loop-engineering
```

macOS/Linux：

```bash
./loop config runtime-root /Volumes/work/loop-engineering
export LOOP_ENGINEERING_HOME=/Volumes/work/loop-engineering
```

Windows：

```cmd
loop.cmd config runtime-root D:\loop-engineering
set LOOP_ENGINEERING_HOME=D:\loop-engineering
```

只有小型 `config.json` 和 `run-index.json` 位于用户配置目录。Worktree、Run、Evidence、`.loop`、`.ralph`、Maven 输出和 iteration 日志全部位于 runtime-root 或其 Worktree 下。

## 5. Java UT 修复流程

从目标 Git 仓库、Maven 模块或其子目录运行：

```bash
./loop run java-ut-fixer --test UserTest
./loop run java-ut-fixer --test UserTest.java#testCreate
./loop run java-ut-fixer --test src/test/java/com/acme/UserTest.java
```

Windows 将 `./loop` 换为 `loop.cmd`。框架会自动识别 Git Root/Maven Module，复制当前 dirty workspace 到隔离 Worktree，以 Git tree object 建立 Runtime Baseline，然后由 Open Ralph 管理 iteration。

Run 不会执行正式 commit 或 review。

### 5.1 其他 Profile

```bash
./loop run codecheck-fixer --target service-quality-gate
./loop run sast-fixer --target CWE-89
./loop run sca-upgrader --target org.example:vulnerable-lib
./loop run dependency-upgrader --target org.example:library:2.0.0
```

- `codecheck-fixer` 默认执行 `mvn -DskipTests verify -Pcodecheck`，允许修改
  `src/main/**` 与 `src/test/**`。
- `sast-fixer` 默认执行 `mvn -DskipTests verify -Psast`，禁止通过
  `NOSONAR`、全局 Suppression 或关闭扫描绕过。
- `sca-upgrader` 与 `dependency-upgrader` 默认执行
  `mvn -DskipTests verify -Psca`，允许修改 `pom.xml` 及必要兼容代码，禁止
  关闭扫描或加入宽泛 Suppression。默认还要求 Maven 输出包含
  `dependency-check-maven`，确保 SCA 插件确实执行；平台更换插件时必须同步
  调整 `requiredOutputPatterns`。

这些 Maven Profile 名称是平台适配点。企业仓库若使用不同的 CodeCheck、
SAST 或 SCA 插件，由平台团队修改对应 `profiles/<name>/profile.json` 的
`verifier.arguments`，普通研发仍只使用上述短命令。

## 6. 查看状态

```bash
./loop status <run-id>
```

输出包含：

- Status、Reason、Target、iteration / max iterations
- 最后一次 Maven/Surefire `Tests run / Failures / Errors / Skipped`
- 测试位置、Assertion、expected/actual、常见 Exception
- 完整 Verifier/Maven 日志和 Evidence 路径
- 当前平台可复制的 Worktree/日志命令

macOS/Linux 示例：

```bash
cd "/path/to/worktree/module"
less "/path/to/maven-output.txt"
```

Windows 示例：

```cmd
cd /d "D:\path\to\worktree\module"
type "D:\path\to\maven-output.txt"
```

## 7. Submit 与清理

PASS 后执行：

```bash
./loop submit <run-id>
```

固定顺序为：

```text
Final Verifier
→ 展示 Delivery/Baseline/Loop Diff
→ Human Confirmation
→ git add -A
→ git commit（保留全部 hooks）
→ configured review command
```

配置企业交付：

```bash
./loop config commit-template /path/to/git-commit-template.txt
./loop config review-command "git review"
```

Review 成功后默认删除 Worktree 和 Runtime Baseline ref，保留 Loop branch 与 Evidence。需要保留现场时：

```bash
./loop submit <run-id> --keep-worktree
```

手动清理：

```bash
./loop cleanup <run-id>
./loop cleanup <run-id> --delete-branch
```

Final Verifier、commit hook 或 review 任一步失败时，Worktree 与 Baseline ref 都保留，便于诊断和重试。

## 8. 状态与故障分类

- `PASS`：确定性 Verifier 通过，可以进入 Human Review/Submit。
- `FAIL`：测试、Policy、覆盖率等逻辑失败，可由下一 iteration 修复。
- `BLOCKED`：Agent 启动、认证、权限确认、Maven/环境等基础设施问题，停止 retry。
- `CANCELLED`：用户或外层 Workflow 取消。

常见处理：

- `AGENT_INTERACTIVE_CONFIRMATION_REQUIRED`：对可信仓库配置 backend 的非交互参数。
- `MAVEN_PROFILE_NOT_CONFIGURED`、`MAVEN_NETWORK_FAILURE`、
  `MAVEN_DEPENDENCY_RESOLUTION_FAILED`：Verifier 基础设施未就绪，Ralph 立即
  abort，不消耗后续修复 iteration。
- `VERIFIER_EVIDENCE_MISSING`：命令虽然结束，但缺少 Profile 要求的扫描器
  执行标记；不得判定 PASS。
- `UNSAFE_RUNTIME_PATH`：`.loop`/`.ralph` 包含符号链接，框架拒绝写入或归档，
  避免 Evidence 越出 Worktree。
- `TARGET_UT_FAILED`：直接查看 `loop status` 的摘要和完整 Maven 日志。
- `POLICY_VIOLATION`：Agent 必须撤销当前 Profile 允许范围之外的修改。
- `COMMIT_FAILED`：修复 commit message/hook 问题后，在保留的 Worktree 中重试。
- review 失败：commit 和 Worktree 均保留，修复 review 环境后处理。

## 9. Evidence

每个 Run 的长期 Evidence 位于：

```text
<runtime-root>/runs/<run-id>/
├── run.json
├── run-config.json
└── evidence/
    ├── loop/
    ├── ralph/
    └── submission/
        ├── loop/
        └── ralph/
```

`.loop/iterations/<NNN>/` 保存 `agent-output.txt`、`verifier-output.txt` 和 `maven-output.txt`。`run.json` 保存 source HEAD、baseline tree、Worktree、branch、changed files 与 submission 状态。

## 10. 安全原则

- 不在 `loop run` 中创建正式 commit。
- 不使用 `git commit --no-verify`。
- Agent 不能自行输出完成 promise；Verifier 是唯一完成裁判。
- Runtime Baseline 使用 Git tree/ref，不污染正式历史。
- OpenCode `--auto`、Claude/企业 Agent 的 trust bypass 仅用于已审核可信仓库。
- 新增 Profile 不应修改 Worktree、Baseline、Open Ralph、Agent、Evidence、
  Status、Submit 或 Delivery 层；只新增 Profile、Task Template、Verifier 参数
  与 Policy。
