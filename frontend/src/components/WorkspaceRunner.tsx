import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { errorText, formatTime } from "../format";
import { PROCESS_STATUS_LABELS } from "../labels";
import type { ManagedProcess, ProcessLogs } from "../types";

const PRESETS = [
  { label: "npm run dev", command: "npm run dev" },
  { label: "npm start", command: "npm start" },
  { label: "python http.server", command: "python -m http.server 8000" },
];

const ACTIVE = new Set(["starting", "running", "stopping"]);
const MAX_LOG_LINES = 2000;

function isActive(process: ManagedProcess): boolean {
  return ACTIVE.has(process.status);
}

export function WorkspaceRunner({
  workspaceId,
  archived = false,
}: {
  workspaceId: string;
  archived?: boolean;
}) {
  const [processes, setProcesses] = useState<ManagedProcess[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selected, setSelected] = useState<ManagedProcess | null>(null);
  const [lines, setLines] = useState<Array<{ seq: number; text: string }>>([]);
  const [command, setCommand] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [stoppingId, setStoppingId] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const lastSeq = useRef(0);
  const logRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    async function load() {
      try {
        const items = await api.listProcesses(workspaceId);
        if (cancelled) return;
        setProcesses(items);
        setSelectedId((previous) => {
          if (previous && items.some((item) => item.id === previous)) {
            return previous;
          }
          return items[0]?.id ?? null;
        });
      } catch {
        // Transient polling failures are not worth a banner.
      }
    }

    void load();
    timer = window.setInterval(load, 2000);
    return () => {
      cancelled = true;
      if (timer) window.clearInterval(timer);
    };
  }, [workspaceId]);

  useEffect(() => {
    if (!selectedId) {
      setLines([]);
      setSelected(null);
      lastSeq.current = 0;
      return;
    }
    let cancelled = false;
    let timer: number | undefined;
    lastSeq.current = 0;
    setLines([]);
    setFollow(true);

    async function tick() {
      try {
        const data: ProcessLogs = await api.getProcessLogs(
          selectedId as string,
          lastSeq.current,
        );
        if (cancelled) return;
        setSelected(data.process);
        setProcesses((previous) =>
          previous.map((item) =>
            item.id === data.process.id ? data.process : item,
          ),
        );
        if (data.lines.length) {
          lastSeq.current = data.lines[data.lines.length - 1].seq;
          setLines((previous) =>
            [...previous, ...data.lines].slice(-MAX_LOG_LINES),
          );
        }
      } catch {
        // Process may have been pruned; stop quietly and let the list refresh.
      }
    }

    void tick();
    timer = window.setInterval(tick, 1200);
    return () => {
      cancelled = true;
      if (timer) window.clearInterval(timer);
    };
  }, [selectedId]);

  useEffect(() => {
    if (!follow) return;
    const element = logRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [lines, follow]);

  async function start(event: React.FormEvent) {
    event.preventDefault();
    const value = command.trim();
    if (!value) return;
    setBusy(true);
    setError(null);
    try {
      const created = await api.startProcess(workspaceId, {
        command: value,
        label: label.trim(),
      });
      setProcesses((previous) => [created, ...previous]);
      setSelectedId(created.id);
      setLabel("");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function stop(processId: string) {
    setStoppingId(processId);
    setError(null);
    try {
      const updated = await api.stopProcess(processId);
      setProcesses((previous) =>
        previous.map((item) => (item.id === processId ? updated : item)),
      );
      setSelected((previous) =>
        previous?.id === processId ? updated : previous,
      );
    } catch (err) {
      setError(errorText(err));
    } finally {
      setStoppingId(null);
    }
  }

  function handleScroll() {
    const element = logRef.current;
    if (!element) return;
    const distance =
      element.scrollHeight - element.scrollTop - element.clientHeight;
    setFollow(distance < 48);
  }

  return (
    <section className="panel workspace-runner">
      <div className="panel-heading">
        <h2>运行面板</h2>
        <span className="hint">
          长驻命令在工作区目录中运行；关闭 Iris 时会一起停止。
        </span>
      </div>
      <p className="hint">
        运行面板直接以当前 Windows 用户身份执行命令，不经过聊天审批，也不是沙箱。
        只运行你信任的命令。
      </p>
      {archived ? (
        <div className="alert alert-warning">
          该工作区已归档，不能启动新进程；已有进程仍可查看和停止。
        </div>
      ) : null}
      {error ? <div className="alert alert-error">{error}</div> : null}

      <form className="runner-form" onSubmit={start}>
        <label>
          命令
          <input
            className="mono"
            value={command}
            onChange={(event) => setCommand(event.target.value)}
            placeholder="npm run dev"
            disabled={archived || busy}
          />
        </label>
        <label>
          名称（可选）
          <input
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            placeholder="dev server"
            maxLength={120}
            disabled={archived || busy}
          />
        </label>
        <button
          type="submit"
          className="button primary"
          disabled={archived || busy || !command.trim()}
        >
          {busy ? "启动中…" : "启动"}
        </button>
      </form>
      <div className="runner-presets">
        {PRESETS.map((preset) => (
          <button
            key={preset.command}
            type="button"
            className="button ghost runner-preset"
            onClick={() => setCommand(preset.command)}
            disabled={archived}
          >
            {preset.label}
          </button>
        ))}
      </div>

      <div className="runner-body">
        <div className="runner-list">
          {processes.length === 0 ? (
            <div className="muted runner-empty">还没有运行中的进程。</div>
          ) : (
            processes.map((item) => (
              <div
                key={item.id}
                className={
                  item.id === selectedId
                    ? "runner-item selected"
                    : "runner-item"
                }
                role="button"
                tabIndex={0}
                onClick={() => setSelectedId(item.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    setSelectedId(item.id);
                  }
                }}
              >
                <div className="runner-item-head">
                  <span className="runner-item-label" title={item.label}>
                    {item.label || item.command}
                  </span>
                  <span className={`badge badge-${item.status}`}>
                    {PROCESS_STATUS_LABELS[item.status] ?? item.status}
                  </span>
                </div>
                <div className="runner-item-command mono" title={item.command}>
                  {item.command}
                </div>
                <div className="runner-item-meta">
                  <span>PID {item.pid ?? "—"}</span>
                  <span>启动 {formatTime(item.started_at)}</span>
                  {item.ended_at ? (
                    <span>
                      结束 {formatTime(item.ended_at)}
                      {item.exit_code !== null
                        ? ` · 退出码 ${item.exit_code}`
                        : ""}
                    </span>
                  ) : null}
                </div>
                {item.error ? (
                  <div className="alert alert-error runner-item-error">
                    {item.error}
                  </div>
                ) : null}
                {isActive(item) ? (
                  <div className="runner-item-actions">
                    <button
                      type="button"
                      className="button danger"
                      onClick={(event) => {
                        event.stopPropagation();
                        void stop(item.id);
                      }}
                      disabled={stoppingId === item.id}
                    >
                      {stoppingId === item.id ? "停止中…" : "停止"}
                    </button>
                  </div>
                ) : null}
              </div>
            ))
          )}
        </div>

        <div className="runner-logs">
          <div className="runner-log-head">
            <div>
              <strong>{selected ? selected.label || selected.command : "日志"}</strong>
              {selected ? (
                <span className="muted runner-log-meta">
                  {" "}
                  · {PROCESS_STATUS_LABELS[selected.status] ?? selected.status}
                  {selected.pid ? ` · PID ${selected.pid}` : ""}
                </span>
              ) : null}
            </div>
            <label className="checkbox-row runner-follow">
              <input
                type="checkbox"
                checked={follow}
                onChange={(event) => setFollow(event.target.checked)}
              />
              跟随最新
            </label>
          </div>
          <pre className="process-log" ref={logRef} onScroll={handleScroll}>
            {lines.length
              ? lines.map((line) => line.text).join("\n")
              : "暂无输出。启动进程后日志会自动刷新。"}
          </pre>
        </div>
      </div>
    </section>
  );
}
