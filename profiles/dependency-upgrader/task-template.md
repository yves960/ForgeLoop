# Objective

升级依赖目标 `{{TARGET}}`，并通过确定性构建与 SCA 验证。

# Evidence

每轮先读取 `.loop/verifier-result.md`、`.loop/maven-output.txt`、当前 git diff 和依赖树。

# Allowed Changes

仅允许修改当前模块的 `pom.xml` 以及兼容性修复所需的 `src/main/**`、`src/test/**`。

# Forbidden Changes

禁止关闭扫描、加入宽泛 Suppression、跳过验证、无关依赖大规模升级或修改模块外文件。

# Workflow

围绕指定坐标/版本实施最小升级，解决必要兼容问题。不要输出任何 `<promise>` 标签；外部 Verifier 是完成状态的唯一依据。
