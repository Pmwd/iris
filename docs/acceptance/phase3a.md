# Phase 3A 验收记录：角色就绪 + Testing 单角色

> 日期：2026-10-24  
> 范围：角色策略层、Coding/Testing、verify 权限、跨角色 handoff。  
> 不包含：五角色、独立角色记忆库、多 Agent。

## 1. 自动化验证

```text
31 tests passed
```

覆盖：

- `roles` API 和角色默认/允许档位；
- Testing 任务必须关联 source task；
- Testing 拒绝 edit 档位；
- source task 的 accepted note 以 `reason=handoff` 进入 Testing 上下文；
- Testing 使用独立 CLI session；
- verify 档位工具为 `Read,Glob,Grep,PowerShell`，允许列表不含 Write/Edit；
- 原有 Phase 1/1.5/2 测试继续通过。

前端构建通过。

## 2. 真实数据迁移

迁移前备份：`data/backups/iris-20261024-070042-107046.db`。

真实 `data/iris.db` 已迁移到 **schema v4**：

- `tasks.role` 默认 `coding`；
- `tasks.source_task_id` 可为空；
- 原有任务、运行、note 和全局 note 数量保持；
- 现有任务角色均为 Coding。

## 3. 真实 Testing 验收

成功任务：

- Task ID：`b8ec8174-a0f5-44d5-9947-0dce9fd465e1`
- Run ID：`db30b98a-4e74-45b3-ac25-159e012bff47`
- Source task：`870787f4-6bc3-4b33-9fe1-0abc9c655827`（分类过滤）
- 角色：Testing
- Profile：verify
- 上下文：
  - `Category filtering outcome`，reason=`handoff`
  - `CSV export outcome`，reason=`matched`
- 结果：**PASS**；实际运行 12 个测试全部通过。
- 独立审查发现：
  - category 过滤大小写/空格敏感且未文档化；
  - 缺少 category 字段的旧数据会抛 KeyError；
  - 缺少 `--to` + category / 双边界 + category 的 CLI 测试；
  - README 未记录 export 选项。
- 没有修改文件，没有修复代码。
- 任务停留在 `needs_review`，没有自动接受为 note。

早期两次 Testing 尝试失败：

- 原因是 base system prompt 与 role system prompt 叠加时，PowerShell 权限层把测试命令误判为需要审批；
- 修复为角色运行使用单一、自包含的 role prompt；
- 修复后第三次真实运行通过。

## 4. 浏览器 UI 冒烟

- 在项目页选择 Testing 角色和被验证任务；
- 创建 Testing 任务后，任务页显示 Testing badge、source task 和默认 `verify` 档位；
- 上下文预览显示 `Category filtering outcome`，reason=`交接`；
- 浏览器控制台无错误；
- 临时 UI 任务已删除。

截图：`data/browser-shots/40-testing-role-ui.png`

## 5. 角色边界验证

- Testing 与 Coding 使用不同 CLI session。
- Testing 只看到 source task 的 accepted note，看不到原始 transcript。
- Testing 默认 verify，没有 Write/Edit 工具。
- source task 的 note 通过显式 handoff 进入上下文，不依赖检索是否命中。
- 没有角色专属数据库或独立 Agent。

## 6. 已知限制

- 只实现 Coding 和 Testing；Scholar/Personal/Health 未实现。
- Testing 必须关联 source task。
- 角色不能在同一 Task 内切换；跨角色通过新 Task + accepted note。
- verify 白名单仍依赖项目配置；复合/临时 PowerShell 命令可能被拒。
- 浏览器 UI 只做了角色创建和 handoff 冒烟；完整 Testing 运行仍通过 API/真实 CLI 验收。
- 多 Agent 协作仍后置。

## 7. 结论

Phase 3A 的垂直切片成立：角色作为策略层可以工作，Testing 能独立审查真实 Coding 结果、复用 accepted note、运行测试且不修改文件。下一步可以先用 Testing 积累真实审查样本，再决定是否加入 Scholar 或 Personal；不建议立即扩展五角色或多 Agent。
