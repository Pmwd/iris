# Phase 2 验收记录

> 日期：2026-10-23  
> 范围：上下文检索、预算排序、最小全局/个人上下文。  
> 环境：Windows 11、Python 3.12.10、SQLite FTS5、Claude Code CLI 2.1.221、React/Vite。

## 1. 自动化结果

```text
26 tests passed
```

Phase 2 新增覆盖：

- 真实数据 schema v1 → v2 迁移：增加 `pinned` / `use_count` / `last_used_at`，创建 `global_notes` 和 FTS 表。
- FTS5 检索与 LIKE 回退。
- 中文短词查询的 LIKE 回退。
- 相关 note、置顶 note、全局 note 的推荐与不相关 note 的排除。
- 预算不足时排除大 note，并记录 `budget` 原因。
- 全局 note CRUD 和项目 note 置顶。
- 运行使用 manual 上下文时记录 project/global scope，并更新使用次数。
- 原有 Phase 1/1.5 测试继续通过。

前端：`npm run build` 通过。

## 2. 真实数据迁移

迁移前备份：`data/backups/iris-20261023-043738-941501.db`。

迁移后验证：

```text
user_version = 2
notes columns: ..., pinned, use_count, last_used_at
global_notes: 1 table
FTS: notes_fts, global_notes_fts
counts: projects=1, tasks=2, runs=3, notes=1, global_notes=0
```

原有项目 `Expense CLI` 和 note `CSV export outcome` 保留。

真实任务 B（`Add date range filtering to CSV export`）的上下文预览：

```text
selected: CSV export outcome
scope: project
recommended: true
reason: matched
search_rank: 0
budget_tokens: 4000
estimated_tokens: 393
```

## 3. 浏览器验收

使用临时 Edge + Playwright 驱动真实 UI：

1. 首页显示全局上下文面板。
2. 创建一个置顶的临时全局 note：`Temporary global preference`。
3. 在 `Expense CLI` 创建临时任务，打开运行配置。
4. 上下文预览同时显示：
   - 置顶全局 note，推荐理由“置顶”。
   - 相关项目 note，推荐理由“相关”。
   - 预算 `4000 tokens`，推荐选择预计约 420 tokens。
5. 控制台无错误。
6. 删除临时任务和全局 note；真实数据恢复为 1 个项目、2 个任务、1 条 note、0 条全局 note。

截图：

- `data/browser-shots/30-global-empty.png`
- `data/browser-shots/31-global-created.png`
- `data/browser-shots/32-context-recommendations.png`

## 4. 实现说明

- 项目 note 仍由任务结果审查后接受进入。
- 全局 note 由用户手写并显式接受，不做自动提取。
- FTS5 使用 unicode61 默认分词；查询词过滤停用词。
- 英文匹配额外使用词边界，避免 `to` 命中 `tomato` 这类子串噪声。
- 中文词或 FTS 无结果时回退到 `LIKE`。
- 排序因素：置顶、FTS/关键词相关度、最近更新时间、使用次数。
- 预算：按字符预算近似 token（`chars / 4`），默认 16000 chars / 4000 tokens；实际 prompt 仍由上下文构建器截断。
- 推荐结果会作为默认选择；用户可以在运行前覆盖。
- 运行快照记录 selection mode、推荐 ID、scope、reason、字符数和估算 token。

## 5. 已知限制

- 没有 embedding/RAG，检索是关键词/FTS 语义，不保证概念级召回。
- 中文短词（少于 3 个字符）可能依赖 LIKE，FTS 分词质量有限。
- 预算是字符启发式，不是模型 tokenizer 的精确计数。
- 推荐权重目前是固定规则；需要更多真实任务来调整。
- 全局 note 没有自动过期、敏感度或权限分级；仅本地单用户。
- 尚未用真实 CLI 重跑一个包含全局 note 的任务；全局上下文注入路径与 Phase 1 已验证的同一构建器一致，自动化测试已覆盖 manifest/scope。

## 6. 推荐精确度修复（2026-10-23）

生活场景试点发现：三条不同主题的置顶全局偏好被注入到每个任务，且“本周”等通用词造成旧清单误匹配。

修复：

- pinned 只增加排序分，不再绕过相关性自动注入。
- 自动选择要求本地关键词/中文 bigram 命中；FTS rank 只作为命中后的排序加分。
- 中文查询使用 bigram；过滤数字、通用任务词和功能字 bigram。
- 全局 note 仍可由用户显式选择，不受自动匹配限制。

回归结果：

| 任务 | 修复前注入 | 修复后注入 |
|---|---|---|
| 本周全身训练计划 | 4 条（含水果/阅读偏好） | 1 条：健身偏好 |
| 推荐三本符合偏好的书 | 4 条（含水果/健身偏好） | 1 条：阅读偏好 |
| 六人聚会水果拼盘 | 4 条（含健身/阅读偏好） | 3 条：水果偏好 + 两份相关清单 |

三个修复验证任务都成功，结果保持 `needs_review`，没有自动进入上下文。自动化测试增加到 25 项。

## 7. Aliases 实验（2026-10-23）

- 同一组 10 个控制/改写用例：
  - 无别名：control 5/5，paraphrase 0/5；
  - 有别名：control 5/5，paraphrase 5/5。
- 实现：`aliases_json` schema v3、FTS/本地匹配包含别名、全局 note 和任务结果表单可填写标签。
- 限制：别名是用户维护的替代措辞，不是语义模型；标签过宽会增加误召回。
- 真实 `data/iris.db` 已备份后迁移到 v3，数据保持；现有 note 的 aliases 为空。

## 8. 结论

Phase 2 的核心目标已实现并验证：现有项目上下文能在真实任务中按相关度被推荐，预算可见且可覆盖，全局 note 可以跨项目参与推荐。pinned 修复消除了多领域偏好污染；aliases 实验把改写召回从 0/5 提升到 5/5，但仍需要用户维护标签。下一步观察真实别名维护成本和误召回，再决定是否需要本地 embedding。
