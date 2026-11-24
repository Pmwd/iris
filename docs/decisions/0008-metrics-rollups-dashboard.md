# ADR 0008：指标 rollups 与系统大盘

- 状态：已实现（2026-11-24）
- 关联：`docs/roadmap.md` M3、`docs/acceptance/m3-dashboard.md`、ADR 0002/0006/0007

## 背景

M1 已提供 overview/health/errors API，但趋势查询仍需扫描 `turns`/`turn_events`；随着原始事件增长，大盘会变慢，且原始日志清理后历史指标会丢失。M2 已用 19 个真实案例确认记忆信号，M3 需要把这些指标与记忆结论可视化。

## 决策

### 1. Schema v9：`metric_rollups`

- 表：`bucket_start`、`bucket_size`（hour/day）、`metric`、`dimensions_json`、`value`、`updated_at`。
- 主键：`(bucket_start, bucket_size, metric, dimensions_json)`。
- 维度：全局、role、project、role+project。
- 指标：Turn 数/状态、成本、工具调用/拒绝。
- 派生数据，可删除重建；旧库非破坏迁移。

### 2. 刷新策略

- `RollupWorker` 启动时 + 每 5 分钟刷新 hour/day。
- `timeseries` 查询时补算当前窗口，避免 worker 未启动/新数据缺失。
- 保留：hour 90 天、day 400 天（当前实现）。

### 3. API 与前端

- `GET /api/metrics/timeseries`：返回桶序列，缺失桶补 0。
- `GET /api/dashboard/overview`：组合 health、KPI、页内告警、最近错误。
- `/dashboard`：KPI、Turn 柱图、成本线图、记忆/工具/存储、过滤（range/role/project）、10 秒轮询。
- 图表使用单序列单色 + 悬停提示 + 数据表；不引入图表库。

### 4. 告警

- 只做页内告警：CLI/DB、stuck Turn、摘要失败、备份过期、磁盘不足、成功率低。
- 不发外部通知；无配置 UI。

## 候选方案

| 方案 | 优点 | 不足 | 结论 |
|---|---|---|---|
| 每次大盘扫描原始表 | 无 schema 改动 | 随事件增长变慢；日志清理后丢失历史 | 未采用 |
| 完整 TSDB（Prometheus 等） | 成熟查询/告警 | 本地单用户过重；部署复杂 | 未采用 |
| 仅内存缓存 | 简单 | 重启丢失；无法回看 | 未采用 |
| rollups 表 + 按需补算（当前） | 轻量、可重建、支持历史 | 需维护维度/桶；派生数据 | **采用** |
| 外部通知/复杂告警 | 主动提醒 | 当前需求不足；易误报 | 暂缓 |

## 后果

- 趋势查询不再扫全表；历史指标在原始事件清理后仍可保留（保留期内）。
- 维度 JSON 让 role/project 过滤无需额外表；代价是查询需精确匹配序列化。
- 记忆/存储趋势仍用窗口聚合；后续可扩展 rollup 指标。
- 告警为页内规则，不是监控系统；需要长期阈值调优。

## 明确不做

- 不引入 Prometheus/Grafana/外部告警。
- 不把消息、事实正文、prompt、工具输入输出写入指标。
- 不做多用户/多进程聚合。
