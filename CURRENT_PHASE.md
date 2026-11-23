# Iris 当前阶段

> 阶段：Phase 4 — Session 化 + 三层记忆 + 双角色
> 状态：后端与前端实现完成；31 个后端测试通过；前端构建通过；待真实 CLI 端到端验收
> 更新时间：2026-11-23
> 依据：`docs/decisions/0006-session-memory.md`、`docs/acceptance/phase4-sessions.md`

## 1. 阶段目标

重新审视 note 形式的记忆后，将 Iris 从 `Project → Task → Run → Note` 改造成：

- **两个角色**：Coding、Scholar。
- **Session 聊天模型**：每个角色下可多开会话；每轮用户消息触发一次 CLI Turn。
- **三层记忆**：
  1. L1 原始记忆：所有消息、工具调用、执行结果完整保存。
  2. L2 摘要记忆：会话结束或达到阈值自动生成滚动摘要。
  3. L3 长期事实：从多次会话摘要提取候选，用户审核后才注入。
- **前端**：参考 Codex / Gemini 的三栏骨架——角色/会话侧栏、聊天主区、记忆侧栏。

## 2. 已实现

### 后端

- Schema **v7**：新增 `sessions`、`turns`、`messages`、`turn_events`、`session_summaries`、`facts`、`fact_extractions`、`facts_fts`；旧表只读保留，**不迁移**。
- **SessionManager**：多轮 Turn，首次 `--session-id`、后续 `--resume`；复用 `build_command`、`ProcessSupervisor`、`normalize_event`。
- **原始记忆**：`messages`（会话级）+ `turn_events`（归一化工具事件）+ 每 Turn 完整 JSONL（`data/session_logs/...`）。
- **并发不变量**：同一 Session 一个活动 Turn；同一工作区一个活动 Coding Turn（DB 部分唯一索引）。
- **MemoryManager**：单 worker 摘要队列；阈值 8 Turn / 24000 字符；会话结束 final 摘要；compact 后清空 CLI session。
- **事实管线**：手动提取、严格 JSON 校验、来源会话校验、指纹去重、`supersedes` 归档；候选只有被接受后才进入上下文。
- **上下文**：事实按角色/作用域/关键词/置顶/预算选择；新 CLI 会话注入摘要，resume 不重复注入；manifest 可追溯。
- **API**：`/api/workspaces`、`/api/sessions`、`/api/turns`、`/api/facts`、`/api/fact-extractions`；健康检查与维护保留。
- 启动时把活动 Turn 标为 `interrupted`，把运行中的摘要/提取标为失败。

### 前端

- 新 `AppShell`：深色角色/会话侧栏 + 聊天主区 + 可折叠记忆侧栏。
- `SessionPage`：消息气泡、Markdown、工具调用卡片（可折叠）、SSE 流式活动、停止、结束、压缩、继续、标题编辑。
- `MemoryPage`：候选/已接受/已拒绝/已归档；接受、编辑、置顶、归档、恢复；提取面板。
- `WorkspacesPage` / `WorkspaceDetailPage`：工作区库、brief、PowerShell 白名单、安全提示、备份入口。
- 删除旧 Task/Project/RunPanel/Mentor/Scholar 前端页面与组件。

### 测试与工具

- 31 个后端测试通过；覆盖会话/Turn、多轮 resume、并发锁、取消、启动校正、原始日志、摘要、compact、事实提取/审核/注入、别名、schema 迁移、备份与安全。
- `scripts/context_report.py` 改为报告 Turn 注入与事实使用。
- `scripts/crash_test.py` 改为 Session Turn 的崩溃/恢复验证。

## 3. 关键决策

- note 是好的长期事实载体，但不应是唯一记忆层；它将 idea 保留为 L3。
- 旧数据不迁移：避免把 Task/Note 语义硬映射到 Session/Fact；旧表只读。
- 摘要自动、事实提取手动 + 审核；模型输出永不自动成为事实。
- 工作区库保留；Coding 必须绑定，Scholar 可选。
- 只保留 Coding / Scholar；Mentor、Testing 移除。
- Scholar 的多子任务研究编排本轮不接入；旧代码与表保留。

## 4. 验收条件

### 4.1 自动化

- [x] Schema v7 创建与旧库非破坏迁移。
- [x] Coding 无工作区被拒绝；Scholar 无工作区可运行。
- [x] 发消息产生 user message、Turn、assistant result、工具事件与原始日志。
- [x] 多轮续聊复用同一 CLI session；resume 失败不自动重试。
- [x] 同 Session / 同工作区并发锁与取消释放。
- [x] 摘要阈值、结束 final 摘要、失败不阻塞、compact 新 CLI 会话 + 摘要注入。
- [x] 事实提取只产候选；接受后才注入；update 归档旧事实；角色/作用域/预算/别名。
- [x] 前端 `npm run build` 通过。

### 4.2 待真实 CLI 验收

- [ ] 真实 CLI 下 Coding 两轮续聊（确认 `--resume`）与工具卡片展示。
- [ ] 真实 CLI 下 Scholar 联网研究（`research` 档位）与来源保留。
- [ ] 真实摘要语义质量与成本观察。
- [ ] 真实事实提取的信噪比、去重与审核体验。
- [ ] compact 在真实 resume 失败场景下的恢复。

## 5. 下一步

1. 用真实 CLI 走一遍 `docs/acceptance/phase4-sessions.md` 的流程。
2. 观察事实注入预算与摘要长度，必要时调整默认阈值。
3. 评估是否把 Scholar 深度研究编排迁移到 Session 之上（单独 ADR）。
4. 视真实使用情况决定是否引入语义检索；当前保持 FTS5 + 关键词 + 别名。
