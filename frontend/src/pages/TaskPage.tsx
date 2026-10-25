import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { errorText, formatCost, formatTime, splitLines } from "../format";
import type {
  ContextPreview,
  PermissionProfile,
  Project,
  Run,
  Task,
} from "../types";
import { MentorPanel } from "../components/MentorPanel";
import { RunPanel } from "../components/RunPanel";
import { ScholarPanel } from "../components/ScholarPanel";
import { StatusBadge } from "../components/StatusBadge";

const ACTIVE = new Set(["starting", "running", "canceling"]);
const RESUMABLE = new Set(["interrupted", "failed", "canceled"]);

const REASON_LABELS: Record<string, string> = {
  pinned: "置顶",
  matched: "相关",
  recent: "最近",
  handoff: "任务交接",
  mentor_state: "导师长期状态",
  budget: "超出预算",
  not_relevant: "未匹配",
};

export function TaskPage() {
  const { taskId } = useParams();
  const navigate = useNavigate();
  const [task, setTask] = useState<Task | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [preview, setPreview] = useState<ContextPreview | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedNotes, setSelectedNotes] = useState<Set<string>>(new Set());
  const [profile, setProfile] = useState<PermissionProfile>("edit");
  const [noteTitle, setNoteTitle] = useState("");
  const [noteContent, setNoteContent] = useState("");
  const [noteAliases, setNoteAliases] = useState("");
  const [noteKind, setNoteKind] = useState<"outcome" | "progress">("outcome");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const contextInitialized = useRef(false);
  const noteInitialized = useRef<string | null>(null);

  async function load() {
    if (!taskId) return;
    const taskData = await api.getTask(taskId);
    const [projectData, previewData, runList] = await Promise.all([
      api.getProject(taskData.project_id),
      api.contextPreview(taskData.id),
      api.listRuns(taskData.id),
    ]);
    setTask(taskData);
    setProject(projectData);
    setPreview(previewData);
    setRuns(runList);
    if (taskData.role === "testing") {
      setProfile((current) =>
        current === "read_only" || current === "verify" ? current : "verify",
      );
    } else if (taskData.role === "mentor") {
      setProfile("read_only");
    } else {
      setProfile((current) => (current === "verify" ? "edit" : current));
    }
    setSelectedRunId((current) => {
      if (current && runList.some((run) => run.id === current)) return current;
      return runList[0]?.id ?? null;
    });
    if (!contextInitialized.current) {
      setSelectedNotes(new Set(previewData.selected_note_ids));
      contextInitialized.current = true;
    }
    if (!previewData.execute_allowed) {
      setProfile((current) => (current === "execute" ? "edit" : current));
    }
  }

  useEffect(() => {
    contextInitialized.current = false;
    noteInitialized.current = null;
    setSelectedRunId(null);
    setError(null);
    setMessage(null);
    void load().catch((err) => setError(errorText(err)));
  }, [taskId]);

  const selectedRun = runs.find((run) => run.id === selectedRunId) ?? null;

  useEffect(() => {
    if (!selectedRun || !task || selectedRun.status !== "succeeded") return;
    if (noteInitialized.current === selectedRun.id) return;
    noteInitialized.current = selectedRun.id;
    setNoteTitle(`${task.title} — outcome`);
    setNoteContent(selectedRun.result_text ?? "");
    setNoteAliases("");
    setNoteKind("outcome");
  }, [selectedRun?.id, selectedRun?.status, selectedRun?.result_text, task?.title]);

  async function startRun(mode: "new" | "resume") {
    if (!task) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const run = await api.startRun(task.id, {
        mode,
        permission_profile: profile,
        context_note_ids: [...selectedNotes],
      });
      setSelectedRunId(run.id);
      await load();
      setMessage(mode === "resume" ? "已请求恢复会话。" : "运行已启动。");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function cancelRun() {
    if (!selectedRun) return;
    setBusy(true);
    setError(null);
    try {
      await api.cancelRun(selectedRun.id);
      await load();
      setMessage("已发送取消请求。");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function acceptNote() {
    if (!task || !project || !selectedRun) return;
    if (!noteTitle.trim()) {
      setError("note 标题不能为空。");
      return;
    }
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const note = await api.createNote(project.id, {
        title: noteTitle,
        content_md: noteContent,
        aliases: splitLines(noteAliases),
        kind: noteKind,
        status: "accepted",
        task_id: task.id,
        source_run_id: selectedRun.id,
      });
      setSelectedNotes((current) => new Set([...current, note.id]));
      await load();
      setMessage(
        noteKind === "progress"
          ? "阶段进展已接受；后续 Mentor 跟进可通过 handoff 看到它。"
          : "结果已接受为项目上下文，后续任务可以复用它。",
      );
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function completeTask() {
    if (!task) return;
    setBusy(true);
    setError(null);
    try {
      await api.completeTask(task.id);
      await load();
      setMessage("任务已标记完成。");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function createTestingTask() {
    if (!task || !project) return;
    setBusy(true);
    setError(null);
    try {
      const testing = await api.createTask(project.id, {
        title: `Verify: ${task.title}`,
        goal_md:
          "独立验证该任务的结果：检查实现和测试，报告通过/失败、风险、缺失测试和建议。不要修改文件，不要修复代码。",
        role: "testing",
        source_task_id: task.id,
      });
      navigate(`/projects/${project.id}/tasks/${testing.id}`);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  function toggleNote(noteId: string) {
    setSelectedNotes((current) => {
      const next = new Set(current);
      if (next.has(noteId)) next.delete(noteId);
      else next.add(noteId);
      return next;
    });
  }

  function changeProjectNoteKind(kind: "outcome" | "progress") {
    setNoteKind(kind);
    if (!task) return;
    setNoteTitle((current) =>
      current === `${task.title} — outcome` ||
      current === `${task.title} — progress`
        ? `${task.title} — ${kind}`
        : current,
    );
  }

  if (!task || !project) {
    return (
      <div className="page">
        {error ? (
          <div className="alert alert-error">{error}</div>
        ) : (
          <div className="muted">加载任务…</div>
        )}
      </div>
    );
  }

  const canResume =
    RESUMABLE.has(task.status) && Boolean(task.current_session_id);
  const selectedRunActive = selectedRun ? ACTIVE.has(selectedRun.status) : false;
  const canStart =
    task.status === "ready" || RESUMABLE.has(task.status);

  return (
    <div className="page">
      <div className="breadcrumb">
        <Link to="/">项目</Link>
        <span>/</span>
        <Link to={`/projects/${project.id}`}>{project.name}</Link>
        <span>/</span>
        <span>Task</span>
      </div>

      <header className="page-header">
        <div>
          <div className="eyebrow">TASK</div>
          <div className="title-row">
            <h1>{task.title}</h1>
            <span className="badge">
              {task.role === "testing"
                ? "Testing"
                : task.role === "scholar"
                  ? "Scholar"
                  : task.role === "mentor"
                    ? "Mentor"
                    : "Coding"}
            </span>
            <StatusBadge status={task.status} />
          </div>
          <div className="muted mono">{project.workspace_path}</div>
          {task.source_task_id ? (
            <div className="muted">
              {task.role === "testing" ? "验证来源任务" : "来源任务"}：
              {task.source_task_id.slice(0, 8)}
            </div>
          ) : null}
        </div>
        <div className="header-meta">
          <span>session {task.current_session_id?.slice(0, 8) ?? "—"}</span>
          <span>更新于 {formatTime(task.updated_at)}</span>
          {task.role === "coding" && (
            <button
              className="button small"
              disabled={busy}
              onClick={() => void createTestingTask()}
            >
              创建 Testing 任务
            </button>
          )}
          {task.status === "needs_review" && (
            <button
              className="button small"
              disabled={busy}
              onClick={() => void completeTask()}
            >
              标记完成
            </button>
          )}
        </div>
      </header>

      {error && <div className="alert alert-error">{error}</div>}
      {message && <div className="alert alert-success">{message}</div>}

      <section className="panel">
        <div className="panel-heading">
          <h2>目标</h2>
        </div>
        <pre className="goal">{task.goal_md || "未填写任务目标。"}</pre>
      </section>

      {task.role === "scholar" ? (
        <ScholarPanel task={task} project={project} onChanged={() => void load()} />
      ) : null}

      {task.role === "mentor" ? (
        <MentorPanel
          task={task}
          project={project}
          selectedRun={selectedRun}
          onChanged={() => void load()}
        />
      ) : null}

      {task.role !== "scholar" && task.status === "running" && (
        <section className="panel">
          <div className="panel-heading">
            <h2>运行中</h2>
            {selectedRunActive && (
              <button
                className="button danger"
                disabled={busy}
                onClick={() => void cancelRun()}
              >
                取消运行
              </button>
            )}
          </div>
          <div className="muted">
            Iris 正在等待 CLI 完成。关闭页面不会中断服务端运行。
          </div>
        </section>
      )}

      {task.role !== "scholar" && canStart && (
        <section className="panel">
          <div className="panel-heading">
            <h2>运行配置</h2>
            <span className="hint">
              上下文只包含用户已接受的 note
            </span>
          </div>
          <div className="run-config">
            <label>
              权限档位
              <select
                value={profile}
                onChange={(event) =>
                  setProfile(event.target.value as PermissionProfile)
                }
              >
                {task.role === "testing" ? (
                  <>
                    <option value="read_only">只读审查 · 不修改文件</option>
                    <option value="verify">
                      验证/测试 · 只读代码 + 白名单 PowerShell
                    </option>
                  </>
                ) : task.role === "mentor" ? (
                  <option value="read_only">
                    只读导师 · 比较选择、指出盲点，不修改文件
                  </option>
                ) : (
                  <>
                    <option value="read_only">只读 · 分析，不修改文件</option>
                    <option value="edit">编辑 · 修改文件，不执行命令</option>
                    <option value="execute" disabled={!preview?.execute_allowed}>
                      执行/测试 · 允许白名单 PowerShell
                    </option>
                  </>
                )}
              </select>
              {task.role === "testing" && !preview?.execute_allowed && (
                <span className="hint">
                  项目未配置 PowerShell 白名单，Testing 只能做静态检查。
                </span>
              )}
              {task.role === "coding" && !preview?.execute_allowed && (
                <span className="hint">
                  先在项目设置中配置允许的 PowerShell 模式。
                </span>
              )}
            </label>

            {preview?.security_warnings?.length ? (
              <div className="alert alert-warning">
                <strong>工作区安全提示</strong>
                <ul>
                  {preview.security_warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            <div className="context-picker">
              <div className="context-heading">
                <strong>本次注入的上下文</strong>
                <div className="inline-actions">
                  <button
                    type="button"
                    className="button small"
                    onClick={() =>
                      setSelectedNotes(
                        new Set(preview?.selected_note_ids ?? []),
                      )
                    }
                  >
                    推荐选择
                  </button>
                  <button
                    type="button"
                    className="button small ghost"
                    onClick={() =>
                      setSelectedNotes(
                        new Set(preview?.notes.map((note) => note.id) ?? []),
                      )
                    }
                  >
                    全选
                  </button>
                  <button
                    type="button"
                    className="button small ghost"
                    onClick={() => setSelectedNotes(new Set())}
                  >
                    清空
                  </button>
                </div>
              </div>
              <div className="context-budget">
                预算 {preview?.budget_tokens ?? "—"} tokens · 推荐选择预计{" "}
                {preview?.estimated_tokens ?? "—"} tokens · 推荐{" "}
                {preview?.selected_note_ids.length ?? 0} /{" "}
                {preview?.notes.length ?? 0} 条
              </div>
              {preview?.notes.length ? (
                <div className="context-list">
                  {preview.notes.map((note) => (
                    <label className="context-item" key={note.id}>
                      <input
                        type="checkbox"
                        checked={selectedNotes.has(note.id)}
                        onChange={() => toggleNote(note.id)}
                      />
                      <span>
                        <div className="context-title">
                          {note.title}{" "}
                          <span className="badge">
                            {note.scope === "global" ? "全局" : "项目"}
                          </span>{" "}
                          {note.pinned ? (
                            <span className="badge badge-pinned">置顶</span>
                          ) : null}{" "}
                          {note.recommended ? (
                            <span className="badge badge-recommended">
                              推荐 · {REASON_LABELS[note.reason] ?? note.reason}
                            </span>
                          ) : note.reason === "budget" ? (
                            <span className="badge">超出预算</span>
                          ) : null}
                        </div>
                        <span className="muted">
                          {" "}
                          · {note.content_md.length} chars · 使用{" "}
                          {note.use_count ?? 0} 次
                        </span>
                        {note.aliases?.length ? (
                          <div className="alias-list">
                            {note.aliases.map((alias) => (
                              <span className="alias-chip" key={alias}>
                                {alias}
                              </span>
                            ))}
                          </div>
                        ) : null}
                        <pre>{note.content_md.slice(0, 500)}</pre>
                      </span>
                    </label>
                  ))}
                </div>
              ) : (
                <div className="empty">
                  项目还没有已接受的上下文。先在任务完成后沉淀一条 outcome，或在首页添加全局 note。
                </div>
              )}
            </div>

            <div className="inline-actions">
              {canResume && (
                <button
                  className="button primary"
                  disabled={busy}
                  onClick={() => void startRun("resume")}
                >
                  恢复会话
                </button>
              )}
              <button
                className={canResume ? "button" : "button primary"}
                disabled={busy}
                onClick={() => void startRun("new")}
              >
                {canResume ? "新会话运行" : "开始运行"}
              </button>
            </div>
          </div>
        </section>
      )}

      {task.role !== "mentor" &&
        task.status === "needs_review" &&
        selectedRun?.status === "succeeded" && (
        <section className="panel">
          <div className="panel-heading">
            <h2>审查并沉淀</h2>
            <span className="hint">
              只有你接受的内容才会进入后续上下文
              {task.source_task_id && noteKind === "progress"
                ? "；该 progress 可供后续 Mentor 跟进"
                : ""}
            </span>
          </div>
          <div className="stack">
            {task.role === "coding" ? (
              <label>
                note 类型
                <select
                  value={noteKind}
                  onChange={(event) =>
                    changeProjectNoteKind(
                      event.target.value as "outcome" | "progress",
                    )
                  }
                >
                  <option value="outcome">任务结果（outcome）</option>
                  <option value="progress">阶段进展（progress）</option>
                </select>
              </label>
            ) : null}
            <label>
              标题
              <input
                value={noteTitle}
                onChange={(event) => setNoteTitle(event.target.value)}
              />
            </label>
            <label>
              内容
              <textarea
                rows={10}
                value={noteContent}
                onChange={(event) => setNoteContent(event.target.value)}
              />
            </label>
            <label>
              别名 / 标签（每行一个）
              <textarea
                rows={2}
                className="mono"
                value={noteAliases}
                onChange={(event) => setNoteAliases(event.target.value)}
                placeholder="补充不同措辞，例如：安全、聚会、饮食禁忌"
              />
            </label>
            <div className="inline-actions">
              <button
                className="button primary"
                disabled={busy}
                onClick={() => void acceptNote()}
              >
                接受为项目 note
              </button>
              <button
                className="button"
                disabled={busy}
                onClick={() => void completeTask()}
              >
                标记任务完成
              </button>
            </div>
          </div>
        </section>
      )}

      {task.role !== "scholar" ? (
      <div className="task-grid">
        <section className="panel">
          <div className="panel-heading">
            <h2>运行历史</h2>
            <span className="muted">{runs.length} 次</span>
          </div>
          {runs.length === 0 ? (
            <div className="empty">还没有运行。</div>
          ) : (
            <div className="run-list">
              {runs.map((run) => (
                <button
                  key={run.id}
                  className={`run-row ${selectedRunId === run.id ? "selected" : ""}`}
                  onClick={() => setSelectedRunId(run.id)}
                >
                  <span>
                    #{run.attempt_no} · {formatTime(run.created_at)}
                  </span>
                  <span className="run-meta">
                    {run.permission_profile} · {formatCost(run.cost_usd)}
                  </span>
                  <StatusBadge status={run.status} />
                </button>
              ))}
            </div>
          )}
        </section>

        {selectedRun ? (
          <RunPanel
            key={selectedRun.id}
            run={selectedRun}
            onTerminal={() => void load()}
          />
        ) : (
          <section className="panel">
            <div className="empty">运行后在这里查看实时事件和结果。</div>
          </section>
        )}
      </div>
      ) : null}

      {task.role !== "scholar" && selectedRun && (
        <section className="panel">
          <div className="panel-heading">
            <h2>上下文快照</h2>
            <span className="muted">这次运行实际注入的内容</span>
          </div>
          <div className="manifest">
            <div>
              预算 {selectedRun.context_manifest.budget_chars ?? "—"} chars ·
              实际 {selectedRun.context_manifest.total_chars ?? "—"} chars
            </div>
            {selectedRun.context_manifest.mentor_state_note_count ? (
              <div className="muted">
                其中导师长期状态{" "}
                {selectedRun.context_manifest.mentor_state_note_count} 条
                （reason=mentor_state）
              </div>
            ) : null}
            {selectedRun.context_manifest.included_notes?.length ? (
              <ul>
                {selectedRun.context_manifest.included_notes.map((note) => (
                  <li key={note.id}>
                    {note.scope === "global" ? "[全局] " : "[项目] "}
                    {note.title} · {note.chars} chars
                    {note.reason ? ` · ${REASON_LABELS[note.reason] ?? note.reason}` : ""}
                  </li>
                ))}
              </ul>
            ) : (
              <div className="muted">本次没有注入项目 note。</div>
            )}
            {selectedRun.context_manifest.excluded_notes?.length ? (
              <details>
                <summary>被排除的 note</summary>
                <ul>
                  {selectedRun.context_manifest.excluded_notes.map((note) => (
                    <li key={note.id}>
                      {note.title} · {note.reason}
                    </li>
                  ))}
                </ul>
              </details>
            ) : null}
          </div>
        </section>
      )}
    </div>
  );
}
