import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api } from "../api";
import { formatTime } from "../format";
import { ROLE_LABELS, sessionPath } from "../labels";
import type { RoleId, Session, Workspace } from "../types";
import { NewSessionDialog } from "./NewSessionDialog";

function roleFromPath(pathname: string): RoleId | null {
  if (pathname.startsWith("/scholar")) return "scholar";
  if (pathname.startsWith("/coding")) return "coding";
  return null;
}

export function Sidebar() {
  const location = useLocation();
  const pathRole = roleFromPath(location.pathname);
  const role = pathRole ?? "coding";
  const [sessions, setSessions] = useState<Session[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [candidates, setCandidates] = useState(0);
  const [dialogOpen, setDialogOpen] = useState(false);

  async function refresh() {
    try {
      const [sessionList, workspaceList, facts] = await Promise.all([
        api.listSessions({ role, limit: 60 }),
        api.listWorkspaces(),
        api.listFacts({ status: "candidate", limit: 200 }),
      ]);
      setSessions(sessionList);
      setWorkspaces(workspaceList);
      setCandidates(facts.length);
    } catch {
      // sidebar is best-effort; pages surface their own errors
    }
  }

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname, location.key]);

  useEffect(() => {
    const timer = window.setInterval(() => void refresh(), 15000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role]);

  const workspaceNames = new Map(workspaces.map((item) => [item.id, item.name]));
  const parts = location.pathname.split("/").filter(Boolean);
  const currentId = parts.length ? parts[parts.length - 1] : "";

  return (
    <aside className="sidebar">
      <div className="brand-row">
        <Link className="brand" to="/coding">
          <span className="brand-mark">◒</span>
          <span>
            Iris
            <small>本地工作台</small>
          </span>
        </Link>
      </div>

      <div className="role-switch">
        <Link
          className={`role-tab${pathRole === "coding" ? " active" : ""}`}
          to="/coding"
        >
          Coding
        </Link>
        <Link
          className={`role-tab${pathRole === "scholar" ? " active" : ""}`}
          to="/scholar"
        >
          Scholar
        </Link>
      </div>

      <button
        type="button"
        className="button primary new-session"
        onClick={() => setDialogOpen(true)}
      >
        ＋ 新会话
      </button>

      <div className="sidebar-section-head">
        <span>{ROLE_LABELS[role]} 会话</span>
        <span className="pill">{sessions.length}</span>
      </div>

      <nav className="session-list">
        {sessions.length === 0 ? (
          <div className="sidebar-empty">还没有会话。创建一个开始。</div>
        ) : (
          sessions.map((session) => (
            <Link
              key={session.id}
              to={sessionPath(session.role, session.id)}
              className={`session-row${session.id === currentId ? " selected" : ""}`}
            >
              <span className={`session-status-dot status-${session.status}`} />
              <span className="session-row-main">
                <span className="session-row-title">{session.title}</span>
                <span className="session-row-meta">
                  {workspaceNames.get(session.project_id ?? "") ??
                    (session.role === "scholar" ? "无工作区" : "—")}
                  {" · "}
                  {formatTime(session.updated_at)}
                </span>
              </span>
            </Link>
          ))
        )}
      </nav>

      <div className="sidebar-footer">
        <Link className="sidebar-link" to="/memory">
          记忆库
          {candidates ? <span className="count-badge">{candidates}</span> : null}
        </Link>
        <Link className="sidebar-link" to="/workspaces">
          工作区
        </Link>
      </div>

      {dialogOpen ? (
        <NewSessionDialog role={role} onClose={() => setDialogOpen(false)} />
      ) : null}
    </aside>
  );
}
