# ADR 0005：Mentor v0 — 类型化长期状态与只读建议

- 状态：已实现（2026-10-25）
- 关联：`docs/decisions/0003-roles.md`、`docs/decisions/0004-scholar-orchestration.md`、`docs/acceptance/phase3c.md`

## 背景

Scholar 已完成两轮真实研究任务，证明受控子对话、来源保留、handoff 和知识复用可以工作。下一步不再扩展 Scholar 编排，而是验证 Mentor 是否能基于用户确认过的长期状态提供建议，而不是替用户做决定。

用户确认的最小模型：

- 用带类型的全局 note 存长期状态：`goal`、`capability`、`blind_spot`、`progress`、`decision`。
- Mentor 默认 `read_only`，不修改文件、不替用户决定。
- Mentor 输出应比较选项、指出盲点和反例、提出需要用户回答的问题；只有在用户确认方向后才拆解阶段任务。
- 后续 Mentor 任务引用已接受的 `progress` / `blind_spot`，而不是自动推断人格或能力评分。
- 不做自动能力评分、自动决策、自动写入长期事实。

## 决策

1. **长期状态只来自用户接受的内容。**
   - `global_notes.kind` 支持 `goal`、`capability`、`blind_spot`、`progress`、`decision`。
   - 只有 `status=accepted` 的 typed global note 才进入 Mentor 长期状态。
   - Iris 不会从对话、运行结果或模型推测中自动提取长期事实。

2. **Role 是策略层，不是独立 Agent。**
   - Mentor 的 `allowed_profiles` 只有 `read_only`；服务端拒绝 `edit` / `execute` 等档位。
   - 不创建角色专属数据库、记忆库或独立模型。

3. **Mentor 上下文策略显式而确定。**
   - Mentor 任务自动包含已接受的 typed global note，`reason=mentor_state`，不依赖关键词是否命中。
   - `source_task_id` 指向的 source task 的已接受 note 仍以 `reason=handoff` 进入上下文。
   - 其他项目/全局 note 继续使用原有检索规则。
   - 非 Mentor 任务不会获得 `mentor_state` 注入。

4. **输出契约写入角色 prompt 和 Mentor 运行 prompt。**
   - 至少比较两个可行选项（收益、成本、风险、可逆性、证据、改变判断的条件）。
   - 指出相关盲点、反例和失败模式。
   - 以 1–3 个只有用户能回答的问题结束。
   - 只有用户已明确确认方向时，才提出阶段任务；所有阶段任务必须标记为未确认，等待用户批准。
   - 不推断人格、不给能力评分、不把猜测写成事实。

5. **阶段任务和跟进都由用户显式创建。**
   - 阶段任务是普通 Coding task，`source_task_id` 指向 Mentor task。
   - 用户可以从已接受的 `goal` note 预填阶段目标，但仍需手动编辑、创建和运行。
   - 阶段任务完成后，用户接受一条 `progress` note；跟进 Mentor task 的 `source_task_id` 指向该阶段任务，从而通过 handoff 看到进展。
   - Mentor 不会自动创建、启动或完成任何任务。

6. **没有 schema 变更。**
   - 复用现有 `global_notes`、`tasks.role`、`tasks.source_task_id`、`notes` 和上下文 manifest。
   - Prompt 版本更新为 `phase3c-mentor-v1`；数据库仍为 schema v6。

## 后果

- Mentor 的长期状态注入是确定性的，便于在上下文预览和运行 manifest 中追溯。
- `progress` 会随时间累积；目前只受上下文预算限制，尚未按类型裁剪或摘要。后续需要时可增加“每类最近 N 条”或用户选择。
- 阶段任务与跟进任务复用现有任务机制，没有新增编排表；好处是简单可审计，代价是阶段关系只通过 `source_task_id` 表达。
- Mentor 仍不是自动规划器：它提供建议和问题，用户负责确认方向、沉淀状态和创建任务。

## 明确不做

- 自动能力评分或人格推断。
- 自动替用户选择方案。
- 自动把 Mentor 输出写成长期事实。
- 自动创建、启动或完成阶段任务。
- Mentor 专属记忆库、独立 Agent 或多 Agent 自由协作。
- 在用户确认前生成并执行阶段任务。
