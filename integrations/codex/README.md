# Codex 接入 KnowNexus

本目录只保存外部客户端配置模板，核心实现位于项目内部。项目不会自动修改你的
`~/.codex` 全局配置。

## 1. 启动本地服务

```powershell
.venv\Scripts\python.exe -m uvicorn study_help_agent.app.main:app --host 127.0.0.1 --port 8001
```

启动后：

- 捕获 API：`http://127.0.0.1:8001/api/external-conversations/turns`
- MCP：`http://127.0.0.1:8001/mcp/`
- 健康检查：`http://127.0.0.1:8001/health`

## 2. 配置 MCP

把 `config.example.toml` 的内容合并到 `~/.codex/config.toml`，然后重启 Codex。
MCP 提供知识检索、记忆溯源、手动捕获和强制蒸馏四个工具。

## 3. 启动自动会话捕获

当前 Codex 桌面端/CLI 没有公开的 `/hooks` 生命周期配置。本项目通过只读监听
`~/.codex/sessions/**/rollout-*.jsonl` 自动捕获已经完成的对话轮次，不会修改
Codex 的配置或会话文件。

打开第二个 PowerShell 窗口，在项目根目录执行：

```powershell
.venv\Scripts\python.exe -m study_help_agent.integrations.adapters.codex.cli
```

监听器默认每 30 秒检查当天目录和近期活跃文件，只读取新增字节；每 60 秒执行一次
全目录发现作为兜底，并且：

1. 忽略 system/developer、推理过程、工具调用和 commentary；
2. 以 `task_complete` 为完成边界，只保存用户输入和最终助手回复；
3. 先写入本地暂存队列，再投递到 8001；后端离线时不会丢失；
4. 通过文件偏移量和 `(session_id, turn_id)` 防止重复保存。

默认不导入监听器启动前的历史会话。确实需要首次回填时，使用：

```powershell
.venv\Scripts\python.exe -m study_help_agent.integrations.adapters.codex.cli --backfill
```

`hooks.example.json` 只保留用于手工模拟事件、验证旧 Hook 接收适配器；Codex
当前不会自动读取该文件，也不需要把它复制到 `~/.codex`。

默认队列位于 `%LOCALAPPDATA%\personal_agent\codex_capture_spool.db`。可用环境变量：

- `PERSONAL_AGENT_URL`：后端地址，默认 `http://127.0.0.1:8001`；
- `PERSONAL_AGENT_CAPTURE_SPOOL`：自定义暂存数据库路径。
- `CODEX_SESSIONS_DIR`：覆盖 Codex 会话目录；
- `PERSONAL_AGENT_CODEX_POLL_INTERVAL`：扫描间隔秒数，默认 `3.0`；
- `PERSONAL_AGENT_CODEX_FULL_SCAN_INTERVAL`：全目录兜底扫描间隔，默认 `60.0`；
- `PERSONAL_AGENT_CODEX_CHECKPOINT`：自定义读取检查点数据库路径。
- `PERSONAL_AGENT_CODEX_INCLUDE_CWD`：只捕获这些目录，Windows 下用分号分隔；
- `PERSONAL_AGENT_CODEX_EXCLUDE_CWD`：排除这些目录，Windows 下用分号分隔；
- `PERSONAL_AGENT_CODEX_MIN_PROMPT_LENGTH`：用户输入最小字符数，默认 `1`；
- `PERSONAL_AGENT_CODEX_CAPTURE_CASUAL`：是否捕获简单寒暄，默认 `true`。

当前只保存可见的用户输入与最终助手回复，不保存隐藏推理、工具内部状态或子 Agent
私有过程。其他 MCP 客户端仍可按需调用 `capture_external_turn`。
