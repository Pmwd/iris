import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { errorText, formatTime, splitLines } from "../format";
import type { BackupInfo, Health, Workspace } from "../types";

export function WorkspacesPage() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [backups, setBackups] = useState<BackupInfo[]>([]);
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [brief, setBrief] = useState("");
  const [tools, setTools] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function load() {
    try {
      const [workspaceList, healthData, backupList] = await Promise.all([
        api.listWorkspaces(),
        api.health().catch(() => null),
        api.listBackups().catch(() => []),
      ]);
      setWorkspaces(workspaceList);
      setHealth(healthData);
      setBackups(backupList);
    } catch (err) {
      setError(errorText(err));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await api.createWorkspace({
        name: name.trim(),
        workspace_path: path.trim(),
        brief_md: brief,
        allowed_tools: splitLines(tools),
      });
      setName("");
      setPath("");
      setBrief("");
      setTools("");
      setMessage("工作区已创建。");
      await load();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function createBackup() {
    setBusy(true);
    setError(null);
    try {
      await api.backup();
      setMessage("数据库备份已创建。");
      await load();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page workspaces-page">
      <header className="page-header">
        <div>
          <div className="eyebrow">WORKSPACES</div>
          <h1>工作区</h1>
          <p className="muted">
            Coding 会话必须绑定一个本地目录；Scholar 会话可选。工作区设置包括 brief 和允许的 PowerShell 模式。
          </p>
        </div>
      </header>

      {error ? <div className="alert alert-error">{error}</div> : null}
      {message ? <div className="alert alert-success">{message}</div> : null}

      <div className="workspace-layout">
        <section className="panel">
          <div className="panel-heading">
            <h2>已有工作区</h2>
            <span className="muted">{workspaces.length} 个</span>
          </div>
          {workspaces.length === 0 ? (
            <div className="empty">还没有工作区。</div>
          ) : (
            <div className="workspace-list">
              {workspaces.map((workspace) => (
                <Link
                  key={workspace.id}
                  className="workspace-card"
                  to={`/workspaces/${workspace.id}`}
                >
                  <div className="workspace-card-head">
                    <h3>{workspace.name}</h3>
                    {workspace.archived_at ? (
                      <span className="pill">已归档</span>
                    ) : null}
                  </div>
                  <div className="mono muted">{workspace.workspace_path}</div>
                  {workspace.brief_md ? (
                    <p className="workspace-brief">{workspace.brief_md}</p>
                  ) : null}
                  <div className="workspace-card-foot">
                    <span className="pill">
                      {workspace.allowed_tools.length} 条命令白名单
                    </span>
                    <span>更新 {formatTime(workspace.updated_at)}</span>
                  </div>
                </Link>
              ))}
            </div>
          )}
        </section>

        <div className="workspace-side">
          <section className="panel">
            <div className="panel-heading">
              <h2>新建工作区</h2>
            </div>
            <form className="stack" onSubmit={create}>
              <label>
                名称
                <input
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="例如：Iris 后端"
                />
              </label>
              <label>
                本地目录
                <input
                  className="mono"
                  value={path}
                  onChange={(event) => setPath(event.target.value)}
                  placeholder="D:\\vibe\\Iris"
                />
              </label>
              <label>
                项目 brief（可选）
                <textarea
                  rows={3}
                  value={brief}
                  onChange={(event) => setBrief(event.target.value)}
                  placeholder="技术栈、约束、关键目录…"
                />
              </label>
              <label>
                PowerShell 白名单（每行一个，可选）
                <textarea
                  rows={3}
                  className="mono"
                  value={tools}
                  onChange={(event) => setTools(event.target.value)}
                  placeholder="PowerShell(python *)"
                />
              </label>
              <button type="submit" className="button primary" disabled={busy}>
                {busy ? "创建中…" : "创建工作区"}
              </button>
            </form>
          </section>

          <section className="panel">
            <div className="panel-heading">
              <h2>运行状态</h2>
            </div>
            {health ? (
              <div className="status-list">
                <div className="status-row">
                  <span>状态</span>
                  <span className={`pill ${health.status === "ok" ? "pill-ok" : "pill-error"}`}>
                    {health.status}
                  </span>
                </div>
                <div className="status-row">
                  <span>CLI</span>
                  <span className="muted">
                    {health.cli.installed
                      ? health.cli.version ?? "已安装"
                      : "未安装"}
                  </span>
                </div>
                <div className="status-row">
                  <span>认证</span>
                  <span className="muted">
                    {health.cli.auth_ok === null
                      ? "未知"
                      : health.cli.auth_ok
                        ? "已登录"
                        : "未登录"}
                  </span>
                </div>
                <div className="status-row">
                  <span>数据目录</span>
                  <span className="mono muted">{health.data_dir}</span>
                </div>
              </div>
            ) : (
              <div className="muted">无法读取健康状态。</div>
            )}
          </section>

          <section className="panel">
            <div className="panel-heading">
              <h2>备份</h2>
              <button
                type="button"
                className="button small"
                onClick={() => void createBackup()}
                disabled={busy}
              >
                立即备份
              </button>
            </div>
            {backups.length === 0 ? (
              <div className="muted">还没有备份。</div>
            ) : (
              <ul className="backup-list">
                {backups.slice(0, 5).map((item) => (
                  <li key={item.path}>
                    <span className="mono">{item.name}</span>
                    <span className="muted">
                      {(item.size / 1024 / 1024).toFixed(1)} MB
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
