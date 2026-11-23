import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { NewSessionDialog } from "../components/NewSessionDialog";
import { StatusBadge } from "../components/StatusBadge";
import { errorText, formatTime } from "../format";
import { ROLE_DESCRIPTIONS, ROLE_LABELS, sessionPath } from "../labels";
import type { RoleId, Session, Workspace } from "../types";

export function RoleHome() {
  const { role } = useParams();
  const navigate = useNavigate();
  const roleId: RoleId | null =
    role === "scholar" ? "scholar" : role === "coding" ? "coding" : null;
  const [sessions, setSessions] = useState<Session[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  useEffect(() => {
    if (!roleId) {
      navigate("/coding", { replace: true });
      return;
    }
    setLoading(true);
    setError(null);
    void (async () => {
      try {
        const [list, workspaceList] = await Promise.all([
          api.listSessions({ role: roleId }),
          api.listWorkspaces(),
        ]);
        setSessions(list);
        setWorkspaces(workspaceList);
      } catch (err) {
        setError(errorText(err));
      } finally {
        setLoading(false);
      }
    })();
  }, [roleId, navigate]);

  if (!roleId) return null;
  const workspaceNames = new Map(workspaces.map((item) => [item.id, item.name]));

  return (
    <div className="page role-home">
      <header className="page-header">
        <div>
          <div className="eyebrow">{roleId.toUpperCase()}</div>
          <h1>{ROLE_LABELS[roleId]}</h1>
          <p className="muted">{ROLE_DESCRIPTIONS[roleId]}</p>
        </div>
        <button
          type="button"
          className="button primary"
          onClick={() => setDialogOpen(true)}
        >
          ＋ 新会话
        </button>
      </header>

      {error ? <div className="alert alert-error">{error}</div> : null}

      {loading ? (
        <div className="muted">加载会话…</div>
      ) : sessions.length === 0 ? (
        <div className="empty-state">
          <div className="empty-illustration">✦</div>
          <h2>开始第一个 {ROLE_LABELS[roleId]} 会话</h2>
          <p className="muted">
            每次会话的原始消息与工具调用都会保存；结束后自动生成摘要；多次会话可以提取成经你审核的长期事实。
          </p>
          <button
            type="button"
            className="button primary"
            onClick={() => setDialogOpen(true)}
          >
            创建会话
          </button>
          {roleId === "coding" && workspaces.length === 0 ? (
            <p className="muted">
              还没有工作区？<Link to="/workspaces">先添加一个本地目录</Link>。
            </p>
          ) : null}
        </div>
      ) : (
        <div className="session-cards">
          {sessions.map((session) => (
            <Link
              key={session.id}
              className="session-card"
              to={sessionPath(session.role, session.id)}
            >
              <div className="session-card-head">
                <h3>{session.title}</h3>
                <StatusBadge status={session.status} />
              </div>
              <div className="session-card-meta">
                <span>
                  {workspaceNames.get(session.project_id ?? "") ??
                    (session.role === "scholar" ? "无工作区" : "—")}
                </span>
                <span>更新 {formatTime(session.updated_at)}</span>
              </div>
              <div className="session-card-foot">
                {session.cli_session_confirmed ? (
                  <span className="pill pill-ok">CLI 会话已建立</span>
                ) : (
                  <span className="pill">尚未运行</span>
                )}
                {session.summary_covers_turn_seq ? (
                  <span className="pill">
                    摘要覆盖 {session.summary_covers_turn_seq} 轮
                  </span>
                ) : null}
              </div>
            </Link>
          ))}
        </div>
      )}

      {dialogOpen ? (
        <NewSessionDialog role={roleId} onClose={() => setDialogOpen(false)} />
      ) : null}
    </div>
  );
}
