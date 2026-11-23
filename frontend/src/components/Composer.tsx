import type { PermissionProfile, RoleId } from "../types";
import { PROFILE_HINTS, PROFILE_LABELS } from "../labels";

export const ROLE_PROFILES: Record<RoleId, PermissionProfile[]> = {
  coding: ["read_only", "edit", "execute"],
  scholar: ["read_only", "research"],
};

export const DEFAULT_PROFILE: Record<RoleId, PermissionProfile> = {
  coding: "edit",
  scholar: "read_only",
};

export function Composer({
  role,
  value,
  onChange,
  onSend,
  onStop,
  profile,
  onProfileChange,
  busy,
  active,
  executeAllowed,
  disabledReason,
}: {
  role: RoleId;
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  profile: PermissionProfile;
  onProfileChange: (profile: PermissionProfile) => void;
  busy: boolean;
  active: boolean;
  executeAllowed: boolean;
  disabledReason?: string | null;
}) {
  const profiles = ROLE_PROFILES[role];
  const canSend = value.trim().length > 0 && !busy && !active && !disabledReason;

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Do not send while an IME (e.g. Chinese pinyin) is composing.
    if (event.nativeEvent.isComposing || event.keyCode === 229) return;

    // Enter sends; Shift+Enter inserts a newline.
    if (event.key === "Enter" && !event.shiftKey) {
      if (canSend) {
        event.preventDefault();
        onSend();
      }
      return;
    }
    // Keep Ctrl/Cmd+Enter as an explicit send shortcut.
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      if (canSend) {
        event.preventDefault();
        onSend();
      }
    }
  }

  return (
    <div className="composer">
      {disabledReason ? (
        <div className="composer-disabled">{disabledReason}</div>
      ) : null}
      <textarea
        className="composer-input"
        rows={3}
        value={value}
        placeholder={
          role === "coding"
            ? "描述要实现的改动、要排查的问题…（Enter 发送，Shift+Enter 换行）"
            : "提出研究问题，或粘贴资料让 Scholar 分析…（Enter 发送，Shift+Enter 换行）"
        }
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
        disabled={Boolean(disabledReason)}
      />
      <div className="composer-bar">
        <div className="composer-profiles">
          {profiles.map((candidate) => (
            <button
              type="button"
              key={candidate}
              className={`profile-chip${candidate === profile ? " selected" : ""}`}
              title={PROFILE_HINTS[candidate]}
              onClick={() => onProfileChange(candidate)}
              disabled={candidate === "execute" && !executeAllowed}
            >
              {PROFILE_LABELS[candidate]}
            </button>
          ))}
          {role === "coding" && !executeAllowed ? (
            <span className="composer-hint">工作区未配置 PowerShell 白名单</span>
          ) : null}
        </div>
        <div className="composer-actions">
          {active ? (
            <button type="button" className="button danger" onClick={onStop}>
              停止
            </button>
          ) : (
            <button
              type="button"
              className="button primary"
              onClick={onSend}
              disabled={!canSend}
            >
              {busy ? "发送中…" : "发送"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
