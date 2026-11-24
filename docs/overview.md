# Iris 项目概览（一页版）

> 用途：对外介绍 / 演示 / 快速理解项目现状。  
> 更新时间：2026-11-24 · 版本：v8（Session + 三层记忆 + 双角色 + SDK 审批 + 工作区运行面板）  
> 技术细节见 `README.md`、`CURRENT_PHASE.md`、`docs/roadmap.md`。

## 1. 一句话

**Iris 是一个本地优先的 AI 工作台：两个角色（Coding / Scholar）、Session 聊天、三层记忆，通过 Claude Agent SDK 驱动本机 Claude Code CLI，并逐条审批工具调用、让人工审核后的长期事实跨会话复用。**

它不是“又一个聊天框”，而是试图解决三个问题：

1. 一次性的对话结果，如何变成下一次可复用的上下文？
2. 原始对话、会话摘要、长期事实，如何分层保存而不互相污染？
3. 让 AI 执行本地任务时，如何保留权限边界、来源与可审计性？

## 2. 现在能做什么（演示路径）

1. 启动后打开 <http://127.0.0.1:8000>。
2. 左侧选择 **Coding** 或 **Scholar**，点「新会话」。Coding 必须选一个本地工作区。
3. 输入任务，观察增量流式文本与实时工具卡片；需要写文件或执行命令时，聊天里出现审批卡片（允许一次 / 总是允许 / 拒绝）。
4. 工作区详情页底部可以打开「运行面板」，直接启动 dev server、查看日志并停止。
5. 可以停止、继续、结束会话；结束后自动生成摘要（也可手动重新生成）。
6. 到「记忆库」手动提取候选事实，逐条接受 / 编辑 / 拒绝。
7. 新建会话时，相关且已接受的事实会自动注入；右侧「记忆」面板可追溯。

> 以下截图使用确定性 fake CLI 生成的演示数据，用于可重复展示；真实 CLI 的验收步骤见 `docs/acceptance/phase4-sessions.md`。

### Coding 首页

![Coding 首页](assets/overview-coding-home.png)

### 会话聊天：多轮、工具卡片、原始日志

![会话聊天](assets/overview-session-chat.png)

### 工具审批：允许一次 / 总是允许 / 拒绝

![审批卡片](assets/approval-pending.png)

### 记忆库：候选事实审核

![记忆库](assets/overview-memory.png)

### 工作区：目录、brief、命令白名单

![工作区](assets/overview-workspaces.png)

## 3. 状态一览（2026-11-23）

| 维度 | 状态 |
|---|---|
| 版本 | schema v8；旧 Task/Run/Note 数据只读保留 |
| 角色 | Coding、Scholar 两个活动角色 |
| 会话 | 多会话；SDK 首次新 session、后续 resume；SSE 增量文本 + 工具事件 |
| 执行与审批 | Claude Agent SDK；`can_use_tool` 逐条审批；会话级 permission rules |
| L1 原始记忆 | 消息 + 工具调用/结果 + 每 Turn 完整 JSONL |
| L2 摘要记忆 | 阈值自动（8 Turn / 24000 字符）或会话结束；滚动累计 |
| L3 长期事实 | 手动提取 → 服务端校验/去重 → 人工审核 → 才注入 |
| 前端 | 三栏聊天工作台、工具卡片、审批卡片、记忆审核、工作区、运行面板 |
| 运行面板 | 工作区内启动/停止长驻命令、PID/退出码、实时日志（内存 + 文件） |
| 自动化 | 46 个后端测试通过；前端构建通过；崩溃恢复脚本通过 |
| 真实 CLI | SDK 审批冒烟通过；T4–T6 通过；完整验收清单待补 T1–T3/Scholar/摘要 |
| 最小可观测 | ✅ M1 API：overview / health / errors；无 Dashboard/告警 |
| 记忆质量 | ✅ M2 19/19（摘要/提取/更新/召回/隔离/冲突/预算/manifest） |
| 系统大盘 | **尚未实现**，已列入 roadmap M3（M1 最小可观测 → M2 记忆质量 → M3 大盘） |

## 4. 架构（单进程、本地优先）

```text
React + TypeScript + Vite（三栏 UI）
        │  REST + SSE（127.0.0.1）
        ▼
FastAPI（单进程）
  ├─ SessionManager       会话 / Turn / 取消 / 启动校正
  ├─ ApprovalManager      can_use_tool 挂起 → HTTP 决策 → 规则写入
  ├─ MemoryManager        摘要队列 / 事实提取（单 worker）
  ├─ ProcessManager       工作区长驻命令 / 日志 / 停止进程树
  ├─ FactRepository       事实审核、作用域、去重、supersede
  ├─ SessionRepository    消息、事件、摘要、审批
  └─ Claude Agent SDK     spawn 原生 claude.exe；streaming；resume
        │
        ▼
SQLite WAL + data/session_logs/<session>/<turn>.jsonl
```

- 没有 Redis、消息队列、微服务或向量数据库。
- 单用户、本地运行；不监听公网，不保存 CLI 凭据。
- 成本/usage 来自 CLI 报告值，不是账单。
- 审批是应用层门禁，不是 OS 沙箱；批准的命令以当前用户身份执行。

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
| Coding | 修改代码、运行测试、交付改动 | 必须绑定 | 只读 / 编辑 / 执行（SDK 逐条审批；CLI 回退用白名单） |
| Scholar | 研究问题、区分事实/观点/假设、保留来源 | 可选 | 只读 / 研究（原生 WebSearch / WebFetch） |

角色是**策略层**：行为、工具权限、上下文策略的组合；不是独立 Agent、模型或记忆库。

审批规则是**会话级**：PowerShell 按命令前缀、Write/Edit 按文件路径、其他工具按精确输入；“总是允许”写入 `permission_rules`，新会话重新请求。

## 7. 质量与验证

- **自动化**：`pytest backend/tests -q` → 46 个测试通过；`npm run build` 通过。
- **审批**：允许/拒绝/总是允许/超时/取消与规则匹配有单测；本机 `claude.exe` + CC Switch/DeepSeek 下真实验证过 PowerShell 审批、文件生成与 resume。
- **可靠性**：`scripts/crash_test.py` 验证强杀后端后 CLI 子进程被清理，重启后 Turn 校正为 `interrupted`。
- **并发**：同一 Session 一个活动 Turn；同一工作区一个活动 Coding Turn（DB 部分唯一索引兜底）。
- **可追溯**：每次 Turn 保存注入事实清单、字符数、是否注入摘要；审批记录写入 `turn_approvals`；原始日志可下载。
- **待验证**：Scholar 联网、真实摘要语义质量、事实提取信噪比、完整审批手工流程。

## 8. 当前限制（介绍时建议主动说明）

- 单用户、本地、单进程；无登录/远程访问/多 worker。
- 审批不是沙箱；SDK 可能加载用户级 hooks/插件，工作区必须可信。
- “总是允许”规则目前是会话级，没有 UI 管理/清除。
- 运行面板不经过审批，也不是沙箱；进程记录只在内存，后端重启会停止进程并清空列表。
- Scholar 的多子任务深度研究编排（旧 `research_jobs`）本轮未接入新 UI。
- 检索仍是 FTS5 + 关键词 + 别名，不做 embedding；未知改写可能漏。
- 摘要/事实提取需要额外 CLI 调用，会产生成本；默认单 worker 串行。
- 事实提取质量取决于模型；必须人工审核。
- 旧 tasks/runs/notes 数据不迁移、不展示。
- 可观测目前是 M1 API；还没有应用内 Dashboard、timeseries/rollups 与告警（M3）。

## 9. 下一步路线（摘要）

| 里程碑 | 内容 |
|---|---|
| **M0 真实验收** | T1–T6、审批全流程、Scholar、真实摘要与阻塞修复 |
| **M1 最小可观测** | ✅ Token/耗时/成功率/健康/错误 API；暂不做告警 |
| **M2 记忆质量** | ✅ 19/19 案例通过（真实 SDK） |
| **M3 全局大盘** | rollups + `/dashboard`：健康、活动、成本、记忆、存储 |
| **M4 Scholar 深度** | 先验证增量价值，再研究会话编排、来源与候选事实 |
| **M5 体验** | 通知、会话搜索、导出、移动端 |

完整内容见 `docs/roadmap.md`。

## 10. 三分钟介绍脚本（可直接用）

1. **30 秒定位**：Iris 不是聊天工具，而是把“执行 → 原始记录 → 会话摘要 → 审核后的长期事实”串起来的本地工作台。
2. **60 秒演示**：打开 Coding → 新会话 → 发任务 → 工具卡片 → 审批卡片允许一次 → 结束会话生成摘要 → 记忆库提取事实并接受 → 新会话看到事实注入。
3. **60 秒讲架构**：两个角色 + Session/Turn；三层记忆；SDK 执行 + 逐条审批；SQLite + JSONL；权限档位与并发锁。
4. **30 秒讲现状**：46 个测试、构建与崩溃恢复通过；SDK 审批真实冒烟通过；T4–T6 真实验收通过；M1 最小可观测已实现；M2 记忆 19/19 通过；下一步补齐 Scholar/摘要验收，再做全局大盘与 Scholar 深度。

## 11. 在哪里看

| 想看什么 | 去哪里 |
|---|---|
| 项目定位、启动、配置、限制 | `README.md` |
| 当前阶段与验收状态 | `CURRENT_PHASE.md` |
| 后续方向、可观测计划、全局大盘设计 | `docs/roadmap.md` |
| v8 架构决策（Session/三层记忆） | `docs/decisions/0006-session-memory.md` |
| SDK 执行与审批决策 | `docs/decisions/0007-agent-sdk-approvals.md` |
| M0 验收矩阵（T1–T6） | `docs/acceptance/m0-real-cli.md` |
| M1 可观测验收 | `docs/acceptance/m1-observability.md` |
| M2 记忆案例集 | `docs/evaluation/memory-benchmark.md` |
| 真实 SDK 验收步骤 | `docs/acceptance/phase4-sessions.md` |
| 演示截图 | `docs/assets/overview-*.png` |
| 实际界面 | 启动后访问 <http://127.0.0.1:8000>；页面包括 `/:role`、`/:role/:sessionId`、`/memory`、`/workspaces` |

启动方式：双击仓库根目录 `start.bat`，或：

```powershell
cd D:\vibe\Iris
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```
