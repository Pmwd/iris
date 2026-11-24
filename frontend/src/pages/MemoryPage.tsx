import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import { ExtractionPanel } from "../components/ExtractionPanel";
import { FactCard } from "../components/FactCard";
import { FactEditor } from "../components/FactEditor";
import { errorText } from "../format";
import type {
  Fact,
  FactStatus,
  MemoryInbox,
  MemoryInboxGroup,
  RoleId,
  Session,
  Workspace,
} from "../types";

const TABS: Array<{ id: FactStatus; label: string }> = [
  { id: "candidate", label: "候选" },
  { id: "accepted", label: "已接受" },
  { id: "rejected", label: "已拒绝" },
  { id: "archived", label: "已归档" },
];

export function MemoryPage() {
  const [params] = useSearchParams();
  const roleParam = params.get("role");
  const initialRole: RoleId | null =
    roleParam === "coding" || roleParam === "scholar" ? roleParam : null;
  const initialProjectId = params.get("project_id");
  const [tab, setTab] = useState<FactStatus>("candidate");
  const [facts, setFacts] = useState<Fact[]>([]);
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [inbox, setInbox] = useState<MemoryInbox | null>(null);
  const [queryText, setQueryText] = useState(params.get("q") ?? "");
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showExtract, setShowExtract] = useState(params.get("extract") === "1");
  const [editor, setEditor] = useState<{ fact: Fact | null } | null>(null);

  async function load() {
    try {
      const q = queryText.trim() || undefined;
      const [
        workspaceList,
        sessionList,
        inboxData,
        candidate,
        accepted,
        rejected,
        archived,
      ] = await Promise.all([
        api.listWorkspaces(),
        api.listSessions({ limit: 500 }),
        api.getMemoryInbox({ role: initialRole ?? undefined, project_id: initialProjectId }),
        api.listFacts({ status: "candidate", limit: 500, q }),
        api.listFacts({ status: "accepted", limit: 500, q }),
        api.listFacts({ status: "rejected", limit: 500, q }),
        api.listFacts({ status: "archived", limit: 500, q }),
      ]);
      setWorkspaces(workspaceList);
      setSessions(sessionList);
      setInbox(inboxData);
      setCounts({
        candidate: candidate.length,
        accepted: accepted.length,
        rejected: rejected.length,
        archived: archived.length,
      });
      const byStatus: Record<FactStatus, Fact[]> = {
        candidate,
        accepted,
        rejected,
        archived,
      };
      setFacts(byStatus[tab]);
      setError(null);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    const next = params.get("q");
    if (next !== null && next !== queryText) setQueryText(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [params]);

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, queryText]);

  const relationByCandidate = new Map<string, MemoryInboxGroup>();
  for (const group of inbox?.groups ?? []) {
    for (const candidate of group.candidates) {
      relationByCandidate.set(candidate.id, group);
    }
  }

  return (
    <div className="page memory-page">
      <header className="page-header">
        <div>
          <div className="eyebrow">MEMORY</div>
          <h1>长期记忆</h1>
          <p className="muted">
            从多次会话摘要中提取候选事实；只有你接受的内容会进入后续上下文。
          </p>
        </div>
        <div className="inline-actions">
          <button
            type="button"
            className="button ghost"
            onClick={() => setShowExtract((value) => !value)}
          >
            {showExtract ? "收起提取" : "提取事实"}
          </button>
          <button
            type="button"
            className="button primary"
            onClick={() => setEditor({ fact: null })}
          >
            ＋ 手动添加
          </button>
        </div>
      </header>

      {error ? <div className="alert alert-error">{error}</div> : null}

      <div className="memory-toolbar">
        <input
          value={queryText}
          onChange={(event) => setQueryText(event.target.value)}
          placeholder="搜索记忆标题、内容、别名、标签…"
        />
        {queryText ? (
          <button type="button" className="button small ghost" onClick={() => setQueryText("")}>
            清除
          </button>
        ) : null}
      </div>

      {inbox ? (
        <div className="inbox-banner">
          <div>
            <strong>记忆收件箱</strong>
            <span className="muted">
              {" "}
              {inbox.counts.candidates} 个候选 · {inbox.counts.duplicates} 个可能重复 ·{" "}
              {inbox.counts.conflicts} 个可能冲突 · {inbox.counts.needs_confirmation} 个需确认
            </span>
          </div>
          {inbox.stale.length ? (
            <span className="pill pill-error">有过期事实</span>
          ) : null}
        </div>
      ) : null}

      {showExtract ? (
        <ExtractionPanel
          workspaces={workspaces}
          initialRole={initialRole}
          initialProjectId={initialProjectId}
          onDone={() => {
            setTab("candidate");
            void load();
          }}
        />
      ) : null}

      <div className="tabs">
        {TABS.map((item) => (
          <button
            type="button"
            key={item.id}
            className={`tab${tab === item.id ? " active" : ""}`}
            onClick={() => setTab(item.id)}
          >
            {item.label}
            <span className="tab-count">{counts[item.id] ?? 0}</span>
          </button>
        ))}
      </div>

      {loading ? (
        <div className="muted">加载记忆…</div>
      ) : facts.length === 0 ? (
        <div className="empty-state">
          <div className="empty-illustration">◇</div>
          <h2>
            {tab === "candidate"
              ? "还没有候选事实"
              : tab === "accepted"
                ? "还没有已接受事实"
                : "这里没有内容"}
          </h2>
          <p className="muted">
            {tab === "candidate"
              ? "先结束一个会话生成摘要，再用「提取事实」生成候选；也可以手动添加。"
              : "接受候选或手动添加后会出现在这里。"}
          </p>
        </div>
      ) : (
        <div className="fact-list">
          {facts.map((fact) => (
            <FactCard
              key={fact.id}
              fact={fact}
              workspaces={workspaces}
              sessions={sessions}
              relationGroup={relationByCandidate.get(fact.id)}
              onChanged={() => void load()}
              onEdit={(target) => setEditor({ fact: target })}
            />
          ))}
        </div>
      )}

      {editor ? (
        <FactEditor
          fact={editor.fact}
          workspaces={workspaces}
          onClose={() => setEditor(null)}
          onSaved={() => {
            void load();
          }}
        />
      ) : null}
    </div>
  );
}
