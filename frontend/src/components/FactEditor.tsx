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
  Fact,
  FactKind,
  FactRole,
  FactScope,
  Workspace,
} from "../types";

export function FactEditor({
  fact,
  workspaces,
  onClose,
  onSaved,
}: {
  fact?: Fact | null;
  workspaces: Workspace[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const editing = Boolean(fact);
  const [scope, setScope] = useState<FactScope>(fact?.scope ?? "global");
  const [projectId, setProjectId] = useState(
    fact?.project_id ?? workspaces[0]?.id ?? "",
  );
  const [role, setRole] = useState<FactRole>(fact?.role ?? "both");
  const [kind, setKind] = useState<FactKind>(fact?.kind ?? "insight");
  const [title, setTitle] = useState(fact?.title ?? "");
  const [content, setContent] = useState(fact?.content_md ?? "");
  const [aliases, setAliases] = useState((fact?.aliases ?? []).join("\n"));
  const [tags, setTags] = useState((fact?.tags ?? []).join("\n"));
  const [validUntil, setValidUntil] = useState(fact?.valid_until ?? "");
  const [pinned, setPinned] = useState(fact?.pinned ?? false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save(accept: boolean) {
    if (!title.trim()) {
      setError("标题不能为空。");
      return;
    }
    if (scope === "workspace" && !projectId) {
      setError("工作区事实必须选择工作区。");
      return;
    }
    setBusy(true);
    setError(null);
    const body = {
      scope,
      project_id: scope === "workspace" ? projectId : null,
      role,
      kind,
      title: title.trim(),
      content_md: content,
      aliases: splitLines(aliases),
      tags: splitLines(tags),
      pinned,
      valid_until: validUntil.trim() || null,
    };
    try {
      if (editing && fact) {
        await api.updateFact(fact.id, body);
        if (accept) await api.updateFact(fact.id, { status: "accepted" });
      } else {
        await api.createFact({ ...body, status: "accepted" });
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal modal-wide"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
      >
        <div className="modal-head">
          <div>
            <div className="eyebrow">{editing ? "EDIT FACT" : "NEW FACT"}</div>
            <h2>{editing ? "编辑长期事实" : "手动添加长期事实"}</h2>
          </div>
          <button type="button" className="icon-button" onClick={onClose}>
            ×
          </button>
        </div>

        {error ? <div className="alert alert-error">{error}</div> : null}

        <form className="stack" onSubmit={(event) => { event.preventDefault(); void save(false); }}>
          <div className="form-row">
            <label>
              作用域
              <select
                value={scope}
                onChange={(event) => setScope(event.target.value as FactScope)}
              >
                {(["global", "workspace"] as FactScope[]).map((value) => (
                  <option key={value} value={value}>
                    {FACT_SCOPE_LABELS[value]}
                  </option>
                ))}
              </select>
            </label>
            {scope === "workspace" ? (
              <label>
                工作区
                <select
                  value={projectId}
                  onChange={(event) => setProjectId(event.target.value)}
                >
                  {workspaces.map((workspace) => (
                    <option key={workspace.id} value={workspace.id}>
                      {workspace.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
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
            <input
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              placeholder="一句话说明这条长期事实"
            />
          </label>

          <label>
            内容（Markdown）
            <textarea
              rows={8}
              value={content}
              onChange={(event) => setContent(event.target.value)}
              placeholder="写清楚事实、适用条件和来源。"
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
                placeholder="补充不同措辞，帮助检索命中"
              />
            </label>
            <label>
              标签（每行一个）
              <textarea
                rows={2}
                className="mono"
                value={tags}
                onChange={(event) => setTags(event.target.value)}
                placeholder="tooling / deployment"
              />
            </label>
          </div>

          <label>
            有效期（可选，ISO 时间；过期后不再注入）
            <input
              className="mono"
              value={validUntil}
              onChange={(event) => setValidUntil(event.target.value)}
              placeholder="2027-01-01T00:00:00+00:00"
            />
          </label>

          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={pinned}
              onChange={(event) => setPinned(event.target.checked)}
            />
            置顶（相关时优先注入）
          </label>

          <div className="modal-actions">
            <button type="button" className="button ghost" onClick={onClose}>
              取消
            </button>
            <button type="submit" className="button" disabled={busy}>
              {busy ? "保存中…" : "保存"}
            </button>
            {editing && fact?.status === "candidate" ? (
              <button
                type="button"
                className="button primary"
                onClick={() => void save(true)}
                disabled={busy}
              >
                保存并接受
              </button>
            ) : null}
          </div>
        </form>
      </div>
    </div>
  );
}
