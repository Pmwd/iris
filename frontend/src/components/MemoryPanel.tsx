import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { errorText, formatTime } from "../format";
import { FACT_REASON_LABELS, FACT_SCOPE_LABELS } from "../labels";
import type { Session, SummaryResponse, Turn } from "../types";
import { MarkdownMessage } from "./MarkdownMessage";
import { StatusBadge } from "./StatusBadge";

export function MemoryPanel({
  session,
  summary,
  lastTurn,
  onChanged,
}: {
  session: Session;
  summary: SummaryResponse | null;
  lastTurn: Turn | null;
  onChanged: () => void;
}) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const latest = summary?.summary ?? null;
  const active = summary?.active ?? null;
  const included = lastTurn?.prompt_manifest?.included_facts ?? [];

  async function regenerate() {
    setBusy(true);
    setError(null);
    try {
      await api.requestSummary(session.id);
      onChanged();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  function extract() {
    const params = new URLSearchParams({ extract: "1", role: session.role });
    if (session.project_id) params.set("project_id", session.project_id);
    navigate(`/memory?${params.toString()}`);
  }

  return (
    <aside className="memory-panel">
      <div className="memory-head">
        <div>
          <div className="eyebrow">MEMORY</div>
          <h2>记忆</h2>
        </div>
        <button
          type="button"
          className="button small ghost"
          onClick={() => navigate("/memory")}
        >
          记忆库
        </button>
      </div>

      {error ? <div className="alert alert-error">{error}</div> : null}

      <section className="memory-section">
        <div className="memory-section-head">
          <span>会话摘要</span>
          {active ? <StatusBadge status={active.status} /> : null}
          <button
            type="button"
            className="button small ghost"
            onClick={() => void regenerate()}
            disabled={busy || Boolean(active)}
          >
            {busy ? "排队中…" : "重新生成"}
          </button>
        </div>
        {latest ? (
          <details className="summary-details">
            <summary>
              覆盖到第 {latest.covers_through_turn_seq} 轮 ·{" "}
              {formatTime(latest.completed_at ?? latest.updated_at)}
            </summary>
            <MarkdownMessage content={latest.content_md} />
          </details>
        ) : active ? (
          <div className="muted">摘要生成中…</div>
        ) : (
          <div className="muted">
            结束会话或达到阈值后会自动生成摘要。也可以现在手动生成。
          </div>
        )}
      </section>

      <section className="memory-section">
        <div className="memory-section-head">
          <span>本次注入的长期事实</span>
          <span className="pill">{included.length}</span>
        </div>
        {included.length ? (
          <ul className="fact-chip-list">
            {included.map((fact) => (
              <li key={fact.id} className="fact-chip">
                <span className="fact-chip-title">{fact.title}</span>
                <span className="muted">
                  {FACT_SCOPE_LABELS[fact.scope]} ·{" "}
                  {FACT_REASON_LABELS[fact.reason ?? ""] ?? fact.reason ?? "相关"}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <div className="muted">
            还没有已接受的事实命中本轮。到记忆库提取或手动添加。
          </div>
        )}
      </section>

      <div className="memory-actions">
        <button type="button" className="button primary" onClick={extract}>
          提取长期事实
        </button>
        <button
          type="button"
          className="button ghost"
          onClick={() => navigate("/memory")}
        >
          审核候选
        </button>
      </div>
      <div className="memory-note">
        候选事实需要你逐条接受后才会进入后续上下文；模型猜测不会自动成为事实。
      </div>
    </aside>
  );
}
