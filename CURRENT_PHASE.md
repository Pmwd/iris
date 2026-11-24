# Iris 当前阶段

> 阶段：Phase 4 收尾 — Session + Memory 2.0 + 双角色 + Claude Agent SDK 审批 + 工作区运行面板 + 系统大盘
> 状态：后端与前端实现完成；70 个后端测试通过；前端构建通过；M0 T1–T9 全部通过；M1 可观测、M2 记忆 19/19、M3 系统大盘、Memory 2.0（自动候选/收件箱/混合检索/近似合并/过期确认）已实现；Scholar 本地 prompt-first，M4 14 题盲评完成（Scholar 12 / Coding 2，未进入编排）；已知边界：CLI 会自动放行部分安全只读命令，不弹 Iris 审批
> 更新时间：2026-11-24
> 依据：`docs/decisions/0006-session-memory.md`、`docs/decisions/0007-agent-sdk-approvals.md`、`docs/decisions/0010-memory-2.md`、`docs/acceptance/memory-2.0.md`

## 1. 阶段目标

重新审视 note 形式的记忆后，将 Iris 从 `Project → Task → Run → Note` 改造成：

- **两个角色**：Coding、Scholar。
- **Session 聊天模型**：每个角色下可多开会话；每轮用户消息触发一次 Turn。
- **三层记忆**：
  1. L1 原始记忆：所有消息、工具调用、执行结果完整保存。
  2. L2 摘要记忆：会话结束或达到阈值自动生成滚动摘要。
  3. L3 长期事实：从多次会话摘要提取候选，用户审核后才注入。
- **执行层**：默认 Claude Agent SDK；需要授权的工具调用逐条审批（允许一次 / 总是允许 / 拒绝）。CLI 自动放行的安全只读命令不经过审批。
- **前端**：参考 Codex / Gemini 的三栏骨架——角色/会话侧栏、聊天主区、记忆侧栏。

## 2. 已实现

### 后端

- Schema **v10**：v7 的 `sessions`、`turns`、`messages`、`turn_events`、`session_summaries`、`facts`、`fact_extractions`、`facts_fts`，v8 新增 `turn_approvals`、`permission_rules`，v9 新增 `metric_rollups`，v10 为事实增加来源/标签/有效期/指纹/`search_text`，并重建预分词 FTS；旧表只读保留，**不迁移**。
- **执行层**：`SdkTurnRunner` 使用 `ClaudeSDKClient` + `can_use_tool`；`cli_path` 指向原生 `claude.exe`；`setting_sources=["user"]` 保留 CC Switch/DeepSeek；`CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` 关闭自动 project memory；首次新 session、后续 resume。
- **审批桥接**：`ApprovalManager` 将 `can_use_tool` 挂起，等待 HTTP 决策；支持允许一次/总是允许/拒绝、超时、取消；事件写入 `turn_events`，记录写入 `turn_approvals`。
- **进程树清理**：每 Turn 附加 Windows Job Object；取消时先调度 async 取消（状态记为 `canceled`），再关闭 Job 并 `taskkill /T /F`，工具子进程不会残留；后端被强杀时 `KILL_ON_JOB_CLOSE` 兜底。
- **审批规则**：会话级规则，PowerShell 命令前缀、Write/Edit 文件路径、其他精确输入；写入 `permission_rules`；“总是允许”后自动放行。
- **CLI 回退**：`IRIS_EXECUTION_BACKEND=cli` 保留旧 one-shot `build_command` + fake CLI 测试路径。
- **工作区运行面板**：`WorkspaceProcessManager` 在工作区目录启动长驻命令，线程读取输出（内存保留 2000 行并追加 `data/workspace_processes/<id>.log`），支持状态、PID、退出码、停止进程树；删除工作区/关闭 Iris 时清理；进程记录仅内存保存。
- **M2 记忆基准**：19/19 通过——摘要保留（A1–A4）、事实提取（B1–B4）、跨 Session 召回/隔离（C1–C5）、冲突/过期（D1–D3）、预算/手动（E1–E2）、manifest 透明（F1）。过程中修复自动 project memory 泄漏与提取 existing_facts 跨工作区目标错误；结果见 `docs/evaluation/memory-benchmark.md`。
- **M1 最小可观测**：`MetricsService` + `/api/metrics/overview|health|errors`；Turn/成本/工具/记忆/错误/存储聚合，支持 role/project/range 过滤；只返回计数、时长、成本、状态与错误类型，不含消息/事实/工具内容。
- **Scholar prompt-first**：强化 `roles.py` 的学术分析方法（问题框定、KNOWN/INFERRED/HYPOTHESIS/UNKNOWN、反例/替代解释、置信度、无来源不编造）；默认关闭 WebSearch/WebFetch（`IRIS_SCHOLAR_WEB=0`），`research` 档位走本地阅读 + 结构化分析；设置 `IRIS_SCHOLAR_WEB=1` 才启用网页工具。
- **M4 Scholar 盲评扩容**：14 个问题、每题 Scholar 本地 prompt vs Coding 只读 baseline；结构化匿名 A/B 盲评（两位主评审交换顺序，4 个分歧题加第三位 tie-break）。Scholar 盲评胜 12/14、Coding 胜 2/14（Q11 跨领域争议、Q14 长期规划）；calibration +0.64、counterargument +0.55，correctness -0.06；14 题合计成本 +5.5%、耗时 +10.5%（原 8 题为 +19.7%/+31.3%，批次波动大）。结论：增量成立但集中在认知结构，暂不投入研究编排。详见 `docs/evaluation/scholar-incremental.md`。
- **M3 系统大盘**：schema v9 `metric_rollups`（小时/天桶 + dimensions JSON）；`/api/metrics/timeseries`；`RollupWorker` 启动时 + 每 5 分钟刷新（查询时也会补算）；`/api/dashboard/overview` 组合健康、KPI、告警、最近错误；前端 `/dashboard` 支持 24h/7d/30d、角色/工作区过滤、Turn 柱图、成本线图、数据表、记忆/工具/存储/成本 Top；告警仅页面内展示。
- **原始记忆**：`messages` + `turn_events` + 每 Turn 完整 JSONL（SDK 消息 JSONL / CLI stream-json）。
- **增量流式**：SDK `include_partial_messages=True`，`text_delta` 聚合成 `assistant.delta`（约 60 字/0.1 秒）写入事件流，经 SSE 推送；最终 `assistant.text` 覆盖草稿。
- **并发不变量**：同一 Session 一个活动 Turn；同一工作区一个活动 Coding Turn（DB 部分唯一索引）。
- **MemoryManager**：单 worker 摘要队列；阈值 8 Turn / 24000 字符；结束 final 摘要；compact 后清空 CLI session；final 摘要成功后自动抽取候选（`trigger=session_end`，每会话最多 5 个，绝不自动接受；可关闭）。
- **Memory 2.0 捕获**：会话结束自动候选；聊天消息“记住”直接创建 quick_capture 事实；近似重复/冲突检测（标题相似度 + token Jaccard）进入收件箱；支持合并/取代/都保留。
- **Memory 2.0 检索**：预分词 `search_text`（英文词 + 中文 bigram + 别名/标签）+ FTS/词法合并；FTS 位置、覆盖、近期确认、使用次数、confidence、pin 排序；最多 6 条、阈值 0.55、无关 abstain；过期事实不注入。
- **Memory 2.0 透明**：manifest 记录入选/排除、score/score_parts、来源会话；右侧显示可能相关/本次注入/排除原因；事实支持 `valid_until`、`last_confirmed_at`、反向 supersede 与 merged_into。
- **事实管线**：手动/自动提取、严格 JSON 校验、来源会话校验、标签/别名、指纹与近似关系；候选只有被接受后才进入上下文。
- **API**：`/api/workspaces`、`/api/sessions`、`/api/turns`、`/api/approvals`、`/api/facts`、`/api/fact-extractions`、`/api/workspaces/{id}/processes`、`/api/processes/{id}`、`/api/metrics/overview|health|errors|timeseries`、`/api/dashboard/overview`；健康检查与维护保留。
- 启动时把活动 Turn 标为 `interrupted`，运行中的摘要/提取标为失败，pending 审批标为过期。

### 前端

- 新 `AppShell`：深色角色/会话侧栏 + 聊天主区 + 可折叠记忆侧栏。
- `SessionPage`：消息气泡、Markdown、工具调用卡片、审批卡片、SSE 流式活动（增量文本 + 工具事件）、停止、结束、压缩、继续、标题编辑。
- `ApprovalCard`：显示工具、命令/文件、风险提示；允许一次 / 总是允许 / 拒绝；决策后显示已允许/已拒绝/已过期。
- SDK 模式下执行档位不再要求工作区 PowerShell 白名单。
- `MemoryPage`：搜索、收件箱计数、候选/已接受/已拒绝/已归档；近似重复/冲突 banner 与合并/取代/都保留；来源会话链接、标签、有效期确认；接受、编辑、置顶、归档、恢复；提取面板。
- `RelatedMemories`：输入时防抖查询“可能相关”；`RememberDialog`：消息旁“记住”并预填来源；`MemoryPanel` 显示本次注入/排除原因、分数与收件箱入口。
- `WorkspacesPage` / `WorkspaceDetailPage`：工作区库、brief、PowerShell 白名单（CLI 回退用）、安全提示、备份入口。
- `WorkspaceRunner`：运行面板——命令/预设、启动、进程列表（状态/PID/退出码）、实时日志轮询（跟随最新）、停止；归档工作区不能启动。
- 删除旧 Task/Project/RunPanel/Mentor/Scholar 前端页面与组件。

### 测试与工具

- **70 个后端测试通过**：会话/Turn、多轮 resume、并发锁、取消、启动校正、原始日志、摘要、compact、事实提取/审核/注入、别名、schema v10 迁移与旧 FTS 重建、备份与安全；审批桥接、运行面板、进程树清理、M1/rollups/dashboard；新增 Memory 2.0：中文/混合 FTS、阈值/abstain、过期排除、聊天记住、标签、收件箱、近似重复/冲突、合并/取代、来源、自动候选，以及 16 条确定性质量集。
- **真实 SDK 冒烟**：本机 CLI 2.1.221 + CC Switch/DeepSeek，`can_use_tool` 触发 PowerShell 审批；允许后文件真实生成；同会话 resume 成功；成本/usage 返回。
- 前端 `npm run build` 通过；T7 用无头 Edge + CDP 在真实页面完成允许/拒绝/总是允许/超时与规则复用，T8/T9 用同一方式验证运行面板与 compact 恢复。
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

- [x] Schema v9 创建与旧库非破坏迁移。
- [x] Coding 无工作区被拒绝；Scholar 无工作区可运行。
- [x] 发消息产生 user message、Turn、assistant result、工具事件与原始日志。
- [x] 多轮续聊复用同一 CLI session；resume 失败不自动重试。
- [x] 同 Session / 同工作区并发锁与取消释放。
- [x] 摘要阈值、结束 final 摘要、失败不阻塞、compact 新 CLI 会话 + 摘要注入。
- [x] 事实提取只产候选；接受后才注入；update 归档旧事实；角色/作用域/预算/别名。
- [x] 审批桥接允许/拒绝/always/超时/取消；规则匹配。
- [x] 运行面板启停、日志增量、PID/退出码、归档拒绝启动、删除工作区时停止进程。
- [x] M1 指标：空库不崩溃、Turn/成本/工具/记忆聚合、role/project/range 过滤、错误不含正文。
- [x] M2 全量：A1–A4/B1–B4/C1–C5/D1–D3/E1–E2/F1 真实 SDK 通过；supersede、预算、隔离、冲突暴露与 manifest 透明均验证；D1 修复跨工作区 update 目标。
- [x] M3 大盘：schema v9 `metric_rollups`、小时/天桶、role/project 过滤、`/dashboard` 与数据表；真实数据截图验证。
- [x] 前端 `npm run build` 通过。

### 4.2 真实 CLI / SDK 验收

- [x] T1–T3：真实问答/流式、Read 工具、Write+PowerShell 审批与文件/命令闭环。
- [x] SDK 在 Windows + 本机 `claude.exe` + CC Switch/DeepSeek 下触发 `can_use_tool`。
- [x] 允许 PowerShell 后真实执行并生成文件；成本/usage 返回。
- [x] 同一 Session 通过 SDK resume 续聊。
- [x] pending 审批卡片在网页中可见并可决策。
- [x] 记忆召回：新 Session 的 manifest 注入 accepted 事实（reason=matched），`use_count` +1，回答使用该事实。
- [x] 取消：允许长驻 `python` 命令后取消，状态 `canceled`，工具子进程被终止，同一 Session 可继续。
- [x] 异常退出：强杀后端后 CLI 与其工具进程被清理；重启 `reconciled_turns=1`，Turn=`interrupted`，pending 审批=`expired`，锁释放，后续 Turn 成功。
- [x] Scholar prompt-first：本地材料/模型知识 + 结构化分析；默认不联网；Web 模式（`IRIS_SCHOLAR_WEB=1`）历史验收通过并保留来源。
- [x] 真实摘要质量与成本观察（A1–A4、T2/T3/Scholar）；记录英文摘要与环境噪声问题。
- [x] 真实事实提取的信噪比、去重、冲突与过期（M2 19/19）。
- [x] compact 在真实 resume 失败场景下的恢复（T9）。
- [x] 真实 UI 中的“允许一次/总是允许/拒绝/超时”完整手工流程（T7）。
- [x] 运行面板：真实 dev server 启动、日志刷新、停止与删除工作区后的进程清理（T8）。
- [ ] 所有 PowerShell 调用强制审批（CLI 自动放行安全只读命令，见 `docs/acceptance/m0-real-cli.md` T7 边界）。
- [ ] POSIX 进程树清理（当前 Job Object 为 Windows 方案）。

## 5. 下一步

后续方向、可观测计划与全局系统大盘见 `docs/roadmap.md`（M0 真实验收 → M1 最小可观测 → M2 记忆质量 → M3 大盘 → M4 Scholar → M5 体验）。

1. 当前阶段收尾：Memory 2.0 已实现并完成 R1–R6 真实验收；下一步进入 M5 体验打磨与真实使用观察。
2. M4：已扩展为 14 题盲评；下一步优先做固定子集的人类 1–5 盲评，再决定是否做最小多轮研究原型。
3. 评估是否需要强制所有 shell 调用审批（PreToolUse 强制询问或自管 shell 工具）。
4. 视 `scripts/memory_eval.py` 与真实使用结果决定是否引入本地 embedding；当前保持预分词 FTS + 关键词/别名/标签。
