import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { MetricChart } from "../components/MetricChart";
import {
  errorText,
  formatAge,
  formatBytes,
  formatCost,
  formatPercent,
  formatSeconds,
  formatTime,
} from "../format";
import { sessionPath } from "../labels";
import type {
  DashboardOverviewResponse,
  MetricTimeseries,
  RoleId,
  Workspace,
} from "../types";

const RANGES = [
  { value: "24h", label: "24 小时" },
  { value: "7d", label: "7 天" },
  { value: "30d", label: "30 天" },
];

const ALERT_TEXT: Record<string, string> = {
  cli_missing: "Claude CLI 未安装或无法探测。",
  cli_auth: "Claude CLI 未认证。",
  db_unwritable: "数据库不可写。",
  stuck_turns: "有活动 Turn 超过运行超时。",
  summary_failures: "最近一半以上的摘要失败。",
  backup_stale: "最近备份已超过 7 天。",
  disk_low: "磁盘剩余不足 2 GiB。",
  success_rate: "窗口内 Turn 成功率低于 80%。",
};

function formatCostShort(value: number): string {
  return `$${value.toFixed(2)}`;
}

export function DashboardPage() {
  const [range, setRange] = useState("24h");
  const [role, setRole] = useState<"" | RoleId>("");
  const [projectId, setProjectId] = useState("");
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [overview, setOverview] = useState<DashboardOverviewResponse | null>(
    null,
  );
  const [turnsSeries, setTurnsSeries] = useState<MetricTimeseries | null>(null);
  const [costSeries, setCostSeries] = useState<MetricTimeseries | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    void api
      .listWorkspaces()
      .then(setWorkspaces)
      .catch(() => setWorkspaces([]));
  }, []);

  useEffect(() => {
    let cancelled = false;
    const bucket = range === "30d" ? "day" : "hour";
    const params = {
      range,
      role: role || undefined,
      project_id: projectId || undefined,
    };

    async function load() {
      try {
        const [data, turns, cost] = await Promise.all([
          api.getDashboardOverview(params),
          api.getMetricTimeseries({ metric: "turns", bucket, ...params }),
          api.getMetricTimeseries({ metric: "cost_usd", bucket, ...params }),
        ]);
        if (cancelled) return;
        setOverview(data);
        setTurnsSeries(turns);
        setCostSeries(cost);
        setError(null);
      } catch (err) {
        if (!cancelled) setError(errorText(err));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    const timer = window.setInterval(() => void load(), 10_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [range, role, projectId, refreshKey]);

  const data = overview?.overview;
  const health = overview?.health;
  const turns = data?.turns;
  const cost = data?.cost;
  const memory = data?.memory;
  const tools = data?.tools;
  const storage = data?.storage;

  const kpis = data
    ? [
        {
          label: "Turn 数",
          value: String(turns?.total ?? 0),
          hint: `${turns?.active ?? 0} 活动 · ${turns?.stuck ?? 0} stuck`,
        },
        {
          label: "成功率",
          value: formatPercent(turns?.success_rate ?? null),
          hint: `${turns?.failed ?? 0} 失败 · ${turns?.canceled ?? 0} 取消`,
        },
        {
          label: "p95 时长",
          value: formatSeconds(turns?.duration_p95_seconds ?? null),
          hint: `p50 ${formatSeconds(turns?.duration_p50_seconds ?? null)}`,
        },
        {
          label: "队列等待 p95",
          value: formatSeconds(turns?.queue_wait_p95_seconds ?? null),
          hint: `resume 率 ${formatPercent(turns?.resume_rate ?? null)}`,
        },
        {
          label: "成本",
          value: formatCost(cost?.total_usd),
          hint: "CLI 报告值",
        },
        {
          label: "每次成功成本",
          value: formatCost(cost?.per_success_usd ?? null),
          hint: `${cost?.by_session?.length ?? 0} 个会话`,
        },
        {
          label: "摘要覆盖率",
          value: formatPercent(memory?.summary_coverage ?? null),
          hint: `滞后 ${memory?.summary_lag ?? 0} Turn`,
        },
        {
          label: "候选事实",
          value: String(memory?.fact_candidates_pending ?? 0),
          hint: `接受率 ${formatPercent(memory?.fact_accept_rate ?? null)}`,
        },
      ]
    : [];

  return (
    <div className="page dashboard-page">
      <header className="page-header dashboard-header">
        <div>
          <div className="eyebrow">SYSTEM</div>
          <h1>系统大盘</h1>
          <div className="muted">
            健康、活动、成本、记忆与存储 ·{" "}
            {overview ? `更新于 ${formatTime(overview.generated_at)}` : "加载中…"}
          </div>
        </div>
        <div className="dashboard-filters">
          <select
            value={range}
            onChange={(event) => setRange(event.target.value)}
            aria-label="时间范围"
          >
            {RANGES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
          <select
            value={role}
            onChange={(event) => setRole(event.target.value as "" | RoleId)}
            aria-label="角色"
          >
            <option value="">全部角色</option>
            <option value="coding">Coding</option>
            <option value="scholar">Scholar</option>
          </select>
          <select
            value={projectId}
            onChange={(event) => setProjectId(event.target.value)}
            aria-label="工作区"
          >
            <option value="">全部工作区</option>
            {workspaces.map((workspace) => (
              <option key={workspace.id} value={workspace.id}>
                {workspace.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="button ghost"
            onClick={() => setRefreshKey((key) => key + 1)}
            disabled={loading}
          >
            刷新
          </button>
        </div>
      </header>

      {error ? <div className="alert alert-error">{error}</div> : null}

      {overview?.alerts?.length ? (
        <section className="dashboard-alerts">
          {overview.alerts.map((alert) => (
            <div
              key={`${alert.rule}-${alert.message}`}
              className={`dashboard-alert level-${alert.level}`}
            >
              <strong>{alert.level === "critical" ? "严重" : "警告"}</strong>
              <span>{ALERT_TEXT[alert.rule] ?? alert.message}</span>
              <span className="pill">{alert.rule}</span>
            </div>
          ))}
        </section>
      ) : null}

      {health ? (
        <section className="dashboard-status">
          <span
            className={`badge badge-${
              health.status === "ok" ? "succeeded" : "failed"
            }`}
          >
            {health.status}
          </span>
          <span>
            CLI {health.cli.installed ? health.cli.version ?? "已安装" : "未安装"}
            {health.cli.auth_ok === false ? " · 未认证" : ""}
          </span>
          <span>DB {health.db_ok ? "可写" : "不可写"}</span>
          <span>
            活动 {health.turns.active} · stuck {health.turns.stuck}
          </span>
          <span>
            摘要队列 {health.queues.summaries_pending}/
            {health.queues.summaries_running} · 提取{" "}
            {health.queues.extractions_running}
          </span>
          <span className="mono muted">{health.execution_backend}</span>
        </section>
      ) : null}

      {data ? (
        <>
          <section className="kpi-grid">
            {kpis.map((kpi) => (
              <div className="kpi-card" key={kpi.label}>
                <span className="kpi-label">{kpi.label}</span>
                <strong className="kpi-value">{kpi.value}</strong>
                <span className="kpi-hint">{kpi.hint}</span>
              </div>
            ))}
          </section>

          <div className="dashboard-charts">
            <MetricChart
              title="Turn 趋势"
              subtitle="窗口内每个时间桶的 Turn 数"
              points={turnsSeries?.points ?? []}
              bucket={turnsSeries?.bucket ?? "hour"}
              mode="bar"
              valueFormat={(value) => String(Math.round(value))}
            />
            <MetricChart
              title="成本趋势"
              subtitle="CLI 报告成本（USD），不是账单"
              points={costSeries?.points ?? []}
              bucket={costSeries?.bucket ?? "hour"}
              mode="line"
              valueFormat={formatCostShort}
            />
          </div>

          <div className="dashboard-columns">
            <section className="panel">
              <div className="panel-heading">
                <h2>记忆</h2>
                <Link className="chip" to="/memory">
                  记忆库
                </Link>
              </div>
              <div className="status-list">
                <div className="status-row">
                  <span>摘要覆盖率</span>
                  <span>{formatPercent(memory?.summary_coverage ?? null)}</span>
                </div>
                <div className="status-row">
                  <span>摘要失败率</span>
                  <span>{formatPercent(memory?.summary_failure_rate ?? null)}</span>
                </div>
                <div className="status-row">
                  <span>摘要滞后</span>
                  <span>{memory?.summary_lag ?? 0} Turn</span>
                </div>
                <div className="status-row">
                  <span>事实接受率</span>
                  <span>{formatPercent(memory?.fact_accept_rate ?? null)}</span>
                </div>
                <div className="status-row">
                  <span>事实注入率</span>
                  <span>{formatPercent(memory?.fact_injection_rate ?? null)}</span>
                </div>
                <div className="status-row">
                  <span>提取成功率</span>
                  <span>
                    {formatPercent(memory?.extraction_success_rate ?? null)}
                  </span>
                </div>
              </div>
              <h3 className="dashboard-subhead">Top 使用事实</h3>
              {memory?.fact_use_top?.length ? (
                <ul className="dashboard-list">
                  {memory.fact_use_top.slice(0, 5).map((fact) => (
                    <li key={fact.id}>
                      <span>{fact.title}</span>
                      <span className="muted">
                        {fact.use_count} 次 · {fact.scope}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">暂无使用记录。</p>
              )}
            </section>

            <section className="panel">
              <div className="panel-heading">
                <h2>工具与错误</h2>
                <span className="pill">
                  {tools?.calls ?? 0} 调用 · {tools?.denials ?? 0} 拒绝
                </span>
              </div>
              {tools?.top?.length ? (
                <ul className="dashboard-list">
                  {tools.top.map((item) => (
                    <li key={item.name}>
                      <span>{item.name}</span>
                      <span className="muted">{item.calls} 次</span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">窗口内没有工具调用。</p>
              )}
              <h3 className="dashboard-subhead">最近错误</h3>
              {overview?.recent_errors?.length ? (
                <ul className="dashboard-errors">
                  {overview.recent_errors.map((item) => (
                    <li key={item.turn_id}>
                      <Link
                        to={sessionPath(item.role, item.session_id)}
                        className="mono"
                      >
                        {item.error_type}
                      </Link>
                      <span className="muted">
                        {formatTime(item.created_at)} · {item.error_message}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">窗口内没有失败 Turn。</p>
              )}
            </section>
          </div>

          <div className="dashboard-columns">
            <section className="panel">
              <div className="panel-heading">
                <h2>存储</h2>
              </div>
              <div className="status-list">
                <div className="status-row">
                  <span>数据库</span>
                  <span>{formatBytes(storage?.db_bytes)}</span>
                </div>
                <div className="status-row">
                  <span>原始日志</span>
                  <span>{formatBytes(storage?.raw_log_bytes)}</span>
                </div>
                <div className="status-row">
                  <span>运行面板日志</span>
                  <span>{formatBytes(storage?.workspace_log_bytes)}</span>
                </div>
                <div className="status-row">
                  <span>最近备份</span>
                  <span>{formatAge(storage?.backup_age_seconds)} 前</span>
                </div>
                <div className="status-row">
                  <span>磁盘剩余</span>
                  <span>{formatBytes(storage?.disk_free_bytes)}</span>
                </div>
              </div>
            </section>

            <section className="panel">
              <div className="panel-heading">
                <h2>成本最高的会话</h2>
              </div>
              {cost?.by_session?.length ? (
                <ul className="dashboard-list">
                  {cost.by_session.map((item) => (
                    <li key={item.session_id}>
                      <span>{item.title}</span>
                      <span className="muted">
                        {formatCost(item.cost_usd)} · {item.turns} Turn
                      </span>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="muted">窗口内没有成本记录。</p>
              )}
            </section>
          </div>
        </>
      ) : loading ? (
        <div className="muted">加载大盘…</div>
      ) : null}
    </div>
  );
}
