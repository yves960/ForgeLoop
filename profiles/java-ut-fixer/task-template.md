# Objective

修复 Java 单元测试：`{{TEST}}`。

# Evidence

每一轮开始必须读取：

- `.loop/verifier-result.md`（如果存在）
- `.loop/maven-output.txt`（如果存在）
- 当前 git diff
- 相关生产代码与测试代码

外部 Verifier 是完成状态的唯一依据。

# Allowed Changes

只允许修改当前模块下：

- `src/test/**`

# Forbidden Changes

禁止修改：

- `src/main/**`
- `pom.xml`
- Maven / Gradle 构建配置
- 生产配置文件
- 当前模块之外的文件

禁止通过以下方式绕过测试：

- 删除测试
- 注释关键断言
- `@Disabled`
- `@Ignore`
- 跳过测试执行
- 吞掉本应失败的异常

# Workflow

1. 分析最新 Verifier/Maven 失败证据。
2. 阅读相关生产代码理解预期行为，但不要修改生产代码。
3. 修改测试代码解决真实失败。
4. 完成本轮实际代码修改后正常退出。
5. 不要自行宣称任务完成；由外部 Verifier 判定。

# Completion

不要输出任何 `<promise>` 标签。
