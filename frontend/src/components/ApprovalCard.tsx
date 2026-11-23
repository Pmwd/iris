import { useState } from "react";
import { api } from "../api";
import { errorText, formatTime } from "../format";
import type { Approval, ApprovalDecision } from "../types";

const STATUS_TEXT: Record<string, string> = {
  pending: "等待批准",
  allowed: "已允许",
  denied: "已拒绝",
  expired: "已过期",
};

export function ApprovalCard({ approval: initial }: { approval: Approval }) {
  const [approval, setApproval] = useState<Approval>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pending = approval.status === "pending";
  const input = approval.input ?? {};
  const command = typeof input.command === "string" ? input.command : null;
  const filePath =
    typeof input.file_path === "string"
      ? input.file_path
      : typeof input.notebook_path === "string"
        ? input.notebook_path
        : null;
  const content = typeof input.content === "string" ? input.content : null;
  const alwaysLabel = command
    ? "总是允许此类命令"
    : filePath
      ? "总是允许此文件"
      : "总是允许此操作";

  async function decide(decision: ApprovalDecision) {
    setBusy(true);
    setError(null);
    try {
      const updated = await api.decideApproval(approval.id, decision);
      setApproval((current) => ({
        ...current,
        ...updated,
        title: updated.title ?? current.title,
        description: updated.description ?? current.description,
      }));
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={`approval-card${pending ? " approval-pending" : ""}`}>
      <div className="approval-head">
        <span className={`approval-dot${pending ? " pending" : ""}`} />
        <strong>{pending ? "需要批准" : "工具审批"}</strong>
        <span className="pill">{approval.tool_name}</span>
        <span
          className={`pill ${
            approval.status === "allowed"
              ? "pill-ok"
              : approval.status === "denied" || approval.status === "expired"
                ? "pill-error"
                : "pill-live"
          }`}
        >
          {STATUS_TEXT[approval.status] ?? approval.status}
        </span>
        {approval.created_at ? (
          <span className="muted approval-time">
            {formatTime(approval.created_at)}
          </span>
        ) : null}
      </div>

      {approval.title ? (
        <div className="approval-title">{approval.title}</div>
      ) : null}
      {approval.description ? (
        <div className="muted approval-desc">{approval.description}</div>
      ) : null}

      {command ? <pre className="approval-command">{command}</pre> : null}
      {filePath ? (
        <div className="approval-file">
          文件：<code>{filePath}</code>
        </div>
      ) : null}
      {content ? (
        <details className="approval-content">
          <summary>查看写入内容</summary>
          <pre>
            {content.slice(0, 4000)}
            {content.length > 4000 ? "\n…" : ""}
          </pre>
        </details>
      ) : null}
      {!command && !filePath && !content ? (
        <pre className="approval-command">
          {JSON.stringify(input, null, 2)}
        </pre>
      ) : null}

      <div className="approval-warning">
        该操作会以 Iris 后端用户身份执行。只批准你理解的操作。
      </div>

      {pending ? (
        <div className="approval-actions">
          <button
            type="button"
            className="button primary"
            onClick={() => void decide("allow")}
            disabled={busy}
          >
            允许一次
          </button>
          <button
            type="button"
            className="button"
            onClick={() => void decide("always")}
            disabled={busy}
          >
            {alwaysLabel}
          </button>
          <button
            type="button"
            className="button danger"
            onClick={() => void decide("deny")}
            disabled={busy}
          >
            拒绝
          </button>
        </div>
      ) : (
        <div className="approval-result">
          {approval.message || STATUS_TEXT[approval.status] || approval.status}
          {approval.decision === "always" ? "（已在本次会话记住规则）" : ""}
        </div>
      )}

      {error ? <div className="alert alert-error">{error}</div> : null}
    </section>
  );
}
