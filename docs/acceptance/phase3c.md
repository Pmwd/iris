# Phase 3C Mentor v0 最小切片

> 日期：2026-10-25  
> 状态：实现完成；fake CLI 测试与前端构建通过；尚未执行真实 CLI Mentor 任务。  
> 依据：`PROJECT_CHARTER.md`、`docs/decisions/0005-mentor-v0.md`

## 1. 已实现

- 带类型的全局 note：`goal`、`capability`、`blind_spot`、`progress`、`decision`。
- Mentor 角色默认 `read_only`，服务端只允许 `read_only`。
- Mentor 任务自动包含已接受的 typed global note，`reason=mentor_state`：
  - 不依赖关键词命中；
  - 只有 `status=accepted` 的全局 note 参与；
  - 非 Mentor 任务不会获得该注入。
- Source task 的已接受 note 继续以 `reason=handoff` 注入。
- Mentor prompt 明确要求：
  - 比较至少两个可行选项；
  - 指出盲点、反例、风险和可逆性；
  - 以 1–3 个需要用户回答的问题结束；
  - 只有用户确认方向后才提出阶段任务，并标记为未确认；
  - 不替用户决定、不评分能力、不推断人格、不自动写入事实。
- 前端 Mentor 面板：
  - 按类型展示已接受的长期状态；
  - 用户手动添加全局长期状态；
  - 用户审查 Mentor 结果并接受为全局 `progress` / `decision`；
  - 从已接受的 `goal` note 预填阶段任务目标；
  - 创建阶段任务（Coding，`source_task_id` 指向 Mentor task）；
  - 阶段任务完成/待审查后，创建跟进 Mentor task（`source_task_id` 指向阶段任务）。
- 阶段任务审查面板增加 `outcome` / `progress` 类型选择；`progress` 会通过 handoff 被后续 Mentor 看到。
- Prompt 版本更新为 `phase3c-mentor-v1`；无 schema 变更，仍为 v6。

## 2. 验收场景与结果

### 场景 1：创建长期目标和当前能力/盲区

- API：`POST /api/global-notes` 支持五种类型。
- UI：首页全局上下文表单和 Mentor 面板均可创建。
- 测试：`test_mentor_role_and_typed_global_notes`、
  `test_mentor_state_is_explicit_and_role_scoped`。
- 结果：通过。`goal` / `capability` / `blind_spot` / `progress` / `decision`
  均以 `mentor_state` 进入 Mentor 上下文；未接受的草稿不会注入。

### 场景 2：Mentor 比较两个选择并指出风险，不直接选一个

- 权限：`test_mentor_rejects_write_profiles` 验证 `edit` 档位返回 422。
- 输出契约：角色 system prompt 与 Mentor 运行 prompt 均要求比较选项、指出盲点和反例、提出用户问题，不替用户选择。
- 结果：权限与上下文策略已由测试覆盖；**建议文本的语义质量尚未用真实 CLI 验证**，fake CLI 只验证调用和状态。

### 场景 3：用户接受一条 progress / decision note

- UI：Mentor 面板“接受本次建议”，写入全局 `progress` 或 `decision`，内容预填自运行结果，用户可编辑。
- 测试：`test_mentor_stage_and_followup_reuse_long_term_state` 通过 API 显式接受
  decision / progress。
- 结果：通过；只有用户接受后才写入，Mentor 运行本身不会自动创建 note。

### 场景 4：基于目标创建阶段任务

- UI：Mentor 面板可用已接受的 `goal` note 预填阶段目标；用户编辑标题/目标后手动创建。
- 实现：阶段任务是 Coding task，`source_task_id` 指向 Mentor task。
- 测试：同一测试手动创建阶段任务并运行。
- 结果：通过；无自动任务创建。

### 场景 5：完成阶段任务后，后续 Mentor 看到进展并继续跟进

- 阶段任务接受 `progress` note（项目 note，`reason=handoff`）。
- 跟进 Mentor task 的 `source_task_id` 指向阶段任务。
- 上下文预览同时包含：
  - 已接受的全局长期状态（`reason=mentor_state`）；
  - 阶段任务的已接受进展（`reason=handoff`）。
- 测试：`test_mentor_stage_and_followup_reuse_long_term_state` 断言两种 reason 和
  `mentor_state_note_count`。
- 结果：通过。

## 3. 验证命令与结果

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
cd frontend
npm run build
```

- 后端：39 个测试通过。
- 前端：TypeScript + Vite 构建通过。

## 4. 已知限制

- 尚未执行真实 CLI Mentor 任务；输出是否稳定满足“比较选项 / 不替用户决定”的语义要求，需要一次真实任务验证。
- 长期 `progress` 会累积；目前只受上下文预算限制，尚未按类型裁剪或摘要。
- 跟进 Mentor 只有在用户于阶段任务接受 `progress` note 后才能通过 handoff 看到具体进展；UI 有提示，但不会强制。
- 全局长期状态没有数据库级 `task_id` / `source_run_id` 外键；Mentor 面板会把来源写进内容文本，但不可结构化追溯。
- Mentor 面板不提供编辑/归档长期状态；这些操作仍在首页全局上下文面板完成。
- 阶段任务和跟进任务的关系仅由 `source_task_id` 表达，没有独立编排表。
- 没有浏览器端完整手工验收记录。

## 5. 明确不做

- 自动能力评分、人格推断或自动决策。
- 自动把 Mentor 输出写成长期事实。
- 自动创建、启动或完成阶段任务。
- 在用户确认方向前生成并执行阶段任务。
- 为 Mentor 建立独立记忆库、独立 Agent 或多 Agent 协作。
