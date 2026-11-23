import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { errorText, formatTime, splitLines } from "../format";
import { sessionPath } from "../labels";
import type { Workspace } from "../types";
import { WorkspaceRunner } from "../components/WorkspaceRunner";

export function WorkspaceDetailPage() {
  const { workspaceId } = useParams();
  const navigate = useNavigate();
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [name, setName] = useState("");
  const [path, setPath] = useState("");
  const [brief, setBrief] = useState("");
  const [tools, setTools] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function load() {
    if (!workspaceId) return;
    setLoading(true);
    try {
      const data = await api.getWorkspace(workspaceId);
      setWorkspace(data);
      setName(data.name);
      setPath(data.workspace_path);
      setBrief(data.brief_md);
      setTools(data.allowed_tools.join("\n"));
      setError(null);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!workspaceId) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      await api.updateWorkspace(workspaceId, {
        name: name.trim(),
        workspace_path: path.trim(),
        brief_md: brief,
        allowed_tools: splitLines(tools),
      });
      setMessage("工作区已保存。");
      await load();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function newCodingSession() {
    if (!workspaceId) return;
    setBusy(true);
    setError(null);
    try {
      const session = await api.createSession({
        role: "coding",
        project_id: workspaceId,
      });
      navigate(sessionPath(session.role, session.id));
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  async function archive() {
    if (!workspaceId) return;
    setBusy(true);
    setError(null);
    try {
      await api.updateWorkspace(workspaceId, {
        archived: !workspace?.archived_at,
      });
      setMessage(workspace?.archived_at ? "工作区已恢复。" : "工作区已归档。");
      await load();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!workspaceId) return;
    if (!window.confirm("删除工作区不会删除本地文件，但会移除 Iris 里的配置。确定？")) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.deleteWorkspace(workspaceId);
      navigate("/workspaces");
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  if (loading || !workspace) {
    return (
      <div className="page">
        {error ? (
          <div className="alert alert-error">{error}</div>
        ) : (
          <div className="muted">加载工作区…</div>
        )}
      </div>
    );
  }

  return (
    <div className="page workspace-detail">
      <div className="breadcrumb">
        <Link to="/workspaces">工作区</Link>
        <span>/</span>
        <span>{workspace.name}</span>
      </div>

      <header className="page-header">
        <div>
          <div className="eyebrow">WORKSPACE</div>
          <h1>{workspace.name}</h1>
          <div className="mono muted">{workspace.workspace_path}</div>
        </div>
        <div className="inline-actions">
          <button
            type="button"
            className="button primary"
            onClick={() => void newCodingSession()}
            disabled={busy || Boolean(workspace.archived_at)}
          >
            ＋ Coding 会话
          </button>
          <button
            type="button"
            className="button ghost"
            onClick={() => void archive()}
            disabled={busy}
          >
            {workspace.archived_at ? "恢复" : "归档"}
          </button>
          <button
            type="button"
            className="button danger"
            onClick={() => void remove()}
            disabled={busy}
          >
            删除
          </button>
        </div>
      </header>

      {error ? <div className="alert alert-error">{error}</div> : null}
      {message ? <div className="alert alert-success">{message}</div> : null}
      {workspace.archived_at ? (
        <div className="alert alert-warning">该工作区已归档，不能新建会话。</div>
      ) : null}
      {workspace.security_warnings?.length ? (
        <div className="alert alert-warning">
          <strong>安全提示</strong>
          <ul>
            {workspace.security_warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="two-column">
        <section className="panel">
          <div className="panel-heading">
            <h2>设置</h2>
          </div>
          <form className="stack" onSubmit={save}>
            <label>
              名称
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </label>
            <label>
              本地目录
              <input
                className="mono"
                value={path}
                onChange={(event) => setPath(event.target.value)}
              />
            </label>
            <label>
              项目 brief
              <textarea
                rows={6}
                value={brief}
                onChange={(event) => setBrief(event.target.value)}
              />
            </label>
            <label>
              PowerShell 白名单（每行一个，仅 CLI 回退模式使用）
              <textarea
                rows={5}
                className="mono"
                value={tools}
                onChange={(event) => setTools(event.target.value)}
                placeholder="PowerShell(python *)"
              />
            </label>
            <button type="submit" className="button primary" disabled={busy}>
              {busy ? "保存中…" : "保存设置"}
            </button>
          </form>
        </section>

        <section className="panel">
          <div className="panel-heading">
            <h2>概览</h2>
          </div>
          <div className="status-list">
            <div className="status-row">
              <span>会话数</span>
              <span>{workspace.session_count ?? 0}</span>
            </div>
            <div className="status-row">
              <span>命令白名单</span>
              <span>{workspace.allowed_tools.length} 条</span>
            </div>
            <div className="status-row">
              <span>创建时间</span>
              <span className="muted">{formatTime(workspace.created_at)}</span>
            </div>
            <div className="status-row">
              <span>最近更新</span>
              <span className="muted">{formatTime(workspace.updated_at)}</span>
            </div>
          </div>
          <p className="hint">
            Coding 会话绑定此目录；SDK 模式下工具调用逐条审批，CLI 回退模式才使用白名单。删除工作区前需要先处理已有会话。
          </p>
        </section>
      </div>

      <WorkspaceRunner
        workspaceId={workspace.id}
        archived={Boolean(workspace.archived_at)}
      />
    </div>
  );
}
