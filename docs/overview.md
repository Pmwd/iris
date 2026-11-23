# Iris 项目概览（一页版）

> 用途：对外介绍 / 演示 / 快速理解项目现状。  
> 更新时间：2026-11-23 · 版本：v7（Session + 三层记忆 + 双角色）  
> 技术细节见 `README.md`、`CURRENT_PHASE.md`、`docs/roadmap.md`。

## 1. 一句话

**Iris 是一个本地优先的 AI 工作台：两个角色（Coding / Scholar）、Session 聊天、三层记忆，通过本机 Claude Code CLI 执行，并让人工审核后的长期事实跨会话复用。**

它不是“又一个聊天框”，而是试图解决三个问题：

1. 一次性的对话结果，如何变成下一次可复用的上下文？
2. 原始对话、会话摘要、长期事实，如何分层保存而不互相污染？
3. 让 AI 执行本地任务时，如何保留权限边界、来源与可审计性？

## 2. 现在能做什么（演示路径）

1. 启动后打开 <http://127.0.0.1:8000>。
2. 左侧选择 **Coding** 或 **Scholar**，点「新会话」。Coding 必须选一个本地工作区。
3. 输入任务，观察实时工具卡片与最终回答；可以停止、继续、结束会话。
4. 结束会话后自动生成摘要（也可手动重新生成）。
5. 到「记忆库」手动提取候选事实，逐条接受 / 编辑 / 拒绝。
6. 新建会话时，相关且已接受的事实会自动注入；右侧「记忆」面板可追溯。

> 以下截图使用确定性 fake CLI 生成的演示数据，用于可重复展示；真实 CLI 的验收步骤见 `docs/acceptance/phase4-sessions.md`。

### Coding 首页

![Coding 首页](assets/overview-coding-home.png)

### 会话聊天：多轮、工具卡片、原始日志

![会话聊天](assets/overview-session-chat.png)

### 记忆库：候选事实审核

![记忆库](assets/overview-memory.png)

### 工作区：目录、brief、命令白名单

![工作区](assets/overview-workspaces.png)

## 3. 状态一览（2026-11-23）

| 维度 | 状态 |
|---|---|
| 版本 | schema v7；旧 Task/Run/Note 数据只读保留 |
| 角色 | Coding、Scholar 两个活动角色 |
| 会话 | 多会话；多轮 `--session-id` / `--resume`；SSE 实时事件 |
| L1 原始记忆 | 消息 + 工具调用/结果 + 每 Turn 完整 JSONL |
| L2 摘要记忆 | 阈值自动（8 Turn / 24000 字符）或会话结束；滚动累计 |
| L3 长期事实 | 手动提取 → 服务端校验/去重 → 人工审核 → 才注入 |
| 前端 | 三栏聊天工作台、工具卡片、记忆审核、工作区 |
| 自动化 | 31 个后端测试通过；前端构建通过；崩溃恢复脚本通过 |
| 真实 CLI | 端到端验收待执行 |
| 系统大盘 | **尚未实现**，已列入 roadmap M1/M2（可观测 → 大盘） |

## 4. 架构（单进程、本地优先）

```text
React + TypeScript + Vite（三栏 UI）
        │  REST + SSE（127.0.0.1）
        ▼
FastAPI（单进程）
  ├─ SessionManager     会话 / Turn / 取消 / 启动校正
  ├─ MemoryManager      摘要队列 / 事实提取（单 worker）
  ├─ FactRepository     事实审核、作用域、去重、supersede
  ├─ SessionRepository  消息、事件、摘要
  └─ Claude Code CLI    本地子进程；stream-json；Job Object 兜底清理
        │
        ▼
SQLite WAL + data/session_logs/<session>/<turn>.jsonl
```

- 没有 Redis、消息队列、微服务或向量数据库。
- 单用户、本地运行；不监听公网，不保存 CLI 凭据。
- 成本/usage 来自 CLI 报告值，不是账单。

## 5. 三层记忆

| 层 | 存什么 | 何时产生 | 谁能用 |
|---|---|---|---|
| L1 原始记忆 | 所有用户/助手消息、工具调用、执行结果、完整 CLI 输出 | 每次 Turn | UI 追溯；供摘要使用 |
| L2 摘要记忆 | 会话目标、完成项、决策、未决问题、产出、失败教训 | 自动阈值或会话结束 | 新 CLI 会话的连续性；事实提取输入 |
| L3 长期事实 | 偏好、决策、约束、产出、洞察、未决问题、档案 | 用户手动提取 + 审核 | 只有 accepted 才进入后续上下文 |

**安全边界**：

- 模型输出不会自动成为事实；候选必须人工接受。
- 事实、摘要、仓库内容在 prompt 中以参考数据块标注，不拼进 system prompt。
- 旧 `notes` / `global_notes` 永不注入；旧数据不迁移、不在新 UI 展示。

## 6. 两个角色

| 角色 | 用途 | 工作区 | 权限档位 |
|---|---|---|---|
| Coding | 修改代码、运行测试、交付改动 | 必须绑定 | 只读 / 编辑 / 执行（白名单 PowerShell） |
| Scholar | 研究问题、区分事实/观点/假设、保留来源 | 可选 | 只读 / 研究（原生 WebSearch / WebFetch） |

角色是**策略层**：行为、工具权限、上下文策略的组合；不是独立 Agent、模型或记忆库。

## 7. 质量与验证

- **自动化**：`pytest backend/tests -q` → 31 个测试通过；`npm run build` 通过。
- **可靠性**：`scripts/crash_test.py` 验证强杀后端后 CLI 子进程被清理，重启后 Turn 校正为 `interrupted`。
- **并发**：同一 Session 一个活动 Turn；同一工作区一个活动 Coding Turn（DB 部分唯一索引兜底）。
- **可追溯**：每次 Turn 保存注入事实清单、字符数、是否注入摘要；原始日志可下载。
- **待验证**：真实 CLI 下的续聊、Scholar 联网、摘要语义质量、事实提取信噪比。

## 8. 当前限制（介绍时建议主动说明）

- 单用户、本地、单进程；无登录/远程访问/多 worker。
- Scholar 的多子任务深度研究编排（旧 `research_jobs`）本轮未接入新 UI。
- 检索仍是 FTS5 + 关键词 + 别名，不做 embedding；未知改写可能漏。
- 摘要/事实提取需要额外 CLI 调用，会产生成本；默认单 worker 串行。
- 事实提取质量取决于模型；必须人工审核。
- 旧 tasks/runs/notes 数据不迁移、不展示。
- 还没有应用内的系统大盘；当前概览以本文档 + 实际 UI 为准。

## 9. 下一步路线（摘要）

| 里程碑 | 内容 |
|---|---|
| **M0 稳定 v7** | 真实 CLI 端到端验收与阻塞修复 |
| **M1 可观测** | 指标层、健康/错误 API、滚动汇总、本地告警 |
| **M2 全局大盘** | `/dashboard`：一屏看健康、活动、成本、记忆、存储、告警 |
| **M3 记忆质量** | 摘要/事实评估，去重合并，检索实验 |
| **M4 Scholar 深度** | 研究会话编排、来源与候选事实 |
| **M5 体验** | 通知、会话搜索、导出、移动端 |

完整内容见 `docs/roadmap.md`。

## 10. 三分钟介绍脚本（可直接用）

1. **30 秒定位**：Iris 不是聊天工具，而是把“执行 → 原始记录 → 会话摘要 → 审核后的长期事实”串起来的本地工作台。
2. **60 秒演示**：打开 Coding → 新会话 → 发任务 → 工具卡片 → 结束会话生成摘要 → 记忆库提取事实并接受 → 新会话看到事实注入。
3. **60 秒讲架构**：两个角色 + Session/Turn；三层记忆；本地 CLI；SQLite + JSONL；权限档位与并发锁。
4. **30 秒讲现状**：31 个测试、构建与崩溃恢复通过；真实 CLI 验收在即；下一步先做可观测与全局大盘，再用数据决定记忆和 Scholar 深度。

## 11. 在哪里看

| 想看什么 | 去哪里 |
|---|---|
| 项目定位、启动、配置、限制 | `README.md` |
| 当前阶段与验收状态 | `CURRENT_PHASE.md` |
| 后续方向、可观测计划、全局大盘设计 | `docs/roadmap.md` |
| v7 架构决策（Session/三层记忆） | `docs/decisions/0006-session-memory.md` |
| 真实 CLI 验收清单 | `docs/acceptance/phase4-sessions.md` |
| 演示截图 | `docs/assets/overview-*.png` |
| 实际界面 | 启动后访问 <http://127.0.0.1:8000>；页面包括 `/:role`、`/:role/:sessionId`、`/memory`、`/workspaces` |

启动方式：双击仓库根目录 `start.bat`，或：

```powershell
cd D:\vibe\Iris
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```
