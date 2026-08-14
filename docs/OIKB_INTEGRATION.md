# OIKB 集成：ForgeLoop evidence → Open WebUI Knowledge Base

让 ForgeLoop run 结束后，把 `runs/<run-id>/evidence/` 自动/手动同步到 Open WebUI 的 Knowledge Base（KB），供 Open WebUI 里的 agent 检索。

## 1. 前置条件

- Open WebUI 已在本机运行（默认 `http://127.0.0.1:8080`）
- Python >= 3.11（oikb 0.4.0 要求）
- 已在 Open WebUI 建好目标 Knowledge Base，记下其 **kb-id**

## 2. 安装 oikb（user 级）

```bash
python3.11 -m pip install --user oikb
oikb --help   # 应能看到 config / daemon / sync / watch 等子命令
```

## 3. 配置（API key 由用户填写，不进仓库）

运行占位脚本，编辑后执行：

```bash
# 编辑 scripts/setup-oikb.sh，把 OIKB_API_KEY 换成你的真实 key
./scripts/setup-oikb.sh
```

脚本内部等价于：

```bash
oikb config set url http://127.0.0.1:8080   # Open WebUI 地址，按实际改
oikb config set token <你的APIKey>            # key 只写入 oikb 用户级配置
```

> ⚠️ 不要把 API key 提交进 git；`setup-oikb.sh` 只是占位模板。

## 4. 手动同步

```bash
./scripts/sync-evidence.sh <run-id> <kb-id>
```

脚本核心即：

```bash
oikb sync $LOOP_HOME/runs/<run-id>/evidence/ --kb-id <kb-id>
```

evidence 目录定位优先级：`LOOP_ENGINEERING_HOME` → 仓库同级 `.loop-engineering/` → `$LOOP_HOME/runs/`。

## 5. 自动触发：loop config hook-on-complete

loop submit 完成后可配 webhook 调 sync-evidence.sh：

```bash
# webhook 需是一个 HTTP(S) URL，收到后自行调 sync-evidence.sh
./loop config hook-on-complete "http://127.0.0.1:9000/hooks/loop-complete"
./loop config show                 # 查看已配置的 hook
./loop config clear-hook-on-complete
```

## 6. daemon（可选，定时/托管同步）

oikb 自带 daemon，读取 `.oikb.yaml` 按配置间隔同步：

```bash
oikb init          # 交互式生成 .oikb.yaml（source=runs 目录, kb-id, interval）
oikb daemon        # 常驻；--port 改健康检查端口，默认 8080 注意与 Open WebUI 区分
```

建议 daemon 端口用 `--port 8790`，避免与本机 Open WebUI(8080) 冲突。

## 7. 故障排查

| 现象 | 处理 |
| --- | --- |
| `oikb: command not found` | 重开终端或 `export PATH="$HOME/.local/bin:$PATH"` |
| sync 报 401 | 运行 setup-oikb.sh 重新填 token |
| 找不到 evidence 目录 | 确认 run id；检查 runtime root（`loop config show`） |
