# ADR 0010：Memory 2.0 — 自动候选、人工审核与本地混合检索

- 状态：已采用（2026-11-24）
- 关联：`docs/decisions/0002-context-retrieval.md`、`0006-session-memory.md`、`docs/evaluation/memory-landscape.md`
- 取代：仅手动提取 + 原始 FTS 的 L3 工作流（保留旧数据与 API 兼容）

## 背景

Iris 的三层记忆结构（L1 原始、L2 摘要、L3 人审事实）是对的，但体验和质量有四个缺口：

1. 会话结束后不会主动整理，用户容易忘记提取事实。
2. 中文查询的分词与 FTS 索引不一致，召回退化到 LIKE；改写/同义查询容易漏。
3. 候选去重只做精确标题指纹，近似重复和冲突没有审核界面。
4. 右侧只显示上一轮注入了什么，没有“写之前可能相关什么”、来源、分数和排除原因。

## 决策

### 1. 自动候选，人工接受

- 仅在 `final` 摘要成功后，对本次会话运行一次抽取；`trigger=session_end`。
- 自动抽取只写 `status=candidate`，每会话最多 5 个；开关 `IRIS_MEMORY_AUTO_CAPTURE=session_end|off`。
- 聊天消息旁提供“记住这条”：用户显式点击，视为人工审核；无相似/冲突时可直接 accepted，有相似/冲突时进入收件箱。
- 不做自动接受、自动合并、自动归档或模型自编辑 accepted 事实。

### 2. 收件箱与近似关系

- `/memory` 增加收件箱：候选按重复/冲突/独立分组，显示相似度和目标事实。
- 关系使用确定性文本相似度（标题相似度 + token Jaccard），只做建议；用户选择合并、取代或都保留。
- 合并保留来源/证据/别名/标签；取代保留 `supersedes_id` 与 `superseded_by_id`，不物理删除旧事实。
- 作用域/角色不同的 workspace 事实不互相建议。

### 3. 本地检索 v2

- `facts.search_text` 存储预分词文本（英文词 + 中文重叠 bigram + 别名 + 标签），FTS5 与 `query_terms` 使用同一 tokenizer。
- 候选由 FTS 与 LIKE/别名/标签合并去重，FTS 命中后不再跳过词法候选。
- 排序综合 FTS 位置、标题/别名/标签覆盖、近期确认时间、使用次数、confidence 与 pin。
- 新增 `IRIS_FACT_CONTEXT_MAX_ITEMS`（默认 6）与 `IRIS_FACT_MIN_SCORE`（默认 0.55）；没有足够相关事实时显式 abstain。
- manifest 记录 `score`、`score_parts`、来源与排除原因；右侧展示“可能相关/本次注入/未注入原因”。

### 4. 时间有效性与来源

- `valid_until` 过期事实不注入；收件箱/记忆库显示“需确认”，确认后清空有效期并更新 `last_confirmed_at`。
- 来源：`source_session_ids`（抽取）、`source_turn_id`（聊天记住）、`extraction_id`（候选批次）；不引入图数据库。

### 5. Schema v10

`facts` 新增：`tags_json`、`origin`、`extraction_id`、`source_turn_id`、`valid_until`、`last_confirmed_at`、`superseded_by_id`、`merged_into_id`、`fingerprint`、`search_text`。

`fact_extractions` 新增：`trigger`、`source_session_id`、`source_summary_id`；同一 final summary 只允许一个自动抽取任务。

`facts_fts` 重建为 `fts5(fact_id UNINDEXED, search_text)`；v10 迁移回填 fingerprint/search_text/origin 并重建索引。旧数据不删除。

## 后果

- 用户更容易在会话结束时获得可审核的记忆候选，跨会话召回在真实 UI 中可见（右侧“可能相关”与注入来源）。
- 自动抽取仍会消耗一次模型调用；候选数量有上限，失败不阻塞摘要。
- 关键词/别名/标签检索仍是词法系统；同义改写可能漏。向量检索作为下一阶段的条件性选项，不默认引入。
- 事实去重仍依赖确定性相似度；语义冲突由用户判断。
- 单进程、单用户、本地 SQLite 架构不变。

## 明确不做

- 图数据库、云同步、多用户、团队工作区。
- 自动接受/自动合并/自动归档。
- 从原始对话或网页直接抽取事实（摘要仍是抽取来源）。
- 默认 embedding/向量库。
- 通用后台任务框架；自动抽取复用现有单 worker。
