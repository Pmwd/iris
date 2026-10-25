import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { errorText, formatTime } from "../format";
import {
  MENTOR_STATE_KINDS,
  NOTE_KIND_LABELS,
  type MentorStateKind,
} from "../labels";
import type { Note, Project, Run, Task } from "../types";
import { StatusBadge } from "./StatusBadge";

type AcceptanceKind = "progress" | "decision";

export function MentorPanel({
  task,
  project,
  selectedRun,
  onChanged,
}: {
  task: Task;
  project: Project;
  selectedRun: Run | null;
  onChanged?: () => void;
}) {
  const navigate = useNavigate();
  const [globalNotes, setGlobalNotes] = useState<Note[]>([]);
  const [allTasks, setAllTasks] = useState<Task[]>([]);
  const [stateForm, setStateForm] = useState<{
    kind: MentorStateKind;
    title: string;
    content_md: string;
  }>({ kind: "goal", title: "", content_md: "" });
  const [noteForm, setNoteForm] = useState<{
    kind: AcceptanceKind;
    title: string;
    content_md: string;
  }>({ kind: "progress", title: "", content_md: "" });
  const [stageForm, setStageForm] = useState({ title: "", goal_md: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function loadAll() {
    const [notes, tasks] = await Promise.all([
      api.listGlobalNotes("accepted"),
      api.listTasks(project.id),
    ]);
    setGlobalNotes(notes);
    setAllTasks(tasks);
  }

  useEffect(() => {
    setError(null);
    setMessage(null);
    void loadAll().catch((err) => setError(errorText(err)));
  }, [project.id]);

  useEffect(() => {
    if (!selectedRun || selectedRun.status !== "succeeded") return;
    setNoteForm({
      kind: "progress",
      title: `${task.title} — 阶段进展`,
      content_md: `来源：Mentor 任务「${task.title}」\n\n${
        selectedRun.result_text ?? ""
      }`,
    });
  }, [
    selectedRun?.id,
    selectedRun?.status,
    selectedRun?.result_text,
    task.title,
  ]);

  const stateNotesByKind = useMemo(() => {
    const groups = new Map<MentorStateKind, Note[]>();
    for (const kind of MENTOR_STATE_KINDS) groups.set(kind, []);
    for (const note of globalNotes) {
      if ((MENTOR_STATE_KINDS as readonly string[]).includes(note.kind)) {
        groups.get(note.kind as MentorStateKind)?.push(note);
      }
    }
    return groups;
  }, [globalNotes]);

  const goalNotes = stateNotesByKind.get("goal") ?? [];
  const stages = allTasks.filter(
    (item) => item.source_task_id === task.id && item.role === "coding",
  );

  function changeAcceptanceKind(kind: AcceptanceKind) {
    setNoteForm((current) => {
      const suffix = kind === "decision" ? "已确认选择" : "阶段进展";
      const prefix = `${task.title} — `;
      return {
        ...current,
        kind,
        title: current.title.startsWith(prefix)
          ? `${prefix}${suffix}`
          : current.title,
      };
    });
  }

  async function addStateNote(event: React.FormEvent) {
    event.preventDefault();
    if (!stateForm.title.trim()) {
      setError("长期状态标题不能为空。");
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await api.createGlobalNote({
        title: stateForm.title.trim(),
        content_md: stateForm.content_md,
        kind: stateForm.kind,
        status: "accepted",
        pinned: false,
      });
      setStateForm((current) => ({
        kind: current.kind,
        title: "",
        content_md: "",
      }));
      await loadAll();
      setMessage(
        "长期状态已添加。后续 Mentor 任务会自动引用这条已接受的全局 note。",
      );
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function acceptMentorResult(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedRun || selectedRun.status !== "succeeded") return;
    if (!noteForm.title.trim() || !noteForm.content_md.trim()) {
      setError("标题和内容不能为空。");
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await api.createGlobalNote({
        title: noteForm.title.trim(),
        content_md: noteForm.content_md,
        kind: noteForm.kind,
        status: "accepted",
        pinned: false,
      });
      await loadAll();
      onChanged?.();
      setMessage(
        "已接受为全局长期状态。Mentor 后续任务会引用它；不会自动创建阶段任务。",
      );
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function createStage(event: React.FormEvent) {
    event.preventDefault();
    if (!stageForm.title.trim()) {
      setError("阶段任务标题不能为空。");
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await api.createTask(project.id, {
        title: stageForm.title.trim(),
        goal_md: stageForm.goal_md,
        role: "coding",
        source_task_id: task.id,
      });
      setStageForm({ title: "", goal_md: "" });
      await loadAll();
      setMessage(
        "阶段任务已创建。目标仍可编辑，运行需要你手动开始；Mentor 不会自动启动。",
      );
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function createFollowup(stage: Task) {
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const follow = await api.createTask(project.id, {
        title: `Mentor 跟进：${stage.title}`,
        goal_md:
          `基于阶段任务「${stage.title}」的已接受进展：\n` +
          "- 回顾长期目标、已确认方向和盲点；\n" +
          "- 比较下一步至少两个选项，指出风险、盲点与反例；\n" +
          "- 不要替我决定；最后提出需要我回答的问题。\n",
        role: "mentor",
        source_task_id: stage.id,
      });
      navigate(`/projects/${project.id}/tasks/${follow.id}`);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  function prefillStageGoal(goal: Note) {
    setStageForm((current) => ({
      ...current,
      goal_md:
        `长期目标：${goal.title}\n${goal.content_md}\n\n` +
        "本阶段要推进：\n\n验收条件：\n\n不要做：\n",
    }));
  }

  return (
    <section className="panel mentor-panel">
      <div className="panel-heading">
        <div>
          <h2>Mentor 长期状态</h2>
          <div className="muted">
            Mentor 默认只读：比较选项、指出盲点；不替你决定，也不自动写入长期事实。
          </div>
        </div>
        <span className="badge">read_only</span>
      </div>

      {error && <div className="alert alert-error">{error}</div>}
      {message && <div className="alert alert-success">{message}</div>}

      <div className="mentor-state-grid">
        {MENTOR_STATE_KINDS.map((kind) => {
          const notes = stateNotesByKind.get(kind) ?? [];
          return (
            <div className="mentor-state-group" key={kind}>
              <div className="mentor-state-heading">
                <span>{NOTE_KIND_LABELS[kind]}</span>
                <span className="badge">{notes.length}</span>
              </div>
              {notes.length ? (
                notes.map((note) => (
                  <div className="mentor-state-note" key={note.id}>
                    <div className="note-title">{note.title}</div>
                    <div className="muted">{formatTime(note.updated_at)}</div>
                    <pre className="note-content">{note.content_md}</pre>
                  </div>
                ))
              ) : (
                <div className="muted">暂无已接受内容</div>
              )}
            </div>
          );
        })}
      </div>

      <details className="mentor-add">
        <summary>添加长期状态（全局 note）</summary>
        <form className="stack" onSubmit={addStateNote}>
          <label>
            类型
            <select
              value={stateForm.kind}
              onChange={(event) =>
                setStateForm({
                  ...stateForm,
                  kind: event.target.value as MentorStateKind,
                })
              }
            >
              {MENTOR_STATE_KINDS.map((kind) => (
                <option value={kind} key={kind}>
                  {NOTE_KIND_LABELS[kind]}
                </option>
              ))}
            </select>
          </label>
          <label>
            标题
            <input
              value={stateForm.title}
              onChange={(event) =>
                setStateForm({ ...stateForm, title: event.target.value })
              }
              placeholder="例如：长期目标"
            />
          </label>
          <label>
            内容
            <textarea
              rows={4}
              value={stateForm.content_md}
              onChange={(event) =>
                setStateForm({ ...stateForm, content_md: event.target.value })
              }
              placeholder="只写你确认过的目标和现状；Mentor 不会替你补全。"
            />
          </label>
          <div className="inline-actions">
            <button className="button" type="submit" disabled={busy}>
              添加为已接受状态
            </button>
          </div>
        </form>
      </details>

      <div className="mentor-section">
        <div className="panel-heading">
          <h3>接受本次建议</h3>
          <span className="hint">只有你接受后才会进入长期状态</span>
        </div>
        {selectedRun?.status === "succeeded" ? (
          <form className="stack" onSubmit={acceptMentorResult}>
            <div className="hint">
              Mentor 输出应先比较选项、指出盲点/反例，并提出需要你回答的问题；
              阶段任务仍由你确认后创建。
            </div>
            <label>
              类型
              <select
                value={noteForm.kind}
                onChange={(event) =>
                  changeAcceptanceKind(event.target.value as AcceptanceKind)
                }
              >
                <option value="progress">阶段进展（progress）</option>
                <option value="decision">已确认选择（decision）</option>
              </select>
            </label>
            <label>
              标题
              <input
                value={noteForm.title}
                onChange={(event) =>
                  setNoteForm({ ...noteForm, title: event.target.value })
                }
              />
            </label>
            <label>
              内容
              <textarea
                rows={10}
                value={noteForm.content_md}
                onChange={(event) =>
                  setNoteForm({ ...noteForm, content_md: event.target.value })
                }
              />
            </label>
            <div className="inline-actions">
              <button className="button primary" type="submit" disabled={busy}>
                接受为全局长期状态
              </button>
            </div>
          </form>
        ) : (
          <div className="empty">
            运行 Mentor 后，在这里审查并把 progress / decision 接受为长期状态。
          </div>
        )}
      </div>

      <div className="mentor-section">
        <div className="panel-heading">
          <h3>阶段任务</h3>
          <span className="muted">需要你确认后创建</span>
        </div>
        <div className="hint">
          先接受一条 progress / decision，再用已确认目标创建阶段任务。阶段任务由
          Coding 执行，仍需你手动运行；完成后接受一条 progress note，后续 Mentor
          才能通过 handoff 看到进展。
        </div>
        {goalNotes.length ? (
          <div className="inline-actions">
            <span className="hint">用已接受目标预填：</span>
            {goalNotes.map((goal) => (
              <button
                type="button"
                className="button small ghost"
                key={goal.id}
                onClick={() => prefillStageGoal(goal)}
              >
                {goal.title}
              </button>
            ))}
          </div>
        ) : null}
        <form className="stack" onSubmit={createStage}>
          <label>
            阶段任务标题
            <input
              value={stageForm.title}
              onChange={(event) =>
                setStageForm({ ...stageForm, title: event.target.value })
              }
              placeholder="例如：完成第一轮每周复核"
            />
          </label>
          <label>
            阶段目标
            <textarea
              rows={5}
              value={stageForm.goal_md}
              onChange={(event) =>
                setStageForm({ ...stageForm, goal_md: event.target.value })
              }
              placeholder="本阶段要推进什么、验收条件、不要做什么…"
            />
          </label>
          <div className="inline-actions">
            <button className="button primary" type="submit" disabled={busy}>
              创建阶段任务（Coding）
            </button>
          </div>
        </form>

        {stages.length ? (
          <div className="stage-list">
            {stages.map((stage) => (
              <div className="stage-row" key={stage.id}>
                <div>
                  <Link
                    className="task-title"
                    to={`/projects/${project.id}/tasks/${stage.id}`}
                  >
                    {stage.title}
                  </Link>
                  <div className="muted">
                    {stage.role} · {formatTime(stage.created_at)}
                  </div>
                </div>
                <div className="inline-actions">
                  <StatusBadge status={stage.status} />
                  {(stage.status === "needs_review" ||
                    stage.status === "done") && (
                    <button
                      type="button"
                      className="button small"
                      disabled={busy}
                      onClick={() => void createFollowup(stage)}
                    >
                      创建 Mentor 跟进
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty">还没有阶段任务。</div>
        )}
        {stages.some((stage) => stage.status === "needs_review") ? (
          <div className="hint">
            有阶段任务待审查：先到阶段任务页接受一条 progress note，再创建跟进。
          </div>
        ) : null}
      </div>
    </section>
  );
}
