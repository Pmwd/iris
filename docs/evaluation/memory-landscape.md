# 主流 Agent 记忆方案调研与 Iris 取舍

> 目的：为 Iris Memory 2.0 提供设计依据；不是供应商评测。
> 日期：2026-11-24。实现决策见 `docs/decisions/0010-memory-2.md`。

## 1. 方案对比

| 方案 | 主要存什么 | 写入 / 整理 | 检索 | 时间与冲突 | 用户控制 |
|---|---|---|---|---|---|
| **Mem0** | 原子事实 + 向量；可选实体图 | LLM 从对话/摘要抽取，比较候选后 add/update/delete；后续版本改为追加 + 读取时冲突处理 | 向量 top-k + 作用域过滤 + 混合排序 | 有创建时间；后加时间端点；历史上倾向覆盖/删除 | API 增删查；user/agent/run 作用域 |
| **Zep / Graphiti** | episode（原始事件）+ 实体 + 事实边 | 增量抽取实体/事实；新事实使旧事实失效 | 向量 + BM25 + 图遍历，RRF/MMR 融合 | **bi-temporal**：`valid_at/invalid_at/created_at`，旧事实保留 | 主要面向开发者/平台；终用户编辑有限 |
| **Letta / MemGPT** | core memory 块 + recall + archival | Agent 通过工具自编辑；可后台整理 | 常驻块 + 显式搜索归档 | 消息时间戳；无正式有效期模型 | 开发者定义块与上限；模型自主性高 |
| **LangMem / LangGraph** | semantic facts / episodic / procedural | 热路径工具或后台 manager 提议增删改 | 向量 + namespace | 时间戳；无 bi-temporal | 开发者配置；无终端审核 UI |
| **ChatGPT** | 保存的记忆 + 从聊天历史合成的引用 | 显式“记住”或后台合成 | 模型注入，用户不可见排序 | 以新替旧；删除聊天不必然删除记忆 | 查看/编辑/删除、开关、临时聊天、项目隔离 |
| **Claude** | 用户级 / 项目级记忆合成 | 自动学习；opt-in；可导入导出 | 注入上下文；项目隔离 | 随时间更新；Incognito 不保存 | 查看/编辑/删除、开关、项目隔离、组织禁用 |
| **Cursor / Claude Code** | 规则文件（`.cursor/rules`、`CLAUDE.md`、`AGENTS.md`）；Claude Code 自动 memory | 人工编写；也有自动 memory | 规则按作用域加载 | 无有效期，git 历史是审计 | 文件可 diff、可版本化；自动 memory 信任成本高 |
| **Iris 现状** | L1 消息/事件/JSONL；L2 摘要；L3 人工审核事实 | 摘要自动；事实手动提取 | FTS5 + 别名 + 中文 bigram | `supersedes_id` + archived；无有效期 | 人审、pin、作用域、manifest 可追溯 |

## 2. 可复用的经验

1. **写路径噪声决定记忆质量。** LLM 抽取会产出过细、无上下文或错误的事实；自动接受会把噪声长期带入上下文。Iris 保留“候选必须人审”，但需要降低审核摩擦。
2. **过期/更新比“记住更多”更难。** 主流方案逐渐引入时间有效性或失效边；Iris 已有 supersede，可补 `valid_until` 与“仍然有效”确认，不引入图数据库。
3. **精确标题去重不够。** 同义改写会积累重复事实；需要近似重复提示与显式合并/取代，而不是静默覆盖。
4. **检索不是越多越好。** 过度注入会挤占任务上下文；应有阈值、条数上限、预算与 abstention。
5. **作用域隔离是共同底线。** 项目/工作区/角色隔离在 ChatGPT、Claude、LangMem、Mem0 中都存在；Iris 继续保持。
6. **用户可见的控制比自动性更重要。** ChatGPT/Claude 提供了查看、编辑、删除、开关；Iris 的记忆库、manifest 和审核流程是优势，但需要把入口放进聊天。
7. **不要照搬 benchmark 数字。** 供应商 benchmark 的数据集、judge、token 预算和答案模型不同；LoCoMo/LongMemEval 等也受到 judge 宽松和样本偏差批评。Iris 使用自己的小型确定性集 + 真实 SDK 验收。

## 3. 对 Iris 的设计映射

| 主流思路 | Iris 采用 | 不采用 |
|---|---|---|
| 自动抽取 | **会话结束自动生成候选**，进入收件箱；不自动接受 | 每轮自动抽取、自动接受 |
| 显式“记住” | 聊天消息旁“记住这条”，预填来源 | 让模型自编辑 accepted 事实 |
| 近似重复/冲突 | 确定性相似度 + 人工合并/取代/都保留 | 自动合并、图数据库 |
| 时间有效性 | `valid_until` + `last_confirmed_at`；过期不注入 | bi-temporal 图 |
| 混合检索 | 预分词 FTS（英文词 + 中文 bigram）、别名/标签、近期/使用/置信度、RRF 风格排序、阈值/abstain | 本轮引入 embedding/向量库 |
| 用户可见 | 右侧“可能相关”、注入原因/分数/来源、收件箱、搜索 | 黑盒隐式记忆 |
| 来源审计 | `source_session_ids`、`source_turn_id`、`extraction_id`、JSONL | 只存摘要不存来源 |

## 4. 为什么本轮不做向量检索

- 短事实的标题、别名、标签信号强；本轮先修中文 FTS 分词错位和排序/阈值，成本低、可解释、无模型下载。
- 本地向量检索需要固定 embedding 模型、维度、归一化、数据库迁移与重建；在 Windows 单用户环境中增加维护面。
- 采用条件：`scripts/memory_eval.py` 的改写/同义召回仍明显不足（例如 recall@5 低于 0.7 且错误集中在 paraphrase），再评估 `fastembed` + `sqlite-vec` 或 BLOB 余弦。

## 5. 主要来源

- Mem0: <https://arxiv.org/abs/2504.19413>；<https://github.com/mem0ai/mem0>
- Zep / Graphiti: <https://arxiv.org/abs/2501.13956>；<https://help.getzep.com/facts>；<https://github.com/getzep/graphiti>
- MemGPT / Letta: <https://arxiv.org/abs/2310.08560>；<https://docs.letta.com/>
- LangMem: <https://www.langchain.com/blog/langmem-sdk-launch>；<https://langchain-ai.github.io/langmem/>
- ChatGPT memory: <https://openai.com/index/memory-and-new-controls-for-chatgpt/>；<https://help.openai.com/en/articles/8590148-memory-faq>
- Anthropic Claude memory: <https://www.anthropic.com/news/memory>
- Claude Code memory: <https://code.claude.com/docs/en/memory>
- SQLite FTS5: <https://sqlite.org/fts5.html>
- sqlite-vec: <https://github.com/asg017/sqlite-vec>
- fastembed: <https://github.com/qdrant/fastembed>
- LongMemEval: <https://arxiv.org/abs/2410.10813>
- LoCoMo: <https://arxiv.org/abs/2402.17753>
