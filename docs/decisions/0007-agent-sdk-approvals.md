# ADR 0007：Claude Agent SDK 与交互式工具审批

- 状态：已实现（2026-11-23）
- 关联：`docs/decisions/0006-session-memory.md`、`README.md`、`CURRENT_PHASE.md`
- 取代：`--permission-mode dontAsk` + 预先白名单的默认执行方式（保留为 CLI 回退）

## 背景

v7 的 Turn 是“一次性 `claude -p` + 预授权 PowerShell 白名单”。用户希望得到接近 Claude terminal 的体验：模型要执行命令时，网页弹出审批，用户逐条选择允许/拒绝。

裸 `control_request/control_response` 协议能实现，但需要自己维护未公开的双向协议。经调研与 spike，Claude Agent SDK 提供官方封装：

- `ClaudeSDKClient` + `can_use_tool` 回调；
- 流式会话、interrupt、`set_permission_mode`；
- `cli_path`、`env`、`setting_sources`、`resume`、cost/usage。

本机 spike（Windows + `claude.exe` 2.1.221 + CC Switch/DeepSeek）已验证：`can_use_tool` 在 Write 和 PowerShell 上触发；允许后文件真实生成；拒绝后工具不执行；同一 Session resume 成功；`ResultMessage` 返回成本与 model usage。

## 决策

### 1. 默认执行后端：Claude Agent SDK

- 新增 `claude-agent-sdk` 依赖，`SdkTurnRunner` 用 `ClaudeSDKClient` 执行 Turn。
- `IRIS_EXECUTION_BACKEND=sdk` 为默认；`cli` 保留为旧 one-shot/fake CLI 回退。
- 普通测试使用 `execution_backend="cli"` 与 fake CLI；审批桥接用独立测试。

### 2. 交互审批

- `ClaudeAgentOptions(permission_mode="default", can_use_tool=...)`。
- `can_use_tool` 先匹配会话级规则；未命中则创建 `turn_approvals` 记录、发出 `approval.requested` 事件，并 await 一个 `asyncio.Future`。
- 前端聊天内 `ApprovalCard` 提供允许一次 / 总是允许 / 拒绝；HTTP `POST /api/approvals/{id}/decide` 解析 Future。
- 决策后发出 `approval.decided`；工具结果继续按正常 `tool.result` 事件进入聊天。
- 超时（默认 600s）按拒绝；取消 Turn 会拒绝所有 pending 审批。

### 3. 规则与审计

- `permission_rules`：会话级“总是允许”规则。
  - PowerShell/Bash：命令前缀（第一个 token）。
  - Write/Edit：文件路径。
  - 其他工具：精确输入 JSON。
- `turn_approvals`：每次请求、决策、决策者（user/auto/system/timeout）与消息。
- 规则在会话删除时级联清理；当前没有 UI 管理/清除规则。

### 4. 工具与权限映射

- `read_only`：禁止 Write/Edit/NotebookEdit/PowerShell/Bash 与 Web/子 Agent。
- `edit`：允许读/写/编辑；禁止 PowerShell/Bash 与 Web/子 Agent。
- `execute`：允许读/写/编辑/PowerShell；写入和 shell 通过审批；禁止 Web/子 Agent。
- `research`：允许 WebSearch/WebFetch 与只读工具；禁止写文件与 shell。
- SDK 模式下 `execute` 不再要求工作区 PowerShell 白名单；白名单只用于 CLI 回退。

### 5. SDK 选项与兼容

- `cli_path` 指向原生 `claude.exe`；Windows 上 npm 的 `claude.cmd` 不被 SDK 直接接受，Iris 会从 shim 推导或使用 `IRIS_CLAUDE_CLI_PATH`。
- `setting_sources=["user"]`：保留用户的 CC Switch/DeepSeek 配置，不加载项目/本地设置；用户级 hooks/插件仍可能加载。
- `system_prompt` 使用角色自包含指令；`resume` 使用 session 的 `cli_session_id`；`max_turns` 沿用配置。
- `ResultMessage.total_cost_usd`、`usage`、`model_usage` 写入 Turn；原始 SDK 消息写入 JSONL。
- 未把 `model` 写死，保持 CC Switch/DeepSeek 的路由。

### 6. 进程树清理与取消语义

- 每个 Turn 创建独立的 Windows Job Object，并在 `ClaudeSDKClient` 启动后把 SDK 拉起的 `claude.exe` 附加进去。
- 取消 Turn：先调度取消 async task（保证状态记为 `canceled`），再关闭 Job Object 并 `taskkill /PID <cli_pid> /T /F`，确保 PowerShell/python 等工具子进程一起结束。
- 后端异常退出：Job Object 句柄随进程关闭，`KILL_ON_JOB_CLOSE` 兜底清理 CLI 与工具进程；重启后 `reconcile` 把 Turn 标为 `interrupted`、pending 审批标为 `expired`、运行中的摘要/提取标为失败。
- 真实 SDK 已验证：取消长时间运行的 `python sleepy.py` 后进程消失、状态为 `canceled`、同一 Session 可继续；强杀后端后 CLI 树被清理，重启后 Turn=`interrupted`、审批=`expired`、锁释放。

### 7. Schema v8

新增：

- `turn_approvals(id, turn_id, session_id, tool_name, input_json, status, decision, message, decided_by, created_at, decided_at)`
- `permission_rules(id, session_id, tool_name, match_type, match_value, created_at)`

旧表与 v7 数据不变。

## 后果

- 网页具备逐条工具审批，粒度接近 terminal，但**不是 OS 沙箱**；批准的命令以 Iris 后端用户权限运行。
- 默认 SDK 依赖 `claude.exe` 和 Python `claude-agent-sdk`；CLI 回退保留。
- Python SDK 的 `can_use_tool` 依赖 streaming 模式；当前 pin 0.2.187 并验证 `ClaudeSDKClient` 路径；升级 SDK 需重跑审批验收。
- SDK 可能加载用户级 hooks/插件；项目/本地设置被排除；工作区仍必须可信。
- “总是允许”是会话级；规则可能较宽（PowerShell 按第一个 token），需要用户理解风险。
- 助手文本按增量块流式（SDK partial messages，约 60 字/0.1 秒聚合，SSE 约 0.25 秒推送），非逐 token；工具事件仍实时。
- 审批请求/决策存储本地 SQLite；不会发送到外部服务。

## 明确不做

- 不自己实现裸 `control_request/control_response` 协议（SDK 已封装）。
- 不提供容器/VM 级隔离；需要强隔离请使用 Windows Sandbox/VM/低权限用户。
- 不自动接受工具权限或自动把审批规则提升为全局。
- 不加载项目/本地 `.claude` 设置；不启用 MCP/插件/子 Agent。
