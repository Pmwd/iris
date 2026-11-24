import { useState } from "react";
import { api } from "../api";
import { errorText, splitLines } from "../format";
import {
  FACT_KINDS,
  FACT_KIND_HINTS,
  FACT_KIND_LABELS,
  FACT_ROLE_LABELS,
  FACT_SCOPE_LABELS,
} from "../labels";
import type {
  FactKind,
  FactRole,
  FactScope,
  Message,
  Session,
  Workspace,
} from "../types";

function firstLine(text: string): string {
  const line = text
    .split("\n")
    .map((item) => item.replace(/^[#>*\-\s]+/, "").trim())
    .find(Boolean);
  return (line ?? "").slice(0, 120);
}

export function RememberDialog({
  message,
  session,
  workspace,
  onClose,
  onSaved,
}: {
  message: Message;
  session: Session;
  workspace: Workspace | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [title, setTitle] = useState(firstLine(message.content) || "一条记忆");
  const [content, setContent] = useState(message.content);
  const [scope, setScope] = useState<FactScope>(
    session.project_id ? "workspace" : "global",
  );
  const [role, setRole] = useState<FactRole>(session.role);
  const [kind, setKind] = useState<FactKind>("insight");
  const [aliases, setAliases] = useState("");
  const [tags, setTags] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function save() {
    if (!title.trim() || !content.trim()) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await api.rememberFact({
        text: content,
        title: title.trim(),
        scope,
        project_id: scope === "workspace" ? session.project_id : null,
        role,
        kind,
        aliases: splitLines(aliases),
        tags: splitLines(tags),
        source_session_id: session.id,
        source_turn_id: message.turn_id,
        accept: true,
      });
      onSaved();
      if (result.needs_review) {
        setNotice(
          "已放入记忆收件箱：它与已有记忆可能重复或冲突，请审核后再接受。",
        );
      } else {
        setNotice(result.accepted ? "已记住，并会在相关会话中召回。" : "已保存为候选。");
      }
    } catch (err) {
      setError(errorText(err));
    } finally {
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
            <div className="eyebrow">REMEMBER</div>
            <h2>记住这条</h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose}>
            ×
          </button>
        </div>
        {error ? <div className="alert alert-error">{error}</div> : null}
        {notice ? <div className="alert alert-success">{notice}</div> : null}
        <div className="stack">
          <div className="form-row">
            <label>
              作用域
              <select
                value={scope}
                onChange={(event) => setScope(event.target.value as FactScope)}
              >
                {(["workspace", "global"] as FactScope[]).map((value) => (
                  <option key={value} value={value} disabled={value === "workspace" && !session.project_id}>
                    {FACT_SCOPE_LABELS[value]}
                    {value === "workspace" && workspace ? ` · ${workspace.name}` : ""}
                  </option>
                ))}
              </select>
            </label>
            <label>
              适用角色
              <select
                value={role}
                onChange={(event) => setRole(event.target.value as FactRole)}
              >
                {(["both", "coding", "scholar"] as FactRole[]).map((value) => (
                  <option key={value} value={value}>
                    {FACT_ROLE_LABELS[value]}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <label>
            类型
            <select
              value={kind}
              onChange={(event) => setKind(event.target.value as FactKind)}
            >
              {FACT_KINDS.map((value) => (
                <option key={value} value={value}>
                  {FACT_KIND_LABELS[value]} · {FACT_KIND_HINTS[value]}
                </option>
              ))}
            </select>
          </label>
          <label>
            标题
            <input value={title} onChange={(event) => setTitle(event.target.value)} />
          </label>
          <label>
            内容
            <textarea
              rows={5}
              value={content}
              onChange={(event) => setContent(event.target.value)}
            />
          </label>
          <div className="form-row">
            <label>
              别名 / 关键词（每行一个）
              <textarea
                rows={2}
                className="mono"
                value={aliases}
                onChange={(event) => setAliases(event.target.value)}
              />
            </label>
            <label>
              标签（每行一个）
              <textarea
                rows={2}
                className="mono"
                value={tags}
                onChange={(event) => setTags(event.target.value)}
              />
            </label>
          </div>
          <div className="modal-actions">
            <button type="button" className="button ghost" onClick={onClose}>
              关闭
            </button>
            <button
              type="button"
              className="button primary"
              onClick={() => void save()}
              disabled={busy || !title.trim() || !content.trim()}
            >
              {busy ? "保存中…" : "记住"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
