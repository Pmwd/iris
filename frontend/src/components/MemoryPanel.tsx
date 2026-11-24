import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import { errorText, formatTime } from "../format";
import { FACT_REASON_LABELS, FACT_SCOPE_LABELS } from "../labels";
import type {
  MemoryInbox,
  Session,
  SummaryResponse,
  Turn,
} from "../types";
import { MarkdownMessage } from "./MarkdownMessage";
import { RelatedMemories } from "./RelatedMemories";
import { StatusBadge } from "./StatusBadge";

export function MemoryPanel({
  session,
  summary,
  lastTurn,
  relatedQuery = "",
  onChanged,
}: {
  session: Session;
  summary: SummaryResponse | null;
  lastTurn: Turn | null;
  relatedQuery?: string;
  onChanged: () => void;
}) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inbox, setInbox] = useState<MemoryInbox | null>(null);

  const latest = summary?.summary ?? null;
  const active = summary?.active ?? null;
  const included = lastTurn?.prompt_manifest?.included_facts ?? [];
  const excluded = lastTurn?.prompt_manifest?.excluded_facts ?? [];
  const selection = lastTurn?.prompt_manifest?.selection;

  useEffect(() => {
    let cancelled = false;
    let timer: number | undefined;

    function loadInbox() {
      api
        .getMemoryInbox({ role: session.role, project_id: session.project_id })
        .then((data) => {
          if (!cancelled) setInbox(data);
        })
        .catch(() => {
          if (!cancelled) setInbox(null);
        });
    }

    loadInbox();
    timer = window.setInterval(loadInbox, 10_000);
    return () => {
      cancelled = true;
      if (timer) window.clearInterval(timer);
    };
  }, [session.role, session.project_id, lastTurn?.id, summary?.summary?.id]);

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

      <RelatedMemories
        query={relatedQuery}
        role={session.role}
        projectId={session.project_id}
      />

      {inbox && inbox.counts.candidates > 0 ? (
        <section className="memory-section inbox-summary">
          <div className="memory-section-head">
            <span>记忆收件箱</span>
            <span className="pill">{inbox.counts.candidates}</span>
          </div>
          <div className="memory-note">
            {inbox.counts.duplicates} 个可能重复 · {inbox.counts.conflicts} 个可能冲突
          </div>
          <button
            type="button"
            className="button small primary"
            onClick={() => navigate("/memory")}
          >
            去审核
          </button>
        </section>
      ) : null}

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
                  {typeof fact.score === "number"
                    ? ` · ${Math.round(fact.score * 100)}%`
                    : ""}
                </span>
                {fact.source_session_ids?.length ? (
                  <button
                    type="button"
                    className="link-button"
                    onClick={() => navigate("/memory")}
                  >
                    来源
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <div className="muted">
            {selection?.abstained
              ? `本轮没有注入记忆（${
                  FACT_REASON_LABELS[selection.abstain_reason ?? ""] ??
                  selection.abstain_reason ??
                  "无相关记忆"
                }）。`
              : "还没有已接受的事实命中本轮。到记忆库提取或手动添加。"}
          </div>
        )}
        {excluded.length ? (
          <details className="excluded-facts">
            <summary>{excluded.length} 条未注入（查看原因）</summary>
            <ul className="fact-chip-list">
              {excluded.slice(0, 12).map((fact) => (
                <li key={fact.id} className="fact-chip">
                  <span className="fact-chip-title">{fact.title}</span>
                  <span className="muted">
                    {FACT_REASON_LABELS[fact.reason] ?? fact.reason}
                  </span>
                </li>
              ))}
            </ul>
          </details>
        ) : null}
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
