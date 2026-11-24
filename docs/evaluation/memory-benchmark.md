# M2 记忆质量基准：案例集设计（10–20 个）

- 状态：设计稿 v1 + **冒烟 5/5 通过**（2026-11-24）；其余 14 个案例尚未执行
- 目标：验证三层记忆是否真的有用，而不是只看“机制存在”。
- 环境：真实 Claude CLI/SDK、独立 `IRIS_DATA_DIR`（例如 `artifacts/memory-benchmark`）、固定工作区。
- 关联：`docs/roadmap.md` M2、`docs/acceptance/m0-real-cli.md`、ADR 0002/0006。
- 原则：期望用结构化断言（manifest/摘要关键词/事实状态），不要求模型逐字复现。

## 1. 指标

| 维度 | 指标 | 记录方式 |
|---|---|---|
| 摘要保留 | 目标/完成/决策/未决/产出/失败教训覆盖率 | 人工 0–2 分或关键词检查 |
| 摘要可信 | 编造/把假设当事实 | 计数 |
| 事实提取 | 候选准确率、接受率、重复率、update 正确率 | 人工判定 + 数据库状态 |
| 跨 Session 召回 | 有关注入率、无关注入率、别名召回 | manifest `included_facts` |
| 作用域隔离 | workspace/role 泄漏次数 | manifest + 事实 id |
| 冲突/过期 | supersede 正确率、旧事实残留 | `facts.status` / `supersedes_id` |
| 预算 | 注入字符数、被预算排除的事实 | manifest `chars` / `reason=budget` |
| 成本/耗时 | 摘要/提取成本、单案例耗时 | `session_summaries.cost_usd`、日志 |

## 2. 案例集

### A. 摘要保留（4）

| ID | 场景 | 输入/步骤 | 期望 | 检查 |
|---|---|---|---|---|
| A1 | 决策保留 | 讨论“为什么选 FTS5 而不是 embedding”，结束会话生成摘要 | 摘要包含决策、理由、未决问题 | 关键词/人工 0–2 |
| A2 | 产出与路径 | 修改 `README.md`、运行测试、记录结果 | 摘要包含文件路径、测试结果 | 路径/测试关键词 |
| A3 | 失败与教训 | 执行失败命令 → 修复 → 重跑成功 | 摘要同时记录失败与修复 | 失败/修复关键词 |
| A4 | 滚动摘要 | 同一会话 10+ 个终态 Turn，触发自动摘要；再继续 2–3 轮 | 新摘要覆盖新增内容且保留关键决策 | 人工比对上一份摘要 |

### B. 事实提取质量（4）

| ID | 场景 | 输入/步骤 | 期望 | 检查 |
|---|---|---|---|---|
| B1 | 稳定偏好 | 用户说“这个项目统一用 pnpm” | 生成 preference 候选；一次性状态不成为事实 | kind/内容 |
| B2 | 带理由的决策 | “选 SQLite 因为本地单用户、无需运维” | 生成 decision 候选，含理由 | kind/evidence |
| B3 | 假设不当事实 | “也许以后该换 Postgres”（未决定） | 不得生成 accepted fact；最多 open_question | kind/status |
| B4 | 重复/更新 | 已有“构建用 npm”；后来“改用 pnpm” | update 候选命中旧事实；接受后旧事实 archived | `action`/`supersedes_id` |

### C. 跨 Session 召回（5）

| ID | 场景 | 输入/步骤 | 期望 | 检查 |
|---|---|---|---|---|
| C1 | 相关召回 | 接受 workspace 事实“构建用 npm run build”；新 Session 问构建命令 | manifest 命中该事实（matched），`use_count` +1 | manifest/事实 |
| C2 | 无关不注入 | 同一事实；新 Session 问与构建无关的问题 | manifest 不含该事实（除非 pinned） | manifest |
| C3 | 工作区隔离 | 事实属于 workspace A；在 workspace B 新 Session 提问 | 不注入 A 的 workspace 事实 | manifest |
| C4 | 角色隔离 | 事实 role=coding；Scholar 新 Session 提问 | 不注入 coding 事实 | manifest |
| C5 | 别名/改写 | 事实 title“构建命令”，aliases 含“打包”；问“怎么打包” | 命中并注入 | manifest/alias |

### D. 冲突与过期（3）

| ID | 场景 | 输入/步骤 | 期望 | 检查 |
|---|---|---|---|---|
| D1 | supersede | 旧事实“用 webpack”；新决策“用 vite” | update 候选目标旧事实；接受后旧 archived，新注入 | `supersedes_id`/status |
| D2 | 过期信息 | 旧部署地址；新地址被接受 | 旧事实不再注入；manifest 只有新地址 | manifest/status |
| D3 | 矛盾事实 | 两条 accepted 事实给出不同答案 | 至少暴露冲突；不应静默二选一 | 人工/注入清单 |

### E. 预算与手动选择（2）

| ID | 场景 | 输入/步骤 | 期望 | 检查 |
|---|---|---|---|---|
| E1 | 预算裁剪 | 构造超出 4000 字符的多条相关事实 | 只注入预算内事实；其余 `reason=budget` | manifest chars/reason |
| E2 | 手动选择 | 发送时指定 `fact_ids` | `reason=manual`；超预算返回 422 | manifest/API |

### F. 注入透明度（1）

| ID | 场景 | 期望 |
|---|---|---|
| F1 | manifest 审计 | 每个新 Session Turn 的 manifest 能列出 included/excluded 与原因；无静默注入 |

**合计 19 个案例**（可按精力裁剪到 12–15 个）。

## 3. 案例模板

```markdown
### <ID> — <名称>

- 类别：摘要 / 提取 / 召回 / 冲突 / 预算
- 前置：workspace、session、facts、summary 的具体状态
- 操作：发送什么消息 / 何时结束会话 / 何时提取
- 期望：
  - manifest：包含/不包含哪些 fact id，reason 是什么
  - 事实：kind/status/action/supersedes
  - 摘要：必须出现的字段或关键词
- 实际：
  - manifest：
  - 事实状态：
  - 摘要摘录：
  - 成本/耗时：
- 判定：通过 / 部分 / 失败
- 备注：
```

## 4. 执行方式（建议）

1. 每个案例使用独立数据目录，避免事实交叉污染。
2. 先用真实 SDK 跑 5 个“冒烟案例”（A1、B1、B4、C1、C3），确认流程可复现。
3. 再扩展到 15–19 个；记录原始 manifest 与摘要，不只记录主观印象。
4. 结果写入本文件下方表格；必要时另建 `memory-benchmark-results-YYYYMMDD.md`。
5. 用不同 prompt/阈值做对照时，保留 held-out 案例，避免在同一批数据上调参后宣称提升。

## 5. Baseline

- 摘要：`IRIS_SUMMARY_TRIGGER_TURNS=8`、`IRIS_SUMMARY_TRIGGER_CHARS=24000`。
- 事实：手动提取、人工接受、`IRIS_FACT_CONTEXT_MAX_CHARS=4000`。
- 检索：FTS5 + 中文 bigram + 别名 + LIKE 回退，无 embedding。
- 模型：本机 CLI 当前配置（CC Switch/DeepSeek 或用户实际 provider），记录版本。

## 6. 结果记录（待执行）

| ID | 结果 | 关键证据 | 成本 | 备注 |
|---|---|---|---|---|
| A1 | ✅ 通过 | 摘要 3185 字符，含决策/FTS5/向量对比/未决问题 | 摘要 $0.04124 | 见冒烟记录 |
| A2 | 未执行 | | | |
| A3 | 未执行 | | | |
| A4 | 未执行 | | | |
| B1 | ✅ 通过 | 1 条 constraint 候选，含 pnpm/不用 npm | | 见冒烟记录 |
| B2 | 未执行 | | | |
| B3 | 未执行 | | | |
| B4 | ✅ 通过 | update 候选命中旧事实并写 supersedes_id；接受后旧 archived、新 accepted | | 见冒烟记录 |
| C1 | ✅ 通过 | 目标事实 matched，`use_count` 1；同时注入 B4 的 pnpm 事实并暴露冲突 | | 建议干净工作区复跑 |
| C2 | 未执行 | | | |
| C3 | ✅ 通过（修复后） | manifest 为空；修复自动 memory 泄漏后 `memory_paths=null` | | 见冒烟记录 |
| C4 | 未执行 | | | |
| C5 | 未执行 | | | |
| D1 | 未执行 | | | |
| D2 | 未执行 | | | |
| D3 | 未执行 | | | |
| E1 | 未执行 | | | |
| E2 | 未执行 | | | |
| F1 | 未执行 | | | |

## 7. 冒烟执行记录（2026-11-24）

环境：真实 Claude SDK/CLI、独立 `IRIS_DATA_DIR`（`artifacts/m2-smoke`）、两个工作区 A/B；结果保存在 `artifacts/m2-smoke/results.json`（gitignored）。

| 案例 | 结果 | 证据 |
|---|---|---|
| A1 | ✅ | 会话 1 轮 + final 摘要；摘要 3185 字符，明确包含 Decision（FTS5）、两条理由、Open question；cost $0.04124 |
| B1 | ✅ | 1 轮 + 摘要 + 提取；生成 1 条 `constraint` 候选：“Use pnpm, never npm…”；未自动接受 |
| B4 | ✅ | 预置 accepted “构建命令”（npm）；会话改为 pnpm；提取出 2 条候选：update（`supersedes_id` 指向旧事实）+ open_question（迁移范围）；接受 update 后旧事实 `archived`，新事实 `accepted` |
| C1 | ✅ | 新会话问构建命令；目标事实 `reason=matched`，`use_count` 1。因同工作区已有 B4 的 pnpm 事实，manifest 同时注入两条，模型明确指出版本冲突——C1 召回通过，同时观察到 D3 式冲突暴露 |
| C3 | ✅（修复后） | 工作区 B 无事实；manifest 为空。首次运行发现 `system.init.memory_paths` 指向 `D--vibe-Iris` 项目 memory，模型回答了不在 manifest 中的无关记忆；设置 `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` 后重跑，`memory_paths=null`，回答“记忆为空”，无泄漏 |

### 发现

1. **Claude Code 自动 memory 会绕过 Iris manifest**：当工作区位于某个 Git 仓库内时，SDK 会按项目加载 `memory_paths`，模型可看到未注入的事实/笔记。这是 manifest 透明度与隐私问题。
   - 修复：SDK `env` 增加 `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`；Iris 只使用自己的三层记忆。
   - 验证：C3 重跑 `memory_paths=null`，manifest 为空。
2. **冲突暴露是可行的**：C1 同时注入旧 npm 与新 pnpm 两条事实时，模型能指出冲突而不是静默选一个；D3 可继续验证“是否应自动去重/提示用户”。
3. **共享工作区会污染案例**：C1 受 B4 接受事实影响；严格 C1 应在干净工作区复跑。
4. **成本可接受**：A1 摘要 $0.04124；5 个冒烟案例整体成本低（详见 results.json 与 `iris.log`）。

### 复跑建议

- C1 在干净工作区复跑，排除 B4 影响。
- 继续 A2/A3/A4、B2/B3、C2/C4/C5、D1/D2/D3、E1/E2、F1。
- 记录每个案例的 manifest 与事实状态，不只记录回答文本。

## 8. 判定规则

M2 通过的最低条件：

1. C1/C3/C4/C5 的注入结果可由 manifest 复现；
2. B3（假设不当事实）与 B4（更新/归档）无错误；
3. D1（supersede）正确；
4. 摘要 A1/A2 至少保留关键决策与产出路径；
5. 所有失败项有明确原因与改进归属，不以“模型偶发”带过。
