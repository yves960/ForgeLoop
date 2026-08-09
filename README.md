# Loop Engineering v0.1.8

Cross-platform engineering control loop for Windows and macOS around Open Ralph Wiggum, configurable Claude Code/OpenCode agent backends, deterministic verification, Git worktree isolation, and an explicit Git delivery stage.

中文安装、OpenCode 配置、运行、状态、提交与故障处理见 [使用与运维指南](docs/USAGE_GUIDE.zh-CN.md)。

## v0.1.8 runtime-location and worktree UX

- Heavy runtime data no longer defaults to `%LOCALAPPDATA%` on C:.
- By default, Loop data follows the target repository drive and lives outside the repository.
- Example: `D:\workspace\service` -> `D:\workspace\.loop-engineering`.
- `runs/`, `worktrees/`, Ralph state, verifier output and evidence all live under that runtime root.
- A platform team can override the location once with `loop config runtime-root D:\loop-engineering`.
- `loop status <run-id>` prints copy/pasteable CMD commands on Windows and POSIX commands on macOS.
- Only the small per-user config and run-id index remain under the user config directory so `status/submit/cleanup` can locate runs across drives.


## Product boundary

Do not use Loop Engineering for every retry.

- **Normal agent**: one small edit or analysis task.
- **Claude Code `/loop`**: simple, single-goal, low-risk repetition with one straightforward completion check.
- **Loop Engineering**: use when isolation, deterministic verification, policy, audit, approvals, multiple gates, or workflow orchestration matter.

The differentiation is not "we can retry too". Claude `/loop` keeps an agent working; Loop Engineering keeps a complex engineering task working under engineering controls until a deterministic verifier accepts it.

## One-time coding-agent configuration

Loop Engineering does not hard-code any company-specific agent command name.

Configure a supported coding-agent command once. OpenCode:

```bash
./loop config agent opencode --protocol opencode
./loop config agent-arg --value=--auto
```

Use `--auto` only for trusted repositories. Claude-Code-compatible backend:

```cmd
loop config agent D:\path\to\enterprise-agent.bat
```

The Claude-Code-compatible command must support:

```text
<agent-command> -p "<prompt>"
```

Check configuration:

```cmd
loop config show
```

Runtime resolution order:

1. per-run `--agent-command`
2. `LOOP_AGENT_COMMAND`
3. machine-level `loop config agent ...`
4. native `claude`, then `opencode`, on PATH as convenience fallbacks

## Runtime data location

By default, Loop keeps heavy runtime data on the same drive as the target repository, outside the repository itself.

Example:

```text
Repository:
D:\workspace\service

Default runtime root:
D:\workspace\.loop-engineering\
├── runs\
└── worktrees\
```

Override once for the machine/user:

```cmd
loop config runtime-root D:\loop-engineering
```

Clear the override and return to repository-drive placement:

```cmd
loop config clear-runtime-root
```

Environment override is also supported:

```cmd
set LOOP_ENGINEERING_HOME=D:\loop-engineering
```

Resolution order is: `LOOP_ENGINEERING_HOME` -> configured `runtimeRoot` -> repository sibling `.loop-engineering`.

The tiny config/run index may remain under the Windows user config directory; Worktrees, runs, Maven output, Ralph state and evidence do not.

## Run: engineering execution only

Implemented profiles:

```cmd
loop run java-ut-fixer --test UserServiceTest
loop run codecheck-fixer --target service-quality-gate
loop run sast-fixer --target CWE-89
loop run sca-upgrader --target org.example:vulnerable-lib
loop run dependency-upgrader --target org.example:library:2.0.0
```

All profiles use the same worktree, baseline, Open Ralph, agent, evidence,
status and submit runtime. A profile contributes only its task template,
allowed paths, bypass patterns, Maven verifier arguments and deterministic
PASS/FAIL reason codes. Platform teams may adapt the Maven profile/goal names
(`codecheck`, `sast`, `sca`) to the repository's approved build profiles.

`loop run` does **not** create a delivery commit.

It automatically:

1. finds the Git root and nearest Maven module
2. reads the current developer working-tree state without changing it
3. creates a dedicated `loop/<profile>/<run-id>` branch + Git worktree from the current source `HEAD`
4. copies current tracked modifications and non-ignored untracked files into the isolated worktree
5. freezes that imported state as a **runtime baseline Git tree object**, not a branch commit
6. keeps a private `refs/loop-engineering/baselines/<run-id>` ref so Git GC cannot discard the baseline while the run exists
7. discovers `mvnw.cmd` / `mvn`
8. creates the internal task contract
9. executes the profile's deterministic verifier at baseline
10. executes Open Ralph iterations through the configured coding agent
11. runs deterministic path/policy/profile verification after every iteration
12. allows Ralph completion only when the external verifier passes
13. archives `.loop` / `.ralph` evidence outside the repository worktree
14. leaves the verified worktree for human review

Users do not manually create worktrees, task files, verifier scripts, Ralph commands, or runtime commits.

## Dirty source working trees

Dirty developer checkouts are supported by default. No manual commit/stash is required before `loop run`.

Example source state:

```text
HEAD = abc123
M  src/main/java/UserService.java
?? src/test/java/UserServiceTest.java
```

Loop Engineering creates an isolated worktree from `abc123`, imports those local files, and freezes the imported state as the runtime baseline:

```text
source HEAD abc123
       +
existing local developer changes
       ↓
Runtime Baseline Tree   (NO COMMIT)
       ↓
Loop-attributed changes
```

Important Git invariant:

```text
Before loop run: branch HEAD = abc123
During loop run: branch HEAD = abc123
After loop PASS: branch HEAD = abc123
```

There is no internal `loop: snapshot ...` commit in branch history.

The baseline tree exists only for policy/verifier comparisons. Pre-existing developer changes are therefore context, not incorrectly attributed to the agent.

Internal `.loop` / `.ralph` files and Git-ignored files are excluded from the baseline tree.

Strict clean mode is still available:

```cmd
loop run java-ut-fixer --test UserServiceTest --require-clean
```

## What the Java UT profile controls

`java-ut-fixer` currently treats the runtime baseline as trusted developer context and attributes only later changes to the Loop.

The deterministic verifier currently enforces:

- Loop-attributed modifications must remain under the current module's `src/test/**`
- common test-bypass additions such as `@Disabled` / `@Ignore` are rejected
- the requested Maven test must actually pass
- the coding agent cannot end the loop by merely claiming success; only verifier PASS emits the Ralph completion promise

## Inspect run status and enter the isolated worktree

Use:

```cmd
loop status <run-id>
```

The status view includes the last verifier result, iteration count, Maven/Surefire
totals, common assertion/exception details, the full Maven log path, and ready-to-copy
CMD commands:

```cmd
cd /d "D:\workspace\.loop-engineering\worktrees\service\<run-id>\<module-path>"
type "D:\workspace\.loop-engineering\runs\<run-id>\evidence\loop\maven-output.txt"
```

`/d` is important on Windows CMD because it changes both the drive and directory.

## Submit: existing Git delivery flow

A successful `loop run` prints a run id, for example:

```text
Run ID: 20260808-141500-a1b2c3
Status: PASS
```

Review the worktree first. Then explicitly enter delivery:

```cmd
loop submit 20260808-141500-a1b2c3
```

`loop submit` performs:

```text
final deterministic verifier
        ↓
show delivery diff
        ↓
show pre-existing developer baseline changes separately
        ↓
show Loop-attributed changes separately
        ↓
human confirmation
        ↓
git add -A
        ↓
git commit
        ↓
existing Git hooks / commit-msg validation
        ↓
git review
```

`loop submit` deliberately does **not** pass `--no-verify` to `git commit`. Existing commit hooks continue to enforce company commit-message rules.

The default review adapter is:

```cmd
git review
```

It can be changed once per machine:

```cmd
loop config review-command "git review"
```

or overridden for one submission:

```cmd
loop submit <run-id> --review-command "git review"
```

### Commit message requirements

Loop Engineering does not invent the company's commit-message format.

If Git / the repository already provides the required commit editor/template and hooks, plain `loop submit` uses the normal interactive `git commit` flow.

A platform team can configure the exact enterprise commit template once:

```cmd
loop config commit-template D:\company\git-commit-template.txt
```

Then `loop submit` runs effectively:

```text
git add -A
git commit -t <enterprise-template>   # normal editor + normal hooks
git review
```

Per-submit alternatives are also available:

```cmd
loop submit <run-id> --message "<message>"
loop submit <run-id> --message-file D:\tmp\commit-message.txt
loop submit <run-id> --commit-template D:\tmp\template.txt
```

Git hooks still run in all of these cases.

### Dirty baseline + delivery commit

If `loop run` started from a dirty developer checkout, a later delivery commit contains the complete final worktree relative to the original source `HEAD`:

```text
formal delivery commit
= pre-existing developer changes
+ Loop-attributed changes
```

Before staging, `loop submit` displays those two categories separately so the developer can review exactly what will be included.

This is intentional: there is only one real delivery commit, and no hidden snapshot commit is added to branch history.

## Cleanup

After `git review` succeeds, `loop submit` automatically removes the worktree and
runtime baseline ref. The Loop branch and evidence remain available. To retain the
worktree and baseline for inspection:

```cmd
loop submit <run-id> --keep-worktree
```

For a failed/blocked run, a failed submission, or a retained worktree, cleanup remains
explicit:

```cmd
loop cleanup <run-id>
```

This removes the worktree and runtime baseline ref but preserves the branch and evidence.

Delete the branch only when explicitly intended:

```cmd
loop cleanup <run-id> --delete-branch
```

## Commands

```cmd
loop config agent D:\path\to\enterprise-agent.bat
loop config commit-template D:\company\git-commit-template.txt
loop config review-command "git review"
loop config runtime-root D:\loop-engineering
loop config clear-runtime-root
loop config show

loop run java-ut-fixer --test UserServiceTest
loop run java-ut-fixer --test UserServiceTest#shouldCreateUser
loop run java-ut-fixer --test UserServiceTest --require-clean

loop status <run-id>
loop submit <run-id>
loop cleanup <run-id>
loop cleanup <run-id> --delete-branch
```

Useful advanced overrides:

```cmd
loop run java-ut-fixer --test UserServiceTest --max-iterations 8
loop run java-ut-fixer --test UserServiceTest --agent-command D:\tools\enterprise-agent.bat
loop run java-ut-fixer --test UserServiceTest --maven D:\apache-maven\bin\mvn.cmd

loop submit <run-id> --yes
loop submit <run-id> --no-review
loop submit <run-id> --keep-worktree
```

## Git lifecycle

```text
Developer checkout (never modified by Loop)
        │
        ├── HEAD
        ├── staged/unstaged tracked changes
        └── non-ignored untracked files
        │
        ▼
Isolated Loop worktree + loop/* branch
        │
        ├── branch HEAD == original source HEAD
        ├── imported developer state
        └── Runtime Baseline Tree (private ref; not a commit)
        │
        ▼
Open Ralph → coding agent → deterministic verifier → retry
        │
        ▼ PASS
Human reviews final diff
        │
        ▼
loop submit
        │
        ├── git add -A
        ├── git commit (normal hooks/message policy)
        └── git review
```

## Current scope

v0.1.8 deliberately implements one Engineering Profile (`java-ut-fixer`) while stabilizing the shared runtime, worktree, baseline, verifier, evidence, and delivery contracts.

The next proof of framework generality should be a second profile such as `codecheck-fixer` that reuses the same runtime and delivery layers without changing them.


## Startup diagnostics

`loop run` now prints immediately before doing dependency/repository discovery, so a slow or failed startup no longer looks like a silent command. The Windows launcher uses `python -u` for unbuffered output and validates that the installation and Python executable are available.

The Java test selector also accepts common file-style input:

```cmd
loop run java-ut-fixer --test User2Test.java
loop run java-ut-fixer --test src\test\java\com\acme\User2Test.java
loop run java-ut-fixer --test User2Test.java#shouldCreate
```

These are normalized internally to Maven `-Dtest` selectors such as `User2Test`, `com.acme.User2Test`, and `User2Test#shouldCreate`.

You can invoke `loop.cmd` from the repository root, a Maven module directory, or a deeper subdirectory. If the current directory is outside Git, the CLI now fails explicitly instead of appearing silent.

## Windows Agent 参数协议（v0.1.6）

Loop 不再把 Ralph 的长自然语言 prompt 穿过 `.cmd/.bat` 链。每轮 Agent 只收到一个稳定的 Claude-Code-compatible 参数：

```text
-p READ_FILE=.loop/task.md
```

完整任务、上一轮 Verifier 结果和 Maven 输出都通过 `.loop/` 文件协议交换。这样避免 Windows batch 引号丢失导致 `too many arguments`，也让迭代证据可持久化和审计。
