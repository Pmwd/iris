import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { errorText, formatTime, splitLines } from "../format";
import type { Note, Project, Task, TaskRole } from "../types";
import { StatusBadge } from "../components/StatusBadge";

export function ProjectPage() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [notes, setNotes] = useState<Note[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [newTask, setNewTask] = useState({
    title: "",
    goal_md: "",
    role: "coding" as TaskRole,
    source_task_id: "",
  });
  const [settings, setSettings] = useState({
    name: "",
    workspace_path: "",
    brief_md: "",
    allowed_tools: "",
  });

  async function load() {
    if (!projectId) return;
    const [projectData, taskList, noteList] = await Promise.all([
      api.getProject(projectId),
      api.listTasks(projectId),
      api.listNotes(projectId),
    ]);
    setProject(projectData);
    setTasks(taskList);
    setNotes(noteList);
    setSettings({
      name: projectData.name,
      workspace_path: projectData.workspace_path,
      brief_md: projectData.brief_md,
      allowed_tools: projectData.allowed_tools.join("\n"),
    });
  }

  useEffect(() => {
    void load().catch((err) => setError(errorText(err)));
  }, [projectId]);

  async function createTask(event: React.FormEvent) {
    event.preventDefault();
    if (!projectId) return;
    setBusy(true);
    setError(null);
    try {
      const task = await api.createTask(projectId, {
        title: newTask.title,
        goal_md: newTask.goal_md,
        role: newTask.role,
        source_task_id: newTask.source_task_id || null,
      });
      setNewTask({
        title: "",
        goal_md: "",
        role: "coding",
        source_task_id: "",
      });
      await load();
      navigate(`/projects/${projectId}/tasks/${task.id}`);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function saveSettings(event: React.FormEvent) {
    event.preventDefault();
    if (!projectId) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const updated = await api.updateProject(projectId, {
        name: settings.name,
        workspace_path: settings.workspace_path,
        brief_md: settings.brief_md,
        allowed_tools: splitLines(settings.allowed_tools),
      });
      setProject(updated);
      setMessage("项目设置已保存。");
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function changeNote(note: Note, status: Note["status"]) {
    try {
      await api.updateNote(note.id, { status });
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function toggleNotePin(note: Note) {
    try {
      await api.updateNote(note.id, { pinned: !note.pinned });
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function removeNote(note: Note) {
    if (!window.confirm(`删除上下文 “${note.title}”？`)) return;
    try {
      await api.deleteNote(note.id);
      await load();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function removeProject() {
    if (!projectId) return;
    if (
      !window.confirm(
        "删除整个项目？任务、运行事件和上下文 note 都会一并删除，且无法撤销。",
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.deleteProject(projectId);
      navigate("/");
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  if (!project) {
    return (
      <div className="page">
        {error ? (
          <div className="alert alert-error">{error}</div>
        ) : (
          <div className="muted">加载项目…</div>
        )}
      </div>
    );
  }

  return (
    <div className="page">
      <div className="breadcrumb">
        <Link to="/">项目</Link>
        <span>/</span>
        <span>{project.name}</span>
      </div>
      <header className="page-header">
        <div>
          <div className="eyebrow">PROJECT</div>
          <h1>{project.name}</h1>
          <div className="muted mono">{project.workspace_path}</div>
        </div>
        <div className="header-meta">
          <span>已信任 {formatTime(project.trusted_at)}</span>
        </div>
      </header>

      {error && <div className="alert alert-error">{error}</div>}
      {message && <div className="alert alert-success">{message}</div>}

      <div className="two-column">
        <section className="panel">
          <div className="panel-heading">
            <h2>任务</h2>
            <span className="muted">{tasks.length} 个</span>
          </div>
          {tasks.length === 0 ? (
            <div className="empty">还没有任务。在右侧创建第一个任务。</div>
          ) : (
            <div className="task-list">
              {tasks.map((task) => (
                <Link
                  className="task-row"
                  key={task.id}
                  to={`/projects/${project.id}/tasks/${task.id}`}
                >
                  <div>
                    <div className="task-title">
                      {task.title}{" "}
                      <span className="badge">
                        {task.role === "testing"
                          ? "Testing"
                          : task.role === "scholar"
                            ? "Scholar"
                            : task.role === "mentor"
                              ? "Mentor"
                              : "Coding"}
                      </span>
                    </div>
                    <div className="muted">
                      {formatTime(task.created_at)} · session{" "}
                      {task.current_session_id?.slice(0, 8) ?? "—"}
                    </div>
                  </div>
                  <StatusBadge status={task.status} />
                </Link>
              ))}
            </div>
          )}
        </section>

        <section className="panel">
          <div className="panel-heading">
            <h2>新建任务</h2>
          </div>
          <form className="stack" onSubmit={createTask}>
            <label>
              任务角色
              <select
                value={newTask.role}
                onChange={(event) =>
                  setNewTask({
                    ...newTask,
                    role: event.target.value as TaskRole,
                    source_task_id:
                      event.target.value === "testing"
                        ? newTask.source_task_id
                        : "",
                  })
                }
              >
                <option value="coding">Coding · 实现和修改</option>
                <option value="scholar">Scholar · 研究并沉淀知识</option>
                <option value="mentor">Mentor · 比较选择与阶段规划</option>
              </select>
              {newTask.role === "mentor" ? (
                <span className="hint">
                  Mentor 默认只读，引用已接受的长期状态；不替你做决定，也不会自动创建任务或写入 note。
                </span>
              ) : null}
            </label>
            {newTask.role === "testing" ? (
              <label>
                被验证的任务
                <select
                  required
                  value={newTask.source_task_id}
                  onChange={(event) =>
                    setNewTask({
                      ...newTask,
                      source_task_id: event.target.value,
                    })
                  }
                >
                  <option value="">选择一个已完成/待审查的任务</option>
                  {tasks
                    .filter((task) => task.role === "coding")
                    .map((task) => (
                      <option value={task.id} key={task.id}>
                        {task.title} · {task.status}
                      </option>
                    ))}
                </select>
                <span className="hint">
                  Testing 会以独立 session 复用该任务已接受的 outcome，不复制原始 transcript。
                </span>
              </label>
            ) : null}
            <label>
              任务标题
              <input
                required
                value={newTask.title}
                onChange={(event) =>
                  setNewTask({ ...newTask, title: event.target.value })
                }
                placeholder="例如：增加 CSV 导出"
              />
            </label>
            <label>
              目标
              <textarea
                rows={6}
                value={newTask.goal_md}
                onChange={(event) =>
                  setNewTask({ ...newTask, goal_md: event.target.value })
                }
                placeholder="要解决的问题、验收条件、不要做什么…"
              />
            </label>
            <button className="button primary" disabled={busy} type="submit">
              {busy ? "创建中…" : "创建并打开任务"}
            </button>
          </form>
        </section>
      </div>

      <section className="panel">
        <div className="panel-heading">
          <h2>项目上下文</h2>
          <span className="muted">{notes.length} 条 note</span>
        </div>
        {notes.length === 0 ? (
          <div className="empty">
            还没有可复用 note。任务完成后，可以在任务页把结果接受为项目上下文。
          </div>
        ) : (
          <div className="note-list">
            {notes.map((note) => (
              <article className="note-row" key={note.id}>
                <div>
                  <div className="note-title">
                    {note.title}{" "}
                    {note.pinned ? (
                      <span className="badge badge-pinned">置顶</span>
                    ) : null}{" "}
                    <StatusBadge status={note.status} />
                  </div>
                  <div className="muted">
                    {note.kind} · {formatTime(note.updated_at)}
                    {note.task_id ? ` · task ${note.task_id.slice(0, 8)}` : ""}
                  </div>
                  {note.aliases?.length ? (
                    <div className="alias-list">
                      {note.aliases.map((alias) => (
                        <span className="alias-chip" key={alias}>
                          {alias}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  <pre className="note-content">{note.content_md}</pre>
                </div>
                <div className="note-actions">
                  <button
                    className="button small"
                    onClick={() => void toggleNotePin(note)}
                  >
                    {note.pinned ? "取消置顶" : "置顶"}
                  </button>
                  {note.status === "draft" && (
                    <button
                      className="button small"
                      onClick={() => void changeNote(note, "accepted")}
                    >
                      接受
                    </button>
                  )}
                  {note.status === "accepted" && (
                    <button
                      className="button small ghost"
                      onClick={() => void changeNote(note, "archived")}
                    >
                      归档
                    </button>
                  )}
                  <button
                    className="button small danger"
                    onClick={() => void removeNote(note)}
                  >
                    删除
                  </button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="panel">
        <div className="panel-heading">
          <h2>项目设置</h2>
          <span className="hint">工作区信任和权限配置</span>
        </div>
        <form className="settings-grid" onSubmit={saveSettings}>
          <label>
            项目名称
            <input
              value={settings.name}
              onChange={(event) =>
                setSettings({ ...settings, name: event.target.value })
              }
            />
          </label>
          <label>
            工作区路径
            <input
              className="mono"
              value={settings.workspace_path}
              onChange={(event) =>
                setSettings({ ...settings, workspace_path: event.target.value })
              }
            />
          </label>
          <label className="wide">
            项目 brief
            <textarea
              rows={4}
              value={settings.brief_md}
              onChange={(event) =>
                setSettings({ ...settings, brief_md: event.target.value })
              }
            />
          </label>
          <label className="wide">
            执行档允许的 PowerShell 模式
            <textarea
              rows={3}
              className="mono"
              value={settings.allowed_tools}
              onChange={(event) =>
                setSettings({ ...settings, allowed_tools: event.target.value })
              }
            />
          </label>
          <div className="wide">
            <button className="button primary" disabled={busy} type="submit">
              {busy ? "保存中…" : "保存项目设置"}
            </button>
          </div>
        </form>
        <div className="danger-zone">
          <div>
            <strong>删除项目</strong>
            <div className="hint">
              会级联删除任务、运行事件和项目 note，无法撤销。
            </div>
          </div>
          <button
            className="button danger"
            disabled={busy}
            onClick={() => void removeProject()}
          >
            删除项目
          </button>
        </div>
      </section>
    </div>
  );
}
