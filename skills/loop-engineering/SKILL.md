---
name: loop-engineering
description: Route iterative engineering work between normal agent execution, native Claude Code /loop, and controlled Loop Engineering. Prefer /loop for simple low-risk single-goal repetition. Use Loop Engineering when deterministic verification, worktree isolation, policy, audit, approvals, multiple gates, or workflow orchestration materially matter.
---

# Loop Engineering Router

## Principle

Use the lightest mechanism that safely completes the engineering task.

Do not use Loop Engineering merely because a task may need multiple attempts.

## Level 0 — Normal coding agent

Use a normal agent interaction when the task is small and repeated autonomous execution adds little value.

Examples:

- explain a failure
- make one obvious localized edit
- add one straightforward test

## Level 1 — Native Claude Code `/loop`

Prefer native `/loop` when all of the following are true:

- one repository
- one clear goal
- one straightforward completion check
- low-risk modification
- no required isolated worktree
- no strong file-change policy
- no enterprise evidence/audit requirement
- no human approval gate
- no multi-verifier workflow

Examples:

- keep fixing one local test until one command passes
- fix a small lint/checkstyle set
- repeatedly refine one implementation under one simple check

## Level 2 — Loop Engineering

Use Loop Engineering when any of the following materially matters:

- automatic Git worktree isolation
- current dirty developer state must be frozen as an explicit baseline
- Loop-attributed changes must be distinguished from pre-existing developer changes
- deterministic external verifier is authoritative for completion
- enforced allowed/forbidden file policy
- multiple verifier gates such as UT + CodeCheck + SAST/SCA
- security remediation or dependency upgrades
- human approval / blocked state handling
- resumable long-running work
- standardized evidence / audit trail
- Multica workflow orchestration
- enterprise Git delivery policy must be preserved

## Implemented profiles

- `java-ut-fixer`: `loop run java-ut-fixer --test <TestClassOrMethod>`
- `codecheck-fixer`: `loop run codecheck-fixer --target <gate-or-module>`
- `sast-fixer`: `loop run sast-fixer --target <finding-or-rule>`
- `sca-upgrader`: `loop run sca-upgrader --target <dependency>`
- `dependency-upgrader`: `loop run dependency-upgrader --target <dependency:version>`

Non-UT profiles use platform-maintained Maven verifier arguments from their
`profile.json`. Ordinary users do not provide verifier commands.

The CLI owns worktree creation, source-state import, runtime baseline-tree creation, internal task rendering, baseline verification, Open Ralph invocation, configured coding-agent invocation, deterministic verifier feedback, evidence capture, and run summary.

Users do not manually create worktrees, runtime baseline commits, task.md files, verifier scripts, or Ralph commands.

The coding-agent backend is machine/platform configuration, not profile logic. Claude Code-compatible CLIs and OpenCode are supported. Long-running controlled loops must be non-interactive: do not wait for terminal trust/login prompts. If the backend requires a documented trust flag for approved repositories, configure it once as a fixed agent argument (for example `loop config agent-arg --value=--skip-safe-check` or OpenCode `--auto`). Interactive agent prerequisites are `BLOCKED` infrastructure state, not logical repair retries.

## Runtime Git contract

Loop Engineering must not create hidden delivery commits during `loop run`.

The Loop branch starts from the source `HEAD`. Existing source working-tree changes are imported into the isolated worktree and frozen as a Git tree object referenced under `refs/loop-engineering/baselines/<run-id>`. This is a verifier baseline, not a branch commit.

Therefore:

- source checkout is not changed, committed, reset, or stashed
- Loop branch `HEAD` remains the original source `HEAD` throughout runtime
- policy compares Loop-attributed changes against the runtime baseline tree
- `.loop` / `.ralph` runtime files are excluded from the engineering tree

## Delivery contract

A PASS from `loop run` means "engineering verification passed", not "code was submitted".

Formal delivery is explicit:

`loop submit <run-id>`

Submission must:

1. rerun the deterministic verifier
2. display the final delivery diff
3. distinguish pre-existing developer changes from Loop-attributed changes
4. require human confirmation unless explicitly running in an approved noninteractive mode
5. run `git add -A`
6. run normal `git commit` without `--no-verify`
7. preserve repository/company commit hooks and commit-message validation
8. invoke the configured review command (current default: `git review`) only after commit succeeds

If commit-message policy is standardized through a template, configure it once with:

`loop config commit-template <path>`

The platform must not invent or bypass the organization's commit-message format.

## Product distinction

Claude `/loop` answers:

"Keep this agent working on a simple goal."

Loop Engineering answers:

"Keep this complex engineering task working under isolation, deterministic verification, policy, evidence, and the existing enterprise delivery process until it is truly complete."

## Runtime location

Heavy Loop runtime data (worktrees, run evidence, Maven output, Ralph state) should not default to the Windows C: user profile. The CLI places it beside the target repository by default, on the repository's drive, under a sibling `.loop-engineering` directory. A platform installation may set a shared location once with `loop config runtime-root <path>` or `LOOP_ENGINEERING_HOME`.

Users enter an isolated run with `loop status <run-id>` and then the printed `cd /d "<path>"` command.
