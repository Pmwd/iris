import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import { DashboardPage } from "./pages/DashboardPage";
import { MemoryPage } from "./pages/MemoryPage";
import { RoleHome } from "./pages/RoleHome";
import { SessionPage } from "./pages/SessionPage";
import { WorkspaceDetailPage } from "./pages/WorkspaceDetailPage";
import { WorkspacesPage } from "./pages/WorkspacesPage";

export function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<Navigate to="/coding" replace />} />
        <Route path="/dashboard" element={<DashboardPage />} />
        <Route path="/memory" element={<MemoryPage />} />
        <Route path="/workspaces" element={<WorkspacesPage />} />
        <Route path="/workspaces/:workspaceId" element={<WorkspaceDetailPage />} />
        <Route path="/:role" element={<RoleHome />} />
        <Route path="/:role/:sessionId" element={<SessionPage />} />
        <Route
          path="*"
          element={
            <div className="page-empty">
              <h2>页面不存在</h2>
              <p className="muted">检查地址，或从左侧选择一个角色。</p>
            </div>
          }
        />
      </Route>
    </Routes>
  );
}
