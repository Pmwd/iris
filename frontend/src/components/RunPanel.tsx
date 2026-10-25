import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { asRecord, asText, formatCost, formatDuration, formatTime } from "../format";
import type { Run, RunEvent } from "../types";
import { StatusBadge } from "./StatusBadge";

const ACTIVE = new Set(["starting", "running", "canceling"]);

function isActive(status: string): boolean {
  return ACTIVE.has(status);
}

function EventBody({ event }: { event: RunEvent }) {
  const payload = asRecord(event.payload);
  switch (event.kind) {
    case "assistant.text":
      return <div className="event-text">{String(payload.text ?? "")}</div>;
    case "tool.use": {
      const name = String(payload.name ?? "tool");
      return (
        <div>
          <div className="event-tool">🔧 {name}</div>
          <pre className="event-pre">{asText(payload.input)}</pre>
        </div>
      );
    }
    case "tool.result": {
      const isError = Boolean(payload.is_error);
      return (
        <div>
          <div className={`event-tool ${isError ? "event-error" : ""}`}>
            {isError ? "⚠ 工具结果（错误）" : "✓ 工具结果"}
          </div>
          <pre className="event-pre">{asText(payload.content)}</pre>
        </div>
      );
    }
    case "run.result":
      return (
        <div>
          <div className="event-tool">运行结果</div>
          <pre className="event-pre">{String(payload.result ?? "")}</pre>
        </div>
      );
    case "permission.denied":
      return (
        <div>
          <div className="event-tool event-error">
            权限拒绝 · {String(payload.tool_name ?? "tool")}
          </div>
          <pre className="event-pre">{asText(payload.tool_input)}</pre>
        </div>
      );
    case "cli.stderr":
      return (
        <div>
          <div className="event-tool event-error">stderr</div>
          <pre className="event-pre">{asText(payload.lines)}</pre>
        </div>
      );
    case "process.exit":
      return (
        <div className="event-meta">
          进程退出，exit code: {String(payload.exit_code ?? "—")}
        </div>
      );
    case "system.init":
      return (
        <div className="event-meta">
          CLI 初始化 · {String(payload.model ?? "unknown model")} ·{" "}
          {String(payload.cwd ?? "")}
        </div>
      );
    case "cli.unparsed":
      return <pre className="event-pre">{String(payload.text ?? "")}</pre>;
    default:
      return <pre className="event-pre">{asText(event.payload)}</pre>;
  }
}

export function RunPanel({
  run,
  onTerminal,
}: {
  run: Run;
  onTerminal?: () => void;
}) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [status, setStatus] = useState(run.status);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const lastSeq = useRef(0);
  const eventList = useRef<HTMLDivElement | null>(null);
  const terminalNotified = useRef(false);
  const onTerminalRef = useRef(onTerminal);
  onTerminalRef.current = onTerminal;

  const notifyTerminal = () => {
    if (terminalNotified.current) return;
    terminalNotified.current = true;
    onTerminalRef.current?.();
  };

  useEffect(() => {
    setStatus(run.status);
  }, [run.status]);

  useEffect(() => {
    let disposed = false;
    let source: EventSource | null = null;
    terminalNotified.current = false;
    setEvents([]);
    setLoading(true);
    setError(null);
    setStatus(run.status);
    lastSeq.current = 0;

    const append = (incoming: RunEvent[]) => {
      if (!incoming.length) return;
      setEvents((current) => {
        const bySeq = new Map(current.map((event) => [event.seq, event]));
        for (const event of incoming) {
          if (event.seq > lastSeq.current) {
            bySeq.set(event.seq, event);
            lastSeq.current = event.seq;
          }
        }
        return [...bySeq.values()].sort((a, b) => a.seq - b.seq);
      });
    };

    async function boot() {
      try {
        const initial = await api.listEvents(run.id, 0);
        if (disposed) return;
        append(initial);
        setLoading(false);
        if (!isActive(run.status)) return;

        source = new EventSource(api.runStreamUrl(run.id, lastSeq.current));
        source.addEventListener("run_event", (message) => {
          try {
            const event = JSON.parse(
              (message as MessageEvent).data,
            ) as RunEvent;
            append([event]);
          } catch {
            // ignore malformed messages; polling still refreshes status
          }
        });
        source.addEventListener("done", () => {
          source?.close();
          void refreshStatus();
        });
        source.onerror = () => {
          // EventSource reconnects automatically. Polling below is the fallback.
        };
      } catch (err) {
        if (!disposed) {
          setError(err instanceof Error ? err.message : String(err));
          setLoading(false);
        }
      }
    }

    async function refreshStatus() {
      try {
        const latest = await api.getRun(run.id);
        if (disposed) return;
        setStatus(latest.status);
        if (!isActive(latest.status)) {
          source?.close();
          notifyTerminal();
        }
      } catch {
        // transient polling failures are ignored
      }
    }

    void boot();
    const interval = window.setInterval(() => {
      if (!disposed) void refreshStatus();
    }, 1500);

    return () => {
      disposed = true;
      window.clearInterval(interval);
      source?.close();
    };
  }, [run.id]);

  useEffect(() => {
    // Keep the page scroll stable; only the event list should follow new
    // events. scrollIntoView used to push the task heading under the sticky
    // header.
    const element = eventList.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [events.length]);

  return (
    <section className="panel run-panel">
      <div className="panel-heading">
        <div>
          <h3>运行 #{run.attempt_no}</h3>
          <div className="muted">
            {run.permission_profile} · {formatTime(run.started_at ?? run.created_at)} ·{" "}
            {formatDuration(run.started_at, run.ended_at)} · {formatCost(run.cost_usd)}
          </div>
        </div>
        <StatusBadge status={status} />
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {loading && <div className="muted">加载事件…</div>}
      {!loading && events.length === 0 && (
        <div className="muted">暂无事件。</div>
      )}

      <div className="event-list" ref={eventList}>
        {events.map((event) => (
          <article className="event" key={event.seq}>
            <div className="event-head">
              <span className="event-kind">{event.kind}</span>
              <span className="event-time">{formatTime(event.created_at)}</span>
            </div>
            <EventBody event={event} />
            {event.truncated ? (
              <div className="event-meta">此事件已截断。</div>
            ) : null}
          </article>
        ))}
      </div>

      {run.error_message && (
        <div className="alert alert-error">
          {run.error_type ?? "error"}: {run.error_message}
        </div>
      )}
    </section>
  );
}
