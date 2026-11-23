import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { errorText } from "../format";
import { ROLE_LABELS } from "../labels";
import type { Extraction, RoleId, Workspace } from "../types";
import { StatusBadge } from "./StatusBadge";

export function ExtractionPanel({
  workspaces,
  initialRole,
  initialProjectId,
  onDone,
}: {
  workspaces: Workspace[];
  initialRole?: RoleId | null;
  initialProjectId?: string | null;
  onDone: () => void;
}) {
  const [role, setRole] = useState<RoleId | "">(initialRole ?? "");
  const [projectId, setProjectId] = useState(initialProjectId ?? "");
  const [maxSessions, setMaxSessions] = useState(8);
  const [job, setJob] = useState<Extraction | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => {
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, []);

  function poll(id: string) {
    if (timer.current) window.clearInterval(timer.current);
    timer.current = window.setInterval(() => {
      void (async () => {
        try {
          const current = await api.getExtraction(id);
          setJob(current);
          if (current.status !== "running") {
            if (timer.current) window.clearInterval(timer.current);
            setBusy(false);
            if (current.status === "succeeded") onDone();
            else setError(current.error ?? "提取失败。");
          }
        } catch {
          // keep polling
        }
      })();
    }, 1000);
  }

  async function start() {
    setBusy(true);
    setError(null);
    setJob(null);
    try {
      const created = await api.extractFacts({
        role: role || null,
        project_id: projectId || null,
        max_sessions: maxSessions,
      });
      setJob(created);
      poll(created.id);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  return (
    <section className="extraction-panel">
      <div className="extraction-head">
        <div>
          <div className="eyebrow">EXTRACT</div>
          <h2>从会话摘要提取长期事实</h2>
          <p className="muted">
            只读取已生成的会话摘要；输出候选事实，不会自动接受。
          </p>
        </div>
      </div>

      {error ? <div className="alert alert-error">{error}</div> : null}

      <div className="extraction-controls">
        <label>
          角色
          <select
            value={role}
            onChange={(event) => setRole(event.target.value as RoleId | "")}
          >
            <option value="">两个角色</option>
            <option value="coding">{ROLE_LABELS.coding}</option>
            <option value="scholar">{ROLE_LABELS.scholar}</option>
          </select>
        </label>
        <label>
          工作区
          <select
            value={projectId}
            onChange={(event) => setProjectId(event.target.value)}
          >
            <option value="">全部工作区 / 全局</option>
            {workspaces.map((workspace) => (
              <option key={workspace.id} value={workspace.id}>
                {workspace.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          最多会话数
          <input
            type="number"
            min={1}
            max={50}
            value={maxSessions}
            onChange={(event) =>
              setMaxSessions(Math.max(1, Number(event.target.value) || 1))
            }
          />
        </label>
        <button
          type="button"
          className="button primary"
          onClick={() => void start()}
          disabled={busy}
        >
          {busy ? "提取中…" : "开始提取"}
        </button>
      </div>

      {job ? (
        <div className="extraction-status">
          <StatusBadge status={job.status} />
          {job.status === "running" ? (
            <span className="muted">正在读取摘要并生成候选…</span>
          ) : job.status === "succeeded" ? (
            <span className="muted">
              生成 {job.candidate_count} 条候选，请到候选列表逐条审核。
            </span>
          ) : (
            <span className="muted">{job.error ?? "提取失败。"}</span>
          )}
        </div>
      ) : null}
    </section>
  );
}
