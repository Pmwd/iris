import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { errorText, formatTime, splitLines } from "../format";
import { NOTE_KIND_LABELS } from "../labels";
import type { BackupInfo, Health, Note, Project } from "../types";
import { StatusBadge } from "../components/StatusBadge";

function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

export function ProjectsPage() {
  const navigate = useNavigate();
  const [projects, setProjects] = useState<Project[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [backups, setBackups] = useState<BackupInfo[]>([]);
  const [globalNotes, setGlobalNotes] = useState<Note[]>([]);
  const [loadingProjects, setLoadingProjects] = useState(true);
  const [loadingBackups, setLoadingBackups] = useState(true);
  const [loadingGlobal, setLoadingGlobal] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [backupBusy, setBackupBusy] = useState(false);
  const [globalBusy, setGlobalBusy] = useState(false);
  const [form, setForm] = useState({
    name: "",
    workspace_path: "",
    brief_md: "",
    allowed_tools: "PowerShell(python *)",
  });
  const [globalForm, setGlobalForm] = useState({
    title: "",
    content_md: "",
    aliases: "",
    kind: "note" as Note["kind"],
    pinned: false,
  });

  useEffect(() => {
    void api
      .listProjects()
      .then(setProjects)
      .catch((err) => setError(errorText(err)))
      .finally(() => setLoadingProjects(false));
    void api
      .listBackups()
      .then(setBackups)
      .catch((err) => setError(errorText(err)))
      .finally(() => setLoadingBackups(false));
    void api.health().then(setHealth).catch((err) => setError(errorText(err)));
  }, []);

  useEffect(() => {
    void api
      .listGlobalNotes()
      .then(setGlobalNotes)
      .catch((err) => setError(errorText(err)))
      .finally(() => setLoadingGlobal(false));
  }, []);

  async function refreshGlobalNotes() {
    const notes = await api.listGlobalNotes();
    setGlobalNotes(notes);
  }

  async function createGlobalNote(event: React.FormEvent) {
    event.preventDefault();
    setGlobalBusy(true);
    setError(null);
    try {
      await api.createGlobalNote({
        title: globalForm.title,
        content_md: globalForm.content_md,
        aliases: splitLines(globalForm.aliases),
        kind: globalForm.kind,
        status: "accepted",
        pinned: globalForm.pinned,
      });
      setGlobalForm({
        title: "",
        content_md: "",
        aliases: "",
        kind: "note",
        pinned: false,
      });
      await refreshGlobalNotes();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setGlobalBusy(false);
    }
  }

  async function toggleGlobalPin(note: Note) {
    try {
      await api.updateGlobalNote(note.id, { pinned: !note.pinned });
      await refreshGlobalNotes();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function changeGlobalStatus(note: Note, status: Note["status"]) {
    try {
      await api.updateGlobalNote(note.id, { status });
      await refreshGlobalNotes();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function removeGlobalNote(note: Note) {
    if (!window.confirm(`删除全局上下文 “${note.title}”？`)) return;
    try {
      await api.deleteGlobalNote(note.id);
      await refreshGlobalNotes();
    } catch (err) {
      setError(errorText(err));
    }
  }

  async function createBackup() {
    setBackupBusy(true);
    setError(null);
    try {
      const backup = await api.backup();
      setBackups((current) => [backup, ...current]);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBackupBusy(false);
    }
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const project = await api.createProject({
        name: form.name,
        workspace_path: form.workspace_path,
        brief_md: form.brief_md,
        allowed_tools: splitLines(form.allowed_tools),
      });
      setProjects((current) => [project, ...current]);
      navigate(`/projects/${project.id}`);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <section className="hero">
        <div>
          <div className="eyebrow">IRIS / LOCAL WORKBENCH</div>
          <h1>把任务、执行和上下文放在同一个地方。</h1>
          <p className="lede">
            创建一个项目，运行本地 Claude Code 任务，审查结果，并把值得复用的成果变成下一个任务的上下文。
          </p>
        </div>
        <div className="health-card">
          <div className="eyebrow">CLI STATUS</div>
          {health ? (
            <>
              <div className="health-row">
                <span>状态</span>
                <strong>{health.status}</strong>
              </div>
              <div className="health-row">
                <span>CLI</span>
                <strong>{health.cli.version ?? "未找到"}</strong>
              </div>
              <div className="health-row">
                <span>认证</span>
                <strong>
                  {health.cli.auth_ok === null
                    ? "未知"
                    : health.cli.auth_ok
                      ? "正常"
                      : "失败"}
                </strong>
              </div>
            </>
          ) : (
            <div className="muted">检查中…</div>
          )}
        </div>
      </section>

      {error && <div className="alert alert-error">{error}</div>}

      <div className="two-column">
        <section className="panel">
          <div className="panel-heading">
            <h2>项目</h2>
            <span className="muted">
              {loadingProjects ? "…" : `${projects.length} 个`}
            </span>
          </div>
          {loadingProjects ? (
            <div className="muted">加载项目…</div>
          ) : projects.length === 0 ? (
            <div className="empty">还没有项目。创建第一个本地工作区。</div>
          ) : (
            <div className="project-list">
              {projects.map((project) => (
                <Link
                  className="project-card"
                  key={project.id}
                  to={`/projects/${project.id}`}
                >
                  <div className="project-title">{project.name}</div>
                  <div className="muted mono">{project.workspace_path}</div>
                  <div className="project-brief">
                    {project.brief_md || "未填写项目说明"}
                  </div>
                </Link>
              ))}
            </div>
          )}
        </section>

        <section className="panel">
          <div className="panel-heading">
            <h2>新建项目</h2>
          </div>
          <form className="stack" onSubmit={submit}>
            <label>
              项目名称
              <input
                required
                value={form.name}
                onChange={(event) =>
                  setForm({ ...form, name: event.target.value })
                }
                placeholder="例如：expense-cli"
              />
            </label>
            <label>
              工作区路径
              <input
                required
                className="mono"
                value={form.workspace_path}
                onChange={(event) =>
                  setForm({ ...form, workspace_path: event.target.value })
                }
                placeholder="D:\\work\\expense-cli"
              />
            </label>
            <label>
              项目 brief
              <textarea
                rows={4}
                value={form.brief_md}
                onChange={(event) =>
                  setForm({ ...form, brief_md: event.target.value })
                }
                placeholder="项目目标、技术栈、约束、常用命令…"
              />
            </label>
            <label>
              执行档允许的 PowerShell 模式
              <textarea
                rows={3}
                className="mono"
                value={form.allowed_tools}
                onChange={(event) =>
                  setForm({ ...form, allowed_tools: event.target.value })
                }
                placeholder="每行一个，例如：PowerShell(python *)"
              />
              <span className="hint">
                仅“执行/测试”档位使用；只读和编辑档位不需要。
              </span>
            </label>
            <button className="button primary" disabled={busy} type="submit">
              {busy ? "创建中…" : "创建项目"}
            </button>
          </form>
        </section>
      </div>

      <section className="panel">
        <div className="panel-heading">
          <h2>全局上下文</h2>
          <span className="muted">
            {loadingGlobal ? "…" : `${globalNotes.length} 条`}
          </span>
        </div>
        <p className="hint">
          跨项目复用的个人偏好、长期决策或通用说明。goal / capability /
          blind_spot / progress / decision 是 Mentor 的已接受长期状态；只有你手写或接受的内容才会被引用。
          置顶只提高相关 note 的排序，不会绕过相关性自动注入。
        </p>
        <div className="two-column">
          <div>
            {loadingGlobal ? (
              <div className="muted">加载全局上下文…</div>
            ) : globalNotes.length === 0 ? (
              <div className="empty">还没有全局 note。</div>
            ) : (
              <div className="note-list">
                {globalNotes.map((note) => (
                  <article className="note-row" key={note.id}>
                    <div>
                      <div className="note-title">
                        {note.title}{" "}
                        <span className="badge">{note.scope === "global" ? "全局" : "项目"}</span>{" "}
                        <span className="badge">{NOTE_KIND_LABELS[note.kind]}</span>{" "}
                        {note.pinned ? <span className="badge badge-pinned">置顶</span> : null}{" "}
                        <StatusBadge status={note.status} />
                      </div>
                      <div className="muted">
                        {note.use_count ?? 0} 次使用 · {formatTime(note.updated_at)}
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
                        onClick={() => void toggleGlobalPin(note)}
                      >
                        {note.pinned ? "取消置顶" : "置顶"}
                      </button>
                      {note.status === "draft" && (
                        <button
                          className="button small"
                          onClick={() => void changeGlobalStatus(note, "accepted")}
                        >
                          接受
                        </button>
                      )}
                      {note.status === "accepted" && (
                        <button
                          className="button small ghost"
                          onClick={() => void changeGlobalStatus(note, "archived")}
                        >
                          归档
                        </button>
                      )}
                      <button
                        className="button small danger"
                        onClick={() => void removeGlobalNote(note)}
                      >
                        删除
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </div>
          <form className="stack" onSubmit={createGlobalNote}>
            <label>
              全局 note 标题
              <input
                required
                value={globalForm.title}
                onChange={(event) =>
                  setGlobalForm({ ...globalForm, title: event.target.value })
                }
                placeholder="例如：我的工作偏好"
              />
            </label>
            <label>
              类型
              <select
                value={globalForm.kind}
                onChange={(event) =>
                  setGlobalForm({
                    ...globalForm,
                    kind: event.target.value as Note["kind"],
                  })
                }
              >
                <option value="note">普通说明</option>
                <option value="goal">长期目标</option>
                <option value="capability">当前能力</option>
                <option value="blind_spot">盲区 / 反复问题</option>
                <option value="progress">阶段进展</option>
                <option value="decision">已确认选择</option>
              </select>
            </label>
            <label>
              内容
              <textarea
                rows={5}
                value={globalForm.content_md}
                onChange={(event) =>
                  setGlobalForm({ ...globalForm, content_md: event.target.value })
                }
                placeholder="希望后续任务复用的个人偏好、约定或长期决策…"
              />
            </label>
            <label>
              别名 / 标签（每行一个）
              <textarea
                rows={2}
                className="mono"
                value={globalForm.aliases}
                onChange={(event) =>
                  setGlobalForm({ ...globalForm, aliases: event.target.value })
                }
                placeholder="例如：安全、聚会、饮食禁忌"
              />
              <span className="hint">
                用来补充 note 的不同措辞，提升改写场景的召回。
              </span>
            </label>
            <label className="checkbox-row">
              <input
                type="checkbox"
                checked={globalForm.pinned}
                onChange={(event) =>
                  setGlobalForm({ ...globalForm, pinned: event.target.checked })
                }
              />
              置顶（优先排序，不强制注入）
            </label>
            <button className="button primary" disabled={globalBusy} type="submit">
              {globalBusy ? "添加中…" : "添加全局 note"}
            </button>
          </form>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <h2>数据维护</h2>
          <button
            className="button small"
            disabled={backupBusy}
            onClick={() => void createBackup()}
          >
            {backupBusy ? "备份中…" : "立即备份数据库"}
          </button>
        </div>
        <div className="muted">
          使用 SQLite 在线备份。恢复时请先停止后端，再替换 `data/iris.db`。
        </div>
        {loadingBackups ? (
          <div className="muted">加载备份…</div>
        ) : backups.length === 0 ? (
          <div className="empty">还没有备份。</div>
        ) : (
          <div className="backup-list">
            {backups.map((backup) => (
              <div className="backup-row" key={backup.name}>
                <span className="mono">{backup.name}</span>
                <span className="muted">
                  {formatTime(backup.created_at)} · {formatBytes(backup.size)}
                </span>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="note-panel">
        <strong>本地优先</strong>
        <span>
          任务、事件和上下文保存在本机。模型调用会把任务内容发送给 CLI
          配置的后端；Iris 不读取或记录 CLI 凭据。
        </span>
      </section>
    </div>
  );
}
