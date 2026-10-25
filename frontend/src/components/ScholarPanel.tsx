import { useEffect, useState } from "react";
import { api } from "../api";
import { errorText, formatTime, splitLines } from "../format";
import type { Note, Project, ResearchJob, Task } from "../types";
import { StatusBadge } from "./StatusBadge";

const ACTIVE = new Set(["planning", "running", "canceling"]);
const SUBTASK_LABELS: Record<string, string> = {
  queued: "排队中",
  running: "研究中",
  succeeded: "完成",
  failed: "失败",
  canceled: "已取消",
  interrupted: "已中断",
};

function statusLabel(status: string): string {
  return (
    {
      planning: "生成计划中",
      planned: "计划待确认",
      running: "并行研究",
      canceling: "取消中",
      completed: "已完成",
      failed: "失败",
      canceled: "已取消",
      interrupted: "已中断",
    }[status] ?? status
  );
}

export function ScholarPanel({
  task,
  project,
  onChanged,
}: {
  task: Task;
  project: Project;
  onChanged?: () => void;
}) {
  const [job, setJob] = useState<ResearchJob | null>(null);
  const [allowWeb, setAllowWeb] = useState(false);
  const [questionsText, setQuestionsText] = useState("");
  const [synthesis, setSynthesis] = useState<Note | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    void api
      .listResearchJobs(task.id)
      .then((jobs) => {
        const latest = jobs[0] ?? null;
        setJob(latest);
        if (latest) {
          setAllowWeb(latest.allow_web);
          setQuestionsText(latest.plan.join("\n"));
        }
      })
      .catch((err) => setError(errorText(err)));
  }, [task.id]);

  useEffect(() => {
    if (job) {
      setAllowWeb(job.allow_web);
      setQuestionsText(job.plan.join("\n"));
    }
  }, [job?.id]);

  useEffect(() => {
    if (!job || !ACTIVE.has(job.status)) return;
    const timer = window.setInterval(() => {
      void api
        .getResearchJob(job.id)
        .then((latest) => {
          setJob(latest);
          if (ACTIVE.has(latest.status) === false) onChanged?.();
        })
        .catch(() => {});
    }, 2000);
    return () => window.clearInterval(timer);
  }, [job?.id, job?.status]);

  useEffect(() => {
    if (!job?.synthesis_note_id) {
      setSynthesis(null);
      return;
    }
    void api
      .listNotes(project.id)
      .then((notes) => {
        setSynthesis(
          notes.find((note) => note.id === job.synthesis_note_id) ?? null,
        );
      })
      .catch(() => {});
  }, [job?.synthesis_note_id, project.id]);

  async function generatePlan() {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const created = await api.createResearchPlan(task.id, allowWeb);
      setJob(created);
      setMessage("研究计划已生成，请审阅后开始。");
      onChanged?.();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function savePlan() {
    if (!job) return;
    const questions = splitLines(questionsText);
    if (!questions.length) {
      setError("研究计划至少需要一个子问题。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await api.updateResearchPlan(job.id, questions);
      setJob(updated);
      setMessage("研究计划已保存。");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function startResearch() {
    if (!job) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const questions = splitLines(questionsText);
      const updated = questions.length
        ? await api.updateResearchPlan(job.id, questions)
        : job;
      const started = await api.startResearchJob(updated.id);
      setJob(started);
      setMessage("研究任务已启动；子问题会按并发上限执行。");
      onChanged?.();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function cancelResearch() {
    if (!job) return;
    setBusy(true);
    setError(null);
    try {
      const canceled = await api.cancelResearchJob(job.id);
      setJob(canceled);
      setMessage("已发送取消请求。");
      onChanged?.();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function acceptSynthesis() {
    if (!synthesis) return;
    setBusy(true);
    setError(null);
    try {
      const accepted = await api.updateNote(synthesis.id, {
        status: "accepted",
      });
      setSynthesis(accepted);
      setMessage("研究 note 已接受，后续 Scholar 任务可以复用。");
      onChanged?.();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const canPlan = !job || ["completed", "failed", "canceled", "interrupted"].includes(job.status);

  return (
    <section className="panel research-panel">
      <div className="panel-heading">
        <div>
          <h2>Scholar 研究编排</h2>
          <div className="muted">
            受控子对话 · 原生 WebSearch/WebFetch · 并发上限{" "}
            {job?.max_concurrency ?? 2}
          </div>
        </div>
        {job ? (
          <span className={`badge badge-${job.status}`}>
            {statusLabel(job.status)}
          </span>
        ) : null}
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {message && <div className="alert alert-success">{message}</div>}

      {canPlan ? (
        <div className="stack">
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={allowWeb}
              onChange={(event) => setAllowWeb(event.target.checked)}
            />
            允许本任务使用原生 WebSearch/WebFetch
          </label>
          <div className="inline-actions">
            <button
              className="button primary"
              disabled={busy}
              onClick={() => void generatePlan()}
            >
              {busy ? "生成中…" : "生成研究计划"}
            </button>
          </div>
        </div>
      ) : null}

      {job && job.status === "planned" ? (
        <div className="stack research-plan">
          <label>
            研究子问题（每行一个，最多 5 个）
            <textarea
              rows={6}
              value={questionsText}
              onChange={(event) => setQuestionsText(event.target.value)}
            />
          </label>
          <div className="inline-actions">
            <button
              className="button"
              disabled={busy}
              onClick={() => void savePlan()}
            >
              保存计划
            </button>
            <button
              className="button primary"
              disabled={busy}
              onClick={() => void startResearch()}
            >
              确认并开始并行研究
            </button>
          </div>
        </div>
      ) : null}

      {job && ["planning", "running", "canceling"].includes(job.status) ? (
        <div className="stack">
          <div className="muted">
            {job.status === "planning"
              ? "正在生成研究计划…"
              : "子问题正在按并发上限执行；完成后自动汇总草稿。"}
          </div>
          {job.status !== "planning" && (
            <div className="inline-actions">
              <button
                className="button danger"
                disabled={busy || job.status === "canceling"}
                onClick={() => void cancelResearch()}
              >
                取消研究
              </button>
            </div>
          )}
        </div>
      ) : null}

      {job && job.subtasks.length ? (
        <div className="subtask-list">
          {job.subtasks.map((subtask) => (
            <details className="subtask" key={subtask.id} open={subtask.status === "running"}>
              <summary>
                <span>
                  #{subtask.seq} {subtask.question}
                  {subtask.attempts > 1 ? (
                    <span className="muted"> · 尝试 {subtask.attempts} 次</span>
                  ) : null}
                </span>
                <span className={`badge badge-${subtask.status}`}>
                  {SUBTASK_LABELS[subtask.status] ?? subtask.status}
                </span>
              </summary>
              {subtask.error && (
                <div className="alert alert-error">{subtask.error}</div>
              )}
              {subtask.result_text && (
                <pre className="subtask-result">{subtask.result_text}</pre>
              )}
              {subtask.sources.length ? (
                <div className="source-list">
                  {subtask.sources.map((source) => (
                    <a href={source} target="_blank" rel="noreferrer" key={source}>
                      {source}
                    </a>
                  ))}
                </div>
              ) : null}
            </details>
          ))}
        </div>
      ) : null}

      {job?.error && <div className="alert alert-error">{job.error}</div>}

      {job?.status === "completed" && synthesis ? (
        <div className="research-synthesis">
          <div className="panel-heading">
            <h3>研究 note 草稿</h3>
            <StatusBadge status={synthesis.status} />
          </div>
          <div className="muted">
            生成于 {formatTime(synthesis.created_at)}。只有接受后才会进入后续上下文。
          </div>
          <pre className="synthesis-content">{synthesis.content_md}</pre>
          {synthesis.status === "draft" ? (
            <button
              className="button primary"
              disabled={busy}
              onClick={() => void acceptSynthesis()}
            >
              接受为研究 note
            </button>
          ) : (
            <div className="alert alert-success">该研究 note 已接受。</div>
          )}
        </div>
      ) : null}
    </section>
  );
}
