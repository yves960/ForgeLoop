# Objective

升级 SCA 目标 `{{TARGET}}` 的漏洞依赖，并保持依赖解析与构建兼容。

# Evidence

每轮先读取 `.loop/verifier-result.md`、`.loop/maven-output.txt`、当前 git diff、依赖树和漏洞证据。

# Allowed Changes

仅允许修改当前模块的 `pom.xml` 以及兼容性修复所需的 `src/main/**`、`src/test/**`。

# Forbidden Changes

禁止关闭 SCA、加入宽泛 Suppression、降低失败阈值、跳过验证或修改当前模块之外的文件。

# Workflow

选择满足安全与兼容约束的最小版本升级，修复必要兼容问题。不要输出任何 `<promise>` 标签；外部 Verifier 是完成状态的唯一依据。
