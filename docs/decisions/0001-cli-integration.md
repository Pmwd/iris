# ADR 0001：Phase 1 的 CLI 集成方式

- 状态：已采用（Phase 1，2026-10-23）
- 日期：2026-10-23
- 依据：`docs/spikes/cli-integration.md`、`docs/acceptance/phase1.md`

## 背景

Phase 0 需要确认本地 Claude Code CLI 能否作为 Iris 的执行后端，并在 Windows 上安全地处理编辑、命令执行、取消和恢复。

## 决策

1. 通过 `shutil.which("claude")` 定位 CLI，直接调用其 `.CMD`；不使用 `shell=True`。
2. 子进程使用 UTF-8 编码，并捕获 stdout 和 stderr。
3. prompt 通过 stdin 传入；不把多行 prompt 作为 `.CMD` 的命令行参数。
4. 新会话使用 `--session-id <uuid>`；恢复使用 `--resume <session_id>`。
5. 流式运行使用 `--output-format stream-json --verbose`。
5. 默认使用 `--safe-mode`，阻止项目 hooks、插件、MCP 和自定义扩展。
6. 使用 `--tools` 限制工具集合；Windows shell 工具名为 `PowerShell`。
7. 权限档位：
   - 只读：`Read,Glob,Grep`。
   - 编辑：`Read,Glob,Grep,Write,Edit` + `acceptEdits`。
   - 执行：加入 `PowerShell`，使用 `dontAsk` + 明确允许/拒绝列表；用户显式开启。
8. 取消运行使用 `taskkill /PID <pid> /T /F`；Phase 1.5 评估 Job Object。
9. 成本显示为 CLI 报告的 `total_cost_usd` / usage，不作为账单依据。
10. 强杀后恢复失败时，新建 session 并注入结构化 handoff，不假装恢复。

## 后果

- Iris 的 CLI 适配层必须感知 Windows 工具名和 `.CMD` 调用。
- 执行档位比 `acceptEdits` 更严格；不能在非交互模式下依赖人工审批。
- 工作区必须显式信任；CLAUDE.md 仍可能被加载，视为不可信输入。
- 需要进程监督、启动时状态校正和可审计的权限记录。
- 真实 CLI 调用只用于显式 smoke test；常规测试使用假 CLI。

## 未决问题

- 认证失败路径未复现。
- 用户级 hooks/MCP/skills、`--add-dir`、超长 prompt 的行为。
- 服务崩溃后的孤儿进程清理。
- 本地 API 的 Origin/Host 保护。
- 跨 CLI 版本的兼容性。
