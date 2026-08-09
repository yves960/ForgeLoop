# Objective

修复 SAST 目标 `{{TARGET}}` 的安全问题，同时保持原有业务行为。

# Evidence

每轮先读取 `.loop/verifier-result.md`、`.loop/maven-output.txt`、当前 git diff 和漏洞定位证据。

# Allowed Changes

仅允许修改当前模块的 `src/main/**` 与相关 `src/test/**`。

# Forbidden Changes

禁止修改构建/扫描配置、增加 `NOSONAR` 或全局 Suppression、关闭安全规则、伪造扫描结果。

# Workflow

定位不可信输入到危险操作的真实数据流，实施最小安全修复并补齐必要验证。不要输出任何 `<promise>` 标签；外部 Verifier 是完成状态的唯一依据。
