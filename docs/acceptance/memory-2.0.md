# Memory 2.0 验收（R1–R6）

- 目标：验证自动候选、收件箱、聊天记住、中文/混合召回、近似合并、过期确认与 UI 透明度。
- 环境：Windows、真实 Claude Agent SDK、临时 `IRIS_DATA_DIR`、`IRIS_MEMORY_AUTO_CAPTURE=session_end`、`IRIS_SCHOLAR_WEB=0`。
- 数据：`artifacts/memory2-real/results.json`（gitignored）；UI 截图：`related-ui.png`、`inbox-ui.png`。
- 日期：2026-11-24。

## 1. 结果矩阵

| 编号 | 目标 | 结果 |
|---|---|---|
| **R1 会话结束自动候选** | final 摘要后自动抽取，只产候选，带来源 | **通过** |
| **R2 聊天记住 / 跨会话召回** | 记住事实后新会话 manifest 注入并用于回答 | **通过** |
| **R3 中文 / 混合查询 + abstain** | CJK 标题命中；无关查询不注入 | **通过** |
| **R4 近似重复与取代** | 相似候选需审核；取代归档旧事实并设置反向边 | **通过** |
| **R5 过期与确认** | 过期事实不注入；确认后恢复注入 | **通过** |
| **R6 UI 右侧可能相关** | 真实页面显示相关记忆、分数与注入事实 | **通过** |

## 2. 关键证据

### R1 自动候选

- 会话 A 结束后 final 摘要成功；自动抽取 `trigger=session_end`、`status=succeeded`、`candidate_count=1`。
- 候选标题：`构建与包管理统一使用 pnpm，禁用 npm`；`origin=extraction`；`source_session_ids` 指向会话 A。
- 未自动接受：候选初始为 `candidate`。

### R2 跨会话召回

- 接受 R1 候选后，新会话 B 提问“本项目构建应该使用什么包管理器？”。
- manifest `included_facts` 含该事实，`reason=matched`、`score=0.8036`、`score_parts.fts=1.0`，来源会话 ID 保留。
- 回答明确使用 pnpm 并解释不使用的 npm；不是只复述标题。

### R3 中文与 abstain

- 事实“每周全身锻炼 3 次”；查询“这周怎么练全身？”命中，`score=0.645`。
- 无关查询“GIL 是什么？”：`included_facts=[]`，`selection.abstained=true`、`abstain_reason=no_relevant_facts`、`candidate_count=2`、`top_score=0.1601`。
- `/api/memory/related?q=怎么练全身` 返回该事实（score 0.6739），右侧 UI 显示“可能相关 1”。

### R4 近似重复 / 取代

- 已有“部署地址 new.example.com”；记住“部署地址 old.example.com”时返回 `needs_review=true`，关系 `duplicate`，score 0.85。
- 选择“取代”后：旧事实 `status=archived`、`superseded_by_id` 指向新事实；新事实 accepted 且 `supersedes_id` 指向旧事实。

### R5 过期与确认

- 创建 `valid_until=2000-01-01` 的事实；匹配查询的 manifest 中不注入，`excluded_facts` 含 `reason=stale`。
- 调用确认后 `valid_until=null`、`last_confirmed_at` 更新；同一查询再次注入该事实。

### R6 UI

- 无头 Edge 打开真实 Session：右侧“可能相关”显示 pnpm 事实与 81% 分数；本次注入显示 80% 与来源按钮。
- `/memory` 显示收件箱 1 个候选、1 个可能重复；“合并/取代/都保留”按钮可用。

## 3. 自动化与成本

- `pytest backend/tests -q`：**70 passed**（真实 SDK 验收另计）。
- `scripts/memory_eval.py`：16 条确定性查询，recall@5 1.0、precision 1.0、false injection 0、abstain accuracy 1.0、stale injection 0。
- 真实 SDK 本轮 6 个 Turn 合计约 **$0.52**；摘要/自动抽取包含在内。
- 前端 `npm run build` 通过。

## 4. 尚未覆盖

- 多用户/远程、跨设备同步。
- Web 来源型长期事实的质量（默认 Web 关闭）。
- 自动抽取在失败/重试/离线模型下的恢复；当前失败不阻塞摘要，但不自动重试。
- 大规模事实集（数千条以上）的排序/索引性能。
- 人类盲评记忆质量；当前为确定性测试 + 真实 SDK 抽检。
