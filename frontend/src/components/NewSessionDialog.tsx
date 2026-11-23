import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { errorText } from "../format";
import { ROLE_LABELS, sessionPath } from "../labels";
import type { RoleId, Workspace } from "../types";

export function NewSessionDialog({
  role,
  onClose,
}: {
  role: RoleId;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState("");
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void (async () => {
      try {
        const items = await api.listWorkspaces();
        setWorkspaces(items);
        if (role === "coding" && items.length) setWorkspaceId(items[0].id);
      } catch (err) {
        setError(errorText(err));
      } finally {
        setLoading(false);
      }
    })();
  }, [role]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (role === "coding" && !workspaceId) {
      setError("Coding 会话必须选择一个工作区。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const session = await api.createSession({
        role,
        title: title.trim(),
        project_id: workspaceId || null,
      });
      onClose();
      navigate(sessionPath(session.role, session.id));
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="modal-head">
          <div>
            <div className="eyebrow">NEW SESSION</div>
            <h2>新 {ROLE_LABELS[role]} 会话</h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose}>
            ×
          </button>
        </div>

        {error ? <div className="alert alert-error">{error}</div> : null}

        {loading ? (
          <div className="muted">加载工作区…</div>
        ) : (
          <form className="stack" onSubmit={create}>
            <label>
              标题（可选）
              <input
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder={
                  role === "coding" ? "例如：修复登录回归" : "例如：比较三种向量检索方案"
                }
              />
            </label>
            <label>
              工作区{role === "coding" ? "（必选）" : "（可选）"}
              <select
                value={workspaceId}
                onChange={(event) => setWorkspaceId(event.target.value)}
              >
                {role === "scholar" ? (
                  <option value="">无工作区（纯研究）</option>
                ) : null}
                {workspaces.map((workspace) => (
                  <option key={workspace.id} value={workspace.id}>
                    {workspace.name} · {workspace.workspace_path}
                  </option>
                ))}
              </select>
            </label>
            {role === "coding" && workspaces.length === 0 ? (
              <div className="alert alert-warning">
                还没有工作区。先到「工作区」创建一个本地目录。
              </div>
            ) : null}
            <div className="modal-actions">
              <button type="button" className="button ghost" onClick={onClose}>
                取消
              </button>
              <button type="submit" className="button primary" disabled={busy}>
                {busy ? "创建中…" : "创建并打开"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
