# Iris 当前阶段

> 阶段：Phase 3C — Mentor v0 最小切片  
> 状态：实现完成并通过 fake CLI 测试；待真实 Mentor 任务验收；Testing 搁置  
> 更新时间：2026-10-25  
> 依据：`PROJECT_CHARTER.md`、`docs/decisions/0005-mentor-v0.md`、`docs/acceptance/phase3c.md`

## 1. 当前阶段目标

Phase 3C 的目标是验证 Mentor 是否能基于用户确认的长期状态提供建议，而不是替用户决定、自动评分或自动规划。

当前确认的方向：

- Testing 角色暂不继续开发；测试类任务由 Coding 角色复用 Claude Code 自身能力完成。
- Testing 已有代码、任务和数据保留，不做破坏性删除；新建任务 UI 已移除 Testing 选项。
- Scholar 已完成两轮真实任务，作为前序验证；Mentor 复用同一套 Task / Session / Context / note 基础设施，但不复用 Scholar 的多子对话编排。
- Iris **不自行构建网页搜索/抓取**；网页访问来自 Claude Code 原生 `WebSearch` / `WebFetch`。
- Iris 负责缺失的编排能力：任务拆分、受限制的小子对话、并行执行、进度、并发限制、取消和持久化。
- Mentor 默认只读；长期状态只来自用户手写/接受的 typed global note；不自动评分、不自动决策、不自动写入长期事实。
- 阶段任务和跟进任务由用户确认后显式创建，Mentor 不会自动创建或启动。

### 已实现的 Scholar 原型

- 自动生成 3–5 个研究问题，可编辑，用户确认后执行；
- 每个问题独立 CLI session，使用 `research` 工具档位；
- 并发上限 2、单子任务 8 轮、600 秒超时；
- 子任务默认 3 次尝试（2 次重试），指数退避 2s / 4s；记录 attempts；
- 失败详情记录 terminal reason、HTTP 状态和 CLI result；
- 取消、状态持久化、启动时中断校正；
- 汇总生成研究 note 草稿，区分事实/观点/假设/来源/gaps；
- 草稿只有用户接受后才进入上下文；
- Schema v6；35 个后端测试通过；前端构建通过。

### 第一个真实研究任务的结果

- 5 个子问题，2 个成功、3 个失败；
- 成功子任务带来源 URL；
- 汇总草稿明确说明失败子问题和未验证假设，约 12.9k 字符；
- 失败信息此前过于笼统；已增加 terminal reason / HTTP 状态记录和 2 次重试，但本任务无法回填；
- 第一轮研究草稿已由用户确认并接受。

### 第二个真实研究任务（复用验证）

- 基于第一轮 accepted note 创建，`source_task_id` 指向第一轮任务；
- 上下文预览以 `reason=handoff` 注入第一轮 note；
- Web 关闭，不进行新的网页检索；
- 5 个子问题，**5/5 成功，全部 attempts=1，未触发重试**；
- 约 289 秒完成；
- 汇总生成约 19.7k 字符研究草稿，继承第一轮来源、事实/观点/假设边界，并扩展为模板和复核流程；
- 第二份草稿已由用户接受，任务标记完成。

结论：编排和知识复用闭环成立；第一轮 Web 子任务可靠性仍有问题，重试尚未在真实 Web 任务中触发验证。真实库为 schema v6。

### 已实现的 Mentor v0（Phase 3C）

- 长期状态：`goal` / `capability` / `blind_spot` / `progress` / `decision`
  使用带类型的全局 note，只有用户手写或接受的内容生效；
- Mentor 默认 `read_only`，`allowed_profiles` 仅 `read_only`；不修改文件、不替用户决定；
- Mentor 任务自动引用已接受的 typed global note，`reason=mentor_state`；
  source task 的已接受 note 仍以 `reason=handoff` 注入；
- 输出契约：比较选项、指出盲点/反例、提出需要用户回答的问题；
  用户确认方向后才提出阶段任务，且标记为未确认；
- 前端 Mentor 面板：查看/添加长期状态、接受 progress/decision、
  从已接受目标创建阶段任务、从阶段任务创建跟进 Mentor；
- 阶段任务接受 `progress` note 后，跟进 Mentor 通过 handoff + mentor_state 看到进展；
- 不做自动能力评分、自动决策、自动写入长期事实或自动创建任务；
- 39 个后端测试通过；前端构建通过；尚未执行真实 CLI Mentor 任务。

Mentor 最小闭环：

1. 用户创建长期目标、当前能力和反复盲区；
2. Mentor 只读比较选项、指出风险并提出问题，不替用户选择；
3. 用户接受一条 progress / decision 全局 note；
4. 用户确认并创建阶段任务；
5. 阶段任务完成并接受 progress 后，跟进 Mentor 看到进展并继续。

Scholar 最小价值闭环：

1. 一个 Scholar 研究目标被拆成受控的小问题；
2. 每个问题在独立、窄上下文的 CLI session 中执行；
3. 多个子任务受并发限制并行运行，可取消、可恢复；
4. 结果带来源，并区分事实、观点和假设；
5. 用户审查后沉淀为可复用知识。
6. Mentor 复用同一套任务/上下文基础设施，但不复用 Scholar 的多子对话编排。

## 2. 已确认的决策

- Testing 角色搁置，不继续扩展；测试能力由 Coding + Claude 负责。
- Scholar 先于 Mentor；Mentor v0 已在 Scholar 两轮验证后实现。
- 不自建搜索、爬虫、排序、反爬、JS 渲染或内容提取。
- 原生 WebSearch/WebFetch 作为网页访问能力。
- Iris 的职责是任务编排，而不是一个不受控的巨型对话。
- 子任务使用独立 session 和窄上下文；不共享完整父 transcript。
- 子任务必须可限制工具、轮数、超时和并发。
- 父任务负责进度、取消、持久化和最终汇总。
- 研究结果必须保留来源，并区分已知事实、个人观点、待验证假设。
- 只有用户接受后的研究 note 才进入可复用知识。
- Mentor 不自动替用户做决定，不做未经确认的人格判断。
- Mentor 长期状态只来自用户手写/接受的 typed global note；不做自动提取或评分。
- Mentor 永远只读；阶段任务和跟进任务由用户显式创建，不由 Mentor 自动生成或启动。

### 技术验证已确认

- 原生 `WebSearch`/`WebFetch` 在 CLI 中可用；一次真实搜索+抓取约 15.6 秒、成本约 `$0.1225`。
- 两个独立 CLI session 可并行完成；测试总耗时约 2.2 秒，session 互不干扰。
- 当前环境未引入自定义搜索/抓取代码。

## 3. 正在验证的假设

| 编号 | 假设 | 验证方式 | 若不成立 |
|---|---|---|---|
| S1 | 原生 WebSearch/WebFetch 在 Scholar 任务中足够用 | 已做一次真实搜索/抓取 | 只做本地研究工作区，不重造搜索 |
| S2 | 多个受限子对话并行可被稳定编排 | 并发 2 session 已通过；还需在 Iris 调度、取消、重启场景验证 | 降低并发或引入独立 worker |
| S3 | 自动生成 3–5 个子问题并由用户确认，是可接受的工作流 | Phase 3B 编排原型验收 | 改为用户手写子问题 |
| S4 | 子任务窄上下文能减少互相污染和成本 | 对比一个巨型对话与多子对话的结果/成本 | 调整上下文预算或拆分数目 |
| S5 | 研究 note 能用的“事实/观点/假设 + 来源”结构足够 | 两个连续 Scholar 任务验收 | 增加结构化字段/知识表 |
| S6 | Scholar 的价值高于继续扩展 Testing | 真实研究任务观察 | 暂停 Scholar，重新评估角色优先级 |
| S7 | 同一套编排可复用于 Mentor 的目标拆解 | Mentor 前置设计评审 | Mentor 保持单对话 + 目标 note |

Mentor v0 结论：不把 Scholar 的多子对话编排套到 Mentor；Mentor 保持单对话，长期状态使用 typed global note，阶段任务和跟进任务由用户显式创建。

## 4. 明确不做

- 自建网页搜索、抓取、内容提取、搜索排序或反爬。
- 一个不受控的巨型 Scholar 对话。
- 让子 Agent 自行扩大工具范围或启动不受控的子 Agent。
- 自动把网络内容或模型推测写成长期事实。
- Mentor 自动评分、自动决策、自动创建阶段任务或自动完成跟进。
- 在真实 Mentor 验证前扩展 Personal/Health、Obsidian、阅读器或多 Agent。
- 继续扩展 Testing 角色或角色专属权限平台。
- 清除已有 Testing 任务、运行或 note。

## 5. 验收条件

### 5.1 Phase 3B 规划/编排原型（已完成）

- [x] 原生 WebSearch/WebFetch 可用性验证。
- [x] 两个独立 CLI session 并行验证。
- [x] 记录“不自建搜索/抓取、Iris 只做编排”的决策。
- [x] 确认默认值：子问题 3–5 个、并发 2、单子任务 8 轮/10 分钟、网页按任务授权。
- [x] 原型：父任务拆分为 3–5 个子问题，用户可审阅/编辑。
- [x] 调度：并发上限、进度、取消单个/全部、重启后状态校正、持久化。
- [x] 子结果带来源；汇总生成结构化研究 note 草稿。
- [x] 用户接受后，后续 Scholar 任务能复用该 note。
- [x] 不在 3B 实现 Mentor、Obsidian 或自定义搜索。

### 5.2 Phase 3C Mentor v0

- [x] 五类 typed global note：goal / capability / blind_spot / progress / decision。
- [x] Mentor 默认且仅允许 read_only；写权限档位被服务端拒绝。
- [x] Mentor 任务自动引用已接受的 typed global note（`mentor_state`），草稿不注入。
- [x] 非 Mentor 任务不获得 `mentor_state` 注入。
- [x] 用户显式接受 progress / decision 全局 note。
- [x] 用户确认后手动创建阶段任务（`source_task_id` 指向 Mentor task）。
- [x] 阶段任务接受 progress 后，跟进 Mentor 通过 handoff + mentor_state 看到进展。
- [x] Mentor 运行不会自动写 note、自动建任务或自动评分。
- [ ] 用真实 CLI 执行一次 Mentor 比较任务并审查输出语义。

### 5.3 验证命令

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
cd frontend
npm run build
```

## 6. 下一步

1. 用真实 CLI 执行一次 Mentor 比较任务，验证输出是否稳定满足：比较选项、指出盲点/反例、提出用户问题、不替用户决定。
2. 走一遍完整 Mentor 流程：长期状态 → 只读比较 → 接受 progress/decision → 阶段任务 → 跟进 Mentor。
3. 观察 progress 累积后是否挤占上下文预算；再决定是否按类型裁剪或摘要。
4. 不在真实 Mentor 验证前扩展 Personal/Health、Obsidian 或多 Agent。
