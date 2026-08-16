# BRIDGE.md — ForgeLoop × WorkMesh 集成桥接文档

> 版本：v0.1.8 · 基准 commit `9026106` · 行号引用以该 commit 为准。
> 面向读者：WorkMesh / Open WebUI / Multica 侧的开发与运维。

## 1. 概述

ForgeLoop 是 WorkMesh × ForgeLoop × Open WebUI × Multica 集成链路中的**受控执行引擎**：WorkMesh 下发修复任务（AICP），ForgeLoop 在 git worktree 隔离环境中驱动 Open Ralph 循环 + 确定性 Maven verifier 完成"单测修复 / 代码检查 / SAST / SCA / 依赖升级"五类工程任务。终态通过 `hook-on-complete` webhook 回调 WorkMesh（`/api/v1/loop/callback`），evidence 产物经 oikb 同步进 Open WebUI Knowledge Base，供 Multica / RAG 检索。ForgeLoop 自身是 Python CLI，不监听端口——WorkMesh 通过 `POST /api/v1/loop/run` 接单后以 **subprocess** 方式启动 `loop run`。

## 2. 触发机制

```
+------------------+  POST /api/v1/loop/run   +------------------------------------------+
|     WorkMesh     | ------------------------> |  WorkMesh adapter（HTTP 入口，AICP 任务） |
|  (任务编排/AICP)  |                          +--------------------+---------------------+
+--------^---------+                                               | subprocess
         |                                                         v
         |                                         +------------------------------+
         |                                         |  loop run <profile> (CLI)   |
         |                                         |  run_controller.execute_run |
         |                                         |  src/run_controller.py:227  |
         |                                         +--------------+---------------+
         |                                                        |
         |                                          prepare_run + worktree 隔离
         |                                          (run_preparation.py:78,143
         |                                           git worktree + 独立分支)
         |                                                        v
         |                          +---------------------------------------------+
         |                          | baseline verifier（真实 Maven 跑一次）      |
         |                          | run_controller.py:148-160                   |
         |                          |  ├─ 已 PASS → NOOP，直接结束                |
         |                          |  └─ FAIL  → 进入受控迭代                     |
         |                          +----------------------+----------------------+
         |                                                 |
         |              RALPH_CLAUDE_BINARY=iteration-adapter.sh (run_controller.py:190)
         |              ralph --max-iterations N --completion-promise COMPLETE
         |                   --abort-promise LOOP_BLOCKED   (run_controller.py:73-100)
         |                                                 v
         |                          +---------------------------------------------+
         |                          |  Open Ralph 循环（每轮一次 iteration）      |
         |                          |  iteration_runner.run_iteration (:196)      |
         |                          |   1. 熔断检查 iteration > max (:203)        |
         |                          |   2. coding agent 改代码                    |
         |                          |   3. 确定性 verifier（Maven）               |
         |                          |   4. FAIL → 写反馈进下一轮；PASS → promise  |
         |                          +----------------------+----------------------+
         |                                                 |
         |                                          终态 PASS / FAIL
         |                                                 |
         |                          +---------------------------------------------+
         |                          | notify_run_complete()  hook_notify.py:87   |
         |                          |  终态门控(:51) + 幂等 marker(:55)           |
         |                          |  urllib POST, 5s 超时(:30,:82)              |
         |                          |  触发点① run 结束 run_controller.py:218     |
         |                          |  触发点② loop submit finally :175           |
         +------------------------- |                                             |
           POST webhook (JSON)      +----------------------+----------------------+
           /api/v1/loop/callback                           |
                                                          v
                                              WorkMesh /api/v1/loop/callback
                                              （回调侧可再触发
                                               scripts/sync-evidence.sh → oikb
                                               → Open WebUI Knowledge Base）
```

两个触发点均为 best-effort：run 正常走到终态（`run_controller.py:218`）或 `loop submit` 结束（`submission_runner.py:171-177` 的 `try/finally`）时各尝试一次；幂等 marker 保证同一 run 只送达一次。

## 3. hook-on-complete 配置

```bash
loop config hook-on-complete https://workmesh-host/api/v1/loop/callback
loop config show
loop config clear-hook-on-complete
```

- **URL 校验**：`config_commands.py:130-133` — `urlparse()` 后要求 scheme ∈ {http, https} 且 netloc 非空，否则报 `Invalid webhook URL` 拒绝写入。
- **存储位置**：写入 `~/.loop-engineering/config.json`（macOS/Linux；`runtime_store.py:20-24` `user_config_root()`）的 `hooks.onComplete` 字段（`config_commands.py:136-139`，读取在 `config_store.py:47-56, 142-147`）。该文件同时承载 agent / delivery / runtimeRoot 配置，`loop config show` 可整体查看。
- **终态门控**：`hook_notify.py:31, 51-52` — 仅 `PASS` / `FAIL` 触发；`RETRY`、`RUNNING`、`BLOCKED`、`NOOP`、`ERROR` 一律静默跳过。
- **幂等保证**：`hook_notify.py:32, 55-56` — run 目录下 marker 文件 `on-complete-delivered` 存在即不再发送；成功送达后写入（`:59-67`，marker 写失败也只容忍重复投递，不抛异常）。
- **失败不阻塞**：`hook_notify.py:82` — urllib 超时 5s（`_TIMEOUT_SECONDS = 5`，`:30`）；投递失败/超时/HTTP≥300 只打 stderr（`[loop] on-complete hook delivery failed: ...`），返回 False，绝不改变 run 或 submit 的退出码（`submission_runner.py:175-177` 在 `finally` 中调用并丢弃返回值）。

**回调 payload**（`hook_notify.py:39-49`）：

```json
{
  "run_id": "r-...",
  "status": "pass",
  "evidence_uri": "/abs/path/runs/<id>/evidence",
  "diff_summary": ["src/main/java/...java"],
  "profile_name": "java-ut-fixer"
}
```

## 4. max_iterations 熔断

- **默认 10**：`profile_store.py:17` `DEFAULT_MAX_ITERATIONS: int = 10`；`run_preparation.py:170-172` 组装 run config 时 `CLI --max-iterations 覆盖 > profile.maxIterations > legacy defaultMaxIterations > 10`（优先级解析见 `profile_store.py:122-129`，要求值 > 0）。
- **超限行为**：`iteration_runner.py:202-211` — 第 N+1 轮在**调用 coding agent 之前**即被熔断，直接落盘 `status=FAIL`、`reason=MAX_ITERATIONS_EXCEEDED`（常量定义 `:163`，落盘逻辑 `:166-194`），退出码 3，输出 `<promise>LOOP_BLOCKED</promise>` 终止 Ralph 循环。
- **双层防御**：
  1. **Ralph 失控时**：熔断检查在 adapter 入口（`run_iteration`）每轮都执行，且 ForgeLoop 把同一个 `maxIterations` 显式传给 Ralph 命令行（`run_controller.py:84-85` `--max-iterations`）；
  2. **adapter 被直调时**：即使绕过 Ralph 直接反复执行 `iteration-adapter.sh`，`_effective_max_iterations`（`iteration_runner.py:65-70`）+ 计数器文件 `iteration-counter.txt` 仍会在第 N+1 次熔断。
- 5 个内置 profile 均已声明 `"maxIterations": 10`（测试 `tests/test_hooks_and_breaker.py:198` 守护），legacy `defaultMaxIterations`（5/7）仅作旧字段回退，不再生效。

## 5. 内置 profile

| profile | 触发场景 | 真实 verifier |
|---|---|---|
| `java-ut-fixer` | 单测修复（单个失败 Java 单测） | Maven `-Dtest` 定向跑目标单测（verifier type `java-ut`） |
| `codecheck-fixer` | 代码检查（质量门禁失败） | Maven profile：`verify -Pcodecheck` |
| `sast-fixer` | SAST（源码漏洞修复） | Maven goal：`verify -Psast` |
| `sca-upgrader` | SCA（漏洞依赖升级） | `verify -Psca` + `requiredOutputPatterns: ["dependency-check-maven"]`（approved verifier 输出 marker） |
| `dependency-upgrader` | 依赖升级（按请求升版本） | Maven goal：`verify -Psca`（升级后过 SCA 门禁） |

各 profile 另带 `allowedPathSuffixes` 路径白名单、`forbiddenAddedPatterns` 禁改标记（如 `NOSONAR`、`@Disabled`）与 `completion.requireVerifierPass: true`，verifier 详情见 `profiles/<name>/profile.json`。

## 6. evidence 同步（oikb 集成）

推荐链路：`loop config hook-on-complete` 指向 WorkMesh 回调，**由回调侧（而非 ForgeLoop 进程内）执行** `scripts/sync-evidence.sh <run-id> <kb-id> [--apply]`（payload 中 `run_id` + `evidence_uri` 可直接取参；详见 `docs/OIKB_INTEGRATION.md` §5）。

- **默认 DRY-RUN**：`sync-evidence.sh:7, 40-42, 118-125` — 省略 `--apply` 时传 `--dry-run` 给 oikb，只打印差量；真传必须显式 `--apply`。
- **白名单 + 黑名单 glob**（`SAFETY GLOBS` 段，`sync-evidence.sh:86-111`，单一真相源）：
  - INCLUDE（只收）：`*.txt` `*.md` `*.json` `*.log`
  - EXCLUDE（拒收）：`*.env` `*.env.*` `*secret*` `*token*` `*auth*` `*credential*` `*password*` `*key*` `*private*` `.DS_Store`
  - 起因：oikb 默认无 include/exclude 会扫整个源目录，干跑 `/tmp` 时曾把 `authstore.json`（API key）与 `oa_token.txt`（OAuth JWT）列入差量。
- **kb-id 强校验**：`sync-evidence.sh:48-53` — 必须匹配 UUID 正则，防参数错位把内容传进错误 KB。
- **代理防御**：`sync-evidence.sh:113-114` 显式 `NO_PROXY=localhost,127.0.0.1`，防 macOS Clash scproxy 劫持 localhost 报 502。
- evidence 目录定位顺序：`LOOP_ENGINEERING_HOME` → 仓库同级 `.loop-engineering/runs/` → `$LOOP_HOME/runs/`（`:62-79`）。

## 7. 安全护栏 / 已知限制

**护栏（已实现）**
- worktree 隔离：每次 run 独立 git worktree + 分支，不污染源树（`run_preparation.py:143`）。
- runtime 目录拒绝符号链接（`runtime_safety.py:14-30`，防逃逸）。
- webhook 全链路 best-effort：5s 超时、stderr 报错、不影响退出码（§3）。
- 迭代熔断默认 10 轮、双层生效（§4）。
- oikb 同步默认 dry-run + 双向 glob + UUID 校验（§6）。

**已知限制（集成方须知）**
1. **没有真正的 dry-run**：ForgeLoop CLI 无 dry_run 选项（`src/` 全量无该 flag）；即使注定 NOOP 的 run，baseline verifier 也会真实执行一次 Maven（`run_controller.py:148-160`）。任何"试跑"语义都会产生真实构建，WorkMesh 侧不要用 dry_run 标志预期 no-op。
2. **callback run_id 关联断裂**：payload 里的 `run_id` 是 ForgeLoop 自身 runId（`hook_notify.py:44`），不携带 WorkMesh/AICP 侧 run_id，WorkMesh 收到回调后无法直接反查原始任务。需要 ForgeLoop 在 run record 中透传 AICP run_id 并进入 payload（待办）。
3. **kimi API 配额依赖**：coding agent 后端依赖 kimi API 配额，当前用户处于账期等待重置状态，配额未恢复前 agent 轮次会失败（表现为 `AGENT_EXECUTION_FAILED`，`iteration_runner.py:96-101`），不影响熔断与 webhook 语义。

---

*验证：`python -m unittest tests.test_hooks_and_breaker` → `Ran 9 tests ... OK`（hook 配置/门控/幂等/失败不阻塞/熔断默认值/优先级/profile 声明/回退/超限不跑 agent 共 9 项）。*
