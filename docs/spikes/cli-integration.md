# Claude Code CLI 集成 Spike

> 日期：2026-10-23  
> 环境：Windows 11、Claude Code 2.1.221、Python 3.12.10（项目 `.venv`）、Node 24.19、Git 2.51  
> 目的：在 Phase 1 前验证本地 CLI 的调用方式、流式输出、权限、取消、恢复和安全边界。  
> 性质：一次性验证，不是产品代码；所有测试都在 `.spike/` 临时工作区执行。

## 1. 结论速览

| 能力 | 结论 | 对 Phase 1 的影响 |
|---|---|---|
| Python 调用 CLI | 可直接调用 `shutil.which("claude")` 返回的 `.CMD` | 不需要额外 shell 包装；需设置 UTF-8 |
| `stream-json` | 可用，但必须加 `--verbose` | 事件解析必须容忍未知类型和 stderr |
| Windows shell 工具 | 是 `PowerShell`，不是 `Bash` | 工具白名单、权限规则都按 `PowerShell` 写 |
| 文件编辑 | `--tools Read,Write,Edit` + `acceptEdits` 可完成 | 编辑档位可行 |
| 命令执行 | `dontAsk` + `PowerShell(命令模式)` 可精确控制 | 执行档位必须用允许/拒绝列表 |
| `acceptEdits` 安全性 | 不能作为 shell 安全边界；简单破坏性命令可能被放行 | 不能只靠 `acceptEdits` |
| 工作区隔离 | Read/PowerShell 文件访问会被限制在 cwd；越界被拒绝 | 每个 run 设置正确 cwd；谨慎使用 `--add-dir` |
| 项目 hooks | 默认会加载并执行 | 默认启用 `--safe-mode`；工作区必须可信 |
| CLAUDE.md | 默认加载，`--safe-mode` 下仍观察到加载 | 视为不可信输入；不能作为安全控制 |
| 取消进程树 | `taskkill /PID <pid> /T /F` 成功清理 3 个进程 | 需要专用 ProcessSupervisor |
| 强杀后恢复 | `--resume <session_id>` 成功恢复并记起上下文 | 可作为首选恢复路径；仍需降级方案 |
| 错误处理 | 非零退出也可能带合法 JSON 错误结果 | 必须同时解析 stdout/stderr 和退出码 |
| 成本字段 | 有 `total_cost_usd`、usage、modelUsage | 显示为 CLI 报告值，不作为账单依据 |

## 2. Windows 调用方式

### 2.1 发现

```text
shutil.which("claude") -> C:\Users\MWD\AppData\Roaming\npm\claude.CMD
```

Python 的 `subprocess.run([cli, "--version"])` 直接执行 `.CMD` 成功：

```text
returncode: 0
stdout: 2.1.221 (Claude Code)
```

不需要 `shell=True`，也不需要 `cmd.exe /c`。用 `cmd.exe /c` 反而在测试中遇到控制台编码问题。

### 2.2 编码与路径

- 需要设置 `PYTHONUTF8=1`、`PYTHONIOENCODING=utf-8`，并以 `encoding="utf-8", errors="replace"` 读取子进程输出。
- 否则在 GBK 控制台打印 PowerShell/hook 输出时可能抛 `UnicodeEncodeError`。
- 已测试 cwd 含空格和中文：`D:\vibe\Iris\.spike\空 格 test` 正常工作。
- 已测试中文提示词：返回 `中文空格正常`。
- 路径和提示词中的引号、换行、超长文本尚未系统测试；Phase 1 应优先通过 stdin 传递 prompt，避免 Windows 命令行长度和转义问题。

## 3. `stream-json` 事件

### 3.1 必须加 `--verbose`

不带 `--verbose` 时：

```text
Error: When using --print, --output-format=stream-json requires --verbose
returncode: 1
```

加上后正常输出 JSONL。

### 3.2 观察到的事件类型

```text
system   subtype=init
system   subtype=thinking_tokens
assistant                # thinking / text / tool_use 内容块
user                     # tool_result
result   subtype=success / error
```

`system/init` 包含：

- `session_id`
- `cwd`
- `model`
- `permissionMode`
- `tools`
- `skills`
- `plugins`
- `mcp_servers`

`result` 包含：

- `is_error`
- `subtype`
- `result`
- `session_id`
- `num_turns`
- `total_cost_usd`
- `usage`
- `modelUsage`
- `permission_denials`
- `terminal_reason`
- `api_error_status`

### 3.3 解析注意

- 一次简单运行也可能产生大量 `system/thinking_tokens` 事件（测试中一个长命令场景有 118 行）。Phase 1 应过滤或聚合这类事件，不要全部推给 UI。
- `assistant` 消息可能分多个事件到达，包含 thinking、text 和 tool_use。
- 工具结果在 `user` 事件中。
- 必须容忍未知事件类型、空行、非 JSON stderr 和未来版本新增字段。
- 不应假设 `result.subtype == "success"` 就代表业务成功；还要检查 `is_error`、`terminal_reason` 和退出码。

### 3.4 prompt 必须通过 stdin

Phase 1 第一次真实任务失败，暴露了一个 Windows 特有问题：

- 把包含多行内容的 prompt 作为 `claude.CMD` 的命令行参数传入时，CLI 可能丢失任务内容或后续参数。
- 失败运行输出的是普通文本而不是 JSONL，解析器只能记录 12 个 `cli.unparsed` 事件，最终被标记为 `cli_no_result`。
- 同样的 prompt 改为写入 stdin 后，CLI 正确看到任务并开始使用工具。

因此 Phase 1 的调用约定是：

```text
claude -p --output-format stream-json --verbose ...
```

不把 prompt 放在 `-p` 后作为位置参数；由 `ProcessSupervisor` 写入 stdin 并关闭。

单行短 prompt 作为参数通常可用，但不应依赖这一行为。该问题很可能与 npm 的 `.cmd` 包装和 Windows 命令行解析有关。

## 4. 工具与权限

### 4.1 工具名称

这个 Windows CLI 的 shell 工具名是 `PowerShell`，不是 `Bash`。

```text
--tools "Read,Bash"       -> init.tools = ['Read']          # Bash 不存在
--tools "Read,PowerShell" -> init.tools = ['PowerShell', 'Read']
```

默认工具集还包含 `Task`、`CronCreate/Delete/List`、`Workflow`、`WebFetch`、`WebSearch`、`DesignSync` 等。Phase 1 必须用 `--tools` 收敛到最小集合，否则 Agent 可能获得超出任务需要的调度、网络或协作能力。

### 4.2 已验证的权限行为

| 配置 | 结果 |
|---|---|
| `--tools Read,Write,Edit` + `acceptEdits` | 成功创建文件 |
| `--tools Read,PowerShell` + `acceptEdits` | `Write-Output` 成功；简单 `Remove-Item temp_delete.txt` 也成功；部分复杂命令需要审批而被拒绝 |
| `--tools Read,PowerShell` + `dontAsk` + `--allowedTools "PowerShell(Write-Output *)"` | `Write-Output` 成功；未列出的 `Remove-Item` 被拒绝 |
| `--tools Read,PowerShell` + `--disallowedTools "PowerShell(Remove-Item*)"` | `Remove-Item` 被拒绝 |
| `--tools Read` + `acceptEdits` 读取 cwd 外文件 | 被拒绝 |
| `--tools Read,PowerShell` + PowerShell 读取/写入 cwd 外文件 | 被 CLI 的 session security hook 阻止 |

**重要结论：**

- `acceptEdits` 只适合编辑档位；不要把它当作命令执行的安全边界。
- 执行档位应使用 `--permission-mode dontAsk` + 明确的 `--allowedTools`，并辅以 `--disallowedTools` 阻止危险模式。
- 默认不使用 `--dangerously-skip-permissions`。
- `--permission-mode manual` 在非交互模式下没有可用的审批 UI，部分命令会被直接阻止；不适合作为 MVP 的执行档位，除非后续实现权限桥接。
- `--permission-mode plan` 会把 plan 写入 `~/.claude/plans`（测试中越过了 cwd 限制）。不要把 plan 模式用于不可信工作区。

### 4.3 建议的 Phase 1 权限档位

| 档位 | 工具 | 权限模式 | 适用场景 |
|---|---|---|---|
| 只读 | `Read,Glob,Grep` | `acceptEdits` 或默认 | 分析、回答问题、生成计划 |
| 编辑 | `Read,Glob,Grep,Write,Edit` | `acceptEdits` | 修改文件，不执行命令 |
| 执行/测试 | `Read,Glob,Grep,Write,Edit,PowerShell` | `dontAsk` + 项目级命令白名单 | 运行测试/构建；每次显式授权 |

建议默认只开放只读或编辑档；执行档需要用户显式选择，并在每次运行记录档位和允许的命令模式。后续可评估 Claude Agent SDK 的权限回调，把命令审批接到 Iris UI。

## 5. Hooks、CLAUDE.md 与 safe-mode

### 5.1 项目 hooks 默认生效

在目标工作区创建 `.claude/settings.json`，配置 `PreToolUse` Read hook：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Read",
        "hooks": [
          { "type": "command", "command": "echo PRE_READ > hook_marker.txt" }
        ]
      }
    ]
  }
}
```

运行普通 `claude -p` 后，`hook_marker.txt` 被创建。

这说明项目 hooks 可以在 Agent 工具权限之外执行本地命令，是重要的供应链/提示注入风险。

### 5.2 safe-mode 与 setting sources

| 配置 | Hook 是否执行 | CLAUDE.md 是否影响回答 |
|---|---|---|
| 默认 | 是 | 是 |
| `--safe-mode` | 否 | 测试中仍然是 |
| `--setting-sources user` | 否（项目 hooks 被排除） | 测试中仍然是 |
| `--safe-mode --setting-sources project` | 否 | 测试中仍然是 |

结论：

- `--safe-mode` 可以有效阻止项目 hooks。
- 在这个 CLI 版本中，`CLAUDE.md` 在 safe-mode 下仍被加载。不能把 safe-mode 当作“完全隔离工作区指令”的保证。
- MVP 默认使用 `--safe-mode`；工作区必须由用户显式信任。
- 不应依赖 CLAUDE.md 做权限控制；它只能作为项目说明，且内容应按不可信输入处理。
- `--strict-mcp-config`、插件和用户级 hooks 尚未系统验证；safe-mode 会关闭这些自定义项。

## 6. 取消与恢复

### 6.1 取消

测试方式：

1. 通过 `subprocess.Popen` 启动 `claude -p`。
2. 提示 Agent 执行 `Start-Sleep -Seconds 60`。
3. 看到 `PowerShell` tool_use 后执行：

```text
taskkill /PID <pid> /T /F
```

结果：

```text
SUCCESS: 终止了 PID 17160（11364 的子进程）
SUCCESS: 终止了 PID 11364（7104 的子进程）
SUCCESS: 终止了 PID 7104（15316 的子进程）
```

之后没有匹配该 session/命令的 CLI 或 `Start-Sleep` 孤儿进程。

**设计要求：**

- 不能只 `Popen.terminate()` 父进程；必须终止进程树。
- Phase 1 使用 `taskkill /T /F`；Phase 1.5 已加入 Windows Job Object（pywin32），保证服务异常退出时子进程也被清理。真实后端强杀测试见 `scripts/crash_test.py`。
- 记录 PID、启动时间、session_id 和取消原因，避免 PID 复用导致误杀。
- 应用层仍需超时和启动时状态校正；CLI 被杀不等于数据库状态自动正确。

### 6.2 强杀后恢复

在 `Start-Sleep` 执行期间强杀进程树，然后用同一 `session_id`：

```text
claude -p "What word did I ask you to remember at the start? Reply with only that word." \
  --resume <session_id> --tools "" --output-format json --max-turns 1
```

结果：

```json
{"is_error": false, "subtype": "success", "session_id": "<same-id>", "result": "PINEAPPLE"}
```

结论：这次测试中，强杀后 `--resume` 成功保留了会话上下文。

**仍需注意：**

- 这是一次特定场景的验证，不能保证所有中断点都可恢复。
- 如果 CLI 会话无法恢复，Iris 应创建新 session，并注入结构化 handoff（任务目标、已完成步骤、修改文件、测试结果、未决问题）。
- 恢复后必须避免重复执行有外部副作用的操作；Iris 应让用户确认，或使用幂等的任务步骤。

## 7. 错误行为

| 场景 | 观察 |
|---|---|
| CLI 不存在 | Python `FileNotFoundError` |
| `stream-json` 缺少 `--verbose` | rc=1，stderr 给出明确错误 |
| 非法模型名 | rc=1，stdout 仍为合法 JSON：`is_error=true`, `terminal_reason=api_error`, `api_error_status=400`，`result` 包含错误说明 |
| 工具权限被拒绝 | `result.permission_denials` 记录被拒工具调用；Agent 可能继续尝试其他方式，需要审计 |
| 无效 API key + `--bare` | 当前环境未复现认证失败（代理似乎接受了请求），因此认证失败路径未验证 |

**错误分类建议：**

- `cli_not_found`
- `cli_spawn_failed`
- `cli_auth_failed`
- `cli_nonzero_exit`
- `cli_api_error`（结合 `api_error_status`）
- `cli_malformed_output`
- `permission_denied`
- `canceled`
- `timeout`
- `interrupted`
- `session_resume_failed`

解析器必须同时读取 stdout 和 stderr；不要因为退出码非零就丢弃 stdout 中的 JSON 错误结果。

## 8. 成本、模型与 usage

- `result.total_cost_usd`、`usage` 和 `modelUsage` 均存在。
- 测试环境报告模型为 `deepseek-v4-flash`；非法模型错误显示该端点支持的是环境特定名称。
- 不应硬编码模型名；默认使用 CLI 配置，只有用户明确选择时才传 `--model`。
- `total_cost_usd` 是 CLI 报告值，不能直接当作真实账单；UI 应标注“CLI 报告成本”。
- 可以记录 input/output tokens、cache tokens、duration 和 num_turns，用于后续监控。

## 9. 对 Phase 1 的具体约束

1. 使用 `shutil.which("claude")` 探测 CLI；正确处理 `.CMD`。
2. 子进程环境设置 UTF-8；使用 `encoding="utf-8", errors="replace"`。
3. prompt 通过 stdin 传入，不作为多行命令行参数；使用 `-p`（无位置 prompt）。
4. 新会话使用 `--session-id <uuid>`；恢复使用 `--resume <session_id>`。
5. 流式运行使用 `--output-format stream-json --verbose`。
5. 默认使用 `--safe-mode`，避免项目 hooks/插件/MCP/自定义扩展执行。
6. 使用 `--tools` 限制工具集合；Windows 执行工具名为 `PowerShell`。
7. 只读/编辑/执行分档；执行档使用 `dontAsk` + 白名单/黑名单，并记录审计。
8. 默认 cwd 为项目根目录；不允许任意路径；`--add-dir` 仅在明确授权时使用。
9. 进程监督使用 `taskkill /T /F`，后续升级 Job Object；记录 PID 和 session。
10. 事件解析归一化；过滤 thinking token 噪音；原文保留在原始事件中，UI 只显示关键事件。
11. 失败时同时解析 stdout、stderr 和退出码；保留 `permission_denials` 供审计。
12. 成本显示为 CLI 报告值；同时展示 tokens 和时长。
13. 测试使用可配置的假 CLI（fake CLI）覆盖确定性场景；真实 CLI 只做显式开启的 smoke test。

## 10. 仍未验证 / 后续风险

- 认证失败的真实行为（当前代理环境无法用无效 key 复现）。
- 用户级 hooks、项目级 MCP、插件和 skills 的完整影响；本 spike 只验证了项目 hooks。
- `--safe-mode` 下 CLAUDE.md 仍会加载的行为是否会在其他 CLI 版本变化。
- `--add-dir` 多目录访问和 symlink 越界。
- 超长 prompt 的边界；stdin 传递已在真实任务中验证，但极端长度仍需测试。
- 应用级超时、最大成本、并发运行和工作区锁。
- 真实服务崩溃时 Job Object 已验证能清理 CLI 后代；仍需在其他 Windows 环境和“进程已在另一个 Job 中”的场景复验。
- 不同模型/后端下 `stream-json` 和工具行为是否一致。
- CLI 升级后的字段、工具名和权限语义变化。

## 11. Phase 0 决策

基于以上验证，Phase 0 采用：

- Python 3.12 + 项目 `.venv`。
- 直接调用 `claude.CMD`，不使用 `shell=True`。
- 默认 `--safe-mode`，并限制工具集合。
- 只读 / 编辑 / 执行三档权限；执行档用 `dontAsk` + 允许/拒绝列表，用户显式开启。
- 新会话用 `--session-id`，恢复用 `--resume`；失败时新 session + handoff。
- 取消使用进程树终止；Phase 1.5 引入 Job Object。
- 成本显示为 CLI 报告值。
