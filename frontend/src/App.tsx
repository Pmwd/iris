import { Link, Route, Routes } from "react-router-dom";
import { ProjectPage } from "./pages/ProjectPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { TaskPage } from "./pages/TaskPage";

export function App() {
  return (
    <div className="app-shell">
      <header className="app-header">
        <Link className="brand" to="/">
          <span className="brand-mark">◒</span>
          <span>
            Iris
            <small>local workbench</small>
          </span>
        </Link>
        <nav>
          <Link to="/">项目</Link>
        </nav>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<ProjectsPage />} />
          <Route path="/projects/:projectId" element={<ProjectPage />} />
          <Route
            path="/projects/:projectId/tasks/:taskId"
            element={<TaskPage />}
          />
          <Route
            path="*"
            element={
              <div className="page">
                <div className="empty">页面不存在。</div>
              </div>
            }
          />
        </Routes>
      </main>
      <footer className="app-footer">
        Iris · 本地优先 · 结果需要审查后才会成为上下文
      </footer>
    </div>
  );
}
