import { useState } from "react";
import type { TimeseriesPoint } from "../types";

const WIDTH = 640;
const HEIGHT = 240;
const PAD = { top: 18, right: 14, bottom: 30, left: 54 };

function niceCeiling(value: number): number {
  if (!Number.isFinite(value) || value <= 0) return 1;
  const exponent = Math.floor(Math.log10(value));
  const base = 10 ** exponent;
  const fraction = value / base;
  const ceiling = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
  return ceiling * base;
}

function bucketLabel(value: string, bucket: "hour" | "day"): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const month = date.getMonth() + 1;
  const day = date.getDate();
  if (bucket === "day") return `${month}/${day}`;
  return `${month}/${day} ${String(date.getHours()).padStart(2, "0")}:00`;
}

export function MetricChart({
  title,
  subtitle,
  points,
  bucket,
  mode = "line",
  valueFormat,
}: {
  title: string;
  subtitle?: string;
  points: TimeseriesPoint[];
  bucket: "hour" | "day";
  mode?: "line" | "bar";
  valueFormat: (value: number) => string;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const values = points.map((point) => point.value);
  const maxValue = niceCeiling(Math.max(...values, 0));
  const innerW = WIDTH - PAD.left - PAD.right;
  const innerH = HEIGHT - PAD.top - PAD.bottom;
  const baseline = PAD.top + innerH;
  const barStep = points.length ? innerW / points.length : innerW;
  const lineStep = points.length > 1 ? innerW / (points.length - 1) : innerW;
  const xFor = (index: number) =>
    mode === "bar"
      ? PAD.left + barStep * index + barStep / 2
      : points.length === 1
        ? PAD.left + innerW / 2
        : PAD.left + lineStep * index;
  const yFor = (value: number) => baseline - (value / maxValue) * innerH;
  const barWidth = Math.max(2, barStep * 0.58);
  const labelEvery = Math.max(1, Math.ceil(points.length / 6));

  const linePath = points
    .map(
      (point, index) =>
        `${index === 0 ? "M" : "L"} ${xFor(index).toFixed(2)} ${yFor(
          point.value,
        ).toFixed(2)}`,
    )
    .join(" ");
  const areaPath =
    points.length > 0
      ? `${linePath} L ${xFor(points.length - 1).toFixed(2)} ${baseline} L ${xFor(
          0,
        ).toFixed(2)} ${baseline} Z`
      : "";

  const hoverPoint = hover !== null ? points[hover] : null;
  const hoverX = hover !== null ? xFor(hover) : 0;
  const hoverY = hoverPoint ? yFor(hoverPoint.value) : baseline;

  return (
    <section className="metric-chart panel">
      <div className="metric-chart-head">
        <div>
          <h3>{title}</h3>
          {subtitle ? <p className="hint">{subtitle}</p> : null}
        </div>
        <span className="pill">{points.length} 个桶</span>
      </div>
      {points.length === 0 ? (
        <div className="muted metric-chart-empty">窗口内没有数据。</div>
      ) : (
        <div className="metric-chart-wrap">
          <svg
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            role="img"
            aria-label={title}
            className="metric-chart-svg"
            onMouseLeave={() => setHover(null)}
          >
            {[0, 0.5, 1].map((fraction) => {
              const y = baseline - innerH * fraction;
              return (
                <g key={fraction}>
                  <line
                    x1={PAD.left}
                    x2={WIDTH - PAD.right}
                    y1={y}
                    y2={y}
                    className="chart-grid"
                  />
                  <text x={PAD.left - 8} y={y + 4} className="chart-y-label">
                    {valueFormat(maxValue * fraction)}
                  </text>
                </g>
              );
            })}

            {mode === "bar" ? (
              points.map((point, index) => {
                const y = yFor(point.value);
                const height = Math.max(0, baseline - y);
                return (
                  <rect
                    key={point.bucket_start}
                    x={PAD.left + barStep * index + (barStep - barWidth) / 2}
                    y={y}
                    width={barWidth}
                    height={height}
                    rx={3}
                    className={
                      hover === index ? "chart-bar hover" : "chart-bar"
                    }
                  />
                );
              })
            ) : (
              <g>
                <path d={areaPath} className="chart-area" />
                <path d={linePath} className="chart-line" />
                {points.map((point, index) => (
                  <circle
                    key={point.bucket_start}
                    cx={xFor(index)}
                    cy={yFor(point.value)}
                    r={hover === index ? 4.5 : 2.5}
                    className="chart-dot"
                  />
                ))}
              </g>
            )}

            {hoverPoint ? (
              <line
                x1={hoverX}
                x2={hoverX}
                y1={PAD.top}
                y2={baseline}
                className="chart-crosshair"
              />
            ) : null}

            {points.map((point, index) => (
              <rect
                key={`hit-${point.bucket_start}`}
                x={
                  mode === "bar"
                    ? PAD.left + barStep * index
                    : xFor(index) - lineStep / 2
                }
                y={PAD.top}
                width={mode === "bar" ? barStep : lineStep}
                height={innerH}
                fill="transparent"
                onMouseEnter={() => setHover(index)}
              />
            ))}

            {points.map((point, index) =>
              index % labelEvery === 0 ? (
                <text
                  key={`label-${point.bucket_start}`}
                  x={xFor(index)}
                  y={HEIGHT - 10}
                  textAnchor="middle"
                  className="chart-x-label"
                >
                  {bucketLabel(point.bucket_start, bucket)}
                </text>
              ) : null,
            )}
          </svg>
          {hoverPoint ? (
            <div
              className="chart-tooltip"
              style={{
                left: `${Math.min(92, Math.max(8, (hoverX / WIDTH) * 100))}%`,
                top: `${Math.min(85, Math.max(18, (hoverY / HEIGHT) * 100))}%`,
              }}
            >
              <span>{bucketLabel(hoverPoint.bucket_start, bucket)}</span>
              <strong>{valueFormat(hoverPoint.value)}</strong>
            </div>
          ) : null}
        </div>
      )}
      <details className="chart-table">
        <summary>数据表</summary>
        <table>
          <thead>
            <tr>
              <th>时间桶</th>
              <th>{title}</th>
            </tr>
          </thead>
          <tbody>
            {points.map((point) => (
              <tr key={`row-${point.bucket_start}`}>
                <td>{bucketLabel(point.bucket_start, bucket)}</td>
                <td>{valueFormat(point.value)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  );
}
