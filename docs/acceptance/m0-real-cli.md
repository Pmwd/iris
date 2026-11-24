# M0 真实 CLI / SDK 验收矩阵（T1–T9）

- 目标：证明 Iris 在真实 Claude CLI / Claude Agent SDK 下完成核心闭环，而不仅是 fake CLI 与自动化测试。
- 环境：Windows、Python 3.12、Node 20+、本机 `claude.exe` 已登录；`IRIS_EXECUTION_BACKEND=sdk`。
- 数据隔离：建议使用独立 `IRIS_DATA_DIR`（例如 `artifacts/verify-*`），验收后删除，不污染主数据。
- 详细操作步骤：`docs/acceptance/phase4-sessions.md`。
- 更新时间：2026-11-24。

## 1. 验收矩阵

| 编号 | 验证目标 | 核心步骤 | 关键证据 | 状态 |
|---|---|---|---|---|
| **T1 简单问答** | CLI 启动、输出解析、增量流式 | 新建 Coding Session（只读档位），发送“只回答两个字：你好” | `system.init` 出现；`assistant.delta`；`assistant.text`；`ResultMessage` 返回 cost/usage | **通过（2026-11-24）** |
| **T2 文件读取** | 工作目录与工具调用 | 在只读档位要求阅读工作区 `README` 并总结 | `Read` 的 `tool.use`/`tool.result`；回答使用 README 的构建命令 | **通过（2026-11-24）** |
| **T3 修改代码并测试** | 完整执行闭环 | 执行档位修改文件 → 审批允许 → 运行测试命令 → 审批允许 | `Write`+`PowerShell` 审批；文件真实生成；命令输出进入回答/摘要 | **通过（2026-11-24）** |
| **T4 新 Session 记忆召回** | Memory 注入 | 预置 accepted 工作区事实 → 新建 Session 发送相关问题 | `prompt_manifest.included_facts` 含该事实（`reason=matched`）；`use_count` +1；回答使用该事实 | **通过（2026-11-24）** |
| **T5 取消任务** | 进程终止与状态更新 | 执行档位允许长驻命令 `python sleepy.py` → 取消 Turn | Turn=`canceled`；工具子进程消失；pending 审批无残留；同一 Session 可继续 | **通过（2026-11-24，修复后）** |
| **T6 异常退出、重启** | 持久化与恢复 | 发起等待审批的 Turn → 强杀后端 → 重启 | 强杀后 CLI 树被清理；重启 `reconciled_turns=1`；Turn=`interrupted`；审批=`expired`；锁释放；后续 Turn 成功 | **通过（2026-11-24）** |
| **T7 UI 审批全流程** | 真实网页审批 | 无头 Edge 打开 Session；分别点击允许一次 / 拒绝 / 总是允许；第二条同类命令验证规则复用；另一 Session 不点击等待超时 | 审批卡真实渲染；`turn_approvals` 状态与决策者正确；允许后文件存在、拒绝后不存在；第二条 `decided_by=auto`；超时 `expired/timeout` | **通过（2026-11-24）** |
| **T8 运行面板真实 dev server** | 长驻进程与清理 | 工作区详情页运行面板启动 `python -m http.server` → 查看日志/HTTP → 停止；删除工作区；停止后端 | 状态 `running`→`stopped`；日志出现 `Serving HTTP`；HTTP 200；停止/删除/关闭后端后端口关闭、PID 消失；日志文件落盘 | **通过（2026-11-24）** |
| **T9 compact 恢复真实 resume 失败** | 摘要重建 CLI 会话 | 首轮成功后把 `cli_session_id` 改为不存在的 ID → 下一轮失败 → 点击「压缩并继续」→ 再发消息 | 失败为 `No conversation found with session ID`；compact 摘要成功；`cli_session_id` 清空；下一轮 `mode=new`、`summary_included=true`、成功 | **通过（2026-11-24）** |

## 2. 验证记录

### T1–T3（2026-11-24）

独立 `IRIS_DATA_DIR` + 真实 SDK：

- **T1**：只读档位，回答“你好”；`system.init.tools` 含 Read/Glob/Grep、**不含** PowerShell；`assistant.delta=1`；cost $0.10741；Turn succeeded。
- **T2**：只读档位，`Read` 读取工作区 `README.md`；`tool.result` 返回内容；回答“构建命令是 npm run build”；结束会话摘要包含 README 与 npm run build。
- **T3**：执行档位，真实触发 `Write` 与 `PowerShell` 两次审批（均允许）；`m0_t3.txt` 内容 `T3_OK`；命令输出 `T3_RUN_OK`；结束摘要包含 `m0_t3.txt`。
- 证据文件：`artifacts/m0-final/results.json`（gitignored）。

### T4（2026-11-24）

- 预置事实：“本项目统一使用 npm run build 构建”（workspace / coding / accepted，未置顶）。
- 新 Session 只读提问“构建项目应该运行什么命令？”。
- 结果：manifest `included_facts` 命中该事实（`reason=matched`），`use_count` 0 → 1，回答复述 `npm run build`。
- 说明：首轮无摘要，`summary_included=false`；事实注入不依赖置顶。

### T5（2026-11-24）

- 首次验证发现真实 Bug：Turn 已变为 `canceled`，但工具拉起的 `python sleepy.py` 仍然存活。
- 原因：SDK 只结束 `claude.exe`，Windows 上不会自动终止其工具子进程。
- 修复：
  - 每个 Turn 为 `claude.exe` 创建独立 Windows Job Object（`KILL_ON_JOB_CLOSE`）；
  - 取消时先调度 async 取消（确保状态记为 `canceled`），再关闭 Job 并 `taskkill /PID <cli_pid> /T /F`；
  - 修复取消与事件循环关闭的竞态（曾返回 500、误记为 `failed/sdk_no_result`）。
- 复测：取消返回 200；Turn=`canceled`；`sleepy.py` 进程消失；同一 Session 后续消息成功。
- 回归：`pytest backend/tests -q` → 46 passed（含 Windows Job Object / taskkill 清理测试）；完整取消路径目前仍以真实 SDK 验证为准。

### T6（2026-11-24）

- 发起一个等待审批的 Turn，记录 CLI PID，直接强杀后端进程。
- 强杀后：后端与 CLI PID 均消失（Job Object 兜底）。
- 重启后：`reconciled_turns=1`；Turn=`interrupted`（`service_restart`）；审批=`expired`；Session `active_turn=null`；同一 Session 新消息成功。

### T7 真实 UI 审批（2026-11-24）

独立数据目录 `artifacts/m0-ui/data`、端口 8041、`IRIS_APPROVAL_TIMEOUT_SECONDS=8`；无头 Edge + CDP 驱动真实 `/coding/<session>` 页面。

- **允许一次**：`Write` 创建 `approval_allow.txt`；点击「允许一次」后审批 `allowed / allow / user`，Turn succeeded，文件内容 `ALLOW_OK`。
- **拒绝**：`Write` 创建 `approval_deny.txt`；点击「拒绝」后审批 `denied / deny / user`，Turn succeeded，文件不存在。
- **总是允许**：`PowerShell` 执行 `python -c "print('ALWAYS_OK')"`；点击「总是允许」后审批 `allowed / always / user`，写入规则 `PowerShell prefix=python`，卡片显示「已允许（已在本次会话记住规则）」。
- **规则复用**：同一 Session 第二条 `python -c "print('ALWAYS_SECOND')"` 自动放行；审批 `allowed / always / auto`，输出 `ALWAYS_SECOND`，无需点击。
- **超时**：新 Session 的 `python -c "import time; time.sleep(1)"` 卡片渲染后不操作；8 秒后审批 `expired / deny / timeout`，Turn 成功返回“审批请求超时，工具未执行”。
- 证据：`artifacts/m0-ui/approval_ui_results.json`、`timeout_ui_results.json`、`ui-approvals-card*.png`、`ui-timeout-card*.png`（gitignored）。
- **边界发现**：`Start-Sleep`、`echo SAFE_MARK`、`Get-Date` 在全新 Session 中未产生审批记录，直接执行；Turn 事件里仍有对应的 `tool.use` / `tool.result`，但没有 `turn_approvals` 记录。原因是 Claude Code 在调用 `can_use_tool` 之前会把部分只读/安全命令视为已允许。因此“逐条审批”只对 CLI 认为需要授权的调用成立，不能承诺所有 PowerShell 调用都会弹卡。若必须强制全部命令审批，需要在 SDK 之上增加 PreToolUse hook 或自管 shell 工具；当前未实施，已记入限制与 ADR 0007。

### T8 运行面板真实 dev server（2026-11-24）

- 工作区详情页运行面板启动 `python -m http.server 8767 --bind 127.0.0.1`，名称 `dev server 8767`。
- 进程 `running`，PID 10756；日志出现 `Serving HTTP on 127.0.0.1 port 8767`；`http://127.0.0.1:8767/` 返回 200；日志文件写入 `data/workspace_processes/<id>.log`。
- 点击「停止」后状态 `stopped`、退出码 1（taskkill 终止）、端口关闭、PID 消失，UI 显示已停止。
- 另建工作区启动 `python -m http.server 8766` 后直接 `DELETE /api/workspaces/{id}`：进程 `stopped`，端口关闭，PID 消失。
- 关闭后端：在另一临时实例中启动 `python -m http.server 8768`，停止 uvicorn 后端口 8768 关闭、PID 消失（lifespan `WorkspaceProcessManager.shutdown`）。
- 证据：`artifacts/m0-ui/runner_ui_results.json`、`runner_delete_results.json`、`shutdown_pre.json`、`shutdown_post.json`、`ui-runner-running.png`、`ui-runner-stopped.png`（gitignored）。

### T9 compact 恢复（2026-11-24）

- 同一 Session 首轮成功，`cli_session_id=01983f99-...`；将数据库中的 `cli_session_id` 改为 `00000000-0000-0000-0000-000000000000`。
- 下一轮以 `resume` 启动，失败：`Claude Code returned an error result: No conversation found with session ID ...`，Turn=`failed`、`error_type=sdk_error`。
- 在网页点击「压缩并继续」：compact 摘要 `succeeded`（1159 字符）；`cli_session_id` 清空。
- 再发消息：Turn succeeded，`mode=new`，manifest `summary_included=true`，回答正确；网页显示新消息与恢复后的会话。
- 证据：`artifacts/m0-ui/compact_ui_results.json`、`compact-queued.png`、`compact-recovered.png`（gitignored）。

### Scholar 本地 prompt-first（2026-11-24，默认）

- Scholar 会话、`research` 档位；默认 `IRIS_SCHOLAR_WEB=0`。
- `system.init.tools` **不含** `WebSearch/WebFetch`；只含 Read/Glob/Grep 等本地工具。
- 回答按 `KNOWN / INFERRED / HYPOTHESIS / UNKNOWN` 标注，包含定义、反例/边界条件、置信度与“什么证据会改变结论”；明确声明为模型知识、未联网核验。
- 成本约 $0.5055；Turn succeeded。
- 证据：`artifacts/scholar-local/results.json`（gitignored）。

### Scholar Web 模式（可选，历史验收 2026-11-24）

- 设置 `IRIS_SCHOLAR_WEB=1` 后，`research` 档位才启用 `WebSearch/WebFetch`。
- 真实触发 `WebSearch` ×6、`WebFetch` ×3（审批允许）；回答含来源 URL，摘要保留 URL。
- 局限：部分官方页面被网络策略拦截（WebFetch 返回 “Unable to verify if domain is safe to fetch”），模型明确说明未直接核验官方原文；来源仍保留。
- 该模式不是默认；见 ADR 0009。

### 真实摘要质量与成本（2026-11-24）

- A1–A4（M2）覆盖决策/理由/未决、artifact+测试、失败+修复、滚动摘要；A1 摘要成本 $0.04124。
- T2/T3 摘要分别保留 README 构建命令与 `m0_t3.txt` + 命令输出。
- **质量观察**：摘要通常为英文（对话为中文）；有时包含路径不确定/git status 等环境噪声，需在 M3/M2 后续评估中收敛。
- 事实提取质量已由 M2 19/19 覆盖（含去重、supersede、冲突、预算）。

## 3. 尚未覆盖

- [x] 真实 UI 中“允许一次 / 总是允许 / 拒绝 / 超时”的完整手工审批流程（T7）。
- [x] 运行面板真实 dev server 的启动、日志、停止与删除工作区清理（T8）；关闭 Iris 时的清理由 `WorkspaceProcessManager.shutdown` 与单测覆盖。
- [x] compact 在真实 resume 失败场景下的恢复（T9）。
- [ ] 所有 PowerShell 调用都强制审批（CLI 对安全只读命令会提前放行，见 T7 边界）。
- [ ] 长期/held-out 记忆样本与成本基线。
- [ ] POSIX 进程树清理（当前 Job Object 为 Windows 方案）。

## 4. 判定规则

M0 通过需要：

1. T1–T9 全部有可复现步骤与记录；
2. 审批全流程与 Scholar 本地 prompt 分析各完成一次真实流程（Web 模式可选）；
3. 发现的阻塞问题（孤儿进程、状态误记、锁未释放）已修复并回验；
4. 失败项有明确原因、影响范围与后续里程碑归属，不能以“偶发”带过。

**结论：M0 通过（2026-11-24）。** T1–T9 全部完成；遗留边界是“CLI 自动放行的安全只读命令不会弹审批卡”，属于能力边界而非回归。若产品要求所有 shell 调用强制审批，应在后续里程碑增加 PreToolUse 强制询问或自管 shell 工具。
