# Objective

修复 CodeCheck 目标 `{{TARGET}}` 的确定性质量门禁失败。

# Evidence

每轮先读取 `.loop/verifier-result.md`、`.loop/maven-output.txt`、当前 git diff 和对应规则输出。

# Allowed Changes

仅允许修改当前模块的 `src/main/**` 与 `src/test/**`。

# Forbidden Changes

禁止修改构建配置、降低规则等级、增加 `NOPMD` / `NOSONAR` / 全局 Suppression，或跳过 CodeCheck。

# Workflow

根据最新规则和文件位置修复根因，完成实际代码修改后正常退出。不要输出任何 `<promise>` 标签；外部 Verifier 是完成状态的唯一依据。
