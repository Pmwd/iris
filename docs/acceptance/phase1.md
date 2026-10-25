# Phase 1 验收记录

> 日期：2026-10-23  
> 环境：Windows 11、Python 3.12.10（项目 `.venv`）、Claude Code CLI 2.1.221、Node 24.19、前端 Vite 构建  
> 工作区：`data/acceptance-expense-cli`（从 `examples/expense_cli` 复制，gitignored）  
> 真实 CLI 报告模型：`deepseek-v4-flash`（环境特定，不代表官方 Claude）

## 1. 验收方法

1. 启动 FastAPI 后端，确认 `/api/health` 中 CLI 已安装且认证正常。
2. 通过 API 创建项目和任务 A。
3. 使用 `execute` 权限档位运行真实 Claude Code CLI，允许 `PowerShell(python *)` 等只读/测试命令。
4. 轮询运行状态并保存事件、结果、成本和上下文快照。
5. 运行工作区测试，检查实际 diff。
6. 将任务 A 的结果接受为项目 note。
7. 创建任务 B，在上下文预览中选中任务 A 的 note，再次运行真实 CLI。
8. 验证任务 B 的运行快照确实包含该 note，并检查测试和 diff。
9. 使用 SSE 读取已完成运行的事件和 `done` 事件。

## 2. 任务 A：CSV 导出

- Task ID：`3a02796f-c46d-4732-b3c5-471ad806ca23`
- 成功 Run ID：`793e3367-cda1-49f0-8761-8fce2576384c`
- 状态：`succeeded` → task `needs_review`
- CLI 报告成本：约 `$0.1903`
- 结果：新增 `export_expenses()` 和 `export` 子命令；CSV 表头为 `date,category,amount,note`；测试从 3 个增加到 5 个，全部通过。
- 实际测试：

```text
Ran 5 tests in 0.014s
OK
```

- 记录中另有一个早期失败运行（多行 prompt 作为 `.CMD` 参数导致 CLI 丢失任务）；修复为 stdin 传递后重新运行成功。

## 3. 结果沉淀

接受的项目 note：

- Note ID：`46c2baeb-cc7f-4ae0-b390-59cc7c37d6cd`
- 标题：`CSV export outcome`
- 状态：`accepted`
- 来源：任务 A 的成功运行
- 内容：记录导出入口、CSV 表头、测试命令、“无新增依赖”、金额保留存储数值等决策。

## 4. 任务 B：日期范围过滤

- Task ID：`542f08f4-e1d5-4a10-bcc1-973862bbace4`
- Run ID：`06c035a5-845d-4817-9aea-fa4452011980`
- 状态：`succeeded` → task `needs_review`
- CLI 报告成本：约 `$0.2174`
- 上下文快照：

```json
{
  "budget_chars": 16000,
  "total_chars": 1546,
  "available_note_count": 1,
  "included_notes": [
    {
      "id": "46c2baeb-cc7f-4ae0-b390-59cc7c37d6cd",
      "title": "CSV export outcome",
      "chars": 354
    }
  ],
  "excluded_notes": []
}
```

- 结果：在已有的 `export_expenses()` 上增加可选 `from_date` / `to_date` 参数，保持原表头和原有导出行为；新增 3 个日期范围测试。
- 实际测试：

```text
Ran 8 tests in 0.025s
OK
```

- 模型在结果中明确说明“复用了同一个 writer/header”，并把过滤逻辑放在现有 `export_expenses()` 内，而不是另起实现。

## 5. 可观察到的价值

- 任务 B 的上下文快照包含任务 A 的 accepted note。
- 任务 B 直接扩展已有的 `export_expenses()`，不需要重新解释 CSV 导出入口、表头或依赖约束。
- 任务 A 和任务 B 的测试都实际运行并通过。
- 事件流、最终结果、成本和上下文快照均可从 API 读取；SSE 可重放事件并以 `done` 结束。

## 6. 权限与安全观察

- 执行档位使用 `--permission-mode dontAsk` + 允许列表；一次复合 PowerShell 命令被拒绝，事件中保留了 `permission_denials`，Agent 随后改用允许的方式继续。
- 工作区外的 Read/PowerShell 文件访问在 spike 中被阻止。
- 项目 hooks 默认执行；Phase 1 运行默认使用 `--safe-mode`，阻止 hooks/插件/MCP。
- 当前 CLI 版本在 safe-mode 下仍会加载 CLAUDE.md；工作区信任仍然必要。
- 后端仅监听 `127.0.0.1`，写操作要求 `X-Iris-Client: web`；这些在自动化测试中有覆盖。

## 7. 自动化验证

```text
8 tests passed
```

覆盖：

- 真实/假 CLI 运行、编辑、note 接受和上下文复用。
- CLI 错误映射。
- 取消后使用同一 session 恢复。
- 执行档位缺少 allowlist 时拒绝启动。
- 本地 API 写操作缺少客户端头时拒绝。
- 启动时将未完成运行标记为 interrupted。
- 命令构建器和上下文 manifest。

## 8. 尚未验证 / 已知限制

- 浏览器端交互式 E2E 未自动化；前端通过 TypeScript 检查和 Vite 构建，后端通过 HTTP/API 测试。
- 真实服务进程崩溃时的孤儿进程清理未测试；Phase 1 使用 `taskkill /T /F`，Phase 1.5 评估 Job Object。
- 认证失败路径、用户级 hooks/MCP、`--add-dir` 和超长/特殊字符 prompt 仍需补测。
- 上下文选择目前是“全部已接受 note + 手动取消勾选”；Phase 2 再引入检索和预算排序。
- CLI 报告成本不是账单；真实模型/端点可能不同。
- 真实任务结果依赖模型能力和项目状态；本记录证明流程闭环，不保证每次模型输出一致。
