# Phase 1.5 验收记录

> 日期：2026-10-23  
> 范围：可靠性、安全与数据维护加固；不新增角色、应用或自动记忆能力。  
> 环境：Windows 11、Python 3.12.10、Claude Code CLI 2.1.221、Node 24.19。

## 1. 自动化结果

```text
15 tests passed
```

涵盖：

- 原有 Phase 1 流程：运行、编辑、note、上下文复用、取消/恢复。
- CLI 超时：run 收敛为 `failed`，`error_type=timeout`。
- CLI 不存在：run 收敛为 `failed`，`error_type=cli_spawn_failed`。
- 坏 JSON 输出：记录 `cli.unparsed` 事件，后续合法 result 仍可完成。
- 备份：生成可读取的 SQLite 备份；备份和恢复 roundtrip 后可找回项目。
- 恢复前自动生成 `pre-restore-*.db` 安全副本。
- 敏感文件：工作区存在 `.env` 时，上下文预览返回警告。
- 安全响应头：`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、CSP。
- 写操作 Content-Type 校验：`text/plain` 被拒绝（415）。
- Windows Job Object：关闭 job handle 后，包装进程和后代进程都被清理。

前端：`npm run build` 通过（TypeScript 检查 + Vite 构建）。

## 2. 真实崩溃恢复测试

脚本：`scripts/crash_test.py`

1. 启动独立后端，使用 fake CLI。
2. 启动一个会创建子进程并休眠的 run。
3. 只强杀 Iris 后端进程（不使用 `/T`），不直接杀 CLI 进程树。
4. 验证 fake CLI 的子进程在 3 秒内消失。
5. 重启后端，验证原 run 被标记为 `interrupted`。

实际结果：

```text
child process gone after backend crash
run_after_restart=interrupted
backend restart reconciliation: OK
```

说明：Job Object 在服务异常退出时提供了进程树兜底清理；启动校正负责把数据库状态收敛为 interrupted。

## 3. 备份与恢复

- API：`POST /api/maintenance/backup`、`GET /api/maintenance/backups`。
- UI：项目首页提供“立即备份数据库”和备份列表。
- CLI：

```powershell
.\.venv\Scripts\python.exe -m app.maintenance --data-dir data list
.\.venv\Scripts\python.exe -m app.maintenance --data-dir data backup
.\.venv\Scripts\python.exe -m app.maintenance --data-dir data restore data\backups\<file>.db
```

恢复注意：

- **先停止后端**，否则可能替换正在使用的数据库。
- 恢复前会尝试生成 `data/backups/pre-restore-*.db`。
- 恢复时删除旧的 `-wal` / `-shm` 文件。
- 当前没有在线恢复接口，这是有意的安全限制。

### 真实数据演练（2026-10-23）

在真实 `data/iris.db` 上完成了一次可回滚演练：

1. 备份前状态：1 个项目、2 个任务、3 次运行、1 条 note；项目为 `Expense CLI`。
2. 创建备份 `data/backups/iris-20261023-043213-028133.db`。
3. 在备份之后创建临时标记项目和 note；状态变为 2 个项目、2 条 note。
4. 停止后端，执行恢复。
5. 恢复后状态：1 个项目、2 个任务、3 次运行、1 条 note；标记项目和 note 均不存在；`Expense CLI` 和 `CSV export outcome` 完好。
6. 恢复前自动生成 `pre-restore-20261023-043225-682482.db`；验证其中确实包含 1 个标记项目和 1 条标记 note，证明安全副本有效。
7. 重启后端，`/api/health` 正常，项目和 note 可读取。

## 4. 日志与审计

- 日志文件：`data/logs/iris.log`，5 MB 轮转，保留 3 份。
- 日志只记录 run id、task id、权限档位、状态、成本等元数据；不记录 prompt、结果正文或凭据。
- CLI 的 `permission_denials` 现在会转成 `permission.denied` 运行事件，可在 UI 中查看。
- 工作区敏感文件警告会出现在任务的上下文预览中。

## 5. 浏览器手工验收结果（已完成）

使用本机 Edge + Playwright Core 以 headless 浏览器驱动真实 UI，并查看截图确认渲染。临时项目在流程结束后已删除。

已完成：

1. 打开首页，CLI 状态显示 `ok`、版本 `2.1.221`、认证正常；项目列表显示 `Expense CLI`。
2. 创建临时项目 `Browser checklist`，工作区包含一个 `.env` 测试文件。
3. 创建只读任务，任务页显示“工作区安全提示”和上下文预览。
4. 真实 CLI 运行完成，事件、结果、成本和上下文快照正常显示。
5. 接受 outcome note，note 在项目页出现；任务可标记完成。
6. 首页点击“立即备份数据库”，备份出现在列表。
7. 创建执行档任务，启动后出现“取消运行”，取消后状态为“已取消”。
8. 删除临时项目，确认对话框生效，项目从列表消失。
9. 浏览器控制台无错误。

### 发现并修复的问题

- **加载状态误导**：首页原先用 `Promise.all` 同时等待项目、健康检查和备份；健康检查较慢时，项目区会暂时显示“0 个项目”。已改为独立请求 + `加载项目…` / `加载备份…` 状态。
- **运行事件自动滚动**：原先 `scrollIntoView` 会把整个页面滚动到事件底部，使任务标题被 sticky header 遮挡。已改为只设置事件列表容器的 `scrollTop`。
- 回归验证：首页项目正常加载；任务页 `window.scrollY = 0`，标题可见；控制台无错误。

截图保存在 `data/browser-shots/`（gitignored），关键文件：

- `01-home.png`
- `03-task-context-warning.png`
- `04-run-result.png`
- `07-backup.png`
- `09-canceled.png`
- `10-deleted.png`
- `20-home-regression.png`
- `21-task-regression.png`

## 6. 已知限制

- 浏览器流程这次使用临时 Playwright 驱动完成，尚未把该驱动纳入仓库依赖；后续可通过 `/run-skill-generator` 固化为项目运行技能。
- Job Object 在进程已经处于另一个 Windows Job 时可能无法附加；这时仍依赖 `taskkill /T /F`。启动时的日志会记录附加失败。
- 认证失败路径、用户级 hooks/MCP、`--add-dir` 和极长 prompt 尚未系统验证。
- 成本显示仍不是账单；没有预算上限或强制停止策略。
- 恢复需要停止后端；没有在线热恢复。
- 单用户、本地运行；没有登录、远程访问或权限审计 UI。
- 任务结果仍依赖模型能力和项目状态，真实任务输出不保证一致。

## 7. 结论

Phase 1.5 的核心加固已完成：进程树兜底清理、真实崩溃恢复、超时/缺失 CLI/坏 JSON 的故障路径、备份恢复、敏感文件提示、安全响应头、审计事件、浏览器手工流程和真实数据恢复演练均已验证。下一步先决定是否进入 Phase 2 的上下文检索和预算能力，或继续积累真实任务数据。
