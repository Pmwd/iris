# ADR 0009：Scholar 默认本地 prompt-first，Web 可选

- 状态：已实现（2026-11-24）
- 关联：ADR 0003/0004、`backend/app/roles.py`、`backend/app/services/sdk_runner.py`、`backend/app/cli/adapter.py`
- 取代/调整：Scholar `research` 档位默认不再包含 WebSearch/WebFetch

## 背景

Scholar 已证明可以联网研究并保留来源（M0，2026-11-24）。但用户希望先不依赖联网：

- 降低网络/来源不可控带来的成本与不确定性；
- 用 prompt 构造提升“学术分析”质量；
- 仍然走 Claude terminal / Agent SDK，不引入独立研究 Agent。

## 决策

### 1. 默认本地 prompt-first

- 强化 Scholar system prompt：
  - 问题框定、术语/范围/假设；
  - KNOWN / INFERRED / HYPOTHESIS / UNKNOWN 四类认知状态；
  - 证据、反例、替代解释、base rate、相关/因果、时效性；
  - 置信度与“什么会改变结论”；
  - 没有来源时标记为模型知识、未验证；绝不编造 URL/引文/统计。
- 输出：结论先行 + 证据/不确定性 + 开放问题 + 验证步骤。

### 2. Web 默认关闭

- `Settings.scholar_web_enabled` 默认 `False`；环境变量 `IRIS_SCHOLAR_WEB=1` 开启。
- SDK：`_disallowed_tools("research")` 默认禁用 `WebSearch/WebFetch`；开启后放行。
- CLI 回退：`research` 档位工具列表同样默认只含 `Read,Glob,Grep`。
- 角色/档位仍保留 `read_only` + `research`；`research` 语义从“联网”调整为“本地分析，可选 Web”。

### 3. 不引入独立研究 Agent

- 仍由 ClaudeSDKClient/CLI 执行；
- 不恢复旧 `research_jobs` 编排；
- 不做自动抓取/爬虫。

## 候选方案

| 方案 | 优点 | 不足 | 结论 |
|---|---|---|---|
| 继续默认联网 | 来源新鲜 | 网络/来源不可控、成本、隐私 | 暂不默认 |
| 本地 prompt-first（当前） | 可控、快、可解释 | 知识可能过时；无外部证据 | **采用** |
| 独立研究 Agent/编排 | 可自动化 | 复杂、成本、未验证价值 | 暂缓（M4 评估） |
| 本地 RAG/向量库 | 可接私有资料 | 需要资料与索引，当前未到触发条件 | 暂缓 |

## 后果

- 默认 Scholar 不声称搜索过网页；没有来源时明确标注“模型知识/未验证”。
- Web 模式仍可用（`IRIS_SCHOLAR_WEB=1`），历史来源保留验收有效。
- UI 档位由“研究/联网”改为“研究/分析”。
- 需要外部事实核验时，用户应提供材料或显式开启 Web。

## 验证

- 测试：`test_command_builder_flags` / `test_scholar_web_toggle_in_sdk_tools` 覆盖默认禁用与显式启用。
- 真实 SDK：本地 Scholar 会话（research 档位）无 Web 工具，输出结构化分析；Web 模式历史验收保留。
- 全量测试：49 passed。
