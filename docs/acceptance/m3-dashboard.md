# M3 全局系统大盘验收

- 状态：已实现（2026-11-24）
- 目标：一屏回答“是否健康、在做什么、花了多少、哪里失败、记忆是否正常”。
- 范围：rollups + timeseries + `/dashboard` + 页内告警；**不做**外部通知、复杂告警系统。
- 自动化：`pytest backend/tests -q` → 48 passed；`npm run build` 通过。

## 1. 数据与 API

### Schema v9

- 新增 `metric_rollups(bucket_start, bucket_size, metric, dimensions_json, value, updated_at)`，主键 `(bucket_start, bucket_size, metric, dimensions_json)`。
- 派生数据，可随时重建；旧库非破坏迁移。

### 刷新

- `RollupWorker`：启动时 + 每 `IRIS_ROLLUP_INTERVAL_SECONDS`（默认 300s）刷新 hour/day。
- `timeseries` 查询时也会补算当前窗口，避免 worker 未运行或刚写入的数据缺失。
- 维度：`{}`、`{"role":...}`、`{"project_id":...}`、`{"role":...,"project_id":...}`。
- 指标：`turns`、`turns_succeeded/failed/canceled/interrupted`、`cost_usd`、`tool_calls`、`tool_denials`。

### API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/metrics/timeseries?metric=&role=&project_id=&range=24h\|7d\|30d&bucket=hour\|day` | 趋势点（缺失桶补 0） |
| GET | `/api/dashboard/overview?role=&project_id=&range=` | 健康 + KPI + 告警 + 最近错误 |

## 2. 页面

`/dashboard`（侧栏「系统大盘」）：

- 状态条：CLI 版本/认证、DB、活动/stuck Turn、摘要/提取队列、后端。
- KPI：Turn 数、成功率、p95 时长、队列等待 p95、成本、每次成功成本、摘要覆盖率、候选事实。
- 图表：Turn 数柱图、成本线图；单序列、单色、悬停提示、数据表。
- 过滤：24h/7d/30d、角色、工作区；10 秒轮询。
- 记忆：摘要覆盖率/失败率/滞后、事实接受率/注入率、提取成功率、Top 使用事实。
- 工具/错误：Top 工具、最近失败 Turn（可跳到会话）。
- 存储：DB、原始日志、运行面板日志、备份年龄、磁盘剩余。
- 成本最高的会话。

## 3. 告警（页内）

| rule | 条件 | 级别 |
|---|---|---|
| `cli_missing` | CLI 未安装/探测失败 | critical |
| `cli_auth` | CLI 未认证 | critical |
| `db_unwritable` | DB 不可写 | critical |
| `stuck_turns` | 活动 Turn 超过运行超时 | critical |
| `summary_failures` | 摘要失败率 ≥ 50% | warning |
| `backup_stale` | 最近备份 > 7 天 | warning |
| `disk_low` | 磁盘剩余 < 2 GiB | warning |
| `success_rate` | 窗口内 Turn ≥5 且成功率 < 80% | warning |

告警只在页面展示，不发外部通知。

## 4. 隐私

- rollups 只存计数、成本、时长、状态；不含消息、事实正文、prompt、工具输入输出。
- 图表与 KPI 不含内容；最近错误只显示截断后的 `error_message`。
- 成本为 CLI 报告值，不是账单，页面已标注。

## 5. 验收清单

- [x] schema v9 创建与非破坏迁移；`metric_rollups` 可重建。
- [x] hour/day 桶、role/project 过滤；非法 metric/bucket 返回 422。
- [x] 空库/真实数据下 dashboard 不崩溃；真实数据 10 Turn、79 工具调用、$6.38 成本显示正确。
- [x] Turn/成本趋势与 SQL 总量一致；成本 30d/day 合计 6.3807。
- [x] KPI、记忆、工具、存储、最近错误、告警均渲染。
- [x] 单序列图表有悬停提示与数据表；颜色通过 chroma/contrast 校验。
- [x] `npm run build` 通过。
- [ ] 移动端/窄屏手工验收（布局已做响应式，未逐一截图）。
- [ ] 外部通知/告警阈值长期调优。

## 6. 已知限制

- rollups 仅覆盖 Turn/成本/工具/拒绝；记忆与存储趋势仍用窗口聚合。
- 告警规则固定，无配置 UI；不发送外部通知。
- health 会探测 CLI（最长约 20 秒），dashboard 侧缓存 15 秒。
- 大盘每 10 秒轮询；没有 WebSocket/SSE。
- `metric_rollups` 是派生数据；直接删除后会在下次刷新重建。
