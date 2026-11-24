# ADR 0006：Session 工作台与三层记忆

- 状态：已实现（2026-11-23）；事实提取已由 ADR 0010 扩展为“会话结束自动候选 + 手动提取 + 聊天记住，仍人工接受”，历史决策保留。
- 关联：`README.md`、`CURRENT_PHASE.md`、`docs/acceptance/phase4-sessions.md`
- 取代：Phase 1–3C 的 Task/Run/Note 交互模型；旧表保留只读

## 背景

Phase 1–3C 用 `Note` 作为唯一记忆层：只有用户手动接受的任务结果/全局 note 会进入后续上下文。重新审视后：

- Note 作为**长期事实载体**是合适的：显式、可审计、用户可控，模型推测不会自动变成事实。
- Note 作为**唯一记忆层**不足：
  - 原始对话与工具调用只存在 `run_events`，且大 payload 被截断，未参与记忆。
  - 没有自动摘要；跨会话的“为什么、试过什么、哪里失败、哪些未决”会丢失。
  - note 靠手工沉淀，`progress` 无界累积。
  - episodic 与 semantic 混在一层；关键词检索对未知改写会漏。

用户确认的新方向：两个角色、Session 聊天、三层记忆、Codex/Gemini 风格前端；旧数据不迁移；摘要自动、事实提取手动并审核；保留工作区库。

## 决策

### 1. 角色只保留 Coding / Scholar

- Role 仍是策略层：行为、工具档位、上下文策略，不是独立 Agent/模型/记忆库。
- Coding：`read_only | edit | execute`，默认 `edit`；必须有工作区。
- Scholar：`read_only | research`，默认 `read_only`；工作区可选。
- Mentor、Testing 从活动角色中移除；旧代码/数据保留只读。

### 2. Session / Turn 模型

- `sessions`：角色、标题、绑定工作区、状态、CLI session id、摘要 checkpoint。
- `turns`：一次用户消息触发的一次 CLI 执行，记录 mode（new/resume）、权限档位、manifest、成本、错误。
- 首次 Turn 使用 `--session-id`，之后 `--resume`；resume 失败**不自动重试**。
- 应用层检查 + DB 部分唯一索引保证：
  - 同一 Session 最多一个活动 Turn；
  - 同一工作区最多一个活动 Coding Turn；
  - Scholar 会话可并发。

### 3. L1 原始记忆

- `messages`：会话级 user / assistant 最终 / system 消息。
- `turn_events`：归一化的工具调用、工具结果、stderr、权限拒绝、process exit 等，用于 UI。
- `data/session_logs/<session>/<turn>.jsonl`：完整 stdout，**不截断**。
- 数据库内事件按 `IRIS_MAX_EVENT_PAYLOAD_CHARS` 截断以控制体积；完整内容在 JSONL。

### 4. L2 摘要记忆

- 触发：成功 Turn 数 ≥ 8 或新增字符 ≥ 24000，或会话结束。
- 单 worker 串行，避免成本尖峰；同一会话已有 pending/running 摘要时跳过重复入队。
- 输入：上一份摘要 + checkpoint 之后的 Turn（用户消息、最终结果、工具名摘要）；上限 30000 字符。
- 输出固定 Markdown 小节：目标、已完成、关键决策、未决问题、产出/文件、失败与教训。
- 存储为累计摘要，带 `covers_through_turn_seq`；最新 succeeded 为当前摘要。
- `compact`：摘要成功后清空 CLI session；下一条消息以 `new` 启动，并注入最新摘要与事实。

### 5. L3 长期事实

- 只从会话摘要提取，**手动触发**；单次只允许一个提取任务。
- 输出严格 JSON；服务端校验枚举、scope/project、来源会话必须是输入子集、update 目标必须存在且 accepted；confidence 截断到 [0,1]。
- 指纹去重（title + kind + scope + project）；同批合并来源；与 accepted 指纹相同转 update。
- 全部写为 `candidate`；**绝不自动接受**。
- 接受 update 时同一事务归档旧事实并写 `supersedes_id`。
- 删除/归档不物理删除已接受事实（UI 提供归档）。

### 6. 上下文注入

- 事实按角色、全局/工作区作用域、关键词/别名、置顶、最近使用与字符预算选择；只有 accepted 可注入。
- 新 CLI 会话（首次或 compact 后）注入最新摘要；resume 不重复注入摘要。
- 事实、摘要、仓库内容用定界块标注为参考数据，不拼入 system prompt。
- 每次 Turn 记录 manifest：注入/排除事实、原因、字符数、是否注入摘要，供 UI 与审计。

### 7. 工作区与旧数据

- 复用 `projects` 表作为工作区库（brief、allowed_tools、archive）。
- 旧 `tasks`、`runs`、`run_events`、`notes`、`global_notes`、`research_*` 只读保留：
  - 不迁移到 Session/Fact；
  - 不进入新 UI；
  - 不进入新上下文；
  - schema v7 迁移非破坏。

### 8. 前端

- 三栏骨架：侧栏（角色切换、会话列表、新会话、记忆/工作区入口）+ 聊天主区 + 记忆侧栏。
- 聊天：用户/助手气泡、Markdown、可折叠工具卡片、SSE 活动、停止、结束、压缩、继续。
- 记忆页：候选/已接受/已拒绝/已归档；接受、编辑、置顶、归档、恢复；提取面板。
- 依赖新增 `react-markdown` + `remark-gfm`；不引入图标库。

## 后果

- 原始对话可追溯，摘要让跨会话回顾不依赖手工 note。
- 长期事实仍由用户把关；候选噪声不会自动污染上下文。
- 旧数据与旧代码隔离，避免语义错配；但旧工作台在新 UI 中不可见。
- 每次摘要/提取会增加 CLI 成本；默认单 worker、阈值可配置。
- 单进程 uvicorn 假设：内存中的进程/取消表不跨 worker；DB 索引仍提供并发兜底。
- 检索仍是词法 + 别名，不是语义检索。

## 明确不做

- 自动接受事实、自动创建会话/任务、自动修改工作区。
- 把旧 task/note 硬迁移为 session/fact。
- Mentor / Testing 角色与其状态模型。
- 本轮接入 Scholar 多子任务深度研究编排。
- 向量检索、embedding、远程多用户、在线热恢复。
