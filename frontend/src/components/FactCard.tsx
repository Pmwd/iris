import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { errorText, formatTime } from "../format";
import {
  FACT_KIND_LABELS,
  FACT_ORIGIN_LABELS,
  FACT_RELATION_LABELS,
  FACT_ROLE_LABELS,
  FACT_SCOPE_LABELS,
  sessionPath,
} from "../labels";
import type { MemoryInboxGroup, Fact, Session, Workspace } from "../types";
import { MarkdownMessage } from "./MarkdownMessage";
import { StatusBadge } from "./StatusBadge";

export function FactCard({
  fact,
  workspaces,
  sessions = [],
  relationGroup,
  onChanged,
  onEdit,
}: {
  fact: Fact;
  workspaces: Workspace[];
  sessions?: Session[];
  relationGroup?: MemoryInboxGroup;
  onChanged: () => void;
  onEdit: (fact: Fact) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function update(body: Parameters<typeof api.updateFact>[1]) {
    setBusy(true);
    setError(null);
    try {
      await api.updateFact(fact.id, body);
      onChanged();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function archive() {
    setBusy(true);
    setError(null);
    try {
      await api.archiveFact(fact.id);
      onChanged();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function merge(mode: "merge" | "supersede" | "keep_both") {
    const target = relationGroup?.target_fact;
    if (!target) return;
    setBusy(true);
    setError(null);
    try {
      await api.mergeFact(fact.id, {
        target_fact_id: target.id,
        mode,
      });
      onChanged();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await api.confirmFact(fact.id);
      onChanged();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  const workspaceName =
    fact.scope === "workspace"
      ? workspaces.find((item) => item.id === fact.project_id)?.name ??
        fact.project_id?.slice(0, 8) ??
        "工作区"
      : null;

  return (
    <article className={`fact-card fact-${fact.status}`}>
      <div className="fact-card-head">
        <div className="fact-title-row">
          {fact.pinned ? (
            <span className="pin" title="置顶">
              📌
            </span>
          ) : null}
          <h3>{fact.title}</h3>
          <StatusBadge status={fact.status} />
        </div>
        <div className="fact-badges">
          <span className="pill">{FACT_KIND_LABELS[fact.kind]}</span>
          <span className="pill">
            {FACT_SCOPE_LABELS[fact.scope]}
            {workspaceName ? ` · ${workspaceName}` : ""}
          </span>
          <span className="pill">{FACT_ROLE_LABELS[fact.role]}</span>
          <span className="pill">{FACT_ORIGIN_LABELS[fact.origin] ?? fact.origin}</span>
          {fact.confidence !== null ? (
            <span className="pill">{Math.round(fact.confidence * 100)}%</span>
          ) : null}
          {fact.tags.map((tag) => (
            <span className="pill tag-pill" key={tag}>
              #{tag}
            </span>
          ))}
        </div>
      </div>

      {relationGroup?.target_fact ? (
        <div className="fact-relation-banner">
          <div>
            <strong>
              {FACT_RELATION_LABELS[relationGroup.kind] ?? relationGroup.kind}
            </strong>
            <span className="muted">
              {" "}
              与「{relationGroup.target_fact.title}」相似{" "}
              {Math.round(relationGroup.score * 100)}%
            </span>
          </div>
          <div className="inline-actions">
            <button
              type="button"
              className="button small"
              onClick={() => void merge("merge")}
              disabled={busy}
            >
              合并
            </button>
            <button
              type="button"
              className="button small ghost"
              onClick={() => void merge("supersede")}
              disabled={busy}
            >
              取代
            </button>
            <button
              type="button"
              className="button small ghost"
              onClick={() => void merge("keep_both")}
              disabled={busy}
            >
              都保留
            </button>
          </div>
        </div>
      ) : null}

      <div className="fact-content">
        <MarkdownMessage content={fact.content_md} />
      </div>

      {fact.source_session_ids.length ? (
        <div className="fact-sources">
          来源：
          {fact.source_session_ids.map((sessionId) => {
            const source = sessions.find((item) => item.id === sessionId);
            return source ? (
              <Link
                key={sessionId}
                to={sessionPath(source.role, source.id)}
                className="source-link"
              >
                {source.title || sessionId.slice(0, 8)}
              </Link>
            ) : (
              <span key={sessionId} className="muted">
                {sessionId.slice(0, 8)}
              </span>
            );
          })}
        </div>
      ) : null}

      {fact.valid_until ? (
        <div className="fact-note">
          有效期至 {formatTime(fact.valid_until)}
          {fact.status === "accepted" ? (
            <button
              type="button"
              className="link-button"
              onClick={() => void confirm()}
              disabled={busy}
            >
              仍然有效
            </button>
          ) : null}
        </div>
      ) : null}

      {fact.supersedes_id ? (
        <div className="fact-note">
          接受后会归档并替换事实 {fact.supersedes_id.slice(0, 8)}。
        </div>
      ) : null}

      {fact.evidence_md ? (
        <details className="fact-evidence">
          <summary>提取依据</summary>
          <pre>{fact.evidence_md}</pre>
        </details>
      ) : null}

      <div className="fact-meta">
        <span>使用 {fact.use_count} 次</span>
        {fact.source_session_ids.length ? (
          <span>来源 {fact.source_session_ids.length} 个会话</span>
        ) : null}
        <span>{formatTime(fact.updated_at)}</span>
      </div>

      {error ? <div className="alert alert-error">{error}</div> : null}

      <div className="fact-actions">
        {fact.status === "candidate" ? (
          <>
            <button
              type="button"
              className="button primary small"
              onClick={() => void update({ status: "accepted" })}
              disabled={busy}
            >
              接受
            </button>
            <button
              type="button"
              className="button small ghost"
              onClick={() => onEdit(fact)}
              disabled={busy}
            >
              编辑
            </button>
            <button
              type="button"
              className="button small danger"
              onClick={() => void update({ status: "rejected" })}
              disabled={busy}
            >
              拒绝
            </button>
          </>
        ) : null}

        {fact.status === "accepted" ? (
          <>
            <button
              type="button"
              className="button small ghost"
              onClick={() => void update({ pinned: !fact.pinned })}
              disabled={busy}
            >
              {fact.pinned ? "取消置顶" : "置顶"}
            </button>
            <button
              type="button"
              className="button small ghost"
              onClick={() => onEdit(fact)}
              disabled={busy}
            >
              编辑
            </button>
            <button
              type="button"
              className="button small danger"
              onClick={() => void archive()}
              disabled={busy}
            >
              归档
            </button>
          </>
        ) : null}

        {fact.status === "rejected" || fact.status === "archived" ? (
          <button
            type="button"
            className="button small"
            onClick={() => void update({ status: "candidate" })}
            disabled={busy}
          >
            恢复为候选
          </button>
        ) : null}
      </div>
    </article>
  );
}
