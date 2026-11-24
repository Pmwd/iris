# M1 最小可观测性验收

- 状态：已实现（2026-11-24）
- 目标：能回答“是否健康、在做什么、花了多少、哪里失败”，并保证指标可对账、不含内容。
- 范围：仅指标层 + 健康/错误 API；**不做** timeseries、rollups、告警、Dashboard。
- 自动化：`pytest backend/tests/test_metrics.py`（3 个测试），全量 46 个后端测试通过。

## 1. API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/metrics/overview?role=&project_id=&range=24h\|7d\|30d` | Turn/成本/工具/记忆/错误/存储总览 |
| GET | `/api/metrics/health` | CLI/DB/活动 Turn/队列状态 |
| GET | `/api/metrics/errors?role=&project_id=&range=&limit=20` | 最近失败（截断错误消息，不含正文） |

实现：`backend/app/services/metrics.py`、`backend/app/api_metrics.py`、`backend/app/services/health.py`。

## 2. 指标范围

**Turn**：总数、活动、stuck、成功/失败/取消/中断、成功率、时长 p50/p95、队列等待 p95、resume 率/失败率、取消率。

**成本**：窗口内总成本、每次成功成本、Top 会话（CLI 报告值）。

**工具**：调用数、拒绝/过期审批数、每次 Turn 调用数、Top 工具。

**记忆**：摘要滞后、摘要失败率、摘要覆盖率、候选事实数、事实接受率、注入率、Top 使用事实、提取成功率。

**错误**：Top error_type、失败 Turn 数；错误列表返回 turn/session/role/project、error_type、截断消息（≤300 字符）。

**存储**：DB（含 WAL/SHM）、原始日志、运行面板日志、备份年龄、磁盘剩余。

## 3. 过滤与范围

- `role=coding|scholar`。
- `project_id`：Turn/Session 按工作区过滤；事实按“全局 + 该工作区”口径。
- `range=24h|7d|30d`；非法值返回 422。
- `active/stuck` 是当前状态，不受 range 限制。

## 4. 隐私

- 指标只返回计数、时长、成本、状态、错误类型；不返回消息、事实正文、prompt、工具输入输出。
- 错误 API 只返回截断后的 error_message（可能含路径）；不返回 result_text/content。
- 成本为 CLI 报告值，不是账单。

## 5. 验收清单

- [x] overview 在空库返回 0/None，不崩溃。
- [x] fake CLI 数据下 Turn 数、成功/失败、成本、工具调用、事实注入、摘要覆盖与 SQL/实际数据一致。
- [x] role/project 过滤正确；非法 range 返回 422。
- [x] health 返回 DB 可写、CLI 探测、活动 Turn、摘要/提取队列。
- [x] errors 返回失败 Turn 且不含正文。
- [x] 不返回消息/事实/工具内容（测试断言字段）。
- [ ] 真实数据下 24h/7d/30d 的人工对账（待真实使用后执行）。
- [ ] timeseries/rollups/告警/Dashboard（M3）。

## 6. 已知限制

- stuck 阈值使用 `IRIS_RUN_TIMEOUT_SECONDS`（默认 1800s）。
- 摘要/提取“队列”用数据库状态近似，无法看到线程池队列长度。
- 工具拒绝数 = 审批 denied/expired + CLI `permission.denied`，口径见实现。
- 事实接受率按窗口内 reviewed/updated 的事实计算；长期接受率需更长时间窗口。
- 成本依赖 CLI 报告；第三方兼容端点可能不准。
- 每次 health 会探测 CLI，最多约 20 秒（两个 10 秒超时）。
