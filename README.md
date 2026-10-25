# Iris

Iris 是一个以个人上下文为核心的本地任务工作台。当前版本完成 Phase 1 核心闭环、Phase 1.5 可靠性加固、Phase 2 上下文检索、Phase 3A Testing 角色切片、Phase 3B Scholar 编排和 Phase 3C Mentor v0：

- 创建项目和任务。
- 通过本地 Claude Code CLI 执行任务。
- 实时查看运行事件，取消运行。
- 中断后识别状态，并支持恢复或新建会话。
- 审查结果，接受为项目 note。
- 后续任务可以预览并注入已接受的上下文。
- Windows Job Object 兜底清理进程树；真实后端强杀后子进程不会残留。
- 数据库在线备份、恢复 CLI、敏感文件提示和运行审计事件。
- SQLite FTS5 关键词检索 + LIKE 回退；按相关度、置顶、最近使用和预算推荐上下文。
- 项目 note 与最小全局 note；置顶、使用次数和推荐理由可见。
- note aliases/tags，用于补充不同措辞。
- 用户可以在运行前覆盖推荐选择，只有接受的 note 会进入上下文。
- Coding / Scholar 两个活动角色：Role 是行为/工具/上下文策略，不是独立 Agent 或记忆库。
- Scholar 受控编排：自动/编辑研究问题，独立子对话并发执行，使用原生 WebSearch/WebFetch，可取消和持久化；子任务失败默认重试 2 次并指数退避；汇总生成研究 note 草稿。
- Mentor v0：只读比较选项、指出盲点并提问，不替用户决定；`goal` / `capability` / `blind_spot` / `progress` / `decision` 带类型的全局 note 是唯一长期状态来源；用户接受 progress/decision 后手动创建阶段任务，再由阶段任务创建跟进 Mentor。
- Testing 角色暂时搁置，新建任务 UI 不再提供；已有 Testing 数据和代码保留。

## 快速启动

要求：Windows、Python 3.12、Node.js 20+、已安装并登录 Claude Code CLI。

```powershell
# 1. 后端依赖
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e "backend[dev]"

# 2. 前端构建
cd frontend
npm install
npm run build
cd ..

# 3. 启动
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000
```

打开 <http://127.0.0.1:8000>。

前端开发模式：

```powershell
# 终端 A
.\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000

# 终端 B
cd frontend
npm run dev
```

Vite 运行在 5173，并将 `/api` 代理到 8000。

## 数据与配置

- 默认数据目录：`./data/`（已 gitignore）。
- 数据库：`data/iris.db`（SQLite WAL，当前 schema v6；启动时自动迁移旧版本）。
- 检索索引：SQLite FTS5，启动时自动建立/重建缺失索引。
- 别名/标签：note 可维护 aliases，用于补充不同措辞；别名进入检索匹配，但不是语义模型。
- 日志：`data/logs/iris.log`（5 MB 轮转，保留 3 份）。
- 备份：`data/backups/`。
- 可用 `IRIS_DATA_DIR` 覆盖数据目录。
- 可用 `IRIS_MAX_TURNS`、`IRIS_RUN_TIMEOUT_SECONDS`、`IRIS_MAX_CONTEXT_CHARS` 调整运行参数。
- 测试用 `IRIS_CLAUDE_COMMAND_JSON` 指定替代 CLI 命令（用于 fake CLI）。
- Iris 不读取、保存或展示 CLI 凭据。

## 权限档位

| 档位 | 工具 | 说明 |
|---|---|---|
| 只读 | `Read,Glob,Grep` | 分析和回答，不修改文件 |
| 编辑 | `Read,Glob,Grep,Write,Edit` | 修改文件，不执行 shell |
| 执行/测试 | 上述工具 + `PowerShell` | 仅允许项目设置中列出的 PowerShell 模式；用户显式选择 |

执行档位使用 `--permission-mode dontAsk` 和允许列表，不使用 `acceptEdits` 作为 shell 安全边界。项目设置中的示例：

```text
PowerShell(python *)
PowerShell(Get-ChildItem *)
PowerShell(Get-Content *)
```

默认使用 `--safe-mode`，阻止项目 hooks、插件、MCP 和自定义扩展。注意：当前 CLI 版本在 safe-mode 下仍可能加载目标仓库的 `CLAUDE.md`，因此工作区必须由用户显式信任。

## 数据维护

```powershell
# 查看备份
.\.venv\Scripts\python.exe -m app.maintenance --data-dir data list
# 创建备份
.\.venv\Scripts\python.exe -m app.maintenance --data-dir data backup
# 恢复（先停止后端）
.\.venv\Scripts\python.exe -m app.maintenance --data-dir data restore data\backups\<file>.db
```

恢复会先生成 `pre-restore-*.db` 安全副本。不要在后端运行时热替换数据库；当前没有在线恢复接口。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
cd frontend
npm run build
```

测试使用确定性的 fake CLI；真实 CLI 验收见 `docs/acceptance/phase1.md`，可靠性验收见 `docs/acceptance/phase1.5.md`，上下文检索验收见 `docs/acceptance/phase2.md`，Testing 角色切片见 `docs/acceptance/phase3a.md`，Scholar 编排原型见 `docs/acceptance/phase3b.md`，Mentor v0 见 `docs/acceptance/phase3c.md`。

真实服务崩溃测试（会启动并强杀独立后端）：

```powershell
.\.venv\Scripts\python.exe scripts\crash_test.py
```

## 当前限制

- 单用户、本地运行，无登录和远程访问。
- 活动角色是 Coding / Scholar / Mentor；Testing 搁置；Personal/Health 未实现。
- Mentor v0 尚无真实 CLI 验收；fake CLI 测试覆盖权限、上下文策略、接受 note 和阶段/跟进闭环。
- Mentor 只读，不会自动创建阶段任务、写入长期 note 或评分能力；长期 `progress` 累积目前只受上下文预算限制。
- 不自建网页搜索/抓取；Scholar 使用原生 WebSearch/WebFetch，Iris 只负责编排。
- Scholar 两轮验证完成：第一轮草稿已接受；第二轮通过 handoff 复用，5/5 子任务成功，第二份草稿也已接受。
- 首轮 Web 研究仍有 3/5 子任务失败；重试/退避已实现，但尚未在真实 Web 任务中触发验证。
- 不做角色专属记忆库、多 Agent、应用扩展、自动记忆提取或向量检索。
- 上下文检索是基于 FTS5/关键词的，不做语义 embedding；别名可补偿已预料的改写，但未知改写仍会漏。
- 全局 note 由用户手写；Mentor 的 typed global note 也只有用户接受后才会被引用；系统不会自动把对话或模型推测提升为全局事实。
- 任务成功后会进入“待审查”；接受 note 后由用户标记完成。
- 后端强杀时 Job Object 会兜底清理 CLI 进程树；如果进程已处于其他 Windows Job 中，可能退化为 `taskkill /T /F`，启动日志会记录附加失败。
- 浏览器手工流程已用本机 Edge + Playwright 完成；该驱动尚未固化为仓库依赖。截图在 `data/browser-shots/`（gitignored）。
- 认证失败、用户级 hooks/MCP、`--add-dir` 和极长 prompt 尚未系统验证。
- 不自动 git 提交、合并、部署或删除文件。
- 任务内容会发送给 CLI 配置的模型后端；本地存储不等于数据不出本机。
- 恢复数据库需要先停止后端；没有在线热恢复。

## 目录

```text
backend/        FastAPI、SQLite、CLI 适配器、运行器、测试
frontend/       React + TypeScript + Vite
docs/           路线图、spike、决策和验收记录
examples/       可复制的示例工作区
scripts/        崩溃恢复等手工可靠性测试
data/           本地运行数据、日志和备份（gitignored）
```
