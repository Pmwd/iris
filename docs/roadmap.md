# Iris 阶段路线图

> 状态：Phase 3C Mentor v0 已实现，等待真实 CLI 验收；Testing 角色暂时搁置  
> 更新时间：2026-10-25  
> 说明：本文件保存长期阶段规划和设计审视；`CURRENT_PHASE.md` 只记录当前阶段。

## 1. 结论摘要

- 项目处于 pre-implementation 阶段：只有项目总纲，没有已有代码或工程基线。
- 产品方向是清晰的，但最大风险是**广度先于深度**：同时建设角色、记忆和应用，容易得到多个演示，却没有一个真正可用的工作流。
- 第一阶段应先证明一条闭环：**任务 → CLI 执行 → 中断识别/恢复 → 结果审查 → 沉淀为上下文 → 后续任务复用**。
- 推荐的验收场景是一个独立的小型代码仓库，而不是 Iris 自身；这样可以稳定验证“第二个任务是否真的更容易”。
- 动工前需要先解决：Python 3.9 EOL、Windows 下 CLI 的非交互权限行为、进程树取消、强杀后的会话恢复、本地 Web API 安全。
- 不建议一开始实现角色、自动记忆、向量检索、应用平台或多 Agent。

## 2. 产品理解

Iris 的差异化不在于“可以调用 Claude Code CLI”，也不在于“有多个角色头像”。它应解决的是：

- 任务可以被持续推进，而不是每次从零开始；
- 有价值的结果能被审查、沉淀，并在后续任务中真正复用；
- 不同 Session、角色和应用之间可以共享经过确认的上下文，而不必共享全部对话；
- 个人知识、工作任务和长期目标逐步形成一个可控的本地系统。

因此，第一阶段的产品判断标准是：

> 用户完成第二个相关任务时，是否需要更少的重复解释，并得到更连贯的结果？

如果答案是否定的，那么即使实现了角色和应用，也没有验证 Iris 的核心价值。

## 3. 已确认、推断与待验证

### 3.1 已确认的要求

来自项目总纲和用户明确要求：

- 产品方向以个人上下文为核心；Task、Session、Context、Backend、App 等概念保持区分。
- 技术基线：Python + FastAPI、React + TypeScript + Vite、SQLite WAL、本地 Claude Code CLI、本地优先。
- 当前优先级是任务闭环、执行、结果保存、恢复、沉淀和复用；角色和应用后置。
- 上下文按需加载；区分原始对话、临时上下文、长期记忆和已验证知识。
- 模型推测不能自动成为用户事实。
- 高风险操作需要最小权限和明确授权。
- 涉及 CLI 的行为必须先验证，不能只依据文档或假设。
- 当前阶段先理解与规划，不立即大规模编码；不覆盖已有成果。
- 长期阶段规划与项目总纲分离。

### 3.2 我的推断

在没有更多信息时，以下是为降低风险而采用的合理推断，尚未成为硬性要求：

- 第一阶段是单用户、本地运行的 Web 工作台，不做登录、远程访问和云同步。
- 第一阶段采用任务中心界面，而不是角色中心或聊天中心。
- 一个 Task 对应一个当前 CLI session；后续任务新建 session，通过显式上下文包复用成果。
- 同一项目同一时间只允许一个会修改工作区的 run。
- 单进程 FastAPI + asyncio 子进程管理足以支撑 MVP。
- SQLite + REST + SSE 足以支撑单用户的任务状态和事件流。

### 3.3 仍需验证的假设

Phase 0 已验证的 CLI 技术事实和证据见 `docs/spikes/cli-integration.md`。仍需验证：

- 用户接受/编辑的 note 是否足以产生可感知的上下文复用价值，而不需要更复杂的检索。
- 本地浏览器工作台是否足以验证价值，还是必须尽早桌面化。
- 认证失败路径、用户级 hooks/MCP/skills、`--add-dir`、超长或特殊字符 prompt 的实际行为。
- 服务异常退出时的孤儿进程清理；Job Object 是否必要。
- 本地 API 的 loopback、Origin/Host 和写操作保护在真实实现中是否足够。
- CLI 报告的 cost/usage 在第三方兼容端点上是否足够准确。
- 当前第三方兼容端点的工具调用行为是否与官方 Claude 一致，以及 CLI 升级后的兼容性。

### 3.4 2026-10-23 已确认的方向决策

- Python 运行时：安装 Python 3.12，使用项目本地 `.venv`。
- 执行权限：受信任工作区 + 分档权限（只读 / 可编辑 / 可执行），默认不使用 bypass。
- 首个验收场景：独立小型代码仓库，不使用 Iris 自身。
- 上下文写入：只有用户接受或编辑后的 outcome 才进入可复用上下文；模型摘要只作为草稿。

## 4. 设计审视

### 4.1 产品与范围

**风险：把“平台能力”当成核心价值。**

五个角色、应用扩展和长期记忆组合起来更像一个个人 AI 操作系统。这个愿景可以保留，但第一个可用版本不能同时验证三个方向。建议以 Coding 任务作为切口，因为 CLI 执行最容易验证，结果也最容易审查。

**风险：做成 CLI 包装器。**

如果 Iris 只是启动 CLI、显示输出，那么用户直接使用 Claude Code 更简单。MVP 必须把“跨任务积累与复用”做成可见、可操作的能力，例如上下文预览、来源追溯和后续任务减少重复解释。

**设计冲突：个人上下文是基础，但 MVP 先做项目上下文。**

这是一个有意的收窄。Phase 1 只验证项目级复用；Phase 2 必须加入最小化的全局/个人上下文，否则可能只验证了一个项目管理工具，而不是 Iris 的长期方向。建议在 Phase 2 中用用户手写的全局 brief 做低成本验证，再考虑自动提取。

**设计冲突：角色是核心概念，但第一阶段不做角色系统。**

MVP 使用一个隐式的 Coding 执行配置。Phase 3 再把角色实现为“行为、工具、上下文策略”的组合，而不是每个角色一个 Agent 实例。不要在没有真实差异需求前引入角色数据库或独立记忆库。

### 4.2 可能遗漏的关键需求

1. **执行权限与审批模型**：总纲提到最小权限，但没有定义具体档位、工作区信任和命令授权。
2. **本地 Web API 安全**：一个能读写文件和启动进程的 localhost 服务，需要防 CSRF、DNS rebinding 和跨站请求。
3. **数据出境说明**：本地存储不等于数据不出本机；任务内容会发送给配置的模型后端。
4. **结果审查与接受流程**：谁判断任务完成、如何接受结果、如何保留来源。
5. **崩溃恢复与取消**：任务状态不能只靠内存；需要启动时校正、超时和进程树管理。
6. **CLI 健康检查与错误分类**：CLI 缺失、未认证、版本不兼容、输出异常都要有可操作提示。
7. **工作区信任与不可信内容**：仓库文件、`.claude` 配置、hooks 和提示注入都可能影响执行。
8. **成本语义**：不同后端的计费字段不可直接比较，应标注为报告值。
9. **备份、导出、删除和保留策略**：本地数据同样需要可迁移、可删除。
10. **上下文溯源**：必须能回答某次运行注入了哪些 note、哪个版本、多少字符。
11. **日志与可观测性**：需要结构化日志，但不能记录凭据和敏感内容。
12. **并发与工作区锁**：多个 Agent 同时修改同一目录会造成冲突。
13. **首次使用引导**：检查 CLI 安装、认证、版本和数据目录。
14. **长任务体验**：切换页面、关闭浏览器、通知和状态恢复。
15. **后端抽象边界**：CLI 专属参数不能散落在业务层；但也不要在只有一个后端时过度抽象。

### 4.3 技术风险

- Python 3.9 已 EOL；当前 pip 来自无关环境，直接使用会污染或依赖错误版本。
- Windows 下 npm CLI 是 `.cmd` 包装，Python 的 `subprocess` 不能想当然地直接执行。
- print 模式可能无法回答交互式权限提示；工具调用可能被自动拒绝。
- `stream-json` 的字段和事件顺序可能随 CLI 版本变化，需要容错解析。
- 强杀后的会话恢复不一定成功；需要降级路径。
- 取消父进程不等于清理子进程；可能导致孤儿进程继续修改文件。
- SQLite 在事件高频写入和 SSE 读取同时发生时可能锁竞争，需要短事务、WAL 和 busy timeout。
- 长 transcript 会造成数据库膨胀和 UI 卡顿，需要截断、分页和原始日志分离。
- 目标仓库可能包含 hooks 或提示注入内容，Agent 可能执行非预期操作。
- localhost 服务被恶意网页调用是现实风险，不能只靠“没有登录”来保护。
- 成本字段在代理/第三方端点下可能不准确。
- CLI 自动更新或用户全局配置变化会改变行为；需要版本检查和行为隔离。

### 4.4 值得考虑的替代方案

| 决策 | 当前建议 | 替代方案 | 结论 |
|---|---|---|---|
| 执行层 | 本地 Claude Code CLI | Claude Agent SDK / 直接 API | 先用 CLI，复用成熟能力；如果权限桥接不足，再考虑 SDK |
| 全栈语言 | Python + React | Node/TypeScript 全栈 | Node 环境已就绪，但改变总纲基线收益不大；保留 Python，升级运行时 |
| 客户端 | 本地 Web 工作台 | Tauri/Electron 桌面应用 | 先验证价值，再桌面化；桌面化不是第一优先级 |
| 上下文 | 显式 note + 预览 | Embedding / RAG | 先验证人工接受的内容是否足够；检索质量不足再引入 |
| 应用扩展 | 第一方窄接口应用 | 完整插件平台 | 先做 Obsidian 等第一方能力；不在没有需求时建插件沙箱 |
| 运行器 | 单进程 + asyncio | 独立 worker/队列 | 单用户 MVP 足够；可靠性和并发需求出现后再拆分 |
| 任务/会话 | 一个 Task 一个当前 session | 一个 Run 一个 session | Task 级 session 更符合连续工作；恢复和复用更清晰 |
| 记忆写入 | 用户接受后写入 | 自动摘要写入 | 自动写入有污染风险；先人工接受，模型摘要只做草稿 |

## 5. 阶段总览

Phase 0 和 Phase 1 核心切片已完成。以下时间为粗略估计，Phase 1.5 启动前再校准。

| 阶段 | 目标 | 预计时间 | 关键交付 |
|---|---|---|---|
| Phase 0 | 验证可行性和安全边界，锁定 Phase 1 | 已完成 | 环境基线、CLI spike、权限模型、数据/接口草案 |
| Phase 1 | 任务闭环 MVP（核心完成） | 已完成核心切片 | 项目/任务/运行、SSE、取消/恢复、note、上下文复用 |
| Phase 1.5 | 可靠性与安全加固（核心完成） | 已完成核心加固 | 崩溃恢复、超时、错误分类、备份、审计、安全检查 |
| Phase 2 | 项目上下文与记忆 v1（核心完成） | 已完成核心能力 | note 生命周期、FTS、上下文预算、溯源、最小全局上下文 |
| Phase 3 | 角色与多项目工作空间（3A 核心完成） | 已完成 Testing 切片 | 角色策略、跨角色上下文、项目 dashboard |
| Phase 4 | 应用扩展 v1 | 1–2 周 | 窄接口应用、Obsidian、运行/成本监控 |
| Phase 5 | 多后端与更高层协作 | 探索性 | Backend 适配器、第二后端、可选任务拆解 |

## 6. 各阶段详情

### Phase 0 — 方向确认与技术可行性

**目标**

用最小成本验证最危险的未知，避免在错误的技术或产品假设上构建 UI。

**解决的问题**

- Python 运行时是否可用、是否有 EOL 风险。
- CLI 在非交互模式下能否完成真实工作。
- 取消、恢复和进程管理是否可靠。
- 权限、工作区信任和本地 API 安全边界是否明确。
- 首个 MVP 场景能否证明上下文复用。

**主要交付物**

- Python 3.12 本地环境、git 初始化、`.gitignore`。
- `docs/spikes/cli-integration.md`：实际命令、事件样例、失败行为、结论。
- 权限模型决策记录。
- Phase 1 数据模型、状态机、API 和验收场景草案。
- 一份简短的“进入 Phase 1”决策记录。

**执行结果（2026-10-23）**

- 已完成：Python 3.12.10 + `.venv`、git 初始化、`.gitignore`。
- 已完成：Windows 下 Python 直接调用 `claude.CMD`；`stream-json`、编辑、PowerShell 权限、工作区隔离、取消进程树、强杀后恢复、错误行为和成本字段均已验证。
- 已确认风险：项目 hooks 默认执行；`--safe-mode` 可阻止 hooks，但 CLAUDE.md 仍会加载。
- 未完成/转入 Phase 1：认证失败路径、本地 API 安全检查、Job Object、并发和 SSE 重连。
- 详细证据见 `docs/spikes/cli-integration.md`。
- 结论：技术可行性验证完成，无阻塞 Phase 1 的未知项；等待用户确认进入 Phase 1。

**验收标准**

- 能从 Python 在 Windows 上正确调用 CLI。
- `stream-json` 可解析，关键事件和最终结果可取。
- 能在选定权限档位下完成文件编辑和测试命令，或明确确认必须降级为只读/其他方案。
- 取消能清理进程树；超时和服务退出有明确行为。
- 已记录强杀后恢复的成功/失败情况，并定义降级方案。
- CLI 缺失、认证失败、非零退出、输出异常和超时都有错误分类。
- 权限、工作区信任、本地 API 安全和数据出境说明已确认。
- 用户确认首个场景、Python 方案和上下文写入规则。

**风险**

- CLI 的 print 模式权限行为可能与交互模式不同。
- 第三方兼容端点的工具行为可能不同。
- 进程树清理和会话恢复在 Windows 上可能比预期复杂。
- 容易在 Phase 0 就滑入功能开发。

**前置依赖**

- 用户确认进入 Phase 0，并允许安装 Python 3.12、初始化 git。

### Phase 1 — 任务闭环 MVP

**目标**

实现一个可真实使用的单用户垂直切片：创建任务、执行、观察、取消、恢复、保存结果、接受上下文、在后续任务中复用。

**解决的问题**

- 任务状态只存在对话里，无法持续推进。
- 执行过程不可见、不可恢复、结果不可追溯。
- 有价值的结果无法沉淀，下一次又要重复解释。

**主要交付物**

- 后端：
  - Project / Task / Run / RunEvent / Note 数据模型和迁移。
  - REST API + SSE 事件流。
  - Claude Code CLI 适配器（命令构建、JSONL 解析、错误映射）。
  - 运行管理器：启动、取消、超时、启动时状态校正。
  - 上下文构建器和注入快照。
  - CLI 健康检查和数据目录配置。
- 前端：
  - 项目创建/选择和工作区路径配置。
  - 任务创建、状态展示和运行历史。
  - 运行、取消、恢复按钮。
  - 实时事件流（可折叠工具事件）。
  - 结果展示和“接受为项目 note”。
  - 运行前的上下文预览和开关。
- 测试：
  - 可注入的假 CLI，用于确定性测试。
  - 状态机、事件解析、上下文构建、取消/恢复测试。
  - 真实 CLI 的 opt-in smoke test。
- 示例仓库和端到端验收脚本/文档。

**执行结果（2026-10-23）**

- 已实现项目/任务/运行/事件/note、REST + SSE、CLI 适配器、运行管理器、上下文快照、健康检查和本地 Web 工作台。
- 真实 CLI 验收：任务 A 修改示例 expense CLI，5 个测试通过；接受 outcome note；任务 B 的运行快照注入该 note，复用现有导出实现，8 个测试通过。
- 取消/恢复、启动校正、本地 API 头和 Host 保护由 fake CLI 测试覆盖；SSE 重放和 `done` 已验证。
- Phase 1 实现偏离：使用 stdlib `sqlite3` + `schema.sql`，未引入 SQLAlchemy/Alembic；前端使用 React Router + 原生 fetch，未引入 TanStack Query。
- 尚未完成：真实服务重启/Job Object、备份恢复、浏览器 E2E、认证失败和用户级扩展测试；这些进入 Phase 1.5。
- 详细验收见 `docs/acceptance/phase1.md`。

**验收标准**

1. 创建项目并指向目标工作区；创建带目标的任务。
2. 启动运行后，CLI 在正确工作区执行，事件在可接受延迟内出现在 UI。
3. 完成运行后，结果、usage、cost、状态和事件被持久化。
4. 取消运行后，进程树被清理，状态正确，日志仍可查看。
5. 服务重启后，进行中的 run 被标记为 interrupted，不自动重跑。
6. 用户可尝试恢复；恢复失败时走新 session + handoff，并清楚展示。
7. 用户可审查结果并接受一条带来源的 outcome note。
8. 新任务启动时，上下文预览包含该 note；运行记录保存注入快照。
9. 后续任务明显复用前一任务的成果，减少重复解释。
10. 同一项目不能同时执行两个会修改工作区的 run。
11. CLI 缺失、认证失败、超时和输出异常不会导致服务崩溃。
12. 自动化测试覆盖关键状态转换；真实 CLI 测试可显式开启。

**风险**

- 权限模型无法在 print 模式下满足真实编码任务。
- 真实 CLI 输出非确定，验收需要检查可观察结果而非固定文本。
- 取消/恢复和 SQLite 事件写入的竞态。
- 范围膨胀到记忆、角色或聊天 UI。
- 示例仓库过于理想化，不能代表真实项目。

**前置依赖**

- Phase 0 通过。
- 用户确认 MVP 场景、权限模型和上下文写入规则。

**明确暂缓**

- 角色、自动记忆、应用扩展、多 Agent、多用户、桌面端、自由聊天。

### Phase 1.5 — 可靠性与安全加固

**目标**

让已实现的闭环从“已验收”变成“敢日常使用”。Phase 1 已有超时、启动校正、基础错误分类和本地 API 保护；Phase 1.5 重点是把它们放回真实故障场景中验证并补强。

**解决的问题**

- 服务崩溃、CLI 强杀、孤儿进程和重复运行。
- 错误不可诊断，日志可能泄露敏感信息。
- 数据没有完整备份、导出和恢复路径。
- localhost API 和不可信工作区的安全边界仍需更完整的检查。
- 浏览器端真实交互尚未经过自动化或手工端到端验收。

**主要交付物**

- 进程监管强化（Windows Job Object 或等价机制）。
- 超时、最大运行时长、取消宽限期的真实场景验证。
- 服务重启、数据库异常和异常退出的故障注入。
- 结构化错误分类、日志轮转和审计事件。
- SQLite 备份/恢复、导出、项目/任务删除的完整流程。
- 敏感文件提示（如 `.env`），不记录凭据。
- 本地 API 的 Origin/Host、写操作保护和回环绑定检查补强。
- 权限档位和工具审计的可视化。
- 浏览器端 E2E 或明确的手工验收清单。

**执行结果（2026-10-23）**

- 已实现 Windows Job Object（`pywin32`）和 `taskkill /T /F` 双重清理。
- `scripts/crash_test.py` 真实强杀后端：子进程消失，重启后 run 收敛为 interrupted。
- 超时、CLI 缺失、坏 JSON、备份/恢复、敏感文件、安全头和 Content-Type 均有测试。
- 15 个后端测试通过；前端 TypeScript + Vite 构建通过。
- 日志轮转和 `permission.denied` 审计事件已实现。
- 浏览器手工流程完成：Edge/Playwright 驱动真实 UI，覆盖项目/任务/上下文警告/真实运行/note/备份/取消/删除；控制台无错误。
- 修复两个 UI 问题：首页加载状态误显示 0 个项目；运行事件滚动遮挡标题。
- 真实数据备份/恢复演练完成：标记项目/note 在恢复后消失，原项目和 note 完好。
- 尚未完成：认证失败/用户级扩展/极长 prompt、成本上限和高并发压力；浏览器驱动尚未固化为项目技能。
- 详细记录见 `docs/acceptance/phase1.5.md`。

**验收标准**

- 注入进程崩溃、数据库异常、CLI 超时、取消和服务重启，状态都能正确收敛。
- 启动后没有明显孤儿进程继续修改工作区。
- 备份可恢复；删除会清理关联数据并有确认。
- 日志中不出现密钥；错误信息可操作。
- 跨站请求和非法 Host 被拒绝。
- 权限档位变化有审计记录。
- 浏览器端能完成项目 → 任务 → 运行 → note → 上下文复用的完整流程。

**风险**

- 过早建设复杂的进程监管或安全机制。
- 兼容性测试只覆盖理想路径。
- 备份和删除规则设计不当造成数据丢失。

**前置依赖**

- Phase 1 核心切片已完成。
- 用户确认继续进入可靠性加固，而不是直接扩展角色/记忆/应用。

### Phase 2 — 项目上下文与记忆 v1

**目标**

让沉淀的成果真正可检索、可选择、可复用，并加入最小化的全局/个人上下文验证。

**解决的问题**

- note 多了以后，人工选择不可扩展。
- 后续任务不知道该带哪些上下文。
- 需要回答“为什么这次注入了这些内容”。

**主要交付物**

- note 生命周期：草稿、接受、归档、编辑、删除。
- 项目内全文检索（优先 SQLite FTS5，不先引入向量库）。
- 上下文构建器：相关性、置顶、最近使用、token/字符预算。
- 上下文预览、手动开关和排除原因。
- 每次运行的上下文快照和来源链接。
- 最小全局上下文：用户手写的个人/工作偏好，可跨项目复用。
- 数据导出和保留策略的进一步实现。

**执行结果（2026-10-23）**

- 已实现 SQLite FTS5 + LIKE 回退，项目/全局 note 检索。
- `notes` 增加 `pinned` / `use_count` / `last_used_at`；新增 `global_notes`。
- 上下文推荐：置顶、相关度、最近、使用次数；预算和推荐理由进入 manifest。
- 前端全局上下文面板、项目 note 置顶、任务页推荐/预算展示。
- 真实 `data/iris.db` 从 schema v1 迁移到 v2，原有项目/任务/运行/note 数量保持；现有 note 在任务 B 预览中被正确推荐（reason=matched）。
- 26 个后端测试通过；前端构建通过；浏览器验证全局上下文与推荐展示，测试数据已清理。
- 生活场景暴露 pinned 全局 note 无条件注入和中文通用词误匹配；已修复为“pinned 只加权、自动注入要求本地关键词/bigram 命中”，并完成三任务回归（注入从 4/4/4 降为 1/1/3）。
- 语义改写实验：无 aliases 时 paraphrase 0/5；加 aliases 后 5/5，control 保持 5/5；schema v3 真实数据迁移完成。
- 高价值别名维护试点：只给水果偏好、两人份清单、健身偏好加别名；API 写入 0.179s，人工约 2–3 分钟。真实检查发现未知改写仍漏（少花钱/采买）、阅读纯改写漏、recent 回退误带水果清单、通用词“适合”误匹配。决定：继续小范围别名，不做全面重构/embedding，先处理 recent 回退和停用词。
- 迁移前备份：`data/backups/iris-20261023-043738-941501.db`。
- 数据导出/保留策略未扩展；中文短词依赖 LIKE；推荐权重需要真实使用校准。
- 详细记录见 `docs/acceptance/phase2.md`。

**验收标准**

- 后续任务能自动选出相关已接受 note，用户可查看并移除。
- 注入内容受预算限制，不把全部历史塞入请求。
- 原始 transcript 不会被当作长期记忆自动注入。
- 模型摘要只能生成草稿，不能自动成为事实。
- 全局 note 可跨项目复用，并受权限/可见性控制。
- 删除 note 后，后续运行不再注入它。

**风险**

- 检索相关性不足或过度注入。
- 用户不接受自动选择，仍要逐条配置。
- 隐私边界、敏感信息和个人上下文被过度收集。
- 过早引入 embedding/RAG，增加成本和复杂度。

**前置依赖**

- Phase 1.5 完成。

### Phase 3 — 角色与多项目工作空间

**目标**

把角色实现为行为、工具和上下文策略的组合，支持多项目工作和跨角色交接。

**解决的问题**

- 单一 Coding 配置无法表达研究、测试、个人事务等不同工作方式。
- 不同角色之间需要共享成果，但不应共享全部 Session。

**主要交付物**

- Role 配置：说明、系统指令、默认工具/权限、上下文策略。
- 任务创建时选择角色；角色不拥有独立记忆库。
- 跨角色任务交接：把已接受 note/结果交给另一个角色。
- 多项目 dashboard 和项目切换。
- 角色权限边界的测试。

**Phase 3A 执行结果（2026-10-24）**

- 已实现 Coding + Testing 两个角色；Role 是策略层，没有角色数据库、独立 Agent 或记忆库。
- Task 增加 `role` 和 `source_task_id`；Testing 任务必须关联同项目 source task。
- Testing 默认 `verify` 档位：Read/Glob/Grep/PowerShell，无 Write/Edit；使用独立 CLI session。
- source task 的 accepted note 以 `reason=handoff` 进入 Testing 上下文；不复制原始 transcript。
- 真实 Testing 任务成功：独立审查分类过滤实现，运行 12 个测试全部通过，发现具体风险/缺失测试，未修改文件。
- 修复了一个 CLI 权限误判：base + role system prompt 叠加会让 PowerShell 命令被要求审批；改为角色 prompt 自包含。
- 31 个后端测试通过；前端构建通过；真实数据迁移到 schema v4。
- 只实现 Testing；Scholar/Personal/Health 和多项目 dashboard 仍未实现。
- 详细记录见 `docs/acceptance/phase3a.md`。

**Phase 3A 后续调整（2026-10-24）**

Testing 角色暂时搁置，不继续扩展；测试类任务由 Coding 角色复用 Claude Code 自身能力完成。已有 Testing 代码、任务和数据保留，不做破坏性删除。

Phase 3B 转向 Scholar，并确认边界：

- 不自建网页搜索/抓取/渲染/提取；
- 网页访问使用原生 WebSearch/WebFetch；
- Iris 负责任务编排：拆分受控子问题、并行小会话、进度、并发限制、取消、持久化和汇总；
- 研究结果区分事实/观点/假设并保留来源；
- Mentor 在 Scholar 验证后再做。
- 原生网页工具和两个并行 CLI session 已完成最小技术验证（见 `docs/decisions/0004-scholar-orchestration.md`）。

**Phase 3B 原型执行结果（2026-10-25）**

- 已实现 Scholar 研究计划生成/编辑、子问题并行执行、并发上限 2、取消、持久化、汇总草稿。
- 34 个后端测试通过；前端构建通过；schema v5。
- 第一个真实研究任务：5 个子问题，2 成功、3 失败；成功子任务带来源；汇总草稿区分事实/观点/假设/来源/gaps；用户已确认并接受。
- 失败原因详情此前不足；已记录 terminal reason/HTTP 状态，并实现 3 次尝试、2s/4s 指数退避。
- 第二个复用任务：source task handoff 注入第一轮 accepted note；Web 关闭；5/5 子任务成功、未触发重试；生成约 19.7k 字符研究草稿，继承来源和证据边界；草稿已由用户接受，任务完成。
- 真实 Web 子任务的可靠性和重试效果仍需新任务验证；长研究 note 的后续 handoff 会截断。
- Scholar 两轮验证完成；Mentor v0 已按确认模型实现（见 Phase 3C）。
- 详见 `docs/acceptance/phase3b.md`。

**Phase 3C Mentor v0 执行结果（2026-10-25）**

- 已实现 `goal` / `capability` / `blind_spot` / `progress` / `decision` 五类 typed global note。
- Mentor 默认且仅允许 `read_only`；服务端拒绝写权限档位。
- Mentor 任务自动引用已接受的 typed global note，`reason=mentor_state`；非 Mentor 任务不获得该注入。
- Source task 的已接受 note 继续以 `reason=handoff` 注入。
- 输出契约写入角色 prompt 和 Mentor 运行 prompt：比较选项、指出盲点/反例、提出用户问题、不替用户决定；用户确认方向后才提出未确认阶段任务。
- 前端 Mentor 面板：长期状态展示/添加、接受 progress/decision、从目标创建阶段任务、从阶段任务创建跟进 Mentor。
- 阶段任务接受 progress 后，跟进 Mentor 通过 handoff + mentor_state 看到进展。
- 不做自动能力评分、自动决策、自动写入长期事实或自动创建任务。
- 39 个后端测试通过；前端构建通过；尚无真实 CLI Mentor 验收。
- 详见 `docs/decisions/0005-mentor-v0.md` 和 `docs/acceptance/phase3c.md`。

**验收标准**

- Coding 与 Testing 任务可以共享同一项目已接受的 note，但拥有独立 session。
- 角色切换不会改变底层事实来源；角色只是策略层。
- 每个角色的工具和权限边界可被测试。
- 不需要为每个角色启动独立 Agent 实例。

**风险**

- 过早抽象角色，导致配置比实际需求复杂。
- 角色 prompt 质量差异大，难以评估。
- 跨角色上下文导致权限泄漏。

**前置依赖**

- Phase 2 完成。

### Phase 4 — 应用扩展 v1

**目标**

通过窄而稳定的接口增加真实工作能力，优先 Obsidian 和运行/成本监控。

**解决的问题**

- 工作成果散落在外部工具中。
- 用户需要查看任务、运行和成本状态。

**主要交付物**

- 应用清单、能力声明、授权和启用/停用。
- 第一方 Obsidian 读写应用，限定在用户授权的 vault。
- 运行监控和成本面板。
- 应用操作审计；应用不得绕过核心权限。
- 应用失败不拖垮核心服务。

**验收标准**

- Obsidian 应用只能访问被授权的 vault 路径。
- 停用应用后立即失去访问能力。
- 监控面板能展示运行、失败、时长和 CLI 报告的成本。
- 应用不能直接调用未授权的后端/CLI 能力。
- 有基本的崩溃隔离或至少故障隔离。

**风险**

- 插件/应用平台的安全边界复杂。
- 第三方代码执行和依赖风险。
- 在核心工作流未稳定前过早投入应用生态。

**前置依赖**

- Phase 1.5 完成；建议至少有一部分 Phase 2 的上下文能力。
- 只有在真实使用中出现需求时才启动，避免为了“平台感”而做。

### Phase 5 — 多后端与更高层协作

**目标**

在真实需求出现后，降低对单一 CLI 的依赖，并探索任务拆解和多角色协作。

**解决的问题**

- 不同任务可能需要不同模型、CLI 或本地工具。
- 复杂任务可能需要拆解和协作。

**主要交付物**

- 稳定的 Backend 适配接口：启动、恢复、取消、事件流、错误和成本归一化。
- 第二个真实后端（只有在有明确需求时）。
- 可选的任务拆解/多 Agent 协作。
- 桌面打包、自动更新和更完整的本地数据管理。

**验收标准**

- 核心任务闭环在第二个后端上可运行，业务层不包含 CLI 专属逻辑。
- 多角色协作不会绕过权限和上下文边界。
- 打包版本可以备份/恢复数据，并明确升级路径。

**风险**

- 过早抽象导致维护成本。
- 多 Agent 协作增加不可预测性和成本。
- 打包/自动更新引入新的安全面。

**前置依赖**

- 明确的真实需求和使用数据；不以“未来可能需要”为理由提前实现。

## 7. Phase 1 建议架构

### 7.1 形态

模块化单体，单用户、本地运行：

```text
React + TypeScript (Vite)
        │  REST + SSE
        ▼
FastAPI (single process)
  ├─ API / schemas
  ├─ TaskService / RunService
  ├─ ContextBuilder
  ├─ ClaudeCodeAdapter ──► local Claude Code CLI
  ├─ ProcessSupervisor
  └─ repositories ──► SQLite (WAL)
```

不引入 Redis、消息队列、Celery、微服务或向量数据库。

### 7.2 数据模型草案

| 表 | 关键字段 | 说明 |
|---|---|---|
| projects | id, name, workspace_path, brief_md, trusted_at, created_at, archived_at | 项目和工作区信任状态 |
| tasks | id, project_id, title, goal_md, status, current_session_id, created_at, updated_at | 工作单元；MVP 一个 task 一个当前 session |
| runs | id, task_id, attempt_no, status, cli_session_id, permission_profile, prompt_version, started_at, ended_at, exit_code, cost_usd, usage_json, error_type, error_message, context_manifest_json | 一次 CLI 调用；上下文快照保存在 manifest |
| run_events | id, run_id, seq, kind, created_at, payload_json, truncated | 追加式事件；SSE 按 seq 重放 |
| notes | id, project_id, task_id, source_run_id, kind, status, title, content_md, created_at, updated_at, accepted_at | 用户接受/编辑后的可复用成果 |

状态机草案：

```text
Task: ready -> running -> needs_review -> done
               |-> interrupted -> running (resume / new session)
               |-> failed -> ready (retry)
               |-> canceled

Run: starting -> running -> succeeded | failed | canceled | interrupted
```

- run 成功后 task 进入 `needs_review`。
- 用户接受 outcome 后 task 才进入 `done`；否则可重试或取消。
- task 完成后，相关后续工作应创建新 task，而不是悄悄重开旧 task。
- 服务启动时将未收敛的 running/starting/canceling 状态标记为 interrupted，不自动重跑。

### 7.3 最小 API

- `GET/POST /api/projects`
- `GET/PATCH/DELETE /api/projects/{id}`
- `GET/POST /api/projects/{id}/tasks`
- `GET/PATCH/DELETE /api/tasks/{id}`
- `GET /api/tasks/{id}/context-preview`
- `POST /api/tasks/{id}/complete`
- `POST /api/tasks/{id}/runs`（new / resume）
- `POST /api/runs/{id}/cancel`
- `GET /api/runs/{id}`
- `GET /api/runs/{id}/events?after_seq=`
- `GET /api/runs/{id}/events/stream`（SSE）
- `GET/POST /api/projects/{id}/notes`
- `PATCH /api/notes/{id}`（编辑/接受/归档）
- `GET /api/health`（CLI 版本、认证、数据库、数据目录）

### 7.4 上下文包

每次运行前构建并保存：

- 项目 brief（用户可编辑）和任务目标。
- 从已接受的项目 note + 全局 note 中推荐/选择的内容。
- 推荐因素：置顶、FTS/关键词相关度、最近更新、使用次数。
- 预算：默认 16000 chars / 约 4000 tokens；超出预算的 note 不注入并记录原因。
- 注入清单：note id、scope、字符数、reason、selection mode、推荐 ID、估算 token。
- 不默认注入原始 transcript、完整历史对话或未接受的模型摘要。
- 用户可以在运行前覆盖推荐选择；实际注入内容以 manifest 为准。

提示词应将仓库内容视为数据而非指令，并要求 Agent 在结束前报告修改、测试和阻塞项；但提示词不能替代权限控制。

### 7.5 安全基线

- 仅监听 `127.0.0.1`；校验 Origin/Host；写请求要求明确的 JSON Content-Type 和自定义请求头。
- 工作区需要用户显式信任；记录信任时间。
- 默认使用 `--safe-mode`，阻止项目 hooks/插件/MCP/自定义扩展执行。
- 必须知道：本版本 CLI 在 safe-mode 下仍会加载 CLAUDE.md；CLAUDE.md 视为不可信项目说明，不能替代权限控制。
- 默认不使用 `--dangerously-skip-permissions`。
- 使用 `--tools` 限制工具集合。Windows 的 shell 工具名是 `PowerShell`，不是 `Bash`。
- 运行档位：
  - 只读：`Read,Glob,Grep`。
  - 编辑：`Read,Glob,Grep,Write,Edit` + `acceptEdits`。
  - 执行：在编辑档基础上加入 `PowerShell`，使用 `--permission-mode dontAsk` + 项目级 `--allowedTools` 白名单，并用 `--disallowedTools` 阻止危险模式；必须由用户显式开启。
- 不使用 `acceptEdits` 作为 shell 安全边界；测试证明简单破坏性 PowerShell 命令可能被放行。
- 默认 cwd 为项目根目录；工作区外访问由 CLI 策略阻止；`--add-dir` 仅在明确授权时使用。
- 不记录 CLI 凭据；提示用户不要在任务中暴露密钥；对 `.env` 等敏感文件给出警告。
- 明确展示当前使用的模型/后端，并说明任务内容会离开本机。
- 不自动 git 提交、合并、部署或删除文件。
- 进程取消、超时和崩溃恢复必须有可观察状态。Phase 1 使用 `taskkill /T /F`，Phase 1.5 评估 Job Object。

### 7.6 测试策略

- **单元测试**：状态机、事件解析、命令构建、上下文预算、错误映射。
- **集成测试**：使用可配置的假 CLI 产生确定性 JSONL；覆盖启动、取消、超时、恢复、SSE 重放。
- **真实 CLI smoke test**：显式开启，限制在一到两个小任务和成本上限内。
- **端到端验收**：在示例仓库中执行任务 A → 中断/重启 → 恢复 → 接受 note → 任务 B 复用上下文。
- **故障注入**：CLI 不存在、认证失败、非零退出、坏 JSON、进程被杀、数据库锁、服务重启。
- **平台验证**：优先覆盖 Windows 路径、编码和 `.cmd` 调用；CI 后续再加其他平台。

## 8. 最小可用工作流

推荐场景：维护一个小型 expense CLI 仓库。

1. 项目指向该仓库，写入项目 brief。
2. 任务 A：增加 CSV 导出。Iris 启动 CLI，在仓库中实现并运行测试。
3. 运行中途取消，验证进程清理和状态。
4. 重启 Iris，识别运行中断；尝试恢复，失败则用新 session + handoff。
5. 任务 A 完成后，用户审查结果，把实现位置、命令、依赖决策和测试情况接受为 outcome note。
6. 任务 B：给 CSV 导出增加日期过滤。Iris 在上下文预览中包含任务 A 的 note。
7. 任务 B 不需要重新解释模块位置和既有决策，运行记录显示注入了该 note。
8. 对比任务 B 的解释成本和结果质量，判断 Iris 是否真的提供了价值。

不推荐把 Iris 自身作为首个目标：自举会干扰验收，也难以区分“Iris 系统有效”和“Claude Code 本身就能完成”。

## 9. 优先级与暂缓

### 优先实现

1. 任务状态、运行、事件持久化、取消。
2. 中断识别和恢复/降级。
3. 结果审查和用户接受的 outcome note。
4. 上下文预览、注入快照和后续任务复用。
5. CLI 健康检查、错误分类和本地 API 安全。

### 后续实现

- 全文检索、上下文预算和最小全局上下文。
- 角色策略、多项目工作空间。
- Obsidian、监控面板和第一方应用。
- 多后端、多 Agent、桌面打包。

### 明确暂缓，直到有真实需求

- Embedding / RAG / 自动记忆。
- 插件市场、第三方应用沙箱。
- 多用户、远程访问、云同步。
- 自动任务调度、自动 git 提交/合并/部署。
- 健康等高风险领域的自动化决策。
- 为了“架构完整”而引入的多 Agent 或分布式基础设施。

## 10. 成功标准

第一阶段不追求代码量、角色数量或应用数量。更有意义的观察指标是：

- 第二个相关任务是否减少了重复解释。
- 用户是否愿意接受并复用生成的 outcome。
- 中断后能否明确知道任务处于什么状态，且不会重复危险副作用。
- 用户是否能看懂某次运行注入了哪些上下文。
- 是否出现孤儿进程、数据丢失或密钥泄漏。
- 用户是否愿意在日常工作中继续使用，而不是退回手动 CLI。

## 11. 决策状态

| 编号 | 决策 | 建议 | 状态 |
|---|---|---|---|
| D1 | Python 运行时 | 安装 Python 3.12，项目本地 `.venv` | 已确认（2026-10-23） |
| D2 | 执行权限模型 | 受信任工作区 + 只读/编辑/执行档位，默认不 bypass | 已确认（2026-10-23） |
| D3 | 首个验收场景 | 独立小型代码仓库，而非 Iris 自身 | 已确认（2026-10-23） |
| D4 | 上下文写入 | 仅用户接受/编辑后的 outcome 进入上下文 | 已确认（2026-10-23） |
| D5 | git 初始化和目录结构 | 采用默认工程结构，数据目录 gitignored | 默认采用 |
| D6 | 数据/接口技术选型 | FastAPI + stdlib SQLite（WAL）+ `schema.sql` + SSE + React/Vite；SQLAlchemy/Alembic 推迟 | Phase 1 已采用 |
| D7 | 会话映射 | 一个 Task 一个当前 CLI session，后续任务新 session | 默认采用 |
| D8 | 并发 | 同一项目同一时间一个活跃 run | 默认采用 |
| D9 | Phase 1 范围 | 只做 Coding 任务闭环，不做角色/应用/自动记忆 | 默认采用 |
| D10 | CLI 扩展隔离 | 默认 `--safe-mode`，阻止项目 hooks/插件/MCP | 已验证并采用 |
| D11 | Windows 执行工具 | 使用 `PowerShell` 工具；执行档使用 `dontAsk` + 允许/拒绝列表 | 已验证并采用 |
| D12 | 取消方式 | Phase 1 使用 `taskkill /T /F`；Phase 1.5 评估 Job Object | 已验证一次并采用 |
| D13 | 成本展示 | 显示 CLI 报告的 cost/usage，并标注非账单值 | 字段已验证；准确性待评估 |
| D14 | prompt 传递 | 通过 stdin 传入，不作为多行命令行参数 | 已验证并采用 |
| D15 | 前端数据层 | React Router + 原生 fetch；TanStack Query 推迟 | Phase 1 已采用 |
| D16 | 崩溃时进程清理 | `taskkill /T /F` + Windows Job Object（pywin32） | 已验证并采用 |
| D17 | 数据维护 | SQLite 在线备份/列表；恢复 CLI 需停止后端并生成安全副本 | 已验证并采用 |
| D18 | 本地 API 硬化 | Host/Origin、X-Iris-Client、JSON Content-Type、CSP/安全头 | 已验证并采用 |
| D19 | 安全与审计 | 敏感文件警告、permission.denied 事件、滚动日志（不含 prompt/凭据） | 已验证并采用 |
| D20 | 检索方式 | SQLite FTS5 + 中文 bigram/停用词/词边界 + LIKE 回退，不引入 embedding | 已验证并采用 |
| D21 | 全局上下文 | 独立 `global_notes` 表，用户手写/接受；项目 note 保持项目 scope | 已验证并采用 |
| D22 | 预算与排序 | 置顶只加权；自动注入要求命中；相关度、最近、使用次数；16000 chars / 约 4000 tokens | 已验证并修复精确度 |
| D23 | 数据迁移 | schema v2 自动迁移，FTS 重建，迁移前备份 | 已验证真实数据 |
| D24 | 中文检索 | 中文 bigram + 停用词/功能字过滤 + 数字过滤；FTS rank 仅排序加分 | 已验证生活场景 |
| D25 | 别名召回 | note aliases/tags 进入 FTS 和本地匹配；用户维护 | 已验证：改写召回 0/5 → 5/5 |
| D26 | 角色形态 | Role 是行为/工具/上下文策略，不是独立 Agent/记忆库 | 已验证 Testing 切片 |
| D27 | 跨角色 handoff | Testing 关联 source task，只复用 accepted notes，使用独立 session | 已验证真实 CLI |
| D28 | 角色 prompt | 每个角色使用单一自包含 system prompt，不与 base 叠加 | 已验证；叠加会误判权限 |
| D29 | Testing 角色 | 暂时搁置；测试交由 Coding + Claude 原生能力 | 待 Scholar 后再评估 |
| D30 | 网页能力 | 不自建搜索/抓取；使用原生 WebSearch/WebFetch | 已验证工具可用 |
| D31 | Scholar 编排 | 父任务拆成 3–5 个受控子对话；并发、取消、持久化、汇总 | 原型已实现；首次真实任务部分失败 |
| D32 | Scholar 网页来源 | 不自建搜索；原生 WebSearch/WebFetch | 已验证可用 |
| D33 | 研究知识沉淀 | 汇总草稿区分事实/观点/假设/来源；用户接受后进入上下文 | 草稿已生成，待审查 |
| D34 | Testing 搁置 | 测试交由 Coding + Claude；保留历史数据 | 已从新任务 UI 移除 |
| D35 | Scholar 重试 | 子任务默认 3 次尝试，指数退避 2s/4s；记录失败详情 | 已实现并测试 |
| D36 | Mentor 长期状态 | 五类 typed global note；只有 accepted 才进入长期状态 | 已实现并测试 |
| D37 | Mentor 上下文 | 已接受 typed global note 以 `mentor_state` 注入；source task 仍用 handoff | 已实现并测试 |
| D38 | Mentor 权限 | 默认且仅允许 `read_only` | 已实现并测试 |
| D39 | Mentor 阶段任务 | 用户确认后手动创建，`source_task_id` 关联 Mentor/阶段任务 | 已实现并测试 |
| D40 | Mentor 自动写入 | 不自动评分、决策、写长期事实或创建任务 | 已确认并测试 |

D1–D4 已由用户确认。D5–D23 已按 Phase 1/1.5/2 实现采用；Phase 2 核心能力完成。

## 12. 下一步

1. 用真实 CLI 执行一次 Mentor 比较任务，验证输出是否稳定满足：比较选项、指出盲点/反例、提出用户问题、不替用户决定。
2. 走完整 Mentor 流程：长期状态 → 只读比较 → 接受 progress/decision → 阶段任务 → 跟进 Mentor。
3. 观察长期 `progress` 累积后是否挤占上下文预算，再决定是否按类型裁剪或摘要。
4. Testing 保持搁置；不删除已有数据；不在真实 Mentor 验证前扩展 Personal/Health、Obsidian 或多 Agent。
