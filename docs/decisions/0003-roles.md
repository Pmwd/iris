# ADR 0003：Phase 3A 角色策略层与 Testing 角色

- 状态：已采用（2026-10-24）
- 范围：Coding + Testing 两个角色；不包含五角色全面实现、多 Agent 或角色专属记忆库。

## 背景

Phase 1/2 已经有 Task、Session、Run、Context 和本地 CLI 执行。Phase 3 需要验证“角色”是否有真实价值，而不是先铺设一套复杂平台。

## 决策

1. Role 是**行为、工具权限和上下文策略的组合**，不是独立 Agent、独立模型或独立记忆库。
2. Task 增加 `role` 和 `source_task_id`：
   - `role` 默认为 `coding`；
   - Testing 任务必须关联一个同项目的 source task。
3. Session 仍属于 Task：Testing 使用独立 CLI session，不复制 Coding 的原始 transcript。
4. 跨角色共享只通过**已接受 note**：
   - source task 的 accepted notes 以 `reason=handoff` 进入 Testing 上下文；
   - 其他 note 仍按正常检索规则选择；
   - 不注入 source task 的完整对话。
5. 新增 `verify` 权限档位：
   - 工具：`Read,Glob,Grep,PowerShell`；
   - 不含 `Write/Edit`；
   - `dontAsk` + 项目 PowerShell 白名单。
6. Testing 角色默认 `verify`，不允许 edit/execute；Coding 角色允许 read_only/edit/execute。
7. 角色 system prompt **独立自包含**，不与通用 base prompt 叠加。实测发现 base+role 两段叠加会让 PowerShell 命令被权限层误判为需审批；role-only 正常工作。
8. 角色不拥有独立记忆；Testing 结果仍是 Task result，只有用户接受后才成为 note。

## 后果

- Testing 能独立审查并运行测试，但不能修改代码。
- Handoff 是显式任务链接，不依赖关键词是否命中。
- 角色机制仍然只有一个策略层，没有角色数据库和独立 Agent。
- 当前只支持 Coding/Testing；Scholar、Personal、Health 等仍是后续假设。

## 未决问题

- 是否允许同一 Task 内切换角色，还是始终新 Task。
- Testing 的 verify 白名单是否需要按项目类型模板化。
- 跨角色 handoff 是否需要显式“接受交接”步骤。
- 何时值得加入第三个角色。
