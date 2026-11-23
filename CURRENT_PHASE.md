# Iris 当前阶段

> 阶段：Phase 4 — Session + 三层记忆 + 双角色 + Claude Agent SDK 审批 + 工作区运行面板
> 状态：后端与前端实现完成；42 个后端测试通过；前端构建通过；SDK 真实审批冒烟通过；T4–T6 真实验收通过；待完整验收
> 更新时间：2026-11-24
> 依据：`docs/decisions/0006-session-memory.md`、`docs/decisions/0007-agent-sdk-approvals.md`、`docs/acceptance/phase4-sessions.md`

## 1. 阶段目标

重新审视 note 形式的记忆后，将 Iris 从 `Project → Task → Run → Note` 改造成：

- **两个角色**：Coding、Scholar。
- **Session 聊天模型**：每个角色下可多开会话；每轮用户消息触发一次 Turn。
- **三层记忆**：
  1. L1 原始记忆：所有消息、工具调用、执行结果完整保存。
  2. L2 摘要记忆：会话结束或达到阈值自动生成滚动摘要。
  3. L3 长期事实：从多次会话摘要提取候选，用户审核后才注入。
- **执行层**：默认 Claude Agent SDK；工具调用逐条审批（允许一次 / 总是允许 / 拒绝）。
- **前端**：参考 Codex / Gemini 的三栏骨架——角色/会话侧栏、聊天主区、记忆侧栏。

## 2. 已实现

### 后端

- Schema **v8**：v7 的 `sessions`、`turns`、`messages`、`turn_events`、`session_summaries`、`facts`、`fact_extractions`、`facts_fts`，新增 `turn_approvals`、`permission_rules`；旧表只读保留，**不迁移**。
- **执行层**：`SdkTurnRunner` 使用 `ClaudeSDKClient` + `can_use_tool`；`cli_path` 指向原生 `claude.exe`；`setting_sources=["user"]` 保留 CC Switch/DeepSeek；首次新 session、后续 resume。
- **审批桥接**：`ApprovalManager` 将 `can_use_tool` 挂起，等待 HTTP 决策；支持允许一次/总是允许/拒绝、超时、取消；事件写入 `turn_events`，记录写入 `turn_approvals`。
- **进程树清理**：每 Turn 附加 Windows Job Object；取消时先调度 async 取消（状态记为 `canceled`），再关闭 Job 并 `taskkill /T /F`，工具子进程不会残留；后端被强杀时 `KILL_ON_JOB_CLOSE` 兜底。
- **审批规则**：会话级规则，PowerShell 命令前缀、Write/Edit 文件路径、其他精确输入；写入 `permission_rules`；“总是允许”后自动放行。
- **CLI 回退**：`IRIS_EXECUTION_BACKEND=cli` 保留旧 one-shot `build_command` + fake CLI 测试路径。
- **工作区运行面板**：`WorkspaceProcessManager` 在工作区目录启动长驻命令，线程读取输出（内存保留 2000 行并追加 `data/workspace_processes/<id>.log`），支持状态、PID、退出码、停止进程树；删除工作区/关闭 Iris 时清理；进程记录仅内存保存。
- **原始记忆**：`messages` + `turn_events` + 每 Turn 完整 JSONL（SDK 消息 JSONL / CLI stream-json）。
- **增量流式**：SDK `include_partial_messages=True`，`text_delta` 聚合成 `assistant.delta`（约 60 字/0.1 秒）写入事件流，经 SSE 推送；最终 `assistant.text` 覆盖草稿。
- **并发不变量**：同一 Session 一个活动 Turn；同一工作区一个活动 Coding Turn（DB 部分唯一索引）。
- **MemoryManager**：单 worker 摘要队列；阈值 8 Turn / 24000 字符；结束 final 摘要；compact 后清空 CLI session。
- **事实管线**：手动提取、严格 JSON 校验、来源会话校验、指纹去重、`supersedes` 归档；候选只有被接受后才进入上下文。
- **上下文**：事实按角色/作用域/关键词/置顶/预算选择；新 CLI 会话注入摘要，resume 不重复注入；manifest 可追溯。
- **API**：`/api/workspaces`、`/api/sessions`、`/api/turns`、`/api/approvals`、`/api/facts`、`/api/fact-extractions`、`/api/workspaces/{id}/processes`、`/api/processes/{id}`；健康检查与维护保留。
- 启动时把活动 Turn 标为 `interrupted`，运行中的摘要/提取标为失败，pending 审批标为过期。

### 前端

- 新 `AppShell`：深色角色/会话侧栏 + 聊天主区 + 可折叠记忆侧栏。
- `SessionPage`：消息气泡、Markdown、工具调用卡片、审批卡片、SSE 流式活动（增量文本 + 工具事件）、停止、结束、压缩、继续、标题编辑。
- `ApprovalCard`：显示工具、命令/文件、风险提示；允许一次 / 总是允许 / 拒绝；决策后显示已允许/已拒绝/已过期。
- SDK 模式下执行档位不再要求工作区 PowerShell 白名单。
- `MemoryPage`：候选/已接受/已拒绝/已归档；接受、编辑、置顶、归档、恢复；提取面板。
- `WorkspacesPage` / `WorkspaceDetailPage`：工作区库、brief、PowerShell 白名单（CLI 回退用）、安全提示、备份入口。
- `WorkspaceRunner`：运行面板——命令/预设、启动、进程列表（状态/PID/退出码）、实时日志轮询（跟随最新）、停止；归档工作区不能启动。
- 删除旧 Task/Project/RunPanel/Mentor/Scholar 前端页面与组件。

### 测试与工具

- **42 个后端测试通过**：会话/Turn、多轮 resume、并发锁、取消、启动校正、原始日志、摘要、compact、事实提取/审核/注入、别名、schema v8 迁移、备份与安全；审批桥接允许/拒绝/always/超时/取消与规则匹配；运行面板启动/日志/停止、参数校验、归档工作区与删除时清理进程；Windows Job Object 与 taskkill 进程树清理。
- **真实 SDK 冒烟**：本机 CLI 2.1.221 + CC Switch/DeepSeek，`can_use_tool` 触发 PowerShell 审批；允许后文件真实生成；同会话 resume 成功；成本/usage 返回。
- 前端 `npm run build` 通过；pending 审批卡片已用 Edge/Playwright 截图验证。
- `scripts/context_report.py` 报告 Turn 注入与事实使用；`scripts/crash_test.py` 验证 Session Turn 崩溃/恢复。

## 3. 关键决策

- note 是好的长期事实载体，但不应是唯一记忆层；它将 idea 保留为 L3。
- 旧数据不迁移：避免把 Task/Note 语义硬映射到 Session/Fact；旧表只读。
- 摘要自动、事实提取手动 + 审核；模型输出永不自动成为事实。
- 工作区库保留；Coding 必须绑定，Scholar 可选。
- 只保留 Coding / Scholar；Mentor、Testing 移除。
- Scholar 的多子任务研究编排本轮不接入；旧代码与表保留。
- 默认 Claude Agent SDK 执行；审批是粒度更细的门禁，但不是 OS 沙箱。

## 4. 验收条件

### 4.1 自动化

- [x] Schema v8 创建与旧库非破坏迁移。
- [x] Coding 无工作区被拒绝；Scholar 无工作区可运行。
- [x] 发消息产生 user message、Turn、assistant result、工具事件与原始日志。
- [x] 多轮续聊复用同一 CLI session；resume 失败不自动重试。
- [x] 同 Session / 同工作区并发锁与取消释放。
- [x] 摘要阈值、结束 final 摘要、失败不阻塞、compact 新 CLI 会话 + 摘要注入。
- [x] 事实提取只产候选；接受后才注入；update 归档旧事实；角色/作用域/预算/别名。
- [x] 审批桥接允许/拒绝/always/超时/取消；规则匹配。
- [x] 运行面板启停、日志增量、PID/退出码、归档拒绝启动、删除工作区时停止进程。
- [x] 前端 `npm run build` 通过。

### 4.2 真实 CLI / SDK 验收

- [x] SDK 在 Windows + 本机 `claude.exe` + CC Switch/DeepSeek 下触发 `can_use_tool`。
- [x] 允许 PowerShell 后真实执行并生成文件；成本/usage 返回。
- [x] 同一 Session 通过 SDK resume 续聊。
- [x] pending 审批卡片在网页中可见并可决策。
- [x] 记忆召回：新 Session 的 manifest 注入 accepted 事实（reason=matched），`use_count` +1，回答使用该事实。
- [x] 取消：允许长驻 `python` 命令后取消，状态 `canceled`，工具子进程被终止，同一 Session 可继续。
- [x] 异常退出：强杀后端后 CLI 与其工具进程被清理；重启 `reconciled_turns=1`，Turn=`interrupted`，pending 审批=`expired`，锁释放，后续 Turn 成功。
- [ ] Scholar 联网研究（`research` 档位）与来源保留。
- [ ] 真实摘要语义质量与成本观察。
- [ ] 真实事实提取的信噪比、去重与审核体验。
- [ ] compact 在真实 resume 失败场景下的恢复。
- [ ] 真实 UI 中的“总是允许/拒绝/超时”完整手工流程。
- [ ] 运行面板：真实 dev server 启动、日志刷新、停止与关闭 Iris 后的进程清理。

## 5. 下一步

后续方向、可观测计划与全局系统大盘见 `docs/roadmap.md`（M0 真实验收 → M1 最小可观测 → M2 记忆质量 → M3 大盘 → M4 Scholar → M5 体验）。

1. 完成 `docs/acceptance/m0-real-cli.md` 的 T1–T6 矩阵与 `docs/acceptance/phase4-sessions.md` 的完整真实 SDK 验收。
2. 按 M1 建立最小指标层与健康/错误 API（Token、耗时、成功率、工具调用、错误），暂不做告警。
3. 按 M2 用 10–20 个真实案例验证摘要保留、事实提取、跨 Session 召回与冲突处理。
4. 基于 M1 指标与 M2 结论做 M3 全局大盘，再决定是否调整摘要阈值、事实注入预算与检索策略。
5. 评估是否把 Scholar 深度研究编排迁移到 Session 之上（先验证相对普通聊天的增量价值，单独 ADR）。
6. 视真实使用情况决定是否引入语义检索；当前保持 FTS5 + 关键词 + 别名。
